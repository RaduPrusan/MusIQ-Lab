# `analyze.py` design — production driver for the MIR pipeline

**Date:** 2026-04-29
**Scope:** v1 of the project deliverable referenced in `docs/README.md`'s quick-start. Single command: MP3 in, JAMS + `summary.json` out.

## Context

The 8-stage pipeline (stem separation → madmom downbeats → beat-this → skey → lv-chordia → basic-pitch → torchfcpe/pesto → reconciliation) was validated end-to-end against `Gorillaz - Silent Running` in April 2026 and reproduces deterministically against the rebuilt `.venv` (April 29 2026 rerun: same byte-for-byte JSON sizes for every stage output). What's missing is the production driver that wraps those stages, applies music-theory derivations, and emits the two canonical files described in `docs/research/output-format.md`.

This design adapts the spec in `output-format.md` to the post-allin1 stack (no segmenter, no orchestrator-corrected chord track) and locks the v1 scope.

## Locked decisions (from brainstorm)

| Question | Choice | Implication |
|---|---|---|
| Scope | **Full-spec deliverable**, every `summary.json` field populated; per-note `role`/`in_chord`/`scale_deg` enrichment; Roman numerals + diatonic functions + scale; `predominant_chord_loop`; `vocal_range`. | `claude_orchestrator` LLM-corrected chord track deferred to v2. |
| Output location | **`cache/<slug>/`** holds both stage intermediates AND the two final files. Don't write near the source MP3. | Diverges from spec wording but matches actual workflow. |
| Implementation arch | **`analyze/` package, one file per stage + derivation + writer modules.** Driver imports & orchestrates. | ~150 lines per stage file; per-stage standalone invocation supported. |
| Sections | **Empty array + provenance warning.** No segmenter, no fake placeholder. | When a real segmenter lands (msaf, custom model), swap in cleanly. |
| Error policy | **Hybrid.** Hard-fail on Stage 1 (stems), Stage 2a (downbeats), Stage 4 (key), Stage 5 (chords), Stage 6 (transcription). Soft-fail on Stage 3 (beat-this cross-check), Stage 7 (vocal F0). Soft-fail on derivation steps. | Cache means soft-fail rerun is cheap. |
| CLI | `python -m analyze <mp3>` (a2). Slug = filename → lowercase → `[^a-z0-9]+` → `_`, strip leading/trailing `_` (b1, deterministic). `--force` flag (c2). Per-stage progress to stderr by default; `--quiet` suppresses (d2). | `--slug NAME` override flag retained as escape hatch. |

## Architecture

### Package layout

```
analyze/
├── __init__.py            # __version__ = "0.1.0", public API surface
├── __main__.py            # entry point — calls cli.main()
├── cli.py                 # argparse, slug derivation, --force, --quiet, --slug
├── pipeline.py            # orchestrate stages 1-8 + derivation, error policy
├── cache.py               # cache layout, slug→dir, is_stage_done(name) probe
├── stages/
│   ├── __init__.py
│   ├── stems.py           # Stage 1: audio-separator subprocess (htdemucs_6s + bs_roformer)
│   ├── beats.py           # Stage 2a (madmom RNNDownBeat → DBNDownBeatTracking)
│   ├── beats_xcheck.py    # Stage 3: beat-this File2Beats
│   ├── key.py             # Stage 4: skey.detect_key + librosa K-S fallback
│   ├── chords.py          # Stage 5: lv_chordia.chord_recognition
│   ├── transcription.py   # Stage 6: basic_pitch.predict per harmonic stem
│   └── vocal_f0.py        # Stage 7: torchfcpe + pesto
├── derived/
│   ├── __init__.py
│   ├── theory.py          # key parsing, chord parsing, Roman numerals, function, scale
│   ├── note_enrichment.py # per-note role / in_chord / scale_deg
│   ├── loop_detect.py     # predominant_chord_loop + loop_appearances
│   └── vocal_range.py     # vocal_range from vocals MIDI
└── writers/
    ├── __init__.py
    ├── jams_writer.py     # JAMS annotations (table below)
    └── summary_writer.py  # summary.json assembly + light schema check
```

