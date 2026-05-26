# Phase C — Structural layer: sections, modulations, time signatures, tempo curves

**Date:** 2026-05-03
**Effort:** ≈2 weeks
**Depends on:** [Phase B](phase-b-pipeline-architecture.md) (selective re-run + sidecars — required to iterate on segmenter params without rewinding the whole pipeline)
**Status:** Sketch — full spec to be written when Phase A+B ships.

## Goal

Fill the missing structural layer that turns the app from a "feature extractor" into a music-analysis tool. The current `summary.json` warning `sections deferred — no segmenter installed` is the single most-felt gap when a musician opens a song in the webui.

## Scope

**In:**

- **Section segmenter** — output `[{"start", "end", "label"}]` covering the full track. Labels at minimum: `intro / verse / chorus / bridge / outro / instrumental`. Approach: start with **MSAF** (Music Structure Analysis Framework) for boundary detection + a heuristic labeler over chord/tempo/loudness features. Upgrade to a neural segmenter (Mehta-2024 / SALAMI-trained CRNN) if MSAF underperforms on the corpus.
- **Per-section key tracking** — re-run the key detector per section, smooth across boundaries with a confidence-weighted HMM. Surface modulations explicitly (`{"section": "bridge", "key": "Bb:major", "modulation_from": "G:major"}`).
- **Time-signature detection** — replace hard-coded `beats_per_bar=[3,4]`. Approach: cluster inter-downbeat intervals after madmom's RNN activation, infer most-likely TS per section. Handle 6/8, 12/8, mixed-meter cases.
- **Per-bar tempo curve** — already implicit in `beat-this`'s output; persist it. Surface accelerando/ritardando in summary stats.
- **Modulation detection** — derived from per-section key.

**Out:**

- Lyrics alignment (separate concern; tracked elsewhere).
- Mood / genre tags (out of scope for the analysis stack; can be a separate plugin).
- Tonal center other than major/minor (modal labels — Phrygian, Mixolydian, etc. — are a Phase D extension, dependent on confidence signals).

## Deliverables

1. **`analyze/stages/sections.py`** (new) — segmenter + labeler.
2. **`analyze/stages/key.py`** — extended for per-section operation when section data is present.
3. **`analyze/stages/beats.py`** — time-signature output added.
4. **`analyze/derivation.py`** (or wherever the pipeline's derivation step lives) — modulation detection.
5. **Webui** — new section track in the piano-roll, a key-modulation strip below the chord track.
6. **Tests** with a labeled subset of the corpus annotated for sections + modulations.

## Validation criteria

- Section boundary F1 ≥ 0.7 on a labeled subset (5–10 hand-annotated tracks).
- Modulation detection: 100% precision on a curated set of known-modulating tracks (better to miss a modulation than to fabricate one).
- Time signature: correct labels on the existing 5-track corpus + an additional 5 tracks with diverse meters (waltz, swing, 6/8 ballad, prog).

## Open questions

- **MSAF vs. neural segmenter**: decide after a Phase 0 benchmark on a small labeled corpus. MSAF is faster to integrate (Python, mature), neural is potentially more accurate but adds a model dependency.
- **Section labels**: the safer initial output is just boundaries + numbered sections (`A`, `B`, `A'`, `C`). Named labels (`verse`, `chorus`) require either learned classification or a heuristic over chord progressions and stem energies. Probably ship boundaries first, named labels in a second iteration.
