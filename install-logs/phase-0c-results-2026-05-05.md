# Phase 0c — Vocal Consensus Improvements — Results

**Date:** 2026-05-05
**Spec:** [`docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md`](../docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md)
**Status:** Steps 1–4 shipped to `main`. Step 5 (Rec 4 / HNR voicing) remains deferred per §7.

## Lesson learned the hard way: a metric isn't a target

The first Step 4 commit landed with `frames_with_finite_consensus_f0` at 98–99% on all three tracks and was *worse* in practice than the pre-Step-4 pipeline. Visual review caught what the metric missed: Viterbi's temporal smoothing was extending the contour through silent passages between vocal phrases, producing a continuous wandering line where the singer was clearly silent.

Root cause: the canonical "this frame is silent" signal in this pipeline is `consensus_voicing.vote_count == 0`, which folds in an RMS-floor veto. **That veto rarely fires on bleed-heavy stems** — the BS-RoFormer-cleaned vocals stem stays above the −45 dBFS floor during silent passages because of residual instrumental energy. PESTO compounds the problem by emitting continuous Hz values everywhere (no internal voicing detector), so the vote count stays at ≥1 throughout silent regions. Anchor-only voicing closes the trap: when basic-pitch hallucinates a vocal note from spectral residue, the anchor candidate (em ≈ 0.36) trivially beats the unvoiced state (em ≈ 4.6), and Viterbi's transition-cost smoothing produces a coherent wandering F0 path through silence.

**Fix:** the silence gate now triggers on `vote_count == 0 OR fcpe_corrected == 0`. FCPE has a proper internal voicing detector that produces genuine zero output on silent / breath / unvoiced-consonant frames; PESTO does not. Using FCPE as the primary voicing authority — and forcing every voiced slot (including the anchor) to `EMISSION_INF` for FCPE-says-silent frames — is the cleanest silence detector available without HNR. False negatives (singer voiced, FCPE missed) cost a 1-frame NaN gap that Viterbi's voicing-on transition recovers from immediately.

The metric `frames_with_finite_consensus_f0` should NOT have been tracked as "higher is better". For a slow ballad like Cohen, the right value is ~40–50%, not 99%. Successive runs without visual cross-checking would have drifted further from ground truth while looking better and better in the receipts.

## Headline metrics — before vs after

Three benchmark vocal-heavy tracks, captured before any Phase 0c change (`phase-0c-baseline-*.json`) and after each step landed (`phase-0c-step{2,3,4}-*.json`).

| Metric | Sting | Radiohead | Cohen |
|---|---|---|---|
| **Frames with finite consensus_f0** | | | |
| Baseline (pre-0c) | 60.2% | 60.8% | 36.5% |
| After Step 2 (decouple voicing) | 95.2% | 94.1% | 93.5% |
| After Step 3 (anchor pre-validation) | 95.2% | 94.1% | 93.5% |
| Step 4 first iteration (broken: extends into silence) | ~99% | ~99% | ~99% |
| **After Step 4 + silence-gate fix** | **64.8%** | **67.8%** | **49.4%** |
| **Voted-voiced frames killed by line filter** | | | |
| Baseline | 9.0% | 14.3% | 38.2% |
| After Step 2 | 5.1% | 5.8% | 8.9% |
| After Step 3 | 5.1% | 5.8% | 8.9% |
| **After Step 4 + silence-gate fix** | **0.7%** | **2.0%** | **10.4%** |

The post-fix `finite_consensus_f0` numbers are now in the right neighborhood for what these tracks actually contain (Sting and Radiohead: vocals on most of the song; Cohen: ~50% silence between phrases). The Cohen kill rate of 10.4% is the singing-frame coverage gap where vote_count ≥ 2 was reached but FCPE stayed unvoiced — typically breath / soft-onset frames; tolerable per visual review.

## Architecture changes shipped

- **Step 1** (commit `7ac29c3`): `vocal_f0` plumbs `fcpe_conf` + `pesto_conf` through the npz; `SCHEMA_VERSION` 1→2; backward-compat fallback in `load()` synthesizes confidence from voicing mask for v1 caches.
- **Step 2** (commit `5139044`): `_build_consensus_f0` returns `(consensus_f0, agreement_strength)`; renderer overhauled to three opacity buckets in `f0-overlay.js`; `STRENGTH_*_CUT` exposed in `f0-prefs.js`. Stage `SCHEMA_VERSION` 2→3.
- **Step 3** (commit `0f2e435`): in-memory anchor pre-validation against F0 medians in `vocal_consensus_contour.run()`; no schema bump (DEFAULT_PARAMS additions shift sidecar fingerprint, forcing re-run). Validator deviates from spec pseudocode after empirical iteration; final shape encodes asymmetric harmonic-lock rules (see commit message).
- **Step 4** (this commit): Viterbi smoothing as the default `consensus_f0` builder. New `analyze/derived/vocal_consensus/viterbi.py` (~280 LOC). 8-state candidate space (`fcpe`/`pesto`/×½/×2 each + anchor + unvoiced). Forward-pass vectorized over states, looped over frames. `agreement_strength` slot now carries `exp(−emission_cost)` instead of heuristic buckets (see spec §5 semantic-shift note). Step 2's `_build_consensus_f0` retained as `viterbi_enabled=False` fallback for A/B + emergency rollback. `viterbi_source` int8 array carried in-memory on `ContourResult` for diagnostics; not serialized (schema stays at 3).