### Stage module contract

Each `analyze/stages/<name>.py` exposes:

```python
def run(mp3: Path, cache_dir: Path) -> dict:
    """Execute the stage. Write canonical artifacts to cache_dir.
    Return the in-memory result dict (also persisted to disk)."""

def cached(cache_dir: Path) -> bool:
    """True iff this stage's outputs are present and newer than the MP3."""

def load(cache_dir: Path) -> dict:
    """Load this stage's persisted outputs from cache_dir."""

# Optional: standalone invocation
if __name__ == "__main__":
    # accept an MP3 path argv, run() against cache_dir derived via the same slug rule
```

The stage bodies are direct ports of the validated bash bodies from `prompts/test-stack-torch27.md` Phase 6 (also captured in `install-logs/rerun-mp3.sh`). No algorithmic changes — translation only.

### Pipeline orchestration

```python
# analyze/pipeline.py
def analyze(mp3_path: Path, *, force: bool = False, quiet: bool = False) -> AnalyzeResult:
    cache_dir = cache.ensure_dir(slug_for(mp3_path))
    if force:
        cache.clear(cache_dir)

    warnings: list[str] = ["sections deferred — no segmenter installed"]
    results: dict[str, dict] = {}

    REQUIRED = [stems, beats, key, chords, transcription]
    OPTIONAL = [beats_xcheck, vocal_f0]

    for stage in REQUIRED + OPTIONAL:
        name = stage.__name__.split(".")[-1]
        if stage.cached(cache_dir):
            log(f"==> Stage {name}: cached")
            results[name] = stage.load(cache_dir)
            continue
        log(f"==> Stage {name}: running")
        try:
            results[name] = stage.run(mp3_path, cache_dir)
        except Exception as e:
            if stage in REQUIRED:
                raise PipelineError(f"required stage {name} failed: {e}") from e
            warnings.append(f"stage {name} failed (soft): {type(e).__name__}: {e}")
            log(f"!!  Stage {name} soft-failed: {e}")

    derived = compute_derived(results, warnings)  # also soft-internally
    jams_path = cache_dir / f"{cache_dir.name}.jams"
    summary_path = cache_dir / f"{cache_dir.name}.summary.json"
    write_jams(jams_path, mp3_path, results, derived, warnings)
    write_summary(summary_path, mp3_path, results, derived, warnings)
    return AnalyzeResult(jams_path, summary_path, warnings)
```

### Cache contract

A stage is "done" iff:
1. Its canonical output file(s) exist in `cache_dir`.
2. The newest output mtime > MP3 mtime.

Per-stage probes:

| Stage | Probe |
|---|---|
| stems | `len(stems_6s/*.wav) == 6 and len(stems_bsroformer/*.wav) == 2` |
| beats | `madmom_downbeats.json` exists |
| beats_xcheck | `beat_this.json` exists |
| key | `skey.json` exists |
| chords | `chords.json` exists |
| transcription | `transcription_summary.json` exists AND all 5 `midi/*.mid` files present |
| vocal_f0 | `vocal_f0.npz` AND `vocal_f0_summary.json` exist |

`--force` deletes cache_dir contents (preserving the dir itself) before the run.

### Slug derivation (b1)

```python
def slug_for(mp3_path: Path) -> str:
    stem = mp3_path.stem.lower()
    s = re.sub(r"[^a-z0-9]+", "_", stem)
    return s.strip("_")
```

`Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3` → `gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg`.

`--slug NAME` flag overrides for hand-picked names.

## Derivation layer (`analyze/derived/`)

### `theory.py`

**Key parsing.** `parse_key("F minor") → Key(tonic_pc=5, mode="minor")`. Handle `Bb`/`A#` and `F#`/`Gb` enharmonic equivalents. Skey returns space-separated form (`"F minor"`); also accept colon form (`"F:min"`) for robustness.

**Chord parsing.** Lv-chordia returns Harte labels:
- Simple: `"F:min"`, `"C:maj"`, `"D:7"`, `"N"` (no-chord), `"X"` (unknown)
- Inversions: `"F:min/3"`, `"Eb:maj/5"`, `"C:7/b7"`
- Letter notation: `"Cmaj7"`, `"F#m7b5/A"` (alternate)

