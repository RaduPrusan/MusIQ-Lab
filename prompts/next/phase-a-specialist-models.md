# Phase A — Specialist models everywhere it matters

**Date:** 2026-05-03
**Effort:** ≈2 weeks
**Depends on:** nothing (current pipeline is the baseline)
**Bundled with:** [Phase B](phase-b-pipeline-architecture.md) — same spec, same PR series
**Spec:** [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md)

## Goal

Replace generalist models with task-specialist models at every stage where a specialist materially outperforms the generalist. The user-visible payoff is a dramatic improvement on the cases that motivated this work (lush sustained piano like JVKE "Golden Hour", vocal pitch detection on real recordings, drum velocity realism).

## Scope

**In:**

- **Stems orchestrator** — per-stem best-of-breed routing instead of "one model fits all six stems":
  - **Vocals**: BS-RoFormer (`model_bs_roformer_ep_317_sdr_12.9755.ckpt`) — already produced, currently unused downstream. SDR ~12.9 vs htdemucs ~9.4 on MUSDB.
  - **Drums + Bass + Other**: `htdemucs_ft` (fine-tuned 4-stem variant) — typically ~0.5 dB SDR over `htdemucs_6s` for these stems.
  - **Guitar**: `htdemucs_6s` (only separator that produces a guitar stem — `htdemucs_ft` is 4-stem only).
  - **Piano**: `htdemucs_6s` (only separator with a piano stem; no better option exists yet for separation — but transcription is where the real gain lives).
  - Optional **Ultra** preset that ensembles two separators per stem.

- **Piano transcription specialist** — ByteDance High-Resolution Piano Transcription (Kong et al. 2021, `piano_transcription_inference` on PyPI). 96% F1 on MAPS vs basic-pitch's ~80%. Routed onto piano content (mix or piano stem; benchmark which works better on this corpus).

- **Vocal F0 → notes** — proper note-segmenter built on the existing FCPE+PESTO consensus. Vibrato handling, voicing gates, semitone snapping with confidence-weighted decisions. Replaces basic-pitch's vocal MIDI entirely (basic-pitch was never built for sustained singing).

- **Drum transcription** — ADTOF (Carsault et al. 2022; PyPI `adtof`) replaces the current `librosa.onset.onset_detect` + amplitude-proxy velocity on LarsNet substems. Real velocity modeling. Optional grid-quantized output as a sibling artifact.

- **basic-pitch** kept as fallback for guitar / bass / "other" (no clear specialist for those).

**Out:**

- Beat tracker swap (current `madmom + beat-this` is already SOTA — no upgrade exists).
- Chord recognizer swap (lv-chordia is decent; SOTA gain is ~3-5% MIREX, not worth the integration cost relative to other phases).
- Key / time-signature / sections / tempo curves — these are Phase C.
- Confidence signal extraction — that's Phase D.
- UI surfacing of new model choices — that's Phase E.

## Deliverables

1. **`analyze/stages/stems.py`** — refactored into a multi-model orchestrator. Old behavior preserved as the `htdemucs_6s_only` legacy branch for cache compatibility during migration.
2. **`analyze/stages/transcription.py`** — refactored to a router that picks per-stem transcribers. basic-pitch retained for stems without specialists.
3. **`analyze/stages/transcription_piano.py`** (new) — ByteDance HR-Piano wrapper.
4. **`analyze/stages/transcription_vocals.py`** (new) — F0→notes module reading the FCPE+PESTO arrays.
5. **`analyze/stages/drums.py`** — ADTOF integrated. LarsNet substem-WAV emission preserved (the webui reads them back).
6. **`scripts/install-bytedance-piano.sh`** (new) — fetches model weights, mirrors `install-larsnet.sh` shape.
7. **`scripts/benchmark-stems-quality.sh`** (new) — A/B harness measuring stems output across model combinations on a labeled corpus subset.
8. **Tests** updated for the new module boundaries. Golden-output tests for the 5-track validation corpus get refreshed baselines.
9. **`docs/history.md`** — chronicle entry per the project's existing convention.
10. **`install-logs/phase-a-validation.md`** — measured improvements vs the April 2026 baseline.

## Validation criteria

- The 5-track corpus from [`install-logs/batch-test-results.md`](../../install-logs/batch-test-results.md) re-runs without regressions on `key`, `bpm`, `chord_count`, `downbeat_count`.
- **Golden Hour** (JVKE) piano `note_count` improves by ≥2× vs the basic-pitch baseline (this is the explicit user-reported failure case).
- **Vocal pitch agreement** (FCPE-vs-PESTO at 50¢) on a sustained-vocals track (Olivia Dean) improves by ≥10% via the new F0→notes pipeline outputting cleaner MIDI.
- Drum onset F1 on the labeled drum tracks improves over the librosa baseline; phantom-onset rate on the Bach orchestral case stays at 0.
- Stems quality presets still satisfy `cached()` correctly; the legacy branch handles existing caches without forcing reanalysis.

## Risks

- **ByteDance HR-Piano** expects 16 kHz mono; needs a resample wrapper. Memory footprint ~2 GB on GPU — fits in 24 GB but watch for VRAM accumulation across stages (lv-chordia already has this kind of leak; see `chords.py` comments).
- **ADTOF** is older code, may have dependency conflicts with Torch 2.7 (the project's pinned ceiling). Validate install before committing to the integration.
- **`htdemucs_ft`** download is large (~80 MB per stem-source). Add to install script with checksum, not to the runtime path.
- **F0→notes** is a new algorithm in this codebase. Edge cases: rapid melisma, breathy passages where voicing is borderline, spoken-word over music. The spec includes a calibration pass on a small labeled subset.