## Step 4 deviations from spec § 4

Two design choices departed from the spec pseudocode after empirical iteration on synthetic clips and the benchmarks:

1. **Skipped explicit dedupe within ±15¢** in candidate building. The spec proposed a per-frame Python-loop pass that merges candidates within 15¢ and applies a tie-breaker (anchor proximity > non-shifted > confidence). The Viterbi state machine encodes the same prior at the cost-function layer: an anchor's own state plus the `prev=anchor → curr=candidate` transition (zero cents jump → zero cost) implements the "anchor-aligned candidate wins" intent without the per-frame scan. Vectorizes cleanly.

2. **`CENTS_NORMALIZER = 300` instead of spec's 100.** The spec value (100) made a fifth-leap (700¢) cost `(700/100)² = 49`, which exceeds the cost of an unvoiced detour around the leap (`λ_voicing_off + λ_voicing_on + unvoiced_emission ≈ 10.6`). Viterbi rejected genuine wide vocal leaps as "too suspicious" and inserted NaN gaps. With `N=300`, a fifth = 5.4 (well under detour) and an octave = 21+5 (with bump) = 26 (well over detour). The threshold lands between a major-seventh and an octave, matching the spec's design intent: "wide melodic leap → follow; octave-glitch → suspect (mark unknown)."

3. **Anchor-proximity emission bonus**, with the anchor's *own* slot excluded. The spec's discrete dedupe-tie-breaker is implemented as a continuous Gaussian bonus in emission cost (`anchor_prox_bonus = 1.0`, `anchor_prox_sigma = 100¢`). Empirically tested by the Cohen 107.7s canary: an early version applied the bonus to all slots including the anchor itself, which caused the anchor candidate to dominate when it disagreed with full-confidence F0 estimators. Excluding the anchor slot from receiving its own bonus fixed this without breaking any synthetic test — the bonus is conceptually about *pulling F0 candidates toward the anchor*, not about boosting the anchor against the F0s; the anchor's confidence (0.7) already encodes its credibility.

These deviations, plus the Step 3 validator's empirical refinement, are documented inline in the affected modules.

## Cohen 107.7s canary — known limit

The spec called out the t=107.7s case (target 87 Hz / F2; YIN: 87, FCPE: 175, PESTO: 349, basic-pitch: silent) as the headline falsifiable test. After Step 4 ships, the canary lands at **349 Hz** — same as Step 3, no regression.

Inspection (`install-logs/_phase_0c_step4_canary_inspect.py` against the Cohen cache) reveals why this case is architecturally unfixable in Step 4 alone:

```
Notes overlapping [107.40s, 108.01s]:
  start=107.286s  end=109.261s  midi=65  hz=349.2  vel=67   ← basic-pitch hallucination
  start=107.648s  end=108.600s  midi=60  hz=261.6  vel=55   ← basic-pitch hallucination
  start=107.670s  end=108.227s  midi=69  hz=440.0  vel=59   ← basic-pitch hallucination
```

basic-pitch hallucinates **three simultaneous notes at the 3rd, 4th, and 5th harmonics** of the 87 Hz fundamental. FCPE consistently locks at the 2nd harmonic (175 Hz). PESTO mostly tracks the 4th (349 Hz), occasionally the 5th (440 Hz).

**Every input stream is above the true fundamental.** The only candidate at 87 Hz in the Viterbi state space is `FCPE/2 = 87.5 Hz`, which carries the half-confidence shift penalty and gets no anchor support (the anchors are all 1200+¢ away). There is no path to truth without auxiliary information.

This is exactly the failure mode Rec 4 (HNR-based voicing) addresses, deferred per spec §7 resolution. The current Step 4 result preserves Step 3's behavior here (no regression) while delivering the headline metrics.

## What's deferred

- **Rec 4 / HNR voicing**: bass-baritone fundamental disambiguation. Re-evaluate after Step 4 lands on real listening tests.
- **Step 5 final visual validation**: the user's webUI walkthrough on each benchmark track. Recommend before declaring Phase 0c complete.

## Files of record

- `install-logs/phase-0c-baseline-{sting,radiohead,cohen}.json`
- `install-logs/phase-0c-step{2,3,4}-{sting,radiohead,cohen}.json`
- Diagnostic scripts: `install-logs/_phase_0c_baseline.py`, `_phase_0c_step{2,3,4}_rerun.py`, `_phase_0c_step4_canary_inspect.py`
- Test surface: 428 analyze unit + 237 webui server + 107 webui js = **772 tests passing** (up from 751 at Step 3 baseline; +14 Viterbi unit tests + 5 contour Viterbi-flow tests + 2 silence-gate unit tests)