Parser yields `Chord(root_pc, bass_pc, quality, extensions, raw_label)`. Quality ∈ `{maj, min, dim, aug, sus2, sus4, unknown}`. Extensions = list of interval strings (`"7"`, `"b9"`, `"#11"`). Inversion bass derived from the `/N` suffix where N is a scale degree relative to the root.

Unparseable labels: return `Chord(None, None, "unknown", [], raw_label)`. These get `roman: null`, `function: null` in output. Warn once per unique unparseable label.

**Roman numeral derivation.** `roman_for(chord, key)`:
1. Compute `interval = (chord.root_pc - key.tonic_pc) % 12`.
2. Look up scale degree by mode:
   - **Major** intervals → degrees: `{0:I, 2:II, 4:III, 5:IV, 7:V, 9:VI, 11:VII}`. Off-diatonic: `{1:bII, 3:bIII, 6:bV/#IV, 8:bVI, 10:bVII}`.
   - **Minor** intervals → degrees: `{0:I, 2:II, 3:III, 5:IV, 7:V, 8:VI, 10:VII}` (natural minor). Off-diatonic: `{1:bII, 4:#III, 6:#IV, 9:#VI, 11:VII (raised leading tone)}`.
3. Case from quality: `maj` / `dom` → uppercase; `min` → lowercase; `dim` → lowercase + `°`; `aug` → uppercase + `+`.
4. Bass inversion: append `/3`, `/5`, `/b7` etc. computed from `(chord.bass_pc - chord.root_pc) % 12`.
5. Extensions appended: `V7`, `ii7`, `iiø7` (half-dim), etc.

**Diatonic function.** `function_for(roman_str, mode)`:
- `tonic` ∈ `{I, i, vi, VI, iii, III}` (depending on mode).
- `predominant` ∈ `{ii, ii°, IV, iv}`.
- `dominant` ∈ `{V, V7, vii°, vii°7, viiø7}`.
- `modal_interchange` = anything off-diatonic (any roman with `b` or `#` accidental, e.g. `bIII`, `bVI`, `bVII`, `bII`).
- `secondary` = roman ending in `/V`, `/IV`, `/ii` (secondary dominants — heuristic only). v1 detects only the simplest case: a major chord whose root is a perfect-fifth above the next chord's root.
- `null` if `roman` is `null`.

**Scale name.** `scale_name(key) → str`:
- `"<tonic> major"` for major keys.
- `"<tonic> natural minor"` for minor keys.
- v1 does not detect modal contexts (Mixolydian, Dorian, etc.) — that requires progression analysis beyond v1 scope.

### `note_enrichment.py`

For each note from each `basic_pitch` MIDI:

- **`in_chord`**: binary-search the (already non-overlapping, snapped) `chords` array for the chord active at note's `t`. Returns the chord's `label` (e.g. `"F:min"`) or `null` (note in `"N"` span or before/after song).

- **`role`** ∈ `{chord_tone, passing_tone, neighbor_tone, non_chord_tone, null}`:
  - Compute pitch class of note relative to `in_chord` root (mod 12).
  - **`chord_tone`** if pc is in the chord's interval set (root, third (3 or 4 by quality), fifth (7), plus 7th/9th/11th from extensions if any).
  - For non-chord-tones, look at previous and next note from the **same stem** (same `basic_pitch` track):
    - **`passing_tone`** if previous and next are chord tones AND the three notes form stepwise motion (each adjacent interval ≤ 2 semitones, monotonic direction).
    - **`neighbor_tone`** if previous and next are the same chord tone AND current is ±1 or ±2 semitones away (returns to same pitch).
    - Otherwise **`non_chord_tone`**.
  - `null` if `in_chord` is `null`.
  - Caveat: this is a simplified classical-theory rubric. Pop/jazz idioms (suspensions, anticipations, blue notes, blues scale ♭5) won't be classified precisely. Best-effort.

