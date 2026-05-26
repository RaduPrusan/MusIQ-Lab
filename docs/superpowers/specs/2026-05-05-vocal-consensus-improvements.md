# Vocal Consensus Pipeline — Phase 0c Improvements

**Date:** 2026-05-05
**Status:** Plan, not yet implemented
**Supersedes:** Stateless per-frame F0 fusion in `analyze/derived/vocal_consensus/`

This document is a **resumable implementation plan**. A fresh session can pick this up by reading the "Current State" section, checking which steps have been completed, and continuing from the first incomplete step.

---

## 1. Background

The vocal consensus pipeline (Phase 0a + 0b, shipped 2026-05-05) fuses three pitch-evidence streams into a "trustworthy" vocal F0 contour for the webUI piano-roll overlay:

- **basic-pitch** (Spotify ICASSP-2022 CNN) — `cache/<slug>/midi/vocals.mid`
- **FCPE** (torchfcpe neural F0) — `cache/<slug>/vocal_f0.npz['fcpe']`, ~100 fps
- **PESTO** (self-supervised CQT F0) — `cache/<slug>/vocal_f0.npz['pesto']`, same shape

Output: `cache/<slug>/vocal_consensus.npz` (with `consensus_f0`, `vote_count`, `octave_corrections`, etc.) + `vocal_consensus.json` (per-note intonation).

A diagnostic agent run on three vocal-heavy tracks (`sting-shape_of_my_heart...`, `radiohead_creep_heads_on_the_radio`, `leonard_cohen_in_my_secret_life`) on 2026-05-05 produced an empirical baseline. Key findings:

| Metric | Sting | Radiohead | Cohen |
|---|---|---|---|
| Frames with finite consensus_f0 | 60.2% | 60.8% | **36.5%** |
| Voted-voiced frames killed by line filter | 9.0% | 14.3% | **38.2%** |
| In-range octave-split frames (FCPE/PESTO 1200±100¢ apart) | 248 | 831 | 1,350 |
| Of those, basic-pitch silent (uncorrectable by current design) | 92% | 90% | **82%** |

Three architectural problems:

1. **Hidden contract bug**: `voicing.py:122-123` says vote=2 if any 2-of-3 evidence streams agree. `contour.py:158` then requires both F0 voiced AND <50¢ disagreement — a stricter rule that kills 38% of voted-voiced frames on bass-baritone material. This is the dominant cause of "discontinuous, breaks mid-phrase".
2. **Anchor-only octave correction**: `octave.py:118-120` skips frames with no basic-pitch anchor. 80–92% of in-range octave splits happen in unanchored frames. Structurally untouched.
3. **Stateless per-frame logic**: No temporal smoothing. The pipeline cannot distinguish "real octave leap in melody" from "single-frame estimator glitch" — they look identical at frame N. Standard MIR practice (pYIN since 2014, CREPE-notes, Melodia) uses Viterbi smoothing for exactly this.

