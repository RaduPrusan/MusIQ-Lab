"""Viterbi smoothing over per-frame F0 candidates.

Phase 0c Step 4. Replaces the stateless per-frame fusion in
`contour._build_consensus_f0` with a forward-pass Viterbi that picks
**one F0 per frame** from a fixed 8-state candidate space, using
temporal continuity as a free additional anchor.

State space (per frame, fixed K=8 slots so every frame's transition
matrix is the same shape and forward-pass vectorizes cleanly):

    slot 0  fcpe          — raw FCPE Hz
    slot 1  pesto         — raw PESTO Hz
    slot 2  fcpe ÷ 2      — octave-down shift of FCPE (recovers from
                            FCPE octave-up lock)
    slot 3  fcpe × 2      — octave-up shift of FCPE
    slot 4  pesto ÷ 2     — octave-down shift of PESTO
    slot 5  pesto × 2     — octave-up shift of PESTO
    slot 6  anchor        — basic-pitch active note as Hz (conf 0.7
                            fixed by spec)
    slot 7  unvoiced      — silence sentinel (always present)

A slot whose underlying source is unavailable at the current frame
(estimator unvoiced, anchor silent, etc.) is filled with `EMISSION_INF`
so it can never win the path. Octave-shifted slots whose Hz falls
outside [hz_min, hz_max] also get EMISSION_INF — the shift is meaningful
only when it lands inside the plausible vocal range.

The shifted slots' confidence is halved per spec, which adds a fixed
−log(0.5) ≈ 0.69 emission penalty: a shift can only win a state when
temporal continuity makes the unshifted alternative more expensive
(i.e., the prior frame's path-min was already on a different octave,
and jumping to the shifted candidate keeps the cents-distance small).

Costs
-----
**Emission** at frame i, state s: `−log(max(conf[i, s], EPSILON))`.
EPSILON = 0.01 floors log(0) at +4.6, which is also the unvoiced state's
emission (its conf is set to EPSILON exactly so it costs −log(EPSILON)).

**Transition** from prev state at frame i−1 to curr state at frame i:

  - both unvoiced: 0 (free to stay silent)
  - voicing on (unvoiced → voiced): +LAMBDA_VOICING_ON
  - voicing off (voiced → unvoiced): +LAMBDA_VOICING_OFF
  - both voiced:
        cents = |1200 · log2(curr_hz / prev_hz)|
        base  = LAMBDA_FREQ · (cents / CENTS_NORMALIZER)²    # quadratic
        bump  = LAMBDA_OCTAVE · exp(−((cents − 1200) / OCTAVE_SIGMA)²)
        cost  = base + bump

The Gaussian peak at exactly 1200¢ is the structural fix the
unsmoothed pipeline lacked: a smooth-quadratic-in-cents alone treats
1200¢ (octave glitch) and 1500¢ (real wide melodic leap) the same. The
bump explicitly suppresses 1200¢ transitions while leaving room for
genuine wide leaps.

Calibration of λ values is a tuning exercise; defaults below come from
spec §4 Step 4 and worked on synthetic clips. The Cohen t=107.7s case
(YIN: 87 Hz; FCPE: 175 Hz; PESTO: 349 Hz; basic-pitch: silent) is the
real-world canary — a pass-through where Viterbi locks onto 87 Hz
through a no-anchor stretch is the architecture-validated outcome.

Output
------
`viterbi_smooth()` returns three same-length arrays:

  f0_path           float32 Hz; NaN where the unvoiced slot was chosen
  path_confidence   float32 in [0, 1] = exp(−emission_at_chosen_state)
  candidate_source  int8 with values 0..7 matching the slot constants

Performance
-----------
Vectorized over states, looped over frames. n_frames × K² operations,
all numpy ops. n=18000 × K²=64 = ~1M ops → ~50ms wall time. The
candidate-build step is also vectorized end-to-end (no per-frame Python
loop).
"""
from __future__ import annotations

import math

import numpy as np


# ---- State slot constants (also exported as candidate_source values) ----
SOURCE_FCPE = 0
SOURCE_PESTO = 1
SOURCE_FCPE_DOWN = 2  # FCPE × 0.5
SOURCE_FCPE_UP = 3    # FCPE × 2
SOURCE_PESTO_DOWN = 4
SOURCE_PESTO_UP = 5
SOURCE_ANCHOR = 6
SOURCE_UNVOICED = 7
N_STATES = 8