- **`scale_deg`**: pc of note relative to **key tonic** (not chord root), mapped to the major-scale-relative scale-degree string with accidental. Conventions: `"1"`, `"♭2"`, `"2"`, `"♭3"`, `"3"`, `"4"`, `"♯4"`, `"5"`, `"♭6"`, `"6"`, `"♭7"`, `"7"`. (Always relative to the major scale of the tonic, regardless of mode — so a minor third in any key reads `"♭3"`. Choosing `♯4` over `♭5` consistently for clarity.)

Cost: ~5000 notes × O(log n_chords) lookup ≈ <100ms total. Negligible.

### `loop_detect.py`

`predominant_chord_loop(chords) → (loop, appearances)`:

1. Collapse consecutive identical chords: `[Fm, Fm, Cm, Cm, Cm, Fm]` → `[Fm, Cm, Fm]`.
2. For window length L ∈ [2, 8]:
   - Generate all length-L windows.
   - Count exact-match occurrences across the collapsed sequence.
   - Score = `count × L`.
3. Best (loop, score) wins. If max score < `2 × 2` (i.e. no length-≥2 loop appears ≥2 times), return `(null, [])`.
4. `loop_appearances`: scan the original (non-collapsed) chord list for runs that match the loop pattern. **Each appearance is one full pass through the loop** (matched as labels with consecutive duplicates collapsed); start = the start time of the first chord in that pass, end = the end time of the last chord in that pass. Two consecutive passes through `[Fm, Cm]` against `[Fm, Fm, Cm, Cm, Fm, Cm]` produce two appearances, not one merged span.

`loop_roman` = same loop, mapped through `roman_for(chord, key)` with the detected key.

### `vocal_range.py`

Load `cache_dir/midi/vocals.mid` via `pretty_midi`. Collect all note pitches across all instruments. `low` = lowest MIDI number → pitch name (`"G3"`). `high` = highest. Return `{"low": "G3", "high": "D5"}`. If no vocals MIDI or 0 notes, return `null` and warn.

## JAMS structure

