# `analyze/` — MusIQ-Lab pipeline driver

Wraps the validated 12-stage MIR pipeline (the original 8-stage validation core — its `sections` stage is deferred — plus identify / essentia / stems-dynamics / vocal-consensus / drums) with per-stem specialists (Phase A+B as of May 2026) behind a single CLI:

```bash
python -m analyze <mp3>
```

Produces `cache/<slug>/<slug>.jams` + `cache/<slug>/<slug>.summary.json`. See [`../docs/superpowers/specs/2026-04-29-analyze-py-design.md`](../docs/superpowers/specs/2026-04-29-analyze-py-design.md) for the original spec and [`../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md) for the Phase A+B additions.

## CLI

```bash
python -m analyze <mp3>                                    # full pipeline
python -m analyze <mp3> --stages-only transcription        # selective re-run (upstream cache must be valid)
python -m analyze <mp3> --from-stage transcription         # re-run from this stage onward
python -m analyze <mp3> --params-json /tmp/overrides.json  # per-stage param overrides
```

`--quiet` suppresses per-stage progress. `--force` invalidates all cached outputs. `--no-identify` and `--no-essentia` skip those second-opinion stages.

## Module layout

- `cli.py` / `__main__.py` — argparse entry
- `pipeline.py` — stage orchestration + error policy (required vs optional stages, soft-fail handling)
- `cache.py` — slug derivation, cache layout, staleness probes
- `stages/` — one module per pipeline stage; each runnable standalone via `python -m analyze.stages.<name> <mp3>`
  - `identify.py` — early-pipeline AcoustID (Chromaprint fingerprint via vendored `fpcalc`) + MusicBrainz → `cache/<slug>/identify.json`. After the May 2026 overhaul (SCHEMA=5): walker-based result iteration, silence-strip preprocessing, MB text-search fallback with `duration_variance < 0.03` guard, artist-plausibility gate with substring rescue, Unicode/smart-quote normalization, demotion protection. `--no-identify` disables the stage. Spec + per-round deltas: [`../docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md`](../docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md), [`../docs/superpowers/identify-overhaul/`](../docs/superpowers/identify-overhaul/)
  - `stems.py` — multi-model orchestrator: htdemucs_6s + htdemucs_ft + BS-RoFormer per preset; writes `stems_routing.json`
  - `beats.py` — madmom downbeats + tempo
  - `beats_xcheck.py` — beat-this (cross-check)
  - `key.py` — skey + librosa K-S fallback
  - `chords.py` — lv-chordia
  - `transcription.py` — router dispatching each harmonic stem to the appropriate transcriber: piano → ByteDance HR-Piano specialist; vocals/bass/guitar/other → basic-pitch
  - `transcription_basic.py` — basic-pitch helper (vocals / bass / guitar / other stems)
  - `transcription_piano.py` — ByteDance HR-Piano specialist (piano stem)
  - **(reverted 2026-05-04)** `transcription_vocals.py` shipped with WI-7 as a homegrown F0→notes specialist for the vocals stem; it had structural flaws on real audio (silently mis-labeled bimodal alternations, F0 octave-glitches surfacing as spurious notes) and was reverted after four iterative fix attempts each broke something different. Vocals now route through basic-pitch like the other non-piano stems. A proper F0→notes library (e.g. crepe-notes, pyin) is deferred to a Phase A+B follow-up and slots back into `TRANSCRIBERS["vocals"]` when chosen — see `docs/pipeline-changes-phase-ab.md` for the full narrative.
  - `drums.py` — ADTOF (full mix) for transcription; LarsNet for per-substem WAVs (kick/snare/toms/hihat/cymbals)
  - `vocal_f0.py` — torchfcpe + pesto; Phase 0c Step 1 plumbs `fcpe_conf` + `pesto_conf` per-frame confidence arrays
  - `stems_dynamics.py` — per-stem RMS envelope at 100 fps (feeds `vocal_consensus_contour`'s RMS-floor voicing veto)
  - `vocal_consensus_contour.py` — orchestrator stage that fuses FCPE / PESTO / basic-pitch into a `consensus_f0` Hz contour with per-frame `agreement_strength` ∈ [0, 1] for confidence-bucketed UI rendering. Also runs anchor pre-validation against F0 medians before octave correction (Phase 0c Step 3)
  - `essentia_extract.py` — second-opinion stage running Essentia's tempo / key / loudness extractors against the pipeline's analyze output. Cross-check function in `derived/agreement.py` flags ±1 BPM disagreements and 2-of-3 key-estimator dissent (krumhansl / temperley / edma), with a half/double-tempo annotation and relative-key (minor↔relative-major) carve-out so common metric / mode ambiguities don't fire false warnings. PyPI Essentia ships without `gaia2`, so the high-level SVMs (danceability / mood / voice-instrumental) degrade gracefully — see memory [[essentia_gaia2_gotcha]]
- `derived/` — pure music-theory transforms
  - `theory.py` — Roman numerals, key parsing, chord parsing, diatonic function, scale name
  - `loop_detect.py` — predominant chord loop
  - `note_enrichment.py` — per-note role / in_chord / scale_deg
  - `vocal_range.py` — low/high pitch from vocals MIDI; also `is_instrumental()` (BS-RoFormer vocals/instrumental RMS ratio < 0.15) which suppresses `vocal_range` on instrumental tracks where stem separators leak pitched non-vocal content
  - `vocal_consensus/` — primitives, voicing (2-of-3 + RMS floor veto), octave correction, per-note intonation, contour orchestrator, and (Step 4) Viterbi smoothing in `viterbi.py`. Spec: [`../docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md`](../docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md). Phase 0c Steps 1–4 shipped May 2026 with two follow-ups (silence-gate via FCPE voicing, canvas + RMS-modulated opacity render). Rec 4 (HNR voicing for the Cohen t=107.7s canary) remains deferred — see [`../install-logs/phase-0c-results-2026-05-05.md`](../install-logs/phase-0c-results-2026-05-05.md) for the full ship report including the "metric isn't a target" lesson
- `writers/` — JAMS + summary.json writers

## Per-stage params + selective re-run

Each stage that accepts parameters stores them in a sidecar JSON (e.g., `stems_6s/.params.json` for the stems stage). `cached()` invalidates when params or `schema_version` change, so swapping a model or threshold automatically triggers a re-run without `--force`.

- `--stages-only=transcription` (comma-separated) runs only the named stages. Their upstream outputs must already be cached — the flag does not re-run dependencies.
- `--from-stage=transcription` runs that stage and everything downstream (useful when fixing a late-stage bug without re-separating stems).
- `--params-json /tmp/overrides.json` accepts a `{stage_name: {param: value}}` dict merged on top of per-stage defaults. The params that actually ran are surfaced in `summary.provenance.per_stage_params`.

## Validation

Phase A+B ship-gate results are in [`../install-logs/phase-a-validation.md`](../install-logs/phase-a-validation.md). Status as of May 2026: **PARTIAL** — Gorillaz integration tests pass; full corpus validation (gates 2/3/4) is blocked pending either user-curated labels in `tests/corpus/labels/` or the deferred web-research-based agreement-check work (sketched at the end of `docs/pipeline-changes-phase-ab.md`). The harness scripts are in place; running the full corpus is one bash command once labels exist.

**Honest note:** the Phase A+B "code-correctness APPROVED" verdict in the validation report was overconfident. Tests passed and the pipeline ran end-to-end without crashing, but several real-audio bugs surfaced post-ship (vocals algorithm produced silently-wrong notes; a JAMS shape-mismatch crashed the writer until caught; an env-var ordering issue silently soft-failed drums). See `docs/history.md` Phase M for the post-ship correction narrative.

## Tests

```bash
pytest tests/        # ~570 tests (analyze unit + integration), no GPU required when cache is populated
```

`tests/` covers the analyze package only (~570). The full repo Python test count is ~1060 (~570 here + ~490 in `webui/tests/`); these drift constantly — `pytest tests/ --collect-only -q | tail -1` is the source of truth. The integration test (`tests/integration/test_gorillaz.py`) runs against the validated `cache/gorillaz_silent_running/` reference data.
