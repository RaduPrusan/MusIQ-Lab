"""Top-level vocal-contour orchestrator.

Chains the pre-cleaning layer (octave correction + voicing consensus)
into a single function that produces a `ContourResult`:

    ┌─ raw inputs ──────────────────────────────┐
    │  FCPE F0 array                            │
    │  PESTO F0 array                           │
    │  basic-pitch notes (list)                 │
    │  RMS envelope (optional)                  │
    └────────────────┬──────────────────────────┘
                     ▼
              octave_correct      ──► corrected FCPE/PESTO + correction flags
                     ▼
              consensus_voicing   ──► per-frame vote_count (0..3)
                     ▼
              build consensus_f0  ──► (consensus_f0, agreement_strength)
                     ▼
              per_note_intonation ──► list[NoteIntonation] aligned with notes

`consensus_f0` is the centerpiece for UI: a single Hz contour with NaN
where no F0 evidence is available at all. Unlike the original Phase 0a
build, it is no longer gated by the `vote_count >= 2` AND `<50¢
agreement` conjunction — that conjunction was stricter than the voicing
filter itself, killing voted-voiced frames whenever any one of {FCPE,
PESTO, basic-pitch} fell silent. On bass-baritone material that hidden
contract bug culled ~38% of voted-voiced frames.

Instead, the renderer now reads `agreement_strength` — a per-frame
scalar in [0, 1] that bins frames into strong/medium/weak/none buckets:

  Strong  (≥0.7)  : both F0 estimators voiced AND agree within threshold
                    (linearly scaled by cents disagreement)
  Medium  (~0.4)  : F0 estimators disagree but a basic-pitch anchor
                    breaks the tie by closeness
  Medium  (~0.5)  : single F0 voiced + basic-pitch anchor active
  Weak    (~0.25) : single F0 voiced, no anchor
  None    (0.0)   : nothing voiced (or RMS-vetoed); consensus_f0 = NaN

The renderer translates these into three SVG paths with descending
opacity. Visually: the contour now fades smoothly with confidence
instead of fragmenting on contract violations. Strong-bucket frames
look the same as before; medium and weak frames that previously
disappeared now show as dimmer strokes the user can choose to ignore.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from analyze.derived.vocal_consensus.intonation import (
    NoteIntonation,
    per_note_intonation,
)
from analyze.derived.vocal_consensus.octave import (
    _build_basic_pitch_frame_lookup,
    correct_octaves,
)
from analyze.derived.vocal_consensus.primitives import midi_to_hz
from analyze.derived.vocal_consensus.viterbi import (
    SOURCE_UNVOICED,
    viterbi_smooth,
)
from analyze.derived.vocal_consensus.voicing import consensus_voicing


@dataclass
class ContourResult:
    """Bundled output of `process_contour()`.

    All array fields are 1-D, length = n_frames, frame-rate aligned.
    `octave_corrections` is shape (n_frames, 2) with int8 signed octave
    shifts — column 0 is FCPE, column 1 is PESTO. `consensus_f0` is
    float32 with np.nan wherever no F0 evidence was available (caller
    should use np.isnan() rather than testing for 0.0, since a true zero
    would be ambiguous with sub-Hz vocal pitches outside the F0 range
    anyway). `agreement_strength` is float32 in [0, 1] aligned with
    `consensus_f0` — see module docstring for bucket semantics.

    `viterbi_source` is int8 length n_frames with values 0..7 matching
    the `viterbi.SOURCE_*` slot constants — diagnostic only, not
    serialized to disk (kept in-memory for tests + ad-hoc analysis).
    The field is present regardless of which builder ran; the Step 2
    fallback fills it with SOURCE_UNVOICED for NaN frames and a
    sentinel "unknown" value (255) for frames where it built consensus
    via heuristic buckets.
    """
    fcpe_corrected: np.ndarray
    pesto_corrected: np.ndarray
    consensus_f0: np.ndarray
    agreement_strength: np.ndarray
    vote_count: np.ndarray
    octave_corrections: np.ndarray
    note_intonation: list[NoteIntonation]
    viterbi_source: np.ndarray


FALLBACK_SOURCE_SENTINEL = np.int8(127)


def process_contour(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    basic_pitch_notes,
    fps: float,
    *,
    rms: np.ndarray | None = None,
    rms_floor_db: float = -45.0,
    cents_agreement_threshold: float = 50.0,
    fcpe_conf: np.ndarray | None = None,
    pesto_conf: np.ndarray | None = None,
    viterbi_enabled: bool = True,
    viterbi_params: dict | None = None,
) -> ContourResult:
    """Run the full vocal-contour pre-cleaning + intonation pipeline.

    Parameters
    ----------
    fcpe, pesto : np.ndarray
        Raw F0 arrays from the vocal_f0 stage (Hz, 0 = unvoiced).
    basic_pitch_notes : list
        basic-pitch's note list (objects with start/end/pitch/velocity).
    fps : float
        Frame rate of the F0 arrays (typically 100.0).
    rms : np.ndarray | None, keyword-only
        Optional per-frame RMS envelope. When supplied, applies the
        voicing floor gate (see consensus_voicing for the semantic).
    rms_floor_db : float, keyword-only, default -45.0
        Floor threshold in dBFS, passed through to consensus_voicing.
    cents_agreement_threshold : float, keyword-only, default 50.0
        Maximum |cents(FCPE/PESTO)| difference for a frame to count as
        agreement. Used both for the consensus_f0 line and for per-note
        intonation. Setting these together (single knob) keeps the
        frame-level visualization and per-note metrics coherent.
    fcpe_conf, pesto_conf : np.ndarray | None, keyword-only
        Optional per-frame confidences in [0, 1]. When None (the default
        for backward compatibility with callers that don't have v2+
        vocal_f0 caches), confidence is synthesized from the voicing
        mask: 1.0 where the estimator is voiced, 0.0 elsewhere — the
        same fallback that `vocal_f0.load()` uses for v1 caches.
    viterbi_enabled : bool, keyword-only, default True
        When True, build consensus_f0 + agreement_strength via Viterbi
        smoothing (Phase 0c Step 4). When False, fall back to Step 2's
        per-frame heuristic builder (`_build_consensus_f0`). The flag is
        plumbed through `vocal_consensus_contour.DEFAULT_PARAMS` so
        flipping it shifts the sidecar fingerprint and forces a re-run
        — useful for A/B comparison and emergency rollback.
    viterbi_params : dict | None, keyword-only
        Optional override of Viterbi's internal λ values. Pass the
        kwargs accepted by `viterbi.viterbi_smooth` (e.g.
        `{"lambda_freq": 1.0, "cents_normalizer": 250.0}`). None means
        "use the module defaults".

    Returns
    -------
    ContourResult
        See class docstring. All array fields are independent copies; the
        function does not mutate its inputs.
    """
    if fcpe.shape != pesto.shape:
        raise ValueError(f"fcpe/pesto shape mismatch: {fcpe.shape} vs {pesto.shape}")
    if fcpe.ndim != 1:
        raise ValueError(f"fcpe must be 1-D, got shape {fcpe.shape}")

    fcpe_c, pesto_c, octave_corr = correct_octaves(
        fcpe, pesto, basic_pitch_notes, fps,
    )
    vote_count = consensus_voicing(
        fcpe_c, pesto_c, basic_pitch_notes, fps,
        rms=rms, rms_floor_db=rms_floor_db,
    )

    bp_active_midi = _build_basic_pitch_frame_lookup(
        basic_pitch_notes, len(fcpe_c), fps,
    )

    # Confidence fallback: derive from voicing mask if not supplied
    # (v1 vocal_f0 caches and tests that pre-date Phase 0c Step 1).
    if fcpe_conf is None:
        fcpe_conf = (fcpe_c > 0).astype(np.float32)
    else:
        fcpe_conf = np.asarray(fcpe_conf, dtype=np.float32)
        # Length-align: a stems_dynamics-driven length truncation upstream
        # may have shortened fcpe_c without touching the conf arrays.
        fcpe_conf = fcpe_conf[: len(fcpe_c)]
    if pesto_conf is None:
        pesto_conf = (pesto_c > 0).astype(np.float32)
    else:
        pesto_conf = np.asarray(pesto_conf, dtype=np.float32)
        pesto_conf = pesto_conf[: len(pesto_c)]

    # Hard silence gate. Two conditions trigger forced-unvoiced:
    #
    #   1. `vote_count == 0` — the upstream RMS-floor veto in
    #      consensus_voicing fired (frame energy below `rms_floor_db`).
    #      Often vacuous on bleed-heavy stems where the RMS sits above
    #      the floor during instrumental-only passages, but kept as
    #      first-line defense for clean-stem tracks.
    #   2. `fcpe_c == 0` — FCPE's voicing detector says silent. FCPE
    #      ships with an internal voicing threshold that produces
    #      genuine zero/Hz output at silent / breath / unvoiced
    #      consonant frames; PESTO does NOT — it emits continuous Hz
    #      values everywhere by design. Using FCPE as the primary
    #      voicing authority is the closest signal to ground truth
    #      this pipeline has access to without HNR. Combined with the
    #      basic-pitch anchor's vulnerability to hallucination on
    #      bleed, an FCPE-says-silent veto is the cleanest silence
    #      detector available. False negatives from FCPE (singer
    #      voiced, FCPE missed) cost a 1-frame NaN gap that Viterbi's
    #      voicing-on transition recovers from on the next frame.
    rms_vetoed = vote_count == 0
    fcpe_unvoiced = fcpe_c == 0
    rms_vetoed = rms_vetoed | fcpe_unvoiced

    if viterbi_enabled:
        vp = dict(viterbi_params or {})
        f0_path, path_conf, source = viterbi_smooth(
            fcpe_c, pesto_c, fcpe_conf, pesto_conf, bp_active_midi,
            force_unvoiced=rms_vetoed,
            **vp,
        )
        consensus_f0 = f0_path
        agreement_strength = path_conf
        viterbi_source = source.astype(np.int8)
    else:
        consensus_f0, agreement_strength = _build_consensus_f0(
            fcpe_c, pesto_c, vote_count, bp_active_midi,
            cents_agreement_threshold,
        )
        # Sentinel viterbi_source for the heuristic builder. NaN frames
        # → SOURCE_UNVOICED; everything else → 127 ("unknown"), since
        # the heuristic doesn't pick from the Viterbi state space.
        viterbi_source = np.where(
            np.isnan(consensus_f0),
            np.int8(SOURCE_UNVOICED),
            FALLBACK_SOURCE_SENTINEL,
        ).astype(np.int8)

    note_intonation = per_note_intonation(
        fcpe_c, pesto_c, vote_count, basic_pitch_notes, fps,
        cents_agreement_threshold=cents_agreement_threshold,
    )

    return ContourResult(
        fcpe_corrected=fcpe_c,
        pesto_corrected=pesto_c,
        consensus_f0=consensus_f0,
        agreement_strength=agreement_strength,
        vote_count=vote_count,
        octave_corrections=octave_corr,
        note_intonation=note_intonation,
        viterbi_source=viterbi_source,
    )


def _build_consensus_f0(
    fcpe: np.ndarray,
    pesto: np.ndarray,
    vote_count: np.ndarray,
    bp_active_midi: np.ndarray,
    cents_agreement_threshold: float,
    *,
    hz_min: float = 65.0,    # ≈ C2; the lowest plausible vocal pitch
    hz_max: float = 1500.0,  # ≈ F#6; whistle-register sopranos still under this
) -> tuple[np.ndarray, np.ndarray]:
    """Build (consensus_f0, agreement_strength) from per-frame evidence.

    Decoupled from the strict `vote_count >= 2 AND <50¢` conjunction that
    Phase 0a used. Each frame produces:

      consensus_f0[i]       — Hz, or NaN if no F0 evidence usable
      agreement_strength[i] — float in [0, 1]:

        Both F0 voiced AND agree (<threshold¢):
          consensus = (fcpe + pesto) / 2
          strength scales linearly from 1.0 (perfect agreement) to 0.7
          (at threshold), then drops to the disagreement branch above it.

        Both F0 voiced AND disagree (≥threshold¢) AND anchor active:
          consensus = whichever F0 is closer (in cents) to the anchor
          strength = 0.4

        Single F0 voiced + anchor active:
          consensus = the voiced F0
          strength = 0.5

        Single F0 voiced, no anchor:
          consensus = the voiced F0
          strength = 0.25

        Otherwise (nothing voiced, vote vetoed, or agreed Hz out of range):
          consensus = NaN
          strength = 0.0

    The hz_min/hz_max clamp is the last-line defense against pathological
    "agreed on the same wrong octave" frames; it survives as a hard veto
    in every branch (consensus is replaced by NaN whenever the chosen Hz
    falls outside the range, and strength stays 0).

    `vote_count == 0` is treated as a hard veto regardless of fcpe/pesto
    being >0. This preserves the RMS-floor mute from `consensus_voicing`:
    a frame where the F0 estimators hallucinated voicing on silence (RMS
    below the floor) gets `vote_count = 0` and stays unvoiced here.
    """
    n = len(fcpe)
    out = np.full(n, np.nan, dtype=np.float32)
    strength = np.zeros(n, dtype=np.float32)

    for i in range(n):
        if vote_count[i] == 0:
            continue  # RMS-veto or nothing voted; leave NaN/0

        fcpe_v = fcpe[i] > 0
        pesto_v = pesto[i] > 0
        bp_active = bp_active_midi[i] >= 0

        if fcpe_v and pesto_v:
            cents_diff = 1200.0 * math.log2(fcpe[i] / pesto[i])
            if abs(cents_diff) < cents_agreement_threshold:
                # Strong: both F0 estimators agree.
                consensus = (float(fcpe[i]) + float(pesto[i])) / 2.0
                if hz_min <= consensus <= hz_max:
                    out[i] = consensus
                    # 1.0 at perfect agreement, 0.7 at threshold.
                    strength[i] = (
                        1.0 - (abs(cents_diff) / cents_agreement_threshold) * 0.3
                    )
            elif bp_active:
                # Disagreement; anchor breaks the tie by Hz proximity.
                bp_hz = midi_to_hz(int(bp_active_midi[i]))
                f_to_bp = abs(1200.0 * math.log2(fcpe[i] / bp_hz))
                p_to_bp = abs(1200.0 * math.log2(pesto[i] / bp_hz))
                chosen = float(fcpe[i] if f_to_bp <= p_to_bp else pesto[i])
                if hz_min <= chosen <= hz_max:
                    out[i] = chosen
                    strength[i] = 0.4
            # else: disagreement, no anchor → leave NaN/0 (defer to Step 4 Viterbi)

        elif fcpe_v and bp_active:
            if hz_min <= fcpe[i] <= hz_max:
                out[i] = float(fcpe[i])
                strength[i] = 0.5
        elif pesto_v and bp_active:
            if hz_min <= pesto[i] <= hz_max:
                out[i] = float(pesto[i])
                strength[i] = 0.5
        elif fcpe_v:
            if hz_min <= fcpe[i] <= hz_max:
                out[i] = float(fcpe[i])
                strength[i] = 0.25
        elif pesto_v:
            if hz_min <= pesto[i] <= hz_max:
                out[i] = float(pesto[i])
                strength[i] = 0.25

    return out, strength