| Namespace | Annotator | Source data |
|---|---|---|
| `beat` | `madmom` | madmom_downbeats.json beats |
| `beat` | `beat_this` | beat_this.json beats (cross-check, only if beats_xcheck succeeded) |
| `beat_position` | `madmom` | madmom downbeats with position-in-bar (re-derive from RNNDownBeatProcessor output's beat_position column) |
| `chord` | `lv_chordia` | chords.json (raw) |
| `chord` | `lv_chordia_snapped` | chords with start times snapped to nearest madmom downbeat (current Stage 8 logic) |
| `key_mode` | `skey` (or `librosa_ks` if fallback) | skey.json |
| `pitch_contour` | `torchfcpe` | vocal_f0.npz `fcpe` array, sampled at 100 Hz over track duration (only if vocal_f0 succeeded) |
| `pitch_contour` | `pesto` | vocal_f0.npz `pesto` array (only if vocal_f0 succeeded) |
| `note_midi` | `basic_pitch[<stem>]` | one annotation per stem (vocals, bass, guitar, piano, other) |
| `tempo` | `madmom_derived` | single tempo value from madmom inter-beat-interval median |

**Absent annotations** (intentional v1 gaps):
- `segment_open` (sections deferred)
- `chord` annotated by `claude_orchestrator` (LLM-corrected track deferred to v2)
- `note_midi` for drums (Stage 6 explicitly skips drum stems; provenance warning)

`annotation_metadata` per JAMS spec:
```python
{
  "annotator": {"name": "<tool>", "version": "<importlib.metadata.version()>"},
  "annotation_tools": "[script: analyze/<module>.py]",
  "data_source": "machine",
  "corpus": "user_library",
}
```

`jams.JAMS.validate()` is called before write. On validation failure, write anyway and log a warning to `provenance.warnings` — better to ship a slightly-non-conforming JAMS than crash after 9 minutes of analysis.

## `summary.json` structure

Faithful to `docs/research/output-format.md` EXCEPT for the deltas below.

### Deltas from spec

| Field | Spec | v1 reality |
|---|---|---|
| `track.time_signature` | from allin1 | hardcoded `"4/4"` (madmom's `beats_per_bar=[3,4]` returns chosen bar length per beat; we take the mode) |
| `sections` | rich array with intro/verse/chorus labels | `[]` always; `provenance.warnings` entry |
| `chords[].agreement` | `consensus` / `split` from cross-validation | `"single_source"` always (cross-check is v2) |
| `chords[].notes` | optional explanation when `split` | omitted in v1 |
| `stems.<name>.notes[].vel` | velocity 0..1 | basic-pitch returns 0..127; we normalize |
| `stems.drums` | `onsets` array | `{"transcribed": false, "reason": "drums skipped per Stage 6"}` + provenance warning |
| `analysis.modal_interchange_count` | computed | count of chords with `function == "modal_interchange"` |
| `analysis.scale` | computed | from `theory.scale_name(key)` |
| `provenance.pipeline_version` | string | from `analyze.__version__` |
| `provenance.models` | dict | populated dynamically; no `beats_sections` (no allin1); separate `downbeats: "madmom@..."` and `beats: "beat_this[final0]@..."` keys |
| `provenance.warnings` | list of strings | always includes sections-deferred; adds soft-failed stages, librosa K-S fallback, unparseable chords, etc. |

### Schema documentation

Inline in `writers/summary_writer.py` as Python `TypedDict`s. No external JSON schema file in v1. `summary.json` validates by being writable as JSON and round-tripping through the TypedDicts at read time.

## CLI

```
python -m analyze <mp3_path> [--force] [--quiet] [--slug NAME]
```

| Flag | Default | Behavior |
|---|---|---|
| `<mp3_path>` (positional) | required | absolute or relative path to MP3 |
| `--force` | off | delete cache_dir contents (preserving the dir), recompute all stages |
| `--quiet` | off | suppress per-stage progress on stderr; only errors print |
| `--slug NAME` | auto from filename | hand-pick the cache dir name |

**Exit codes:**
- `0` — success (incl. soft-failed stages with warnings)
- `1` — required-stage failure (Stage 1, 2a, 4, 5, or 6)
- `2` — invalid MP3 / file not found / permissions
- `3` — cache or output write failure

**Stderr output format:**
```
==> Stage stems: running
    htdemucs_6s: 6 WAVs (218M)
    bs_roformer: 2 WAVs (73M)
==> Stage beats: running
    107.14 BPM, 379 beats, 95 downbeats
==> Stage beats_xcheck: running
    374 beats, 94 downbeats (1.3% off madmom — agree)
==> Stage key: running
    F minor (skey, conf=1.0)
==> Stage chords: running
    94 chord events
==> Stage transcription: running
    bass:554, guitar:922, other:1004, piano:955, vocals:1097 notes
==> Stage vocal_f0: running
    21502 frames, 80.4% agree within 50¢
==> Derivation: scale=F natural minor, loop=[F:min, C:min, C#:maj, Ab:maj, Eb:maj], 12 modal-interchange chords
==> Wrote cache/<slug>/<slug>.jams (148KB)
==> Wrote cache/<slug>/<slug>.summary.json (24KB)
```

`!! ` prefix for soft-fails. Matches the rerun-mp3.sh aesthetic.

## Per-stage standalone invocation

Each stage module is also runnable standalone for debugging:

```bash
python -m analyze.stages.chords <mp3_path>     # runs only Stage 5; reuses cached upstream
python -m analyze.derived.theory                # runs theory.py self-tests
```

Standalone invocation uses the same `slug_for()` derivation, writes to the same `cache/<slug>/`, and assumes upstream cache is present (errors clearly if not).

## Out of scope (v1)

The following are explicit v2 (or later) features:

- **`claude_orchestrator` LLM-corrected chord track** — would cross-validate lv-chordia against bass-stem MIDI via a Claude call, populate `chords[].agreement = consensus/split` and `notes` field. Goes into JAMS as a separate `chord` annotation with `annotator: claude_orchestrator`.
- **Real section detection** — msaf, librosa-recurrence, or a custom small model trained on SALAMI/Harmonix. When available, populates `summary.json["sections"]` and a `segment_open` JAMS annotation.
- **Drums transcription** — onset detection on the drums stem (madmom or aubio). Populates `stems.drums.onsets`.
- **Modal scale detection** — current `scale_name()` returns `"<tonic> major"` or `"<tonic> natural minor"`. v2 could detect `"D mixolydian"` for I-bVII-IV progressions, etc.
- **Per-note `most_common_octave`** for vocal_range and `tessitura` percentiles.
- **Secondary dominant detection beyond the trivial case** — current heuristic catches only `V/X` where the next chord's root is a perfect-fifth below the V chord. Real voice-leading analysis is out of scope.
- **Schema-validated `summary.json`** — v1 uses TypedDicts inline; v2 could add a JSON Schema file and CLI validation.

## Testing strategy

### Unit tests (`tests/unit/`)

Pure functions, no I/O. Run in milliseconds.

- **`test_theory.py`**: ~30 cases covering Roman numeral derivation across the diatonic set (major and minor keys), modal interchange (bII, bIII, bVI, bVII, II in major, etc.), inversions (`/3`, `/5`, `/b7`), and the simplest secondary dominant (`V/V`). Chord parsing: known Harte labels, alternate-letter labels, unparseable labels. Key parsing: enharmonic equivalents, colon vs space form.
- **`test_loop_detect.py`**: synthetic chord sequences with known repeating loops, edge cases (no repeats, single-chord "loop", all-different).
- **`test_note_enrichment.py`**: small synthetic note + chord lists, assert role classification for the four canonical cases (chord_tone, passing_tone, neighbor_tone, non_chord_tone). One pop-idiom edge case to document the known limitation.

### Integration test (`tests/integration/test_gorillaz.py`)

Runs full pipeline against `cache/gorillaz_silent_running/`'s already-validated stage outputs (cache hits all stages, no GPU work). Asserts:

- `summary.json["track"]["key"] == "F minor"`
- `summary.json["track"]["tempo_bpm"]` ∈ `[105, 110]`
- `len(summary.json["chords"]) == 94`
- `summary.json["analysis"]["scale"] == "F natural minor"`
- `summary.json["analysis"]["predominant_chord_loop"]` contains both `"F:min"` and `"C:min"`
- `summary.json["sections"] == []`
- JAMS file passes `jams.load(jams_path).validate()`
- `provenance.warnings` contains the sections-deferred string and no required-stage failures
- `len(summary.json["stems"]["vocals"]["notes"])` == 1097 (matches Stage 6 output)
- Sample notes have `role`, `in_chord`, `scale_deg` populated

This is the regression net. No fresh-MP3 CI test (no GPU in CI).

### Test infrastructure

- `pytest` already installable in the venv (transitive via various packages); add explicit pin in a `requirements-dev.txt` if not already present.
- Tests run with `python -m pytest tests/` from project root with `.venv` activated.

## Open questions deferred to implementation

These are tactical decisions safe to make during implementation, not design-shaping:

- Exact `pretty_midi` API for note iteration (single Instrument vs flatten across all).
- Whether to write JAMS via `jams.JAMS()` builder or by constructing the JSON dict directly (former is canonical, latter is faster — pick during implementation based on how cleanly the builder API maps).
- `--quiet` exact verbosity threshold (errors only, vs. errors + final summary line).
- Whether `python -m analyze.stages.X` should run *only* its stage or also run upstream cached stages on demand (lean toward only-itself-with-cache-required; clearer contract).

## Related files

- `prompts/test-stack-torch27.md` — validated runbook; Phase 6 stage bodies are the canonical source for stage logic.
- `install-logs/rerun-mp3.sh` — consolidated runner that proves the stages work end-to-end against the rebuilt venv. After `analyze.py` ships, this script can be retired (or kept as a smoke test).
- `cache/gorillaz_silent_running/` — validated artifacts, used by the integration test.
- `docs/history.md` — context for why allin1 was dropped and what the validated stack does instead.
- `docs/research/output-format.md` — the original (allin1-era) spec for JAMS + summary.json. This design is the v1-realistic adaptation.
