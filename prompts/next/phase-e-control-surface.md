# Phase E — Control surface: advanced settings, presets, A/B compare

**Date:** 2026-05-03
**Effort:** ≈1.5 weeks
**Depends on:** [Phase A+B](phase-a-specialist-models.md) (specialist models + selective re-run) and [Phase D](phase-d-confidence-signals.md) (confidence signals to surface in the UI).
**Status:** Sketch — full spec to be written after Phase A+B ships and confidence signals are in.

## Goal

The advanced-settings modal that started this conversation. With Phases A–D in place, the modal does real work: knobs that control specialist models, selective re-run that keeps iteration fast, confidence signals that tell the user where to focus, and presets that capture known-good parameter bundles per use case.

## Scope

**In:**

- **Tabbed advanced settings** inside both the Analyze and Reanalyze modals. Tabs: **Stems**, **Beats**, **Key/Chords**, **Transcription**, **Drums**, **Sections**.
- **Per-stage knobs** matching the Phase A pipeline:
  - Stems: model choice (htdemucs_6s / htdemucs_ft / BS-RoFormer / Mel-RoFormer / ensemble), `shifts`, `overlap`.
  - Transcription per-stem: onset/frame thresholds, min note length, min/max frequency, melodia trick, transcriber choice (basic-pitch / ByteDance / F0→notes for vocals).
  - Drums: per-substem onset thresholds, gate dB, optional grid quantization.
  - Sections: segmenter sensitivity, named-vs-numbered labels.
  - Key/Chords: vocab, smoothing strength.
- **"Re-run only…" multi-select** that maps to Phase B's `--stages-only`. Huge iteration speed-up.
- **Named presets** — known-good parameter bundles per use case. E.g. *"Singer-songwriter"*, *"Lush production"*, *"Aggressive piano"*, *"Drum-light"*, *"Acoustic"*. Each preset is a small JSON file in `webui/presets/`. User can save custom presets too.
- **Persistence** — last-used per-track params saved alongside the cache (`cache/<slug>/.user_params.json`). Modal opens populated with last-used.
- **A/B compare mode** — run the same track with two parameter sets, render both outputs in the piano-roll for direct visual comparison. This is what makes tuning feel real.

**Out:**

- Inventing new MIR algorithms in the modal. The modal exposes what Phases A–D produce.
- Cross-track preset application ("apply these settings to all jazz tracks"). YAGNI for v1.

## Deliverables

1. **`webui/static/js/ui/analyze-advanced.js`** (new) — tabbed advanced-settings panel as a collapsible section in the existing modal.
2. **`webui/presets/`** (new directory) — bundled named presets.
3. **`webui/static/js/ui/analyze-ab-compare.js`** (new) — A/B compare overlay in the track view.
4. **`webui/webui/server.py`** — analyze + reanalyze endpoints accept the full param payload.
5. **`webui/webui/analyze_runner.py`** — forwards param payload to the WSL command line.
6. **`analyze/__main__.py`** — accepts `--params-json <path>` for the full param bundle (cleaner than dozens of CLI flags).
7. **E2E tests** — Playwright spec covering modal open → advanced toggle → tweak → re-run → verify only intended stage changed.

## Validation criteria

- Reanalyze with default settings is unchanged from current behavior.
- Tweaking a transcription threshold and clicking "Re-run transcription only" finishes in seconds (not minutes).
- A/B compare correctly stores and renders two output sets.
- Presets load and save round-trip cleanly.
- Per-track persistence: closing and reopening the modal shows the user's last-used settings for that track.

## Risks

- **UI density** — six tabs of knobs is intimidating. Mitigation: keep the modal in "simple mode" (just quality preset + a checkbox to expose advanced) by default. Power users opt in.
- **Param-bundle versioning** — a saved preset that references models/params no longer in the pipeline must fail gracefully. Add a `compatibility` field to preset JSON and version-check at load.
