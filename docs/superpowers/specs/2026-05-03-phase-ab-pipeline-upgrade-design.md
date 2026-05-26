# Phase A+B — Pipeline upgrade: specialist models + selective re-run

**Date:** 2026-05-03
**Status:** Design spec — implementation-ready. Self-contained for execution in a fresh session.
**Roadmap:** [`prompts/next/README.md`](../../../prompts/next/README.md)
**Effort:** ≈3 weeks (Phase A: ~2w, Phase B: ~1w; bundled because they share cache + pipeline-driver work)
**Execution:** `claude-agent-sdk` ralph loops with reviewer subagents — see [Execution plan](#execution-plan).

---

## 1. Context

### Where we are

The MusIQ-Lab analyze pipeline (validated April 2026, batch-tested on 5 mixed-genre tracks per [`install-logs/batch-test-results.md`](../../../install-logs/batch-test-results.md)) runs eight stages in sequence:

| # | Stage | Module | Models | Cache invalidation |
|---|---|---|---|---|
| 1 | Stems | [`analyze/stages/stems.py`](../../../analyze/stages/stems.py) | `htdemucs_6s` (6 stems) + `bs_roformer_ep_317` (vocals/instrumental, gate use only) | **`.params.json` sidecar** ✓ |
| 2 | Beats | [`analyze/stages/beats.py`](../../../analyze/stages/beats.py) | madmom `RNNDownBeat` + `DBNDownBeatTracking` | output-presence only |
| 3 | Key | [`analyze/stages/key.py`](../../../analyze/stages/key.py) | `skey` (deezer/skey) + librosa-KS fallback | output-presence only |
| 4 | Chords | [`analyze/stages/chords.py`](../../../analyze/stages/chords.py) | lv-chordia (CNN+BiLSTM ensemble) | output-presence only |
| 5 | Transcription | [`analyze/stages/transcription.py`](../../../analyze/stages/transcription.py) | `basic-pitch` (ICASSP 2022) on all 5 melodic stems | output-presence only |
| 6 | Beats x-check | [`analyze/stages/beats_xcheck.py`](../../../analyze/stages/beats_xcheck.py) | `beat-this` `final0` | output-presence only |
| 7 | Vocal F0 | [`analyze/stages/vocal_f0.py`](../../../analyze/stages/vocal_f0.py) | FCPE + PESTO consensus | output-presence only |
| 8 | Drums | [`analyze/stages/drums.py`](../../../analyze/stages/drums.py) | LarsNet substems + `librosa.onset.onset_detect` | schema-version sidecar ✓ |

### Honest gap analysis

Three categories of weakness motivate this work:

1. **Transcription is generalist where specialists exist.** `basic-pitch` is a single model used for vocals, bass, guitar, piano, and "other". It is mediocre on lush sustained piano (e.g. JVKE "Golden Hour"), worse on sustained vibrato-heavy singing, and was never designed for polyphonic real recordings. Specialists exist:
   - **ByteDance High-Resolution Piano Transcription** (Kong et al. 2021): ~96% F1 on MAPS vs basic-pitch's ~80% on the same.
   - **F0→notes** (own implementation on top of FCPE+PESTO): the existing F0 stage already produces a cleaner pitch curve than basic-pitch can extract for vocals; we just don't quantize it into notes.
   - **ADTOF** (Carsault et al. 2022): a CRNN trained on multi-dataset drum data; consistently outperforms onset-detection-on-substems.

2. **Stems leave the better signal on the floor.** BS-RoFormer is already running on every track and produces a vocals stem that is meaningfully cleaner than htdemucs's (SDR ~12.9 vs ~9.4 on MUSDB), but the transcription stage reads vocals from `stems_6s/`, not `stems_bsroformer/`. Additionally, `htdemucs_ft` (fine-tuned variant) outperforms `htdemucs_6s` on drums/bass/guitar by ~0.5 dB SDR for a one-pass cost.

3. **Cache is all-or-nothing.** Tuning a basic-pitch threshold currently means a full reanalyze (~5 min/track because stems re-runs). The `stems` stage already has a `.params.json` sidecar pattern that invalidates on param drift; no other stage does. The pattern needs to be generalized so the upcoming Phase E modal can offer "tune this stage, re-run only this stage" iteration.

### Why bundle A and B

Phase A (specialist models) without Phase B (per-stage params + selective re-run) is unusable. Every transcription tweak to evaluate the new piano specialist would rewind the stems pass. The two phases share the same files (`analyze/pipeline.py`, every `analyze/stages/*.py`, `webui/webui/analyze_runner.py`); splitting them means double-touching every file. Bundle.

---

## 2. Goals

### Phase A goals

1. **Per-stem stems orchestration.** Vocals from BS-RoFormer; drums/bass/guitar from `htdemucs_ft`; piano from `htdemucs_6s` (no better separator exists yet); other from `htdemucs_6s` or residual.
2. **Piano transcription specialist** integrated. ByteDance HR-Piano routed onto the piano signal (mix or stem; benchmark which works better on this corpus).
3. **Vocal F0→notes pipeline** integrated. New transcriber that turns FCPE+PESTO consensus into MIDI with vibrato handling, voicing gates, and confidence-weighted semitone snapping. Replaces basic-pitch on the vocals stem.
4. **ADTOF for drums.** Replaces `librosa.onset.onset_detect` on LarsNet substems. Real velocity modeling.
5. **basic-pitch retained** for guitar / bass / "other" — no clear specialist, and the current params are fine for those stems.
6. **No regressions** on the existing 5-track validation corpus for `key`, `bpm`, `chord_count`, `downbeat_count`, instrumental detection.

### Phase B goals

1. **Generalized `.params.json` sidecar** in every stage that takes parameters.
2. **Schema-versioned sidecars** so default-value changes in code don't silently revalidate stale caches.
3. **Stage dependency graph** — explicit, in code, type-checked.
4. **Selective re-run** via `--stages-only` and `--from-stage` CLI flags + matching webui payload.
5. **Selective cache clear** — `_clear_cache_dir` clears only the artifacts of stages being re-run.
6. **Backward compatibility** — existing `analyze` and `reanalyze` calls without new flags behave identically. Existing caches without sidecars are revalidated by re-running the affected stages once (one-time cost).

### Non-goals

- **UI for selecting models / params** — that's Phase E. This spec only adds the CLI + API surface.
- **New beats / key / chords models** — out of scope. Current models are competitive.
- **Sections, modulations, time signatures, tempo curves** — Phase C.
- **Per-detection confidence extraction** — Phase D.
- **Export improvements** — Phase F.
- **Library-wide cache migration tooling** — accept that some users will see a one-time reanalyze on next run.

---

## 3. Architecture

### Phase A: stems orchestrator

The current `stems.py:131-167 run()` shells out to `audio-separator` twice (once for `htdemucs_6s`, once for `bs_roformer_ep_317`). Replace with a model-aware orchestrator:

```python
# analyze/stages/stems.py — new shape

@dataclass(frozen=True)
class StemSpec:
    """Where to source a stem from after orchestration."""
    cache_subdir: str        # e.g. "stems_6s", "stems_bsroformer", "stems_htdemucs_ft"
    file_pattern: str        # glob matching the produced WAV — e.g. "*(Vocals)*.wav"

# Per-stem routing for the default ("normal" / "best" / "fast") presets. Models run as
# a union; routing tells downstream stages which produced WAV represents which stem.
DEFAULT_ROUTING: dict[str, StemSpec] = {
    "vocals":  StemSpec("stems_bsroformer",   "*(Vocals)*.wav"),
    "drums":   StemSpec("stems_htdemucs_ft",  "*(Drums)*.wav"),
    "bass":    StemSpec("stems_htdemucs_ft",  "*(Bass)*.wav"),
    # htdemucs_ft is a 4-stem model (vocals/drums/bass/other) — no guitar/piano.
    # htdemucs_6s remains the only separator that produces guitar and piano stems.
    "guitar":  StemSpec("stems_6s",           "*(Guitar)*.wav"),
    "piano":   StemSpec("stems_6s",           "*(Piano)*.wav"),
    "other":   StemSpec("stems_htdemucs_ft",  "*(Other)*.wav"),
}

# Models to run for a given preset. Each entry is (audio-separator model_filename, output_subdir).
MODELS_PER_PRESET: dict[str, list[tuple[str, str]]] = {
    "fast":   [("htdemucs_6s.yaml",                                  "stems_6s"),
               ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer")],
    "normal": [("htdemucs_6s.yaml",                                  "stems_6s"),
               ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
               ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer")],
    "best":   [("htdemucs_6s.yaml",                                  "stems_6s"),
               ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
               ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer")],
    "ultra":  [...]   # post-launch: ensemble of two separators per stem
}
```

The previous `STEMS_QUALITY_PRESETS: dict[str, tuple[shifts, overlap]]` becomes `STEMS_QUALITY_PARAMS` keyed by preset, mapping to `{shifts, overlap}`. Same shape on disk for sidecar compatibility, just renamed for clarity.

**Cache layout after Phase A:**

```
cache/<slug>/
├── <slug>.mp3                        # source mirror (preserved across reanalyze)
├── stems_6s/
│   ├── *(Vocals)*.wav
│   ├── *(Drums)*.wav
│   ├── *(Bass)*.wav
│   ├── *(Guitar)*.wav
│   ├── *(Piano)*.wav
│   ├── *(Other)*.wav
│   └── .params.json
├── stems_htdemucs_ft/                # NEW (4-stem model: vocals/drums/bass/other)
│   ├── *(Vocals)*.wav
│   ├── *(Drums)*.wav
│   ├── *(Bass)*.wav
│   ├── *(Other)*.wav
│   └── .params.json
├── stems_bsroformer/                 # unchanged
│   ├── *(Vocals)*.wav
│   ├── *(Instrumental)*.wav
│   └── .params.json
├── stems_routing.json                # NEW — declared mapping for downstream
├── ...
```

`stems_routing.json` is the contract between the stems stage and every downstream stage. Schema:

```json
{
  "version": 1,
  "preset": "normal",
  "routing": {
    "vocals":  {"path": "stems_bsroformer/foo_(Vocals)_model_bs_roformer_ep_317_sdr_12.9755.wav"},
    "drums":   {"path": "stems_htdemucs_ft/foo_(Drums)_htdemucs_ft.wav"},
    "bass":    {"path": "stems_htdemucs_ft/foo_(Bass)_htdemucs_ft.wav"},
    "guitar":  {"path": "stems_6s/foo_(Guitar)_htdemucs_6s.wav"},
    "piano":   {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"},
    "other":   {"path": "stems_htdemucs_ft/foo_(Other)_htdemucs_ft.wav"}
  }
}
```

Downstream stages — transcription, drums, vocal_f0 — read `stems_routing.json` instead of glob-matching `stems_6s/`. This decouples them from the orchestrator's internal layout and makes future per-stem-model overrides trivial.

### Phase A: piano transcription specialist

New module: `analyze/stages/transcription_piano.py`. Wraps `piano_transcription_inference.PianoTranscription` (PyPI). Reads from the stems-routing path for `piano`. Writes a MIDI file via the same path conventions as the current transcription stage.

```python
# analyze/stages/transcription_piano.py — new file
from __future__ import annotations
from pathlib import Path

CANONICAL = "transcription_piano.json"
DEFAULT_PARAMS = {
    "onset_threshold":      0.3,   # ByteDance recommended default
    "offset_threshold":     0.3,
    "frame_threshold":      0.3,
    "pedal_offset_threshold": 0.2,
    "transcribe_full_mix":  False, # if true, ignore stems_routing piano and use mp3 directly
}

def cached(cache_dir: Path, **params) -> bool: ...
def load(cache_dir: Path) -> dict: ...
def run(mp3: Path, cache_dir: Path, **params) -> dict: ...
```

Two routing options for the piano signal — benchmark in Phase 0 (Section 5):

- **Stem-based**: read `stems_routing.json`'s `piano.path`, transcribe that.
- **Mix-based**: transcribe the original mp3. ByteDance's training data was predominantly solo piano; if the htdemucs piano stem has too many artifacts, the mix may be cleaner input. The model is robust to background but produces extra notes when other instruments are loud — gate with `transcribe_full_mix=True` only when the piano stem RMS is too low or shows obvious bleed.

VRAM: ~2 GB. Add a `gc + cuda.empty_cache` cleanup at end of stage matching `chords.py:38-46` pattern.

### Phase A: vocal F0 → notes

New module: `analyze/stages/transcription_vocals.py`. Reads `cache/<slug>/vocal_f0.npz` (already produced by the existing `vocal_f0` stage), runs an F0→notes algorithm, writes `midi/vocals.mid` (replacing basic-pitch's output for vocals).

Algorithm:

1. **Voicing gate.** A frame is "voiced" if FCPE confidence > `voicing_threshold` AND PESTO output is also non-zero AND |FCPE-PESTO| in cents < `agreement_cents`. Default thresholds: `voicing_threshold=0.5`, `agreement_cents=50`.
2. **Median-filter** the F0 curve over voiced regions to suppress single-frame jitter (window: 5 frames @ 16kHz step → 50 ms).
3. **Vibrato suppression for note quantization** — track the long-window mean of F0 (window: 200 ms) and use it for semitone snapping. Vibrato modulation around the mean stays in the per-note F0 bend metadata, not a new note event.
4. **Note segmentation** — emit a new note when (a) the long-window F0 crosses a semitone boundary AND stays past the boundary for ≥ `min_note_ms`, or (b) voicing transitions from off to on after silence ≥ `min_silence_ms`. Defaults: `min_note_ms=80`, `min_silence_ms=80`.
5. **Confidence per note** = mean FCPE-PESTO agreement over the note's frames.
6. **Velocity per note** = derived from vocal stem RMS in the note's window, normalized to track-max. Provides a usable velocity curve from a stage that doesn't produce one today.

Output:

- `cache/<slug>/midi/vocals.mid` — MIDI file with notes + velocity + confidence as MIDI metadata.
- `cache/<slug>/transcription_vocals.json` — note events with full per-note details for the webui.

### Phase A: ADTOF for drums

Replace the librosa-onset post-processing in `drums.py:244-265`. Two integration patterns to evaluate:

- **A**: ADTOF on the LarsNet substems (current architecture), per-substem CRNN inference.
- **B**: ADTOF on the full mix (its native input) and use LarsNet substems only for the WAVs that the webui plays back.

ADTOF works on the full mix natively. **Default to pattern B** unless the corpus benchmark shows pattern A is meaningfully more accurate (unlikely — ADTOF was trained on full mixes).

```python
# analyze/stages/drums.py — partial new shape
def run(mp3, cache_dir, **params):
    # ... existing gate logic (RMS check vs other stems) ...
    # ... existing LarsNet substem WAV emission (kept for webui playback) ...

    from adtof.io.mir import MIR
    from adtof.model.model import Model
    transcriber = Model(...)
    events_per_piece = transcriber.predict(str(mp3))
    # events_per_piece: dict[str, list[(time, velocity, confidence)]]
    # Map ADTOF's drum classes to our SUBSTEMS naming and write summary
```

ADTOF's drum classes don't map 1:1 to our `(kick, snare, toms, hihat, cymbals)`. Mapping table in the new module:

| ADTOF class | Our piece |
|---|---|
| `35`/`36` (Kick) | `kick` |
| `38`/`40` (Snare) | `snare` |
| `41`/`43`/`45`/`47`/`48`/`50` (Tom*) | `toms` |
| `42`/`44`/`46` (Hi-Hat closed/pedal/open) | `hihat` |
| `49`/`51`/`52`/`53`/`55`/`57`/`59` (Crash/Ride/Splash/China/Bell) | `cymbals` |

Velocity comes from ADTOF directly (not the amplitude-window proxy). Confidence comes from the model's per-detection score.

### Phase A: transcription router

`transcription.py` becomes a thin router that dispatches per-stem to the appropriate transcriber:

```python
# analyze/stages/transcription.py — new shape

TRANSCRIBERS: dict[str, str] = {
    "vocals": "vocals",   # F0→notes via transcription_vocals.py
    "piano":  "piano",    # ByteDance via transcription_piano.py
    "bass":   "basic",    # basic-pitch (current; default params)
    "guitar": "basic",    # basic-pitch
    "other":  "basic",    # basic-pitch
}

def run(mp3, cache_dir, **params):
    routing = json.loads((cache_dir / "stems_routing.json").read_text())
    results = {}
    for stem, transcriber_name in TRANSCRIBERS.items():
        if transcriber_name == "vocals":
            results[stem] = transcription_vocals.run(mp3, cache_dir, **params.get("vocals", {}))
        elif transcriber_name == "piano":
            results[stem] = transcription_piano.run(mp3, cache_dir, **params.get("piano", {}))
        else:  # basic
            results[stem] = _run_basic_pitch_for_stem(stem, routing[stem], cache_dir, **params.get(stem, {}))
    return results
```

The MIDI output paths (`midi/vocals.mid`, `midi/piano.mid`, etc.) stay unchanged — downstream consumers don't notice the swap.

### Phase B: per-stage params sidecar primitive

New module: `analyze/cache.py` gets two helpers (or a new `analyze/sidecar.py` if `cache.py` is already long):

```python
# analyze/sidecar.py — new file
from __future__ import annotations
import json
from pathlib import Path

def write(cache_dir: Path, stage: str, params: dict, *, schema_version: int) -> None:
    """Write cache_dir/<stage>/.params.json (or cache_dir/.params_<stage>.json
    for stages without their own subdir). schema_version is bumped manually
    in the stage module when the meaning of the params changes."""
    sidecar_path = _sidecar_path(cache_dir, stage)
    sidecar_path.parent.mkdir(exist_ok=True, parents=True)
    sidecar_path.write_text(json.dumps({
        "schema_version": schema_version,
        "params": params,
    }, indent=2, sort_keys=True))

def matches(cache_dir: Path, stage: str, expected_params: dict, *, expected_schema_version: int) -> bool:
    """True iff the on-disk sidecar exists, has the matching schema_version,
    and its params dict equals expected_params (deep equality, key order agnostic)."""
    sidecar_path = _sidecar_path(cache_dir, stage)
    if not sidecar_path.exists():
        return False
    try:
        data = json.loads(sidecar_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if data.get("schema_version") != expected_schema_version:
        return False
    return data.get("params") == expected_params

def _sidecar_path(cache_dir: Path, stage: str) -> Path:
    """Stage-with-subdir → .../<subdir>/.params.json; else → cache/.params_<stage>.json."""
    STAGE_TO_SUBDIR = {"stems": "stems_6s"}  # reuses existing sidecar location
    sub = STAGE_TO_SUBDIR.get(stage)
    if sub:
        return cache_dir / sub / ".params.json"
    return cache_dir / f".params_{stage}.json"
```

Every stage uses `sidecar.write` after `run()` and `sidecar.matches` inside `cached()`.

### Phase B: stage dependency graph

Declared in `analyze/pipeline.py`:

```python
# analyze/pipeline.py — addition

STAGE_DEPS: dict[str, frozenset[str]] = {
    "stems":         frozenset(),
    "beats":         frozenset(),
    "key":           frozenset(),
    "chords":        frozenset(),
    "transcription": frozenset({"stems"}),
    "beats_xcheck":  frozenset(),
    "vocal_f0":      frozenset({"stems"}),
    "drums":         frozenset({"stems"}),
}

def downstream_of(stage: str) -> set[str]:
    """Return the transitive closure of stages that depend on `stage`."""
    out = set()
    frontier = [stage]
    while frontier:
        s = frontier.pop()
        for candidate, deps in STAGE_DEPS.items():
            if s in deps and candidate not in out:
                out.add(candidate)
                frontier.append(candidate)
    return out
```

Tested against ground truth via a meta-test that reads each stage's source for cross-stage filesystem reads (`stems_routing.json`, `vocal_f0.npz`, etc.) and asserts the deps set is a superset of what's actually read.

### Phase B: selective re-run

`analyze.analyze()` gains:

```python
def analyze(
    mp3_path: Path,
    *,
    force: bool = False,
    quiet: bool = False,
    slug: Optional[str] = None,
    stems_quality: str = stems.DEFAULT_STEMS_QUALITY,
    stages_only: Optional[set[str]] = None,   # new — run only these (and their deps if uncached)
    from_stage: Optional[str] = None,         # new — re-run this stage and everything downstream
    params: Optional[dict[str, dict]] = None, # new — per-stage param overrides
) -> AnalyzeResult: ...
```

Semantics:

- `stages_only={"transcription"}`: validate caches for stems (transcription's only dep). If uncached, fail loudly — selective re-run requires a complete upstream cache. If cached, run only transcription, then re-run derivation, then re-write `summary.json`.
- `from_stage="transcription"`: invalidate `transcription` and all downstream stages, run from there. Equivalent to `stages_only={"transcription"} | downstream_of("transcription")`.
- Both flags absent: current all-or-nothing behavior.
- `force=True` overrides everything (full reanalyze).

`__main__.py` exposes both flags:

```bash
python -m analyze foo.mp3 --stages-only transcription
python -m analyze foo.mp3 --from-stage transcription
python -m analyze foo.mp3 --params-json /tmp/params.json
```

`--params-json` is a single JSON file of the form `{stage: {param: value, ...}, ...}` — cleaner than ~30 individual CLI flags. The webui will use this exclusively.

### Phase B: webui plumbing

`webui/webui/analyze_runner.py` changes:

- `_clear_cache_dir(cache, *, only_stages: set[str] | None = None)` — selective. Each stage declares its produced artifacts in a registry (also in `pipeline.py`); `_clear_cache_dir` deletes only those when `only_stages` is set.
- `run_analyze_stream(slug, source_path, quality, *, stages_only=None, params=None)` — forwards new params to the WSL command line via `--params-json` (written to a temp file, path passed in).

`webui/webui/server.py` analyze + reanalyze endpoints accept optional `stages` (list of stage names) and `params` (JSON object) in their payloads. Backward-compatible defaults.

The actual modal UI for these is **Phase E**, not this spec.

---

## 4. Files to create / modify

### New files

| File | Purpose |
|---|---|
| `analyze/sidecar.py` | Shared sidecar read/write helpers |
| `analyze/stages/transcription_piano.py` | ByteDance HR-Piano wrapper |
| `analyze/stages/transcription_vocals.py` | F0→notes pipeline |
| `analyze/stages/transcription_basic.py` | basic-pitch single-stem helper (extracted) |
| `scripts/install-bytedance-piano.sh` | Model fetch + checksum |
| `scripts/install-htdemucs-ft.sh` | Model fetch (audio-separator handles caching, but we pre-warm + verify) |
| `scripts/install-adtof.sh` | Pip install + smoke test |
| `scripts/benchmark-pipeline.sh` | A/B harness for the validation corpus |
| `tests/test_sidecar.py` | Sidecar primitive tests |
| `tests/test_stage_deps.py` | Meta-test asserting STAGE_DEPS is a superset of actual reads |
| `tests/test_selective_rerun.py` | Round-trip selective re-run tests |
| `tests/corpus/labels/<slug>.json` | Hand-labeled ground truth for benchmark (5–10 tracks) |
| `install-logs/phase-a-validation.md` | Measured improvements vs April 2026 baseline |

### Modified files

| File | Change |
|---|---|
| `analyze/stages/stems.py` | Multi-model orchestrator; emits `stems_routing.json` |
| `analyze/stages/transcription.py` | Becomes a thin router over per-stem transcribers |
| `analyze/stages/drums.py` | ADTOF integration; LarsNet WAV emission preserved |
| `analyze/stages/beats.py` | `cached()` signature normalized; sidecar write |
| `analyze/stages/key.py` | `cached()` signature normalized |
| `analyze/stages/chords.py` | `cached()` signature normalized |
| `analyze/stages/vocal_f0.py` | `cached()` signature normalized; reads from `stems_routing.json` |
| `analyze/stages/beats_xcheck.py` | `cached()` signature normalized |
| `analyze/pipeline.py` | `STAGE_DEPS`, `downstream_of()`, selective-run logic; param threading |
| `analyze/__main__.py` | New CLI flags |
| `analyze/cache.py` | Possibly hosts `sidecar.py` helpers if too small to split |
| `analyze/summary_writer.py` | Provenance block extended with per-stage params |
| `webui/webui/analyze_runner.py` | Selective `_clear_cache_dir`; param forwarding |
| `webui/webui/server.py` | Endpoints accept `stages` + `params` payloads |
| `webui/webui/tracks.py` | Reads new `stems_routing.json` if it surfaces metadata in track listings |
| `analyze/README.md` | Document new CLI flags + per-stage params model |
| `docs/history.md` | Chronicle entry |
| `requirements.lock` | New deps: `piano_transcription_inference`, `adtof` |

---

## 5. Phase 0 — validation harness

Before touching any stage, build the harness that proves the work. This is the **first ralph-loop deliverable**.

### Corpus

5 tracks from the existing batch corpus + 5 new tracks, hand-labeled per the dimensions we'll regress on:

- **JVKE — Golden Hour** (lush sustained piano; the explicit failure case)
- **Olivia Dean — quiet acoustic** (sustained vocals, low-energy drums; existing corpus)
- **Gorillaz — Silent Running** (multi-instrument pop; existing corpus, used as baseline)
- **Bach — orchestral cello quintet** (instrumental; tests the drum gate)
- **Radiohead — Creep** (existing corpus; mp3 header malformation case)
- 5 additional tracks chosen for: 1× waltz / 6/8, 1× modulating, 1× heavy reverb, 1× lo-fi, 1× rapper / sustained-vocals contrast.

Per-track labels in `tests/corpus/labels/<slug>.json`:

```json
{
  "key": "Bb:major",
  "bpm": 120.0,
  "time_signature": "4/4",
  "downbeat_count": 96,
  "vocal_pitch_range": ["G3", "C5"],
  "piano_present": true,
  "drums_present": false,
  "expected_chord_root_count": 4
}
```

These are coarse features, intentionally — high-precision ground truth (per-note MIDI) is too expensive to label manually. Coarse labels catch regressions; fine measurements come from inter-model agreement (ByteDance vs basic-pitch on the same piano signal, FCPE vs PESTO at 50¢ for vocals).

### `scripts/benchmark-pipeline.sh`

Runs the full pipeline on every corpus track at three operating points:

1. **Baseline** (current code) — captures the April 2026 numbers.
2. **Phase A only** — new specialists, all-or-nothing cache.
3. **Phase A + B** — same outputs, plus selective-re-run roundtrip integrity check.

Outputs a Markdown table to `install-logs/phase-a-validation.md` with per-track per-metric deltas and explicit pass/fail flags.

This is a **gating artifact**: every reviewer subagent in the execution plan reads it before signing off.

---

## 6. Caching + migration

### Existing caches

After Phase B ships, an existing cache (no sidecars on most stages) will:

1. Pass `cached()` for `stems` (already has sidecar).
2. **Fail** `cached()` for every other stage on first run because the sidecar is absent.
3. Re-run those stages once — output is byte-identical to before (we haven't changed their internals yet at the start of Phase B), then writes the sidecar.
4. Future runs hit cache normally.

This is acceptable: a one-time per-track cost on the first post-deploy reanalyze. Document it.

### Phase A model caches

`htdemucs_ft` weights download on first use of "normal" or "best" preset; audio-separator caches them in its own model dir. Pre-warm via `scripts/install-htdemucs-ft.sh` to avoid first-run latency surprises.

ByteDance HR-Piano weights are ~165 MB; fetched by `scripts/install-bytedance-piano.sh` to a known location, similar to LarsNet's vendor pattern.

ADTOF's models are small and fetched on PyPI install.

### Schema versions

Each stage carries an explicit `SCHEMA_VERSION` constant. Bump when:

- Param defaults change in code.
- Param semantics change (a previously-unused field becomes consumed).
- The sidecar format itself changes.

Tests assert the constant matches the actual JSON written.

---

## 7. Testing strategy

Three tiers:

### Tier 1: unit — fast, hermetic

- `tests/test_sidecar.py`: write+read round-trip, schema-version invalidation, params-equality semantics.
- `tests/test_stage_deps.py`: meta-test that introspects each stage's source code for filesystem reads and asserts `STAGE_DEPS` is a conservative superset.
- `tests/test_transcription_vocals.py`: F0→notes algorithm fed synthetic FCPE/PESTO arrays for: pure tone, vibrato, gliss, silence-with-onset, breathy onset. Assertions on note count, durations, snapped pitches.
- `tests/test_transcription_router.py`: mock per-stem transcribers; verify routing dispatches correctly and respects `stems_routing.json`.

### Tier 2: integration — slow, but per-PR

- `tests/test_selective_rerun.py`: full pipeline run on a small fixture mp3 (Gorillaz cached fixture from existing tests), then `--stages-only=transcription`, assert only `midi/` and the derivation block changed.
- `tests/test_pipeline_e2e.py`: existing tests updated to the new module boundaries; assertions on `summary.json` keys remain stable.

### Tier 3: corpus benchmark — nightly / on-demand

- `scripts/benchmark-pipeline.sh` against `tests/corpus/labels/`. Generates `install-logs/phase-a-validation.md`. Run before each PR merge in this series.

### Existing webui tests

`webui/tests/` and `webui/tests-e2e/` should be left unchanged in the API contract. `webui/tests/test_server.py` will need updates only where new optional payload fields land.

---

## 8. Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| ByteDance HR-Piano memory accumulation | High | Apply the lv-chordia pattern (`gc.collect()` ×2 + `torch.cuda.empty_cache()`) at end of stage. Test: run the stage 10× in a process and assert VRAM doesn't grow. |
| ADTOF's Torch dep clash with 2.7 pin | High | Validate install in Phase 0 before committing the integration. If clash is hard, fall back to running ADTOF in a sub-venv and shelling out (matches existing `wsl --` pattern). |
| `htdemucs_ft` weights not in audio-separator's default mirror | Medium | Pre-flight check in `install-htdemucs-ft.sh`; test passes only if the model resolves. |
| F0→notes algorithm has edge cases on low-corpus | Medium | Phase 0 calibration on the labeled corpus before integrating. Knobs are conservative defaults; expose for Phase E tuning. |
| Sidecar path collisions between stages | Low | Path scheme uses `cache/.params_<stage>.json` for stages without their own subdir — guaranteed unique. Tested. |
| `stems_routing.json` becomes stale if stems re-runs but downstream cache claims valid | Medium | Routing-file write is the **last** action of `stems.run()`; `transcription/cached()` reads the routing file's **mtime** and invalidates if newer than its own output. Existing pattern in stems' `.params.json` extends here naturally. |
| Selective re-run leaves stale derivation in summary.json | Medium | Derivation pass + `summary.json` write is **always** re-run as the last step, regardless of which stages ran. Summary is cheap; correctness > speed. |
| Existing webui Reanalyze with quality-only payload breaks | Low | Backward-compat: `params` and `stages` payload fields are optional. Server-side defaults preserve current behavior. |
| User expectations on Golden Hour piano improvement | Medium | Phase 0 measures concretely. If ByteDance HR-Piano on stem-input doesn't beat tuned basic-pitch by ≥2× note count, fall back to "transcribe the mix" mode. If neither approach hits the validation criterion, the spec gets revised before we declare Phase A done. |

---

## 9. Validation criteria (ship gates)

A PR in this series merges only when:

1. All Tier 1 + Tier 2 tests pass.
2. `install-logs/phase-a-validation.md` shows:
   - Zero regressions on `key`, `bpm`, `chord_count`, `downbeat_count`, instrumental detection across the corpus.
   - **JVKE Golden Hour**: piano `note_count` ≥ 2× the basic-pitch baseline.
   - **Sustained-vocals tracks**: vocal MIDI note count ≥ 1.5× basic-pitch baseline AND FCPE-PESTO agreement on the produced notes ≥ 0.85.
   - **Drum tracks**: ADTOF onset F1 ≥ 0.85 against hand-labeled subset; phantom-onset rate on instrumental tracks remains 0.
3. `scripts/benchmark-pipeline.sh` runs end-to-end without manual intervention on a fresh checkout.
4. Selective re-run round-trip (`--stages-only=transcription`) on a freshly-cached track completes in < 90 s on the validation hardware (RTX 3090).
5. The reviewer subagent (see below) signs off on the change against this spec's acceptance list.

---

## 10. Execution plan

This work runs in a fresh Claude Code session (no conversation context from this thread is needed — the spec is self-contained). The execution model is **`claude-agent-sdk` ralph loops with reviewer subagents**, per the `local-skills:ralph-loop` skill at `~/.claude/skills/ralph-loop/`.

### Decomposition into work items (WIs)

Each WI is independently runnable and reviewable. WIs in the same wave can run in parallel via the `superpowers:dispatching-parallel-agents` pattern.

```
WAVE 1 (parallel, foundation):
├── WI-1: Sidecar primitive + STAGE_DEPS + selective-re-run plumbing (Phase B core)
├── WI-2: Validation harness + corpus labels + benchmark script (Phase 0)
├── WI-3: F0→notes algorithm (transcription_vocals.py) — pure unit-tested module
├── WI-4: install-htdemucs-ft.sh + install-bytedance-piano.sh + install-adtof.sh
└── WI-5: stems_routing.json contract + reader helper (consumed by Wave 2)

WAVE 2 (parallel, model integrations — depend on Wave 1):
├── WI-6: Stems orchestrator (multi-model, emits stems_routing.json)
├── WI-7: ByteDance HR-Piano transcriber (transcription_piano.py)
├── WI-8: ADTOF drum transcriber (drums.py refactor)
└── WI-9: transcription.py refactor to a router

WAVE 3 (sequential, integration + validation):
├── WI-10: Pipeline integration — wire orchestrator + router + selective re-run end-to-end
├── WI-11: Webui plumbing — analyze_runner.py + server.py for new payloads (no UI yet)
├── WI-12: Run benchmark, write validation report, gate-check vs Section 9 criteria
└── WI-13: Documentation pass (analyze/README.md, history.md, install-logs entry)
```

### Per-WI ralph loop structure

Each WI gets its own prompt file at `prompts/next/phase-ab/wi-<n>-<slug>.md` (the implementation plan, generated via `superpowers:writing-plans`, drives this) and its own SDK runner script at `scripts/loops/wi-<n>.py`.

The runner shape (based on the `ralph-loop` skill's `claude-agent-sdk` runner template):

```python
# scripts/loops/wi-N.py — generated from a template
import asyncio
from claude_agent_sdk import Agent, AgentConfig

async def loop():
    iteration = 0
    while iteration < 10:  # hard cap; reviewer can short-circuit
        iteration += 1
        # 1. Implementer agent does the work
        impl_result = await Agent(config=AgentConfig(
            system_prompt=open("prompts/next/phase-ab/wi-N-<slug>.md").read(),
            allowed_tools=[...],
        )).run(f"Continue iteration {iteration}.")

        # 2. Reviewer subagent gates
        review_result = await Agent(config=AgentConfig(
            system_prompt=REVIEWER_PROMPT_FOR_WI_N,
            allowed_tools=["Bash","Read","Grep","Glob"],   # read-only review
        )).run(f"Review the implementer's work for WI-N. Return ACCEPT or REJECT with reasons.")

        if "ACCEPT" in review_result.output:
            break
        # else: feed reviewer's REJECT reasons back into the next iteration's
        # impl prompt as additional context.
```

The reviewer is a separate Claude instance with its own system prompt focused exclusively on this WI's acceptance criteria. It cannot edit code — it reads the diff and gates.

### Reviewer subagent prompt template

For every WI, a reviewer prompt of this shape:

```
You are a strict code reviewer for MusIQ-Lab's Phase A+B pipeline upgrade.

Read the spec at:
  docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md

You are reviewing **WI-<N>: <title>**.

Acceptance criteria for this WI (from Section 10 of the spec, plus the
WI-specific deliverables):

  <checklist copied from the WI's prompt file>

Review process:

1. Run `git diff main...HEAD` and read the full diff.
2. Run the test suites:
     - Windows webui: `cd webui && uv run pytest`
     - WSL analyze: `wsl -- bash -c 'cd /mnt/f/...../MusIQ-Lab && source .venv/bin/activate && pytest tests/'`
     (exact WSL invocation lives in `analyze/README.md` — read it before running.)
3. For Phase 0 / WI-12, run `scripts/benchmark-pipeline.sh` and read
   `install-logs/phase-a-validation.md`. Confirm Section 9's gates.
4. Check for these patterns in the diff and flag any violations:
   - Sidecar writes that don't include schema_version
   - Stage cached() implementations that ignore params kwarg
   - Hard-coded model paths (must go through audio-separator or
     `analyze/vendor/<model>/`)
   - Missing gc.collect()+empty_cache for new GPU stages
   - Tests that mock the database or skip with reason="not yet"
5. Output ACCEPT only if every acceptance criterion is met AND no
   violations found. Otherwise output REJECT with a numbered list of
   specific issues (file:line where applicable).

Do not edit code. Do not stage commits. Read-only review.
```

### Subagent tool-allowance posture

- **Implementer agents**: full `Edit`, `Write`, `Bash`, `Read`, `Grep`, `Glob`, `TaskCreate`/`TaskUpdate`. May NOT push or open PRs (gated by reviewer).
- **Reviewer agents**: `Read`, `Grep`, `Glob`, `Bash` (for running tests and benchmark only). No `Edit`, no `Write`.
- **Both** disallowed: `git push`, `gh pr` ops. The session that *invokes* the loop opens the PR after Wave 3 completes.

### Failure modes + escalation

- Reviewer rejects 3 iterations in a row on the same WI → loop exits with status `BLOCKED`. The user is paged with the reviewer's last output and the implementer's last attempt.
- Tier 3 corpus benchmark fails Section 9 gates after Wave 3 → escalate to user with the report, do not auto-merge.
- Any model fetch script returns a checksum mismatch → loop exits immediately with `INTEGRITY_FAIL`. No retries — model upstream changed and humans need to vet it.

---

## 11. Deliverable checklist

Use this list as the go/no-go for the Phase A+B PR series. The reviewer subagent verifies each item.

- [ ] All new files in [Section 4](#4-files-to-create--modify) exist and are non-empty.
- [ ] All modified files in Section 4 reflect the new shapes per Section 3.
- [ ] `analyze/sidecar.py` has 100% coverage from `tests/test_sidecar.py`.
- [ ] `analyze/pipeline.py:STAGE_DEPS` is asserted-conservative by `tests/test_stage_deps.py`.
- [ ] `analyze/__main__.py` accepts `--stages-only`, `--from-stage`, `--params-json` and validates them.
- [ ] `analyze/stages/stems.py` writes `stems_routing.json` and `.params.json` on every successful run.
- [ ] `analyze/stages/transcription.py` reads `stems_routing.json` and dispatches correctly.
- [ ] `analyze/stages/transcription_vocals.py`, `transcription_piano.py` exist with `cached()`/`load()`/`run()` matching the protocol.
- [ ] `analyze/stages/drums.py` uses ADTOF for transcription, retains LarsNet WAV emission.
- [ ] `webui/webui/analyze_runner.py` handles selective `_clear_cache_dir`.
- [ ] `webui/webui/server.py` accepts optional `stages` + `params` in payloads with backward-compat defaults.
- [ ] `requirements.lock` updated; `webui/.venv` install passes; WSL `.venv` install passes.
- [ ] `install-logs/phase-a-validation.md` exists with measured numbers showing Section 9 gates green.
- [ ] `docs/history.md` has a chronicle entry per project convention.
- [ ] `analyze/README.md` documents the new CLI flags + per-stage param model.
- [ ] All Tier 1 + Tier 2 tests pass (Windows webui + WSL analyze).
- [ ] No new lint/type errors.
- [ ] No `# TODO` or `# FIXME` left in new code without an issue link.

---

## 12. Out-of-scope reminders

The temptation will be to fold Phase E (the modal UI) into this work because the user asked for advanced settings first. **Do not.** Phase E lands on top of A+B as a dedicated PR series after this ships. The CLI + API surface added here is sufficient for Phase E to consume; the modal does not need to land same-PR.

Other deferments:

- Sections / time signatures / modulations: Phase C.
- Per-detection confidence rollup: Phase D.
- Export formats (per-instrument MIDI, MusicXML): Phase F.

If a reviewer subagent finds itself wanting to expand into one of these areas, output REJECT with rationale. The fix is: ship A+B, then the next phase.