# ---- Cost-scale constants ----
EPSILON = 0.01
EMISSION_INF = 1e6           # unavailable slot — un-pickable in argmin
UNVOICED_CONF = EPSILON      # unvoiced state's "confidence"
SHIFT_CONF_FACTOR = 0.5      # octave-shifted candidates start at half conf
ANCHOR_CONF = 0.7            # basic-pitch anchor's fixed confidence

# ---- Default λ parameters (tunable from contour.py / stage params) ----
#
# Rationale on CENTS_NORMALIZER=300 (deviates from spec §4 default of 100):
# A 1-frame unvoiced detour costs λ_voicing_off + λ_voicing_on + unvoiced_em
# ≈ 3 + 3 + 4.6 = 10.6. With N=100, a fifth-leap costs (700/100)² = 49,
# which is more expensive than the detour — Viterbi rejects genuine wide
# vocal leaps as "too suspicious" and inserts NaN gaps. With N=300,
# fifth-leap = 5.44 (well under detour) and octave = 21 + 5 (bump) = 26
# (well over detour). The threshold lands between a major-seventh (~10.7)
# and an octave, which matches the design intent: "wide melodic leap →
# follow; octave-glitch → suspect (mark unknown)".
#
# Rationale on ANCHOR_PROX_BONUS / SIGMA: the spec's discrete dedupe
# tie-breaker ("prefer anchor-proximate candidate to crowd out wrong-
# octave full-conf candidates") is implemented here as a continuous
# emission-cost reduction. Within ANCHOR_PROX_SIGMA cents of an active
# anchor, candidates get up to ANCHOR_PROX_BONUS subtracted from their
# emission cost. Falloff is Gaussian, so wrong-octave candidates (1200¢
# off the anchor) get effectively zero help.
DEFAULT_LAMBDA_FREQ = 1.0
DEFAULT_CENTS_NORMALIZER = 300.0
DEFAULT_LAMBDA_OCTAVE = 5.0
DEFAULT_OCTAVE_SIGMA = 150.0
DEFAULT_LAMBDA_VOICING_ON = 3.0
DEFAULT_LAMBDA_VOICING_OFF = 3.0
DEFAULT_ANCHOR_PROX_BONUS = 1.0
DEFAULT_ANCHOR_PROX_SIGMA = 100.0