A separately-considered surface fix (`maximum_frequency=1500` cap on basic-pitch's vocal predictions) was rejected by the user because it doesn't help: most octave jumps happen below it.

## 2. Goals & non-goals

### Goals (Recs 1+2+3+5 from the diagnostic report)

- **Rec 5** — plumb FCPE/PESTO per-frame confidence through `vocal_f0.npz` (foundational; Rec 1 needs it)
- **Rec 2** — decouple consensus-line voicing from vote-count rule; emit `agreement_strength` for renderer (small fix; immediate visible improvement)
- **Rec 3** — pre-validate basic-pitch notes against F0 medians before they become anchors (closes the "poisoned anchor" failure mode at the source)
- **Rec 1** — replace `_build_consensus_f0` with a Viterbi pass over per-frame F0 candidates with octave-aware transition penalties (the deep fix)

### Non-goals (deferred)

- **Rec 4** (loosening 50¢ agreement gate; HNR-based voicing instead of RMS) — useful polish, not on critical path
- Segmentation-based work (deferred per earlier scope reset)
- Removing the existing defensive caps (`max_abs_octave_shift=1`, `hz_min/hz_max` clamp) — they're cheap insurance, keep them as last-line defense
- Changing the per-note intonation module (`intonation.py`) — its strict 50¢ gate is appropriate for that job
- basic-pitch hyperparameters in `transcription_basic.py` — not touching `maximum_frequency` per user direction

### Success criteria

After all four recommendations land, the same diagnostic against the same three tracks should show:

| Metric | Today | Target |
|---|---|---|
| Sting finite consensus_f0 | 60.2% | ≥ 90% |
| Radiohead finite consensus_f0 | 60.8% | ≥ 85% |
| Cohen finite consensus_f0 | 36.5% | ≥ 80% |
| Cohen voted-voiced frames killed | 38.2% | ≤ 5% |
| In-range octave splits remaining post-pipeline | 184 / 555 / 979 | < 50 / < 100 / < 200 |
| Visual review on Cohen | "all over the place" | continuous, octave-stable |

The Cohen ground-truth case at t=107.7s (YIN: 87 Hz; FCPE: 175 Hz; PESTO: 349 Hz; basic-pitch: silent) **must** end up tracking the 87 Hz fundamental after Viterbi lands, or the architecture failed.

## 3. Current state

As of 2026-05-05 (Phase 0c Steps 1–4 shipped, plus two post-Step-4 follow-ups):

- ✅ Phase 0a complete: primitives, voicing (with RMS floor gate), octave correction (with `max_abs_octave_shift=1` cap), per-note intonation
- ✅ Phase 0b complete: orchestrator, RMS envelope stage, vocal_consensus_contour stage, server endpoints, webUI rendering with three contour toggles (consensus / FCPE / PESTO)
- ✅ **Step 0 done** (commit `8ea89d0`): baseline diagnostics + this spec committed.
- ✅ **Step 1 done** (commit `7ac29c3`): `vocal_f0` plumbing for `fcpe_conf` + `pesto_conf`. PESTO emits real per-frame confidence; FCPE uses a binary mask synthesized from `f0 > 0`. Schema 1 → 2.
- ✅ **Step 2 done** (commit `5139044`): `_build_consensus_f0` returns `(consensus_f0, agreement_strength)`. Three-bucket render path. Schema 2 → 3.
- ✅ **Step 3 done** (commit `0f2e435`): anchor pre-validation. **The committed rule diverges from this section's pseudocode in three empirically motivated ways** — see "Step 3 final rule shape" subsection below.
- ✅ **Step 4 done** (commit `3b0d8b7`): Viterbi smoothing. New `analyze/derived/vocal_consensus/viterbi.py` (~280 LOC). 8-state candidate space (FCPE/PESTO/×½/×2 each + anchor + unvoiced); transition cost quadratic-in-cents with Gaussian bump at 1200¢; anchor-proximity Gaussian emission bonus. Schema stays at 3 (Viterbi reuses `agreement_strength` slot for `path_confidence`). Step 2's `_build_consensus_f0` retained as `viterbi_enabled=False` fallback. Step 4 deviated from spec §4 in three documented ways (skipped explicit ±15¢ dedupe, `CENTS_NORMALIZER=300` not 100, anchor excluded from its own proximity bonus) — see commit message + `install-logs/phase-0c-results-2026-05-05.md`.
- ✅ **Step 4 silence-gate follow-up** (commit `413fa02`): the first Step 4 commit pushed `finite_consensus_f0` to ~99% on all three tracks but visual review caught Viterbi extending the contour through silence between phrases. Root cause: the canonical `vote_count == 0` silence signal rarely fires on bleed-heavy stems (residual instrumental energy keeps RMS above the −45 dBFS floor; PESTO has no internal voicing detector). Fix: silence gate triggers on `vote_count == 0 OR fcpe_corrected == 0` — FCPE has a real voicing detector. Post-fix benchmark numbers (below) match what the tracks actually contain.
- ✅ **Canvas refactor + RMS opacity** (commit `06a34e3`): F0 overlay refactored from SVG to canvas to support per-frame variable opacity along the contour. Vocals-stem RMS modulates opacity; strength-bucket info preserved as line-width modulation. New tunables in `f0-prefs.js` (`RMS_DB_FLOOR/CEIL`, `RMS_OPACITY_FLOOR/CEIL`).
- 🟡 **Rec 4 (HNR voicing) deferred** per §7 resolution. The Cohen t=107.7s canary still lands at 349 Hz post-Step-4 — basic-pitch hallucinates three simultaneous notes at the 3rd/4th/5th harmonics, FCPE locks at the 2nd, PESTO at the 4th; **every input stream is above the true 87 Hz fundamental**, so no Viterbi state-space path can reach truth without auxiliary information. Re-evaluate after real listening tests.
- 🟡 **Step 5 final visual walkthrough**: the user's per-track sanity check in the webUI on Sting / Radiohead / Cohen. The metric-vs-truth lesson (see follow-up above) makes this load-bearing — automated metrics are no longer trusted as the sole gate.

Test surface after the canvas refactor:
**~426–428 analyze unit + 237 webui server + ~119 webui js = 784 tests passing** (the canvas refactor added 6 `rmsToOpacity` unit tests + 4 server `vocals_rms` shape tests + 1 track-data test on top of Step 4's 14 Viterbi + 5 contour-flow + 2 silence-gate tests).

Headline benchmark metrics — full Phase 0c arc:

| Metric | Baseline | Step 2 | Step 3 | Step 4 (post silence-gate) |
|---|---|---|---|---|
| Sting finite_consensus_f0 | 60.2% | 95.2% | 95.2% | **64.8%** |
| Radiohead finite_consensus_f0 | 60.8% | 94.1% | 94.1% | **67.8%** |
| Cohen finite_consensus_f0 | 36.5% | 93.8% | 93.5% | **49.4%** |
| Sting voted-voiced killed | 9.0% | 5.1% | 5.1% | **0.7%** |
| Radiohead voted-voiced killed | 14.3% | 5.8% | 5.8% | **2.0%** |
| Cohen voted-voiced killed | 38.2% | 8.9% | 8.9% | **10.4%** |

**Read this carefully:** the Step 4 finite_consensus_f0 numbers are *lower* than Step 2/3 not because Step 4 regressed, but because Step 4 + silence-gate correctly assigns silence to NaN. For Cohen (slow ballad, ~50% silence between phrases), the right value is ~50%, not 99%. The pre-Step-4 numbers were inflated by the line filter producing values across silent regions. See `install-logs/phase-0c-results-2026-05-05.md` "Lesson learned the hard way" for the full narrative — this is the most important Phase 0c discovery and must inform any future tuning.

### Step 3 final rule shape (committed code; supersedes §4 Step 3 pseudocode)

The committed validator at `analyze/stages/vocal_consensus_contour.py::_validate_anchor_notes` evolved through three diagnostic-driven refinements during implementation. The original spec pseudocode dropped Cohen anchors at 39%, far above the 5–15% target. Final shape:

1. Both medians within ±50¢ of MIDI: keep.
2. **At least one** median within ±50¢ of MIDI: keep — the other has its own glitch which `correct_octaves` downstream will fold using this anchor. Dropping here defeats octave correction.
3. Estimators disagree with each other: keep (uncertainty — defer to Step 4 Viterbi when it lands).
4. Estimators agree on same PC, evidence **below** basic-pitch: octave-correct (real basic-pitch over-octave error).
5. Estimators agree on same PC, evidence **above** basic-pitch: keep — F0 estimators rarely sub-harmonic-lock, so an upward octave shift is almost always 2nd-harmonic lock (common on low voices), not a real basic-pitch error. Asymmetric correction.
6. Estimators agree on different PC at integer harmonic ratio (3rd, 5th, 7th): keep — harmonic-lock signature, not hallucination.
7. Estimators agree on different PC, |delta| < 7 semitones: keep — too small to poison `correct_octaves` (which only fires on octave-multiple matches); likely note-boundary timing artifact.
8. Estimators agree on different PC, |delta| ≥ 7, non-harmonic: drop.

Empirical results post-refinement: Sting 4.4% drops, Radiohead 6.9%, Cohen 16.0% (within or just over the 5–15% target). Corrections 5.0% / 5.4% / 5.0%. Kill rates basically unchanged from Step 2 (Sting 5.1%, Radiohead 5.8%, Cohen 8.9%).

A resumable session checks completion of each step below by inspecting whether the listed files have been modified vs the baseline at this date.

## 4. Phased implementation plan

Each step lists: files to modify, algorithmic specifics, tests to add, verification criteria, rollback notes.

**Effort estimate (focused work, single implementer):**

| Step | Description | Estimate |
|---|---|---|
| 0 | Pre-flight + baseline diagnostics | ~0.5 day |
| 1 | F0 confidence plumbing | ~1 day |
| 2 | Decouple consensus_f0 + agreement_strength | ~1 day |
| 3 | Anchor pre-validation | ~1 day |
| 4 | Viterbi + parameter tuning | ~3–5 days |
| 5 | End-to-end validation + commit | ~1–2 days |

Total: roughly **one focused week + 1–2 days for validation/polish**, with most variance concentrated in Step 4 Viterbi parameter calibration. The plan is structured so Steps 1–3 each ship independently; if Step 4 hits unexpected tuning depth, the project still benefits from the upstream fixes already in main.

---

### Step 0 — Pre-flight

**Purpose:** establish baseline before changes; verify environment.

1. Confirm 690 tests pass on a fresh checkout:
   ```bash
   wsl bash -c 'cd "<PROJECT_WSL_PATH>" && source .venv/bin/activate && python -m pytest tests/unit/ -q --ignore=tests/integration | tail -3'
   ./.venv/Scripts/python.exe -m pytest webui/tests -q | tail -3   # webui server
   cd webui && node --test "tests-js/*.test.js" | tail -8         # webui js
   ```
2. **Unconditionally** re-run the diagnostic snapshot on Sting / Radiohead / Cohen (use the queries from §1) and save outputs as `install-logs/phase-0c-baseline-<track>.json`. These files are the receipts that prove Step 4 worked; do not skip even if the §1 numbers "look right" — Step 5's before/after comparison reads from these JSON files, not from this document.
3. Note: the empirical baseline above was taken when basic-pitch's `max_anchor_midi=95` filter applied via `vocal_consensus_contour.py:51` (so anchors at 90–95 still leaked through). This is unchanged.

**Verification:** all three test surfaces green, baseline metrics match §1 within ±1% (random-seed-free, deterministic numbers).

**Rollback:** N/A; this is read-only.

---

### Step 1 — Recommendation 5: F0 confidence plumbing

**Purpose:** capture per-frame confidence from FCPE and PESTO so downstream stages (Step 4 Viterbi especially) can do weighted soft evidence instead of binary voting. Foundational change, additive only.

#### Files to modify

- `analyze/stages/vocal_f0.py` — main change
- `tests/unit/test_vocal_f0.py` — add round-trip tests (create file if absent)

#### Algorithmic specifics

**FCPE confidence:** torchfcpe's `infer()` returns the F0 array with unvoiced frames set to 0 by an internal threshold (`threshold=0.006` at line 55). The pre-threshold confidence is what we want. Two approaches:

- **Preferred**: call `infer()` twice — once with `threshold=0` (gives raw F0 always) and once with the production threshold (gives the voiced/unvoiced gating). Confidence is then a derived quantity: 1.0 where the thresholded version is voiced, smoothly down to 0 elsewhere. Compute via the ratio of pre/post-threshold or via a small wrapper around the decoder.
- **Alternative**: clone the FCPE inference call to expose confidence directly. May require reading torchfcpe internals; check `spawn_bundled_infer_model` and decoder path.

If the decoder doesn't expose confidence cleanly, a pragmatic substitute: use the binary voiced/unvoiced mask as confidence (1.0 voiced, 0.0 unvoiced). Less informative but still better than the current code which throws even that away.

**PESTO confidence:** the call at line 59 is:
```python
_, f0_pesto, _, _ = pesto.predict(audio_cpu, sr=16000, step_size=10.0, inference_mode="cqt")
```
The four return values are (timestamp, f0, confidence, activations). **Position 3 is confidence.** Just capture it instead of discarding. Returns float array same shape as f0_pesto.

**Schema bump:**

```python
SCHEMA_VERSION = 2  # was 1; bumped for confidence arrays

# vocal_f0.npz now contains:
#   fcpe        — (n_frames,) float32 Hz, 0 = unvoiced
#   pesto       — (n_frames,) float32 Hz
#   fcpe_conf   — (n_frames,) float32 in [0, 1]    NEW
#   pesto_conf  — (n_frames,) float32 in [0, 1]    NEW
```

The `load()` function returns the new keys. Old caches without confidence arrays must continue to work — `load()` should fall back to deriving confidence from the voiced/unvoiced mask:

```python
def load(cache_dir):
    z = np.load(cache_dir / CANONICAL_NPZ)
    fcpe = z["fcpe"]
    pesto = z["pesto"]
    fcpe_conf = z["fcpe_conf"] if "fcpe_conf" in z.files else (fcpe > 0).astype(np.float32)
    pesto_conf = z["pesto_conf"] if "pesto_conf" in z.files else (pesto > 0).astype(np.float32)
    summary = json.loads(...)
    return {**summary, "fcpe_array": fcpe, "pesto_array": pesto,
            "fcpe_conf_array": fcpe_conf, "pesto_conf_array": pesto_conf}
```

The `cached()` function must invalidate on schema version mismatch (it already does this via the sidecar — just bumping `SCHEMA_VERSION` triggers re-run).

#### Tests

- `test_vocal_f0_writes_confidence_arrays`: run the stage on a tiny synthetic clip, verify the npz has `fcpe_conf` and `pesto_conf` keys.
- `test_vocal_f0_load_with_old_npz_falls_back_gracefully`: create a v1-format npz (no conf keys) and verify `load()` synthesizes them from voiced mask.
- `test_vocal_f0_confidence_is_high_on_clean_voicing`: synthetic sine input → confidence near 1.0 in voiced regions.
- `test_vocal_f0_confidence_is_zero_in_silence`: silence in → confidence near 0.0.

#### Verification

- Stage re-runs on existing tracks (sidecar invalidation triggers it).
- Resulting npz files contain the four arrays.
- Downstream stages (`vocal_consensus_contour`) still load successfully (no breakage).
- Run on the three benchmark tracks; record `fcpe_conf` and `pesto_conf` distributions for use in Step 4 Viterbi tuning.

#### Rollback

- Revert `vocal_f0.py` changes; old caches still valid.
- Bump `SCHEMA_VERSION` back to 1; sidecar invalidation re-runs (compatible because confidence arrays were additive).

---

### Step 2 — Recommendation 2: decouple consensus_f0 from vote-count + agreement_strength

**Purpose:** stop the line-render filter from being stricter than the voicing filter. Output a per-frame `agreement_strength` scalar (not just NaN-or-Hz) so the renderer can show the contour with confidence-modulated opacity instead of disappearing entirely.

This is the **immediate-visible-improvement** step. Should ship and be reviewable within an afternoon.

#### Files to modify

- `analyze/derived/vocal_consensus/contour.py` — main algorithmic change
- `analyze/stages/vocal_consensus_contour.py` — pass through new array to disk
- `tests/unit/test_vocal_consensus_contour.py` — extend tests
- `tests/unit/test_vocal_consensus_contour_stage.py` — extend tests
- `webui/webui/f0.py` — decode new array
- `webui/tests/test_f0.py` + `webui/tests/test_server.py` — extend tests
- `webui/static/js/data/track-data.js` — load new array
- `webui/static/js/render/f0-overlay.js` — render with strength-modulated opacity
- `webui/tests-js/track-data.test.js` — extend test

#### Algorithmic specifics

Replace `_build_consensus_f0` with two outputs: a **single F0 line** that uses the best available evidence per frame, and an **agreement_strength** scalar in [0, 1] that says how trustworthy that frame's F0 is.

```python
def _build_consensus_f0(
    fcpe_corrected, pesto_corrected, vote_count, basic_pitch_active_midi,
    cents_agreement_threshold,
    *,
    hz_min=65.0, hz_max=1500.0,
):
    """
    Returns:
      consensus_f0       — (n_frames,) float32 Hz; NaN where no F0 available at all
      agreement_strength — (n_frames,) float32 in [0, 1]
    """
    out = np.full(n, np.nan, dtype=np.float32)
    strength = np.zeros(n, dtype=np.float32)

    for i in range(n):
        fcpe_v = fcpe_corrected[i] > 0
        pesto_v = pesto_corrected[i] > 0
        bp_active = basic_pitch_active_midi[i] >= 0

        if fcpe_v and pesto_v:
            cents_diff = 1200 * log2(fcpe[i] / pesto[i])
            if abs(cents_diff) < cents_agreement_threshold:
                # Strong: both F0 estimators agree
                consensus = (fcpe[i] + pesto[i]) / 2
                if hz_min <= consensus <= hz_max:
                    out[i] = consensus
                    # Strength scales inversely with cents_diff up to threshold
                    strength[i] = 1.0 - (abs(cents_diff) / cents_agreement_threshold) * 0.3
                    # → 1.0 at perfect agreement, 0.7 at threshold
            else:
                # Estimators disagree on octave or note. If basic-pitch is active,
                # use the F0 closer to its pitch (octave-wise).
                if bp_active:
                    bp_hz = midi_to_hz(basic_pitch_active_midi[i])
                    f_to_bp = abs(1200 * log2(fcpe[i] / bp_hz))
                    p_to_bp = abs(1200 * log2(pesto[i] / bp_hz))
                    chosen = fcpe[i] if f_to_bp < p_to_bp else pesto[i]
                    if hz_min <= chosen <= hz_max:
                        out[i] = chosen
                        strength[i] = 0.4   # Medium: anchor breaks tie
        elif fcpe_v and bp_active:
            # Only FCPE voiced, anchor present
            if hz_min <= fcpe[i] <= hz_max:
                out[i] = fcpe[i]
                strength[i] = 0.5
        elif pesto_v and bp_active:
            if hz_min <= pesto[i] <= hz_max:
                out[i] = pesto[i]
                strength[i] = 0.5
        elif fcpe_v and pesto_v == False:
            # Only FCPE, no anchor — weak evidence
            if hz_min <= fcpe[i] <= hz_max:
                out[i] = fcpe[i]
                strength[i] = 0.25
        elif pesto_v:
            if hz_min <= pesto[i] <= hz_max:
                out[i] = pesto[i]
                strength[i] = 0.25
        # else: no F0 estimator voiced; out stays NaN, strength stays 0

    return out, strength
```

The strength buckets are intentional and renderer-meaningful:

- **0.7–1.0 (strong)** — both F0 agree; render at full opacity (white, sharp)
- **0.4–0.6 (medium)** — only one F0 + anchor, or both disagree but anchor breaks tie; render dimmed
- **0.1–0.3 (weak)** — single F0, no anchor; render very dim (or hidden if user prefers)
- **0.0** — NaN F0; no line

#### Schema additions

`ContourResult` dataclass gains `agreement_strength: np.ndarray`.

`vocal_consensus.npz` gains an `agreement_strength` key. Bump the stage's `SCHEMA_VERSION` from **2 to 3** — the file already sits at 2 from a prior vocal-MIDI-range filter bump (`vocal_consensus_contour.py:39`); a fresh "1 → 2" would no-op the sidecar invalidation and silently keep stale caches. Confirm the live constant before bumping.

#### Frontend changes

`webui/webui/f0.py:decode_f0`:
```python
out["consensus"] = {
    ...
    "agreement_strength": [
        0.0 if not np.isfinite(s) else float(s)
        for s in agreement_strength[:cn]
    ],
}
```

`webui/static/js/data/track-data.js`: load `agreement_strength` as Float32Array.

`webui/static/js/render/f0-overlay.js`: change `_buildConsensusPaths` from binning by `vote_count` (3 vs 2) to binning by `agreement_strength`:

```javascript
// Three buckets, three paths:
//   strong:  strength >= STRENGTH_STRONG_CUT  (default 0.7)
//   medium:  STRENGTH_MEDIUM_CUT <= strength < STRENGTH_STRONG_CUT  (default 0.4)
//   weak:    STRENGTH_WEAK_CUT   <= strength < STRENGTH_MEDIUM_CUT  (default 0.1)
// Frames with strength < STRENGTH_WEAK_CUT break the pen (NaN-equivalent).
```

Three SVG path elements with three opacity values. Z-order: weak underneath (so it doesn't dominate), strong on top.

**Bucket cuts as prefs, not constants.** Define `STRENGTH_STRONG_CUT`, `STRENGTH_MEDIUM_CUT`, `STRENGTH_WEAK_CUT` in `webui/static/js/music/f0-prefs.js` (the file already exists, untracked). This way:
- Step 4's Viterbi confidence distribution can be re-tuned without a code edit (per the §5 semantics-shift note).
- Power users can tighten/loosen the visual hierarchy.
- The defaults stay 0.7 / 0.4 / 0.1 and are not exposed in the sidebar UI yet — adding a UI toggle is a Step 5 tail item, not a Step 2 requirement.

Do not add a "show weak frames" sidebar toggle — bake the visual hierarchy into the buckets via opacity. The user can hide weak frames by raising `STRENGTH_WEAK_CUT` in prefs.

#### Interaction with the existing median-MIDI smoother

`webui/static/js/render/f0-overlay.js` already exports `medianMidiOver()` — a window-median smoother that operates in log-Hz space and is exercised by `webui/tests-js/f0-overlay-smooth.test.js`. Bucket paths and the smoother need to compose correctly:

- **Smoothing must not cross bucket boundaries.** If the median window straddles a frame at strength=0.9 and a neighbor at strength=0.3, the *smoothed* Hz value at the lower-strength frame will reflect the higher-strength neighborhood — that's fine *if* it stays in the same bucket path. But if the renderer picks bucket membership from the raw `agreement_strength[i]` and Hz from the smoothed array, the strong-bucket SVG path can suddenly jump to a frame that's also drawn (dimmer) on the medium-bucket path. Visually: a bright dot orphaned from the strong segment.
- **Decision rule:** for each frame, compute the bucket from `agreement_strength[i]` *first*, then run the smoother *within each bucket's frame set* (treating other buckets' frames as gaps the smoother ignores). The existing `medianMidiOver` already gracefully handles NaN/zero gaps — pass a per-bucket masked array.
- **Test:** add a `f0-overlay-smooth.test.js` case that mixes high-strength and low-strength frames in the same window and verifies the smoothed Hz at a high-strength frame is computed only from other high-strength frames.

#### Tests

- Extend `test_vocal_consensus_contour.py`: `test_agreement_strength_strong_when_both_f0_agree`, `test_agreement_strength_medium_when_anchor_breaks_tie`, `test_agreement_strength_weak_when_only_one_f0`, `test_agreement_strength_zero_when_all_unvoiced`.
- Extend `test_vocal_consensus_contour_stage.py`: `test_npz_contains_agreement_strength`.
- Extend `webui/tests/test_f0.py`: verify `agreement_strength` in API response.
- Extend `webui/tests-js/track-data.test.js`: verify `agreement_strength` is Float32Array.
- (Optional) extend `webui/tests-js/f0-prefs.test.js` if any pref change.

#### Verification

- Run on Cohen track. Re-check the kill-rate metric: should drop from 38% to under 5% (because frames with one-F0-only no longer get killed).
- Visual: in webUI, Cohen vocals should show a continuous line (with dim sections) instead of a fragmented one.
- The 690-test suite still passes.

#### Rollback

- `_build_consensus_f0` change is local; revert in one diff.
- Schema bump means old caches re-run; that's expected and reversible.
- Frontend changes are isolated to `f0-overlay.js` and consumers of `f0.consensus.agreement_strength`.

---

### Step 3 — Recommendation 3: anchor pre-validation

**Purpose:** stop basic-pitch's wrong-octave or hallucinated-pitch notes from poisoning octave correction. Before any anchor-based logic runs, validate each note against F0 medians and either correct or drop.

Independent of Steps 1, 2, 4. Could run before or after them; placed here because it cleans inputs to Step 4 Viterbi.

#### Files to modify

- `analyze/stages/vocal_consensus_contour.py` — add `_validate_anchor_notes` helper called inside `run()` between loading bp_notes and passing to `process_contour`
- `tests/unit/test_vocal_consensus_contour_stage.py` — add tests with synthetic glitched anchors

#### Algorithmic specifics

```python
def _validate_anchor_notes(
    bp_notes,            # list of pretty_midi.Note objects
    fcpe, pesto,         # raw (pre-correction) F0 arrays
    fcpe_conf, pesto_conf,  # confidence arrays from Step 1
    fps,
    *,
    min_validation_frames=5,
    confidence_threshold=0.4,
):
    """
    For each anchor note, check whether the F0 evidence over its span
    agrees with its MIDI pitch.

    Decision tree per note:
      1. Compute median FCPE Hz and median PESTO Hz over the note's middle 60%
         (skip attack/release transients), restricted to confident frames.
      2. If fewer than min_validation_frames confident frames: keep note
         unchanged (no evidence to validate against).
      3. If both medians present:
         a. Compute cents from each median to the note's MIDI integer.
         b. If both medians agree with MIDI within ±50¢: keep unchanged.
         c. If both medians disagree by an integer multiple of 1200¢
            (octave error): correct the note's pitch by that octave delta.
         d. If both medians disagree on the SAME pitch class (different
            octave) but unanimously: correct.
         e. Otherwise (medians inconsistent with each other and with MIDI):
            DROP the note from the anchor list (do NOT remove from MIDI
            on disk; just exclude from anchor evidence).
      4. If only one median present (other estimator unconfident):
         - Use it as a single witness; require ±50¢ agreement to keep,
           otherwise drop.

    Returns: filtered, possibly octave-corrected list of notes for use as
    anchors. The original midi/vocals.mid file is not modified.
    """
```

Two output decisions:

- **Corrected anchor list** — passed to `process_contour` for octave correction and Viterbi candidate generation
- **Dropped notes** — logged as warnings in the stage summary; included as "rejected_anchors" count in `vocal_consensus.json` for transparency

The validation rules are conservative (require unanimity from F0 estimators) so a noisy F0 estimator can't drop a correct note. The dropped-anchor counts on benchmark tracks should be small (estimated <5% based on the diagnostic numbers).

#### Tests

- `test_anchor_at_correct_pitch_is_kept` — both F0 agree with MIDI → no change.
- `test_anchor_one_octave_off_gets_corrected` — both F0 unanimously say MIDI−12 → note's `.pitch` is reduced by 12 in the returned list (original MIDI file untouched).
- `test_anchor_with_unrelated_pitch_is_dropped` — F0 say a totally different note → dropped from anchors.
- `test_anchor_with_only_one_confident_f0_uses_single_witness` — single-witness fallback works.
- `test_short_anchor_with_no_validation_frames_kept_unchanged` — sub-5-frame note returns as-is.

#### Verification

- On benchmark tracks: count notes dropped vs kept. Should be small (under 5%) on Sting/Radiohead, somewhat higher (5–15%) on Cohen.
- Run downstream consensus stage; in-range octave-split metric should improve modestly (not as much as Step 4 will, but visibly — this protects against the worst-case anchor failures).
- 690-test suite still passes.

#### Rollback

- Single helper function added to one file. Revert in one diff. No schema change.

---

### Step 4 — Recommendation 1: Viterbi pass over F0 candidates

**Purpose:** the deep fix. Replace stateless per-frame consensus_f0 building with a Viterbi smoothing pass that picks one F0 per frame from a candidate set, using temporal continuity as a free additional anchor.

This is the largest change — multi-day implementation. After it lands, `_build_consensus_f0` (the function modified in Step 2) becomes a *fallback* used only when Viterbi is disabled or fails.

#### Files to modify

- **NEW** `analyze/derived/vocal_consensus/viterbi.py` — algorithm implementation (~150-250 LOC)
- `analyze/derived/vocal_consensus/contour.py` — call Viterbi instead of (or before) the Step 2 builder; keep Step 2's builder as named fallback
- `tests/unit/test_vocal_consensus_viterbi.py` — synthetic tests
- `tests/unit/test_vocal_consensus_contour.py` — integration tests with Viterbi

#### Algorithmic specifics

##### Per-frame candidate set

For each frame i, build candidates:

```python
candidates = []
if fcpe[i] > 0 and hz_min <= fcpe[i] <= hz_max:
    candidates.append(("fcpe", fcpe[i], fcpe_conf[i]))
if pesto[i] > 0 and hz_min <= pesto[i] <= hz_max:
    candidates.append(("pesto", pesto[i], pesto_conf[i]))
# Octave-shifted variants — recovers from estimator octave glitches
for hz, conf, source in [(fcpe[i], fcpe_conf[i], "fcpe"), (pesto[i], pesto_conf[i], "pesto")]:
    if hz > 0:
        for shift in (-1, +1):
            shifted = hz * (2.0 ** shift)
            if hz_min <= shifted <= hz_max:
                candidates.append((f"{source}×2^{shift}", shifted, conf * 0.5))
                # Penalty: shifted candidates start with half confidence
# Anchor candidate — basic-pitch note as Hz
if basic_pitch_active_midi[i] >= 0:
    bp_hz = midi_to_hz(basic_pitch_active_midi[i])
    if hz_min <= bp_hz <= hz_max:
        candidates.append(("anchor", bp_hz, 0.7))   # fixed confidence
# Unvoiced state — always present
candidates.append(("unvoiced", None, 0.0))

# Deduplicate: candidates within ±15¢ of each other merge.
# Tie-breaker (in order):
#   1. Prefer the candidate whose Hz is closest to the active anchor (if any),
#      so a wrong-octave full-conf candidate cannot crowd out the correct
#      shifted half-conf candidate that landed near the anchor.
#   2. If no anchor (or equidistant): prefer non-shifted over shifted.
#   3. If still tied: prefer higher confidence.
# This deliberately overrides naive "max conf wins" — the failure mode is
# FCPE (or PESTO) octave-locked at full confidence; we want temporal
# continuity (handled below by Viterbi) AND anchor proximity (handled here)
# to outvote raw confidence on the dedupe step.
```

Cap candidates per frame at K=8 (more is rarely useful and slows Viterbi).

##### State space and costs

State = candidate index (or "unvoiced" sentinel).

**Emission cost** at frame i, state s: `−log(max(conf[s], ε))` where ε = 0.01 to avoid log(0).

**Transition cost** from state s_prev at frame i−1 to state s_curr at frame i:

```python
def transition_cost(prev_hz, curr_hz, *, was_voiced, is_voiced):
    if not was_voiced and not is_voiced:
        return 0.0  # free to stay unvoiced
    if not was_voiced and is_voiced:
        return LAMBDA_VOICING_ON      # ~3.0
    if was_voiced and not is_voiced:
        return LAMBDA_VOICING_OFF     # ~3.0
    # Both voiced: penalty scales with cents jump, with bonus penalty on octaves
    cents = abs(1200 * log2(curr_hz / prev_hz))
    base = LAMBDA_FREQ * (cents ** 2) / (CENTS_NORMALIZER ** 2)   # quadratic in cents
    octave_bump = LAMBDA_OCTAVE * exp(-((cents - 1200) ** 2) / (OCTAVE_SIGMA ** 2))
    return base + octave_bump
```

Suggested initial parameters (to be calibrated against benchmark tracks):

```python
LAMBDA_FREQ = 1.0              # quadratic-in-cents penalty scale
CENTS_NORMALIZER = 100.0       # cost of 1.0 at a 1-semitone jump (before octave bump)
LAMBDA_OCTAVE = 5.0            # extra cost peak at exactly 1200¢
OCTAVE_SIGMA = 150.0           # width of octave-jump penalty band (¢)
LAMBDA_VOICING_ON = 3.0
LAMBDA_VOICING_OFF = 3.0
```

The octave bump is critical: a smooth quadratic in cents alone wouldn't distinguish a 1200¢ (octave glitch) from a 1500¢ (real pitch jump in a melodic leap, rare but possible). The Gaussian peak at 1200¢ explicitly suppresses the octave-glitch transition while leaving room for genuine wide leaps.

##### Forward pass

Standard Viterbi:

```python
costs = np.full((n_frames, K_max), np.inf)
backpointers = np.full((n_frames, K_max), -1, dtype=np.int32)

# Frame 0: emission cost only
for s in range(K_max):
    costs[0, s] = emission_cost[0, s]

for i in range(1, n_frames):
    for s in range(K_max):
        em = emission_cost[i, s]
        # Best predecessor
        best_prev_cost = np.inf
        best_prev_s = -1
        for s_prev in range(K_max):
            t = transition_cost(...)
            total = costs[i-1, s_prev] + t
            if total < best_prev_cost:
                best_prev_cost = total
                best_prev_s = s_prev
        costs[i, s] = em + best_prev_cost
        backpointers[i, s] = best_prev_s

# Backtrack from frame n−1's argmin
path = backtrack(costs, backpointers)
```

Vectorize with numpy: at each frame, compute the (K × K) transition cost matrix and (K × K) total = costs[i-1, :, None] + trans + emission[i, None, :]. Take argmin along axis 0.

##### Output

```python
def viterbi_smooth(
    fcpe, pesto, fcpe_conf, pesto_conf,
    basic_pitch_active_midi, fps,
    *, hz_min=65.0, hz_max=1500.0,
    # ... weight kwargs
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
      f0_path           — (n_frames,) float32 Hz; NaN where unvoiced state chosen
      path_confidence   — (n_frames,) float32 in [0, 1]
      candidate_source  — (n_frames,) int8: 0=fcpe, 1=pesto, 2=fcpe_shifted,
                           3=pesto_shifted, 4=anchor, 5=unvoiced
    """
```

`path_confidence` is `exp(−emission_cost_at_chosen_state[i])` clamped to [0, 1]. This becomes the `agreement_strength` field from Step 2 (replacing the heuristic buckets with the actual Viterbi confidence).

##### Integration with Step 2

In `contour.py`, the orchestrator becomes:

```python
def process_contour(...) -> ContourResult:
    fcpe_c, pesto_c, octave_corr = correct_octaves(...)
    vote_count = consensus_voicing(...)

    # NEW: Viterbi pass replaces _build_consensus_f0
    bp_active = _build_basic_pitch_frame_lookup(bp_notes_validated, n_frames, fps)
    consensus_f0, agreement_strength, source = viterbi_smooth(
        fcpe_c, pesto_c, fcpe_conf, pesto_conf,
        bp_active, fps,
    )

    note_intonation = per_note_intonation(...)
    return ContourResult(
        ...,
        consensus_f0=consensus_f0,
        agreement_strength=agreement_strength,
        viterbi_source=source,        # NEW field for diagnostics
    )
```

Keep Step 2's `_build_consensus_f0` as a fallback callable, accessible via a `viterbi_enabled` flag for A/B comparison and emergency rollback.

**Flag location:** add `viterbi_enabled: bool = True` to `DEFAULT_PARAMS` in `analyze/stages/vocal_consensus_contour.py`. This puts it in the sidecar (so flipping it invalidates the cache and forces re-run, which is what we want for A/B), gives it a default value in one place, and lets tests override it via the standard `**params` pathway. Plumb it through `process_contour(..., viterbi_enabled=p["viterbi_enabled"])` and branch inside `process_contour` between Step 4's Viterbi and Step 2's `_build_consensus_f0`.

#### Tests

Synthetic clip tests (extend `_vocal_synth.py` if needed):

- `test_viterbi_recovers_from_single_frame_octave_glitch`: clean F0 with one frame doubled → Viterbi picks the un-glitched neighbor based on transition cost.
- `test_viterbi_picks_anchor_when_F0_disagree`: FCPE+PESTO disagree, anchor available → Viterbi picks the F0 closer to anchor.
- `test_viterbi_uses_temporal_continuity_when_anchor_silent`: stable F0 with no anchor for several frames; Viterbi maintains the path.
- `test_viterbi_allows_genuine_wide_pitch_leap`: F0 actually leaps a fifth; Viterbi follows (cost should be < cost of 1200¢ glitch).
- `test_viterbi_handles_unvoiced_gaps`: silence between voiced regions; Viterbi cleanly transitions on/off.
- `test_viterbi_uses_octave_shifted_candidates`: FCPE consistently 2× too high but PESTO correct; Viterbi prefers the FCPE/2 candidate.

Empirical validation: re-run on the three benchmark tracks. Confirm metrics from §2 success criteria.

#### Verification

- Cohen ground-truth case at t=107.7s: F0 path lands near 87 Hz (bass-baritone fundamental), not the harmonic-locked 175/349 Hz.
- In-range octave-split count drops to <50/<100/<200 across tracks.
- Cohen finite consensus_f0 ratio reaches ≥80%.
- 690-test suite still passes (existing tests; their scope doesn't intersect with new Viterbi paths).

#### Rollback

- `viterbi_enabled=False` flag falls back to Step 2's `_build_consensus_f0`.
- Single new file (`viterbi.py`) is removable.
- `contour.py` change is a single conditional path.

---

### Step 5 — Final validation and ship

**Purpose:** end-to-end verification + documentation.

1. Re-run the diagnostic snapshot from §1 on all three benchmark tracks. Compare numbers against §2 success criteria.
2. Visual review in webUI: load each track, verify the consensus contour is continuous and octave-stable.
3. Run full test suite end-to-end (analyze unit + webui server + webui js).
4. Update `analyze/derived/vocal_consensus/__init__.py` docstring with the new architecture.
5. Update `CLAUDE.md` if architectural notes mention the consensus pipeline.
6. Write a brief follow-up note in `install-logs/phase-0c-results-<date>.md` with before/after numbers.
7. Single commit per logical step (Steps 1, 2, 3, 4 each as their own commit). Final commit is the validation note.

---

## 5. Cross-cutting concerns

### Schema versioning

Two schema bumps land in this work:

- `vocal_f0.SCHEMA_VERSION`: 1 → 2 (Step 1 adds confidence arrays)
- `vocal_consensus_contour.SCHEMA_VERSION`: **2 → 3** (Step 2 adds agreement_strength). The file is currently at 2, not 1 — the prior vocal-MIDI-range filter bumped it (`vocal_consensus_contour.py:39`). Read the constant at implementation time and bump *the live value* by 1; do not hard-code "3" in case another bump lands first. Unchanged through Steps 3-4 (Viterbi reuses the agreement_strength slot for path_confidence — see "agreement_strength semantics" below).

### `agreement_strength` semantics across Step 2 vs Step 4

The same `agreement_strength` array (and same `npz` slot) carries different meanings before vs after Step 4:

- **After Step 2, before Step 4 lands:** four-bucket heuristic (1.0 / 0.5 / 0.25 / 0.0) derived from how many evidence streams agreed. Renderer cuts at 0.7 / 0.4 / 0.1.
- **After Step 4 lands:** continuous `exp(−emission_cost)` from the Viterbi forward pass. Distribution may not match the bucket boundaries.

The renderer cuts (and any consumers binning on strength) **must be re-validated** on benchmark tracks immediately after Step 4. If the Viterbi distribution is bimodal or skewed, expose the cuts as user prefs (Step 5 tail) rather than re-tuning constants.

Both bumps trigger automatic re-run via the existing sidecar invalidation mechanism. Old caches re-run cleanly on next analysis.

### Cache invalidation chain

Re-running `vocal_f0` triggers re-run of `vocal_consensus_contour` (`STAGE_DEPS["vocal_consensus_contour"] = {"vocal_f0", "transcription"}`). Re-running `vocal_consensus_contour` doesn't re-run anything else (it's a leaf stage).

### Test surface to watch for regressions

- `tests/unit/test_stage_deps.py` — modify if STAGE_DEPS changes (Step 1, 2, 4 don't change deps; safe).
- `tests/unit/test_vocal_consensus_*.py` — extend, don't break.
- `webui/tests/test_f0.py`, `test_server.py` — extend for new fields.
- `webui/tests-js/track-data.test.js` — extend for new array.
- The deferred (`[DEFERRED]`) tasks remain deferred; this work doesn't unblock them.

### Performance budget

- Step 1 (FCPE re-call with threshold=0): doubles FCPE inference time (~1-2s per track). Acceptable.
- Step 4 (Viterbi): O(n_frames × K²). At 18000 frames × 64 states² = 1.1M ops, sub-second in numpy.

Total stage runtime increase: estimated under 3 seconds per track. Negligible relative to the 30s+ MIR pipeline.

### Risk surface

- **Step 1 highest risk to FCPE access patterns.** torchfcpe's API may not expose confidence cleanly; the workaround (binary mask as confidence) is a known good fallback.
- **Step 4 highest risk to algorithmic correctness.** Viterbi parameter calibration is non-trivial; under-penalize transitions and Viterbi mirrors the noisy input, over-penalize and it kills real pitch jumps. Mitigation: extensive synthetic-clip tests + benchmark-track validation before changing the default `viterbi_enabled` flag.
- **Step 2 lowest risk.** Local change, easy to reason about, immediate empirical verification (the Cohen kill-rate metric).

## 6. Resume protocol for a fresh session

A fresh Claude Code session picking up this work should:

1. Read this document end-to-end.
2. Check the current state of each step by inspecting files:
   - Step 1 done if `analyze/stages/vocal_f0.py` has `fcpe_conf` and `pesto_conf` written to the npz, and `SCHEMA_VERSION = 2`.
   - Step 2 done if `analyze/derived/vocal_consensus/contour.py` has `agreement_strength` in `ContourResult` and `_build_consensus_f0` returns a tuple.
   - Step 3 done if `analyze/stages/vocal_consensus_contour.py` has `_validate_anchor_notes` defined and called in `run()`.
   - Step 4 done if `analyze/derived/vocal_consensus/viterbi.py` exists.
3. Run the test suite from §3 to confirm baseline.
4. Pick up at the first incomplete step.
5. After each step, update §3 of this document with completion checkmark and date.

If the agent's diagnostic numbers (§1) need re-confirming, the queries are reproducible — see the agent dispatch transcript in conversation history (date 2026-05-05) for the exact diagnostic Python.

## 6.5 Deferred work (as of post-Step-4 + canvas-refactor)

Phase 0c shipped Steps 1–4 with two follow-ups (silence-gate fix, canvas + RMS opacity refactor). What remains:

**Rec 4 (HNR-based voicing)** — deferred per §7 resolution. The Cohen t=107.7s canary lands at 349 Hz post-Step-4: basic-pitch hallucinates three simultaneous notes at the 3rd/4th/5th harmonics, FCPE locks at the 2nd, PESTO at the 4th — every input stream is above the true 87 Hz fundamental, so no Viterbi state-space path reaches truth without auxiliary voicing information. Re-evaluate after real listening tests motivate the additional dependency. Detailed rationale in `install-logs/phase-0c-results-2026-05-05.md` "Cohen 107.7s canary — known limit".

**Step 5 final visual walkthrough** — the user's per-track webUI walkthrough on each benchmark track. Recommend before declaring Phase 0c fully complete. The post-Step-4 silence-gate fix demonstrated that automated metrics alone are insufficient — visual review caught the "wandering line through silence" failure mode that `frames_with_finite_consensus_f0` rated as a 99% improvement.

---

## 7. Open questions for user judgment

- **Default agreement-strength rendering thresholds** (Step 2): the proposed 0.7 / 0.4 / 0.1 boundaries are heuristic. Consider asking the user for visual review before committing.
- **Viterbi tuning** (Step 4): the suggested λ values are a starting point. May need 1-2 iterations of tuning on benchmark tracks. Worth letting the user see initial results before locking parameters.
- **Whether to keep `_build_consensus_f0` as fallback** after Step 4 ships: code health argument for removal once Viterbi is proven; safety argument for keeping a 30-line fallback indefinitely. User's call.
- **Whether to chain into Recommendation 4** (HNR voicing) after Step 5 lands: addresses different failure modes, complementary not redundant. User's call after seeing Step 5 results.

**Resolved 2026-05-05:** Rec 4 stays deferred to post-Step 5. The "loosen the 50¢ gate" half of Rec 4 evaporates anyway once Step 2 turns the threshold into a strength multiplier. The HNR-voicing half is a separate axis (estimator quality, not algorithmic structure) and bundling it with Steps 3–4 would entangle two calibration-heavy redesigns into one validation cycle — losing the per-step causal attribution that's the main reason for phasing. Re-evaluate after Step 5 lands and the residual failure modes are visible against a Viterbi-smoothed baseline.