def _midi_int_to_hz(midi: int) -> float:
    """Local copy to avoid cross-module dep cycle. Equivalent to primitives.midi_to_hz."""
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _build_candidates(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    fcpe_conf: np.ndarray,
    pesto_conf: np.ndarray,
    bp_active_midi: np.ndarray,
    *,
    hz_min: float,
    hz_max: float,
    anchor_prox_bonus: float = DEFAULT_ANCHOR_PROX_BONUS,
    anchor_prox_sigma: float = DEFAULT_ANCHOR_PROX_SIGMA,
    force_unvoiced: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build per-frame candidate Hz, voicing, and emission cost matrices.

    All inputs are length-n_frames 1-D arrays. Output shapes:

      cand_hz       (n_frames, N_STATES) float32 — Hz, NaN for unused/unvoiced slots
      cand_voiced   (n_frames, N_STATES) bool     — True for slots representing actual voicing
      cand_emission (n_frames, N_STATES) float32  — −log(max(conf, EPSILON)), or
                                                    EMISSION_INF for unavailable slots

    "Unavailable" includes:
      - estimator unvoiced (raw Hz == 0)
      - estimator Hz outside [hz_min, hz_max] (raw or after shift)
      - anchor with bp_active_midi == −1
    """
    n = len(fcpe)
    cand_hz = np.full((n, N_STATES), np.nan, dtype=np.float32)
    cand_voiced = np.zeros((n, N_STATES), dtype=bool)
    cand_emission = np.full((n, N_STATES), EMISSION_INF, dtype=np.float32)

    fcpe = np.asarray(fcpe, dtype=np.float32)
    pesto = np.asarray(pesto, dtype=np.float32)
    fcpe_conf = np.clip(np.asarray(fcpe_conf, dtype=np.float32), 0.0, 1.0)
    pesto_conf = np.clip(np.asarray(pesto_conf, dtype=np.float32), 0.0, 1.0)

    def _fill(slot: int, hz_arr: np.ndarray, conf_arr: np.ndarray) -> None:
        """Populate a slot from an Hz array and confidence array.

        A frame is voiced for this slot iff hz > 0 AND in [hz_min, hz_max].
        Emission cost at unvoiced frames stays at EMISSION_INF.
        """
        in_range = (hz_arr > 0) & (hz_arr >= hz_min) & (hz_arr <= hz_max)
        cand_hz[in_range, slot] = hz_arr[in_range]
        cand_voiced[in_range, slot] = True
        # Emission: −log(max(conf, EPSILON)) for the in-range voiced frames
        conf_floored = np.maximum(conf_arr[in_range], EPSILON)
        cand_emission[in_range, slot] = -np.log(conf_floored).astype(np.float32)

    # Slot 0/1: raw FCPE / PESTO at native confidence
    _fill(SOURCE_FCPE, fcpe, fcpe_conf)
    _fill(SOURCE_PESTO, pesto, pesto_conf)

    # Slot 2/3: FCPE × 0.5 / × 2 with halved confidence
    _fill(SOURCE_FCPE_DOWN, fcpe * 0.5, fcpe_conf * SHIFT_CONF_FACTOR)
    _fill(SOURCE_FCPE_UP, fcpe * 2.0, fcpe_conf * SHIFT_CONF_FACTOR)
    # Slot 4/5: PESTO × 0.5 / × 2
    _fill(SOURCE_PESTO_DOWN, pesto * 0.5, pesto_conf * SHIFT_CONF_FACTOR)
    _fill(SOURCE_PESTO_UP, pesto * 2.0, pesto_conf * SHIFT_CONF_FACTOR)

    # Slot 6: anchor (basic-pitch active note → Hz)
    bp_active = bp_active_midi >= 0
    if bp_active.any():
        # Vectorize MIDI→Hz: 440 * 2^((m-69)/12)
        bp_hz = 440.0 * np.power(
            2.0, (bp_active_midi.astype(np.float32) - 69.0) / 12.0,
        )
        anchor_in_range = bp_active & (bp_hz >= hz_min) & (bp_hz <= hz_max)
        cand_hz[anchor_in_range, SOURCE_ANCHOR] = bp_hz[anchor_in_range]
        cand_voiced[anchor_in_range, SOURCE_ANCHOR] = True
        cand_emission[anchor_in_range, SOURCE_ANCHOR] = float(-math.log(ANCHOR_CONF))

    # Slot 7: unvoiced — always present, fixed emission
    cand_emission[:, SOURCE_UNVOICED] = float(-math.log(UNVOICED_CONF))
    # cand_voiced[:, SOURCE_UNVOICED] stays False; cand_hz stays NaN.

    # Hard silence gate: where `force_unvoiced` is True (typically frames
    # vetoed by the upstream RMS-floor check in consensus_voicing), set
    # every voiced slot to EMISSION_INF. The unvoiced sentinel slot is
    # the only viable choice → Viterbi outputs NaN there even if the F0
    # estimators or basic-pitch had stale values to offer. Without this
    # gate, basic-pitch hallucinations during instrumental-only passages
    # would still light up the anchor candidate (em ≈ 0.36) and beat
    # the unvoiced state (em ≈ 4.6), pulling the contour into silence.
    if force_unvoiced is not None and bool(np.any(force_unvoiced)):
        mask = np.asarray(force_unvoiced, dtype=bool)
        # Zero out every slot except SOURCE_UNVOICED. The unvoiced slot's
        # cand_voiced is already False, so excluding it from the gate
        # isn't strictly necessary — but doing so explicitly documents
        # the intent and prevents accidental cross-pollution if slot
        # semantics ever change.
        for s in range(N_STATES):
            if s == SOURCE_UNVOICED:
                continue
            cand_emission[mask, s] = EMISSION_INF
            cand_voiced[mask, s] = False
            cand_hz[mask, s] = np.nan

    # Anchor-proximity emission bonus (continuous version of the spec's
    # discrete dedupe tie-breaker). Where an anchor is active, candidates
    # within ANCHOR_PROX_SIGMA¢ of the anchor's Hz get up to
    # ANCHOR_PROX_BONUS subtracted from their emission cost. Beyond the
    # band the bonus tapers to ~0 (Gaussian), so wrong-octave full-conf
    # candidates don't get help.
    #
    # The anchor's OWN slot is intentionally excluded — the bonus is
    # about pulling F0 candidates toward the anchor, not about boosting
    # the anchor candidate against the F0s. Including the anchor slot
    # double-counts the "trust the anchor" prior: the anchor's
    # confidence (0.7) already encodes its credibility, and stacking a
    # full bonus on top makes anchor-only-active frames win against
    # disagreeing full-confidence F0 estimators (the Cohen 107.7s
    # failure mode where basic-pitch hallucinates 5×fundamental).
    if bp_active.any() and anchor_prox_bonus > 0.0:
        # Per-frame anchor Hz (NaN where anchor inactive). Broadcasting
        # below propagates NaN into bonus → np.where filters to 0.
        anchor_hz_full = np.where(
            bp_active,
            440.0 * np.power(2.0, (bp_active_midi.astype(np.float32) - 69.0) / 12.0),
            np.nan,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            cents_to_anchor = np.abs(
                1200.0 * np.log2(cand_hz / anchor_hz_full[:, None])
            )
            bonus = anchor_prox_bonus * np.exp(
                -((cents_to_anchor / anchor_prox_sigma) ** 2)
            )
        # NaN bonus where anchor inactive or candidate slot unvoiced.
        # Also gate on cand_voiced so the unvoiced sentinel slot (NaN Hz
        # but populated emission) doesn't get an accidental bonus.
        bonus = np.where(np.isnan(bonus) | ~cand_voiced, 0.0, bonus)
        # Exclude anchor's own slot from receiving its own bonus.
        bonus[:, SOURCE_ANCHOR] = 0.0
        cand_emission = cand_emission - bonus.astype(np.float32)

    return cand_hz, cand_voiced, cand_emission


def _viterbi_forward(
    cand_hz: np.ndarray,
    cand_voiced: np.ndarray,
    cand_emission: np.ndarray,
    *,
    lambda_freq: float,
    cents_normalizer: float,
    lambda_octave: float,
    octave_sigma: float,
    lambda_voicing_on: float,
    lambda_voicing_off: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Standard Viterbi forward pass, vectorized over states.

    Returns
    -------
    costs        (n_frames, N_STATES) float32 — cumulative path cost
    backpointers (n_frames, N_STATES) int16   — best-prev state index per frame
                                                 (frame 0 backpointer = -1)
    """
    n_frames, K = cand_emission.shape
    costs = np.full((n_frames, K), np.inf, dtype=np.float64)
    backpointers = np.full((n_frames, K), -1, dtype=np.int16)

    # Frame 0: emission only.
    costs[0] = cand_emission[0].astype(np.float64)

    # Pre-compute log2 of Hz arrays (with NaN handling) so cents math
    # vectorizes cleanly. log2_hz[i, s] is log2(cand_hz[i, s]) where the
    # slot is voiced; NaN otherwise. Used only for voiced→voiced transitions.
    with np.errstate(divide="ignore", invalid="ignore"):
        log2_hz = np.log2(cand_hz, where=cand_voiced, out=np.full_like(cand_hz, np.nan))

    for i in range(1, n_frames):
        prev_costs = costs[i - 1, :, None]      # (K, 1)  prev state on axis 0
        em = cand_emission[i, None, :]          # (1, K)  curr state on axis 1

        # Transition cost matrix shape (K, K): rows = prev state, cols = curr.
        prev_voiced = cand_voiced[i - 1, :, None]   # (K, 1)
        curr_voiced = cand_voiced[i, None, :]        # (1, K)

        # Voicing component
        v_off = prev_voiced & ~curr_voiced
        v_on = ~prev_voiced & curr_voiced
        trans = np.zeros((K, K), dtype=np.float64)
        trans = np.where(v_off, lambda_voicing_off, trans)
        trans = np.where(v_on, lambda_voicing_on, trans)

        # Frequency component (only when both voiced)
        both_voiced = prev_voiced & curr_voiced
        if both_voiced.any():
            # |cents| from log2-Hz difference. Use absolute value so the
            # octave bump catches both directions.
            cents = np.abs(
                1200.0 * (log2_hz[i, None, :] - log2_hz[i - 1, :, None]),
            )
            base = lambda_freq * (cents / cents_normalizer) ** 2
            bump = lambda_octave * np.exp(
                -((cents - 1200.0) / octave_sigma) ** 2
            )
            freq_cost = base + bump
            # NaN-safe: where both_voiced is False, cents is NaN — replace with 0
            freq_cost = np.where(both_voiced, freq_cost, 0.0)
            trans = trans + freq_cost

        # total[s_prev, s_curr] = prev_costs[s_prev] + trans[s_prev, s_curr] + em[s_curr]
        total = prev_costs + trans + em
        best_prev = np.argmin(total, axis=0)         # (K,)
        costs[i] = total[best_prev, np.arange(K)]
        backpointers[i] = best_prev.astype(np.int16)

    return costs, backpointers


def _backtrack(costs: np.ndarray, backpointers: np.ndarray) -> np.ndarray:
    """Standard backtrack from the argmin of the final-frame costs."""
    n_frames = costs.shape[0]
    path = np.zeros(n_frames, dtype=np.int16)
    path[-1] = int(np.argmin(costs[-1]))
    for i in range(n_frames - 1, 0, -1):
        path[i - 1] = backpointers[i, path[i]]
    return path


def viterbi_smooth(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    fcpe_conf: np.ndarray,
    pesto_conf: np.ndarray,
    bp_active_midi: np.ndarray,
    *,
    hz_min: float = 65.0,
    hz_max: float = 1500.0,
    lambda_freq: float = DEFAULT_LAMBDA_FREQ,
    cents_normalizer: float = DEFAULT_CENTS_NORMALIZER,
    lambda_octave: float = DEFAULT_LAMBDA_OCTAVE,
    octave_sigma: float = DEFAULT_OCTAVE_SIGMA,
    lambda_voicing_on: float = DEFAULT_LAMBDA_VOICING_ON,
    lambda_voicing_off: float = DEFAULT_LAMBDA_VOICING_OFF,
    anchor_prox_bonus: float = DEFAULT_ANCHOR_PROX_BONUS,
    anchor_prox_sigma: float = DEFAULT_ANCHOR_PROX_SIGMA,
    force_unvoiced: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Viterbi-smoothed F0 path over the 8-state candidate space.

    Parameters
    ----------
    fcpe, pesto : np.ndarray
        Length-n F0 arrays (Hz). 0 = unvoiced. Should be POST octave
        correction (i.e. fcpe_corrected/pesto_corrected) — Viterbi adds
        its own octave-shift candidates on top, but starting from
        already-corrected inputs reduces the search space we exercise.
    fcpe_conf, pesto_conf : np.ndarray
        Length-n confidence in [0, 1]. Pre-Phase-0c-Step-1 caches
        synthesize this from the voicing mask via vocal_f0.load(); v2+
        caches have actual values.
    bp_active_midi : np.ndarray
        Length-n int array; per-frame active basic-pitch MIDI integer,
        −1 where no note is active. Built by
        `octave._build_basic_pitch_frame_lookup`.

    Returns
    -------
    f0_path : np.ndarray
        Length-n float32 Hz; NaN where the unvoiced slot was chosen.
    path_confidence : np.ndarray
        Length-n float32 in [0, 1]: exp(−emission_at_chosen_state). The
        unvoiced state lands at exp(−4.6) ≈ 0.01.
    candidate_source : np.ndarray
        Length-n int8 with values 0..7 (see SOURCE_* slot constants).
    """
    if fcpe.shape != pesto.shape:
        raise ValueError(f"fcpe/pesto shape mismatch: {fcpe.shape} vs {pesto.shape}")
    n = len(fcpe)
    if n == 0:
        empty32 = np.zeros(0, dtype=np.float32)
        return empty32, empty32, np.zeros(0, dtype=np.int8)

    cand_hz, cand_voiced, cand_emission = _build_candidates(
        fcpe, pesto, fcpe_conf, pesto_conf, bp_active_midi,
        hz_min=hz_min, hz_max=hz_max,
        anchor_prox_bonus=anchor_prox_bonus,
        anchor_prox_sigma=anchor_prox_sigma,
        force_unvoiced=force_unvoiced,
    )

    costs, backpointers = _viterbi_forward(
        cand_hz, cand_voiced, cand_emission,
        lambda_freq=lambda_freq,
        cents_normalizer=cents_normalizer,
        lambda_octave=lambda_octave,
        octave_sigma=octave_sigma,
        lambda_voicing_on=lambda_voicing_on,
        lambda_voicing_off=lambda_voicing_off,
    )
    path = _backtrack(costs, backpointers)

    # Decode chosen states back into Hz / confidence / source arrays.
    rows = np.arange(n)
    chosen_hz = cand_hz[rows, path]
    chosen_em = cand_emission[rows, path]

    # f0_path: NaN where unvoiced state, Hz otherwise.
    f0_path = chosen_hz.astype(np.float32)  # already NaN at unvoiced slot

    # path_confidence = exp(−emission). Clip to [0, 1]. Force exactly 0
    # at unvoiced frames so consumers can use the same "strength == 0.0"
    # guard as in the Step 2 fallback (the heuristic builder produced
    # bit-equal 0 there; the unvoiced state's natural exp(−4.6) ≈ 0.01
    # would silently break that contract).
    path_confidence = np.exp(-chosen_em).astype(np.float32)
    path_confidence = np.clip(path_confidence, 0.0, 1.0)
    path_confidence[path == SOURCE_UNVOICED] = 0.0

    candidate_source = path.astype(np.int8)
    return f0_path, path_confidence, candidate_source
