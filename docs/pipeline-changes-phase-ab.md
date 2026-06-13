# Pipeline changes — before vs after Phase A+B (May 2026)

**Status:** Shipped through HEAD `574f3ab` (post-vocals revert; see Phase M in `history.md` for the iteration story).

A successor's quick-reference: what the analyze pipeline looked like before this work, what it looks like now, and why each piece moved. For the full design rationale see [`superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md). For the validation report see [`../install-logs/phase-a-validation.md`](../install-logs/phase-a-validation.md).

> **Phase A original goal "vocal F0 specialist" was reverted post-ship.** WI-7 shipped a homegrown F0→notes module (`transcription_vocals.py`) that produced silently-wrong notes on real audio. After four iterative fix attempts each broke something different, the module was deleted and vocals routed back through basic-pitch — the pre-WI-7 baseline. The router architecture made this a clean ~50-line revert. See `docs/history.md` Phase M and the section "Transcription router (Stage 5)" below for the full story. A proper F0→notes specialist (crepe-notes, pyin) is deferred as a follow-up.

---

## Stages at a glance

| # | Stage | Before | After |
|---|---|---|---|
| 1 | Stems | `htdemucs_6s` (6 stems) + `bs_roformer_ep_317` (vocals/instr) — run twice | **Multi-model orchestrator**: htdemucs_6s + **htdemucs_ft** (NEW, normal/best presets) + bs_roformer; emits `stems_routing.json` |
| 2 | Beats | madmom RNNDownBeat + DBNDownBeatTracking | unchanged (added sidecar) |
| 3 | Key | deezer/skey + librosa-KS fallback | unchanged (added sidecar) |
| 4 | Chords | lv-chordia (CNN+BiLSTM) | unchanged (added sidecar) |
| 5 | Transcription | `basic-pitch` on every melodic stem (vocals, bass, guitar, piano, other) | **Thin router**: piano → ByteDance HR-Piano specialist; vocals + bass + guitar + other → basic-pitch (vocals specialist reverted, see below) |
| 6 | Beats x-check | beat-this | unchanged (added sidecar) |
| 7 | Vocal F0 | FCPE + PESTO consensus → `vocal_f0.npz` | unchanged (added sidecar) |
| 8 | Drums (optional) | LarsNet substems + `librosa.onset.onset_detect` per substem | **ADTOF on full mix** for transcription; LarsNet preserved for substem WAVs |

---

## What's actually different

### 1. Stems orchestrator (Stage 1)

**Before** — `analyze/stages/stems.py` shelled out to `audio-separator` twice: once for `htdemucs_6s.yaml` (6 stems: vocals/drums/bass/guitar/piano/other) and once for `model_bs_roformer_ep_317_sdr_12.9755.ckpt` (2 stems: vocals/instrumental, used only for the `is_instrumental()` gate).

**After** — `stems.py` is a model-aware orchestrator:

```python
MODELS_PER_PRESET = {
    "fast":   [htdemucs_6s,            bs_roformer],
    "normal": [htdemucs_6s, htdemucs_ft, bs_roformer],
    "best":   [htdemucs_6s, htdemucs_ft, bs_roformer],
}
```

`htdemucs_ft.yaml` (new) is a 4-stem fine-tuned variant of htdemucs that beats `htdemucs_6s` by ~0.5 dB SDR on drums/bass/other. It doesn't produce guitar/piano (those still come from `htdemucs_6s`).

**Why:** BS-RoFormer's vocals stem (SDR ~12.9 on MUSDB) is meaningfully cleaner than htdemucs's (~9.4); routing transcription to it instead of htdemucs's vocals stem was free quality. `htdemucs_ft` is ~0.5 dB SDR better than `htdemucs_6s` on drums/bass/other for one extra pass — also free quality on the "normal" and "best" presets.

**New contract:** `cache/<slug>/stems_routing.json` — a per-stem routing dict that downstream stages read to find the right WAV. Decouples orchestrator internals from consumers.

```json
{
  "version": 1,
  "preset": "normal",
  "routing": {
    "vocals": {"path": "stems_bsroformer/foo_(Vocals)_bs_roformer.wav"},
    "drums":  {"path": "stems_htdemucs_ft/foo_(Drums)_htdemucs_ft.wav"},
    "bass":   {"path": "stems_htdemucs_ft/foo_(Bass)_htdemucs_ft.wav"},
    "guitar": {"path": "stems_6s/foo_(Guitar)_htdemucs_6s.wav"},
    "piano":  {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"},
    "other":  {"path": "stems_htdemucs_ft/foo_(Other)_htdemucs_ft.wav"}
  }
}
```

Reader at `analyze/stems_routing.py` (`load`, `path_for`, `RoutingError`).

---

### 2. Transcription router (Stage 5)

**Before** — `analyze/stages/transcription.py` glob-matched `cache/<slug>/stems_6s/*.wav`, ran basic-pitch on each (skipping drums) with per-stem hyperparameters tuned for the 5 melodic stems. One model, 5 outputs.

**After (current, post-vocals revert)** — `transcription.py` is a thin router:

```python
TRANSCRIBERS = {
    "vocals": "basic",    # basic-pitch (homegrown F0→notes specialist reverted; see 2a)
    "piano":  "piano",    # ByteDance HR-Piano via transcription_piano.py  (NEW, kept)
    "bass":   "basic",    # basic-pitch via transcription_basic.py  (extracted)
    "guitar": "basic",    # basic-pitch
    "other":  "basic",    # basic-pitch
}
```

Reads `stems_routing.json` (no more glob-matching). Per-stem errors are captured in the summary, not raised — one failing stem doesn't kill others.

#### 2a. Vocals → basic-pitch (the WI-7 specialist was reverted)

**WI-7 originally shipped a homegrown F0→notes specialist at `analyze/stages/transcription_vocals.py`** that read `cache/<slug>/vocal_f0.npz` and quantized the FCPE+PESTO consensus into MIDI. The motivation was real: basic-pitch is mediocre on sustained vibrato-heavy singing, and the pipeline already produced cleaner pitch data (FCPE+PESTO) than basic-pitch could extract internally — so quantizing that should beat basic-pitch on vocals.

**It didn't.** The homegrown algorithm had four structural bugs (note pitch locked at note-open time; aggregation as median was wrong for bimodal distributions; one window doing two jobs of boundary detection AND vibrato suppression; boundary check using the wrong comparison). Each bug surfaced when the user opened the piano roll and saw artifacts that weren't in the F0 curve. Four iterative fix attempts (commits `003ae86`, `2441335`, `dcb0ea3`, plus an uncommitted attempt) each addressed one symptom and introduced another.

**Reverted at commit `574f3ab`.** `transcription_vocals.py` is deleted; the router dispatches `vocals` to basic-pitch like the other non-piano stems. basic-pitch on vocals is mediocre on sustained vibrato — but it's *known* mediocre, not silently broken. See `docs/history.md` Phase M for the full iteration story and lessons.

**Why basic-pitch instead of just-fixing-the-algorithm:** by attempt 4, the algorithm had accumulated four patches and the boundary-detector design was wrong in ways that weren't a one-line fix. F0→notes is a 30-year-old solved problem with mature libraries (pyin, crepe-notes); shipping homegrown logic with synthetic-input unit tests was the original mistake. A proper library wrapper is deferred as a Phase A+B follow-up — the router architecture means swap-back is ~3 lines once a library is chosen.

#### 2b. Piano → ByteDance HR-Piano (new specialist, kept)

`analyze/stages/transcription_piano.py`. Wraps the `piano_transcription_inference` PyPI package (~165 MB weights, fetched via `scripts/install-bytedance-piano.sh`).

- API takes a 16 kHz mono float32 numpy array (NOT a file path; the spec template was wrong).
- Loaded onto CUDA; ~2 GB VRAM.
- Reads piano stem from `stems_routing.json`'s `piano.path`; falls back to the original mp3 if routing is missing or has no piano entry. `transcribe_full_mix=True` forces the original mix (useful when stem separation has too much bleed).
- gc + `torch.cuda.empty_cache()` cleanup in a `finally` block — same pattern as `chords.py` for the lv-chordia leak.

**Why:** ByteDance HR-Piano hits ~96% F1 on MAPS vs basic-pitch's ~80% on the same. On Gorillaz (not piano-centric), it produced **676 notes vs basic-pitch's 326** = 2.07× ratio. On the explicit failure case (JVKE Golden Hour) the gain is expected to be larger — that's the gate the spec was written for.

**Verification status:** the 2.07× ratio is a *count* comparison, not a *correctness* one. As of commit `574f3ab`, no one has loaded `cache/.../midi/piano.mid` in a DAW and listened against the source piano. The 676 notes might include garbage — same risk class as the WI-7 vocals failure — and would only show up by ear. The Phase L "code-correctness APPROVED" verdict was based on "pipeline doesn't crash, files have expected shape" which we now know isn't enough. Spot-checking HR-Piano output on a real piano-heavy track is in the post-ship-verification TODO at the end of this doc.

#### 2c. basic-pitch extracted (refactor)

`analyze/stages/transcription_basic.py`. Pulls the per-stem hyperparameter dict out of the old monolithic `transcription.py` so the router can dispatch to it for bass/guitar/other.

- `BASIC_PITCH_PARAMS` per-stem dict is **byte-identical** to the original (no tuning happens in this refactor — Phase E owns tuning).
- `run_for_stem(stem, wav_path, midi_out_dir, *, params=None)` — single-stem entry point.

---

### 3. Drums — ADTOF on full mix (Stage 9)

**Before** — `analyze/stages/drums.py` ran LarsNet to split the htdemucs `(Drums)` stem into 5 substems (kick/snare/toms/hihat/cymbals), bandpassed each to its core spectral band, then ran `librosa.onset.onset_detect` per substem with stem-tuned `delta` thresholds. Velocity was a peak-amplitude heuristic in a 50 ms window after each onset.

**After** — same RMS gate (skip drums when stem is too quiet vs other stems), same LarsNet substem-WAV emission (kept for webui playback), but transcription is now ADTOF on the **full mix mp3**:

```python
ADTOF_CLASS_MAP = {
    35: "kick",   36: "kick",
    38: "snare",  40: "snare",
    41: "toms",   43: "toms", 45: "toms", 47: "toms", 48: "toms", 50: "toms",
    42: "hihat",  44: "hihat", 46: "hihat",
    49: "cymbals", 51: "cymbals", 52: "cymbals", 53: "cymbals",
    55: "cymbals", 57: "cymbals", 59: "cymbals",
}
```

Schema bumped to v3; `model` field changed from `"larsnet"` to `"adtof+larsnet"`. *(The drums schema has since advanced to v4 — see `analyze/stages/drums.py`; this doc is frozen at Phase A+B authorship.)*

**Important install facts** (saved as memory `adtof_install_facts.md`):

- ADTOF is **GitHub-only** (`pip install git+https://github.com/MZehren/ADTOF.git`), NOT PyPI.
- ADTOF uses **TensorFlow**, not Torch. The spec's anticipated Torch 2.7 conflict was a false alarm.
- Requires `tf_keras` shim + `TF_USE_LEGACY_KERAS=1` env var (set in `analyze/__init__.py` so it's the very first thing on `python -m analyze` — basic-pitch's transitive TF import is too late if you set it inside drums).
- Current model outputs only 5 MIDI classes (`[35, 38, 47, 42, 49]`); the 19-class map above is forward-compat.
- ADTOF doesn't return velocities/confidences — events emit `vel: 0.0, conf: 0.0` as sentinels.

**Why:** ADTOF (Carsault et al. 2022) is a CRNN trained on multi-dataset full-mix drums; consistently outperforms onset-detection-on-substems. On Gorillaz: 1407 events across 5 pieces with the right magnitude shape (kick 299, snare 195, hihat 886, cymbals 17, toms 10).

**Verification status:** "right magnitude shape" was my visual judgment of the counts, not a comparison against actual drum hits in the song. Spot-checking 3-4 kick onset times in `drums_summary.json["stems"]["kick"]["events"][].t` against where the kick actually fires in the audio would tell you whether ADTOF is timing things correctly — that hasn't been done yet. Same caveat as HR-Piano: shape-of-output validates the integration; correctness-of-output requires listening.

---

### 4. Per-stage params + selective re-run (Phase B core)

**Before** — only the `stems` stage had a `.params.json` sidecar that invalidated cache when params changed. Every other stage used output-presence-only as the cache check. Tuning a basic-pitch threshold meant a full reanalyze (~5 min/track because stems re-ran).

**After** — generalized sidecar primitive at `analyze/sidecar.py` with two functions:

```python
sidecar.write(cache_dir, stage, params, *, schema_version)
sidecar.matches(cache_dir, stage, expected_params, *, expected_schema_version)
```

Every stage that takes parameters now:

- Writes `cache/<slug>/.params_<stage>.json` after `run()` (or `cache/<slug>/stems_6s/.params.json` for stems via the existing convention).
- Checks the sidecar inside `cached()` — params drift OR schema_version drift invalidates.

**Stage dependency graph** at `analyze/pipeline.py`:

```python
STAGE_DEPS = {
    "stems":         frozenset(),
    "beats":         frozenset(),
    "key":           frozenset(),
    "chords":        frozenset(),
    "transcription": frozenset({"stems"}),
    "beats_xcheck":  frozenset(),
    "vocal_f0":      frozenset({"stems"}),
    "drums":         frozenset({"stems"}),
}

downstream_of("stems")  # {"transcription", "vocal_f0", "drums"}
```

A meta-test scans each stage's source for cross-stage filesystem reads (e.g. `vocal_f0.npz`) and asserts `STAGE_DEPS` is a conservative superset. Catches "added a read, forgot to update deps" silent staleness.

**New CLI flags:**

```bash
python -m analyze <mp3> --stages-only transcription          # run only this stage
python -m analyze <mp3> --from-stage transcription           # this stage + downstream
python -m analyze <mp3> --params-json /tmp/overrides.json    # per-stage param overrides
```

`--stages-only` validates that upstream caches are populated before running (raises `PipelineError` otherwise).

`--params-json` accepts `{"stage": {"param": value}}` overrides; per-stage params take precedence over per-stage kwargs (e.g. `--stems-quality`) on key collision.

**Validation:** selective re-run via `--stages-only=transcription` against a fresh Gorillaz cache completes in **45.5 s on RTX 3090** (spec gate is 90 s).

---

### 5. Provenance — per-stage params in summary.json

**Before** — `summary.provenance` had `pipeline_version`, `models` (importlib version dict), `stems_quality`, `warnings`. No record of what params each stage actually ran.

**After** — additional `provenance.per_stage_params` block populated by reading every sidecar on disk:

```json
"provenance": {
  "pipeline_version": "0.1.0",
  "models": {...},
  "stems_quality": "normal",
  "warnings": [...],
  "per_stage_params": {
    "stems":               {"schema_version": 1, "params": {"quality": "normal", "shifts": 4, ...}},
    "beats":               {"schema_version": 1, "params": {}},
    "transcription_vocals": {"schema_version": 1, "params": {"voicing_threshold_hz": 1.0, "agreement_cents": 50.0, ...}},
    "transcription_piano":  {"schema_version": 1, "params": {"onset_threshold": 0.3, ...}},
    ...
  }
}
```

Lets a reviewer see exactly what params produced a given analysis.

---

### 6. Webui plumbing (Phase B surface, no UI yet)

**Before** — `webui/webui/server.py`'s reanalyze endpoint accepted only `{"quality": preset}`. `_clear_cache_dir` was a full-clear (preserving chat.json, lyrics, user_meta.json, source mp3).

**After** — both reanalyze endpoint + the analyze upload endpoint + the YouTube/URL endpoint accept optional `{"stages": [...], "params": {...}}` with backward-compat defaults. `_clear_cache_dir` accepts an optional `only_stages: set[str]` that deletes only the listed stages' artifacts.

`STAGE_ARTIFACTS` registry in `analyze_runner.py` declares which on-disk artifacts each stage produces — duplicated rather than imported from `analyze.pipeline` so the webui stays ML-free.

Forwarding into the WSL command line:
- `stages_only` → `--stages-only foo,bar,baz`
- `params` → JSON file at `cache/<slug>/.webui_params.json`, passed as `--params-json <wsl-path>`. Cleaned up in the `finally`.

**No modal UI.** The Phase E PR series will add the modal that calls into this surface. WI-11 only made the surface available.

---

## Cache layout — what's new on disk

```
cache/<slug>/
├── <slug>.mp3                          # source mirror
├── stems_6s/                           # htdemucs_6s outputs + .params.json sidecar
│   ├── *(Vocals)*.wav  *(Drums)*.wav  *(Bass)*.wav  *(Guitar)*.wav  *(Piano)*.wav  *(Other)*.wav
│   └── .params.json                    # stems sidecar (existing convention)
├── stems_htdemucs_ft/                  # NEW (only on normal/best presets)
│   └── *(Vocals)*.wav  *(Drums)*.wav  *(Bass)*.wav  *(Other)*.wav
├── stems_bsroformer/                   # vocals/instrumental
│   └── *(Vocals)*.wav  *(Instrumental)*.wav
├── stems_routing.json                  # NEW — orchestrator → consumers contract
├── midi/                               # transcription router output (1 mid per stem)
│   └── vocals.mid  bass.mid  guitar.mid  piano.mid  other.mid
├── transcription_summary.json          # router-shape summary {schema_version, stems: {...}}
├── transcription_vocals.json           # REVERTED (574f3ab) — NOT produced; see §2a
├── transcription_piano.json            # NEW — HR-Piano detail
├── stems_drums/                        # LarsNet substem WAVs (preserved for webui)
│   └── kick.wav snare.wav toms.wav hihat.wav cymbals.wav
├── drums_summary.json                  # v3 at authorship; now v4 (drums.py)
├── vocal_f0.npz  vocal_f0_summary.json
├── chords.json  skey.json  madmom_downbeats.json  beat_this.json
├── .params_beats.json                  # NEW — per-stage sidecars
├── .params_chords.json                 # NEW
├── .params_key.json                    # NEW
├── .params_vocal_f0.json               # NEW
├── .params_beats_xcheck.json           # NEW
├── .params_transcription.json          # NEW
├── .params_transcription_vocals.json   # REVERTED (574f3ab) — NOT produced
├── .params_transcription_piano.json    # NEW
├── <slug>.jams                         # final JAMS export
└── <slug>.summary.json                 # final compact digest (now with per_stage_params)
```

---

## Migration story

Existing pre-Phase-A+B caches (28 tracks at the time of this work) will be transparently re-analyzed on next `python -m analyze` invocation:

- Stems will re-run because the new `stems_routing.json` is required by `cached()`.
- Drums will re-run because schema bumped from v2 → v3.
- Other stages will re-run **once** on first invocation because their sidecars don't exist (`cached()` returns False); thereafter they hit cache normally.

The first reanalyze takes the full pipeline duration (~3 min on a 3-min track at "normal" preset, RTX 3090). Subsequent runs hit cache. This is acceptable per spec §6 ("Caching + migration").

---

## Test counts

| Surface | Before | After (post-revert) |
|---|---|---|
| analyze unit + integration | ~103 passing, 3 pre-existing failures | **201 passing, 0 failures** |
| webui | 221 passing | 226 passing |

The 3 pre-existing `test_cache.py` slug failures were resolved as a follow-up (`897ae01`) — they were stale tests against an older `slug_for()` policy, not Phase A+B regressions. The drop from 211 (pre-revert) to 201 (post-revert) is the 10 `transcription_vocals` unit tests that went away with the homegrown specialist.

---

## What we got wrong, and what's next

This is the honest section. Skip it if you only want the "what changed" reference.

### What we got wrong

1. **Synthetic-input unit tests gave false confidence.** The WI-7 vocals specialist passed 7 unit tests covering pure tone, ideal vibrato, perfect step transitions, silence-then-onset, etc. None of them used real audio. The first time anyone opened the piano roll on Gorillaz, the algorithm was visibly wrong. Lesson: any stage that produces audio/MIDI output needs a verification path that compares output to ground truth, not just to itself or to mocks.

2. **The Phase L ship gate was a vibe check.** WI-12's verdict was "code-correctness APPROVED" because the test suite passed and the pipeline ran end-to-end without crashing. Both true; neither sufficient. The real ship gates from spec §9 (regression on key/bpm/chord/downbeat, JVKE 2× piano notes, sustained-vocals 1.5× + 0.85 confidence, ADTOF F1 ≥ 0.85) were all marked BLOCKED on user labels — and the whole release shipped on Gorillaz alone with no labeled comparison. The bugs that surfaced post-ship would have been caught by any of those gates if they were actually evaluable.

3. **Iterative patches on a flawed design make it worse, not better.** The vocals fix arc (medians-at-emit → smooth/snap split → smooth-window-100ms+coherence-filter → uncommitted mode-attempt) added complexity at every step without addressing the structural flaws: a `note_pitch` state variable locked at note-open time, a window doing two jobs, no HMM smoothing, no understanding of bimodal distributions. The right move after fix attempt 1 would have been to recognize F0→notes is a solved problem with mature libraries and reach for one. Instead the algorithm was patched four times. Lesson: if a homegrown algorithm fails on the first realistic case, look for a library before patching.

4. **Integration tests that mocked peer writers couldn't catch shape drift.** The `jams_writer.py` consumed the pre-WI-9 transcription shape and crashed with `Path(1["midi"]) → TypeError` when the router output had `schema_version` as the first iterated key. Every integration test mocked the JAMS writer entirely so the bug rode through 11 work items. Lesson: integration testing has to actually call the integration boundary; mocking peer writers makes them effectively untested.

5. **Env-var ordering for ML libraries is a real category.** `TF_USE_LEGACY_KERAS=1` was set inside `drums._run_adtof()`, which runs after `basic-pitch` has already imported TensorFlow. Drums silently soft-failed for several WIs. Lesson: anything read at import time has to be set in `__init__.py` or earlier. There's probably a similar latent issue with CUDA visible devices or MKL thread counts that we just haven't tripped over yet.

6. **`--from-stage X` honored the cache.** The selective-rerun flags passed the user-named stage to `module.cached(cache_dir, ...)` first; if it returned True the run was skipped. Symptom: a 45-second "reanalysis" that didn't actually re-analyze. Bug found by accident while debugging vocals. Lesson: explicit user invalidation flags should bypass cache checks unconditionally — there's no scenario where "user said re-run X but X is cached" should mean "skip X."

### Post-ship-verification TODO (concrete spot-checks anyone can do)

The following haven't been verified and should be before Phase A+B is considered "verified-shipped":

- **HR-Piano output**: load `cache/<piano-heavy-track>/midi/piano.mid` in a DAW (LMMS, Ardour, REAPER) alongside the source mp3. The piano notes should match. >10% nonsense = the integration is broken.
- **ADTOF onset times**: open `cache/<drum-track>/drums_summary.json`. Look at `stems.kick.events[].t` (kick onset times in seconds). Spot-check 3-4 against where the kick actually fires in the audio. Off by >50ms repeatedly = misalignment.
- **htdemucs_ft separation quality**: A/B `cache/<track>/stems_htdemucs_ft/*(Drums)*.wav` vs `cache/<track>/stems_6s/*(Drums)*.wav`. The ft version should be at least as clean (the spec claims ~0.5 dB SDR better; our metric is ear).
- **`stems_routing.json` correctness**: open it, eyeball that `vocals.path` actually points at the bsroformer vocals (not htdemucs vocals or, worse, drums).
- **Selective rerun on a non-vocals stage**: `python -m analyze X.mp3 --stages-only beats` should be fast (~15s) and ONLY touch `madmom_downbeats.json` + the beats sidecar. `--from-stage chords` should re-run chords + transcription + downstream. Watch what gets modified.
- **Webui stages/params payload**: `curl -X POST http://127.0.0.1:8765/api/tools/reanalyze/<slug> -H 'Content-Type: application/json' -d '{"stages": ["transcription"]}'`. Watch `webui/webui.log.err` to confirm the WSL command actually got `--stages-only transcription`.

If any of these surface a problem, the fix is local — same revert pattern as vocals — because the router architecture and per-stage sidecar design isolate each stage. None of them require a full Phase A+B re-do.

### Phase G — proposed: pre-analysis web research + post-analysis agreement check

The corpus + hand-labels item from `install-logs/phase-a-validation.md` is now load-bearing. Without ground truth, the pipeline's output can be silently wrong (as the vocals failure demonstrated) and tests will still pass. The user is learning music analysis from this project and isn't qualified to hand-label, so the realistic path is autonomous web research.

Sketched plan (NOT YET IMPLEMENTED):

1. **`analyze/research.py`** — pure-Python module. Given a slug + (optional) artist+title parsed from the cache mp3 filename, queries Spotify Web API (free dev account; returns key/BPM/time_sig/duration), falls back to songbpm.com / musicstax.com scrape, falls back to Wikipedia infobox parse. Output: `cache/<slug>/research.json` with `{key, bpm, time_sig, instruments_present, sources}`.
2. **`analyze/derived/agreement.py`** — pure-Python. Reads `summary.json` + `research.json`, normalizes (relative major/minor key equivalence, BPM tolerance), produces `cache/<slug>/agreement.json` with per-metric `AGREE / DISAGREE / UNKNOWN` + a `passed: bool`. Pipeline calls this as the last step.
3. **Webui chat-actor surfaces the agreement check.** First message on opening a track: "Spotify says F minor at 107 BPM. The pipeline computed F minor at 107.14 BPM — that matches. Vocal range looks consistent with Damon Albarn's other tracks. The piano transcription has X notes — I haven't verified those by ear; want me to walk you through the first 30 seconds against the audio?" Claude is doing presentation, not analysis.
4. **Pipeline stays deterministic and offline.** No Anthropic API key required for `python -m analyze`. The research + agreement scripts run alongside, never inside, the analysis path.

Effort: ~2 days. Concrete worked example proven (Gorillaz Silent Running's key + BPM + time-sig confirmed via songbpm.com lookup in 30 seconds). The benchmark can fail loudly when a future change regresses on any spec §9 metric for any track that has Spotify metadata. Independent of (and complementary to) the manual hand-labeling workflow.

---

## What's NOT in this work (deferred to subsequent phases)

- **Phase C** — sections / time signatures / modulations / tempo curves.
- **Phase D** — per-detection confidence rollups across stages.
- **Phase E** — modal UI for selecting models / params (the API surface added in WI-11 is what Phase E consumes). Should not land until current stages are verified-correct.
- **Phase F** — export improvements (per-instrument MIDI, MusicXML).
- **Phase G** — web-research + agreement-check (sketched above; the natural follow-up to make validation load-bearing).
- **Vocal F0→notes specialist (proper)** — using crepe-notes or pyin's note-transcription mode. Slots back into `TRANSCRIBERS["vocals"]` when chosen. Should not land until Phase G is in place to verify it doesn't regress vs basic-pitch on real tracks.

---

## Where to read next

1. [`superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md) — full design spec.
2. [`superpowers/plans/2026-05-03-phase-ab-pipeline-upgrade.md`](superpowers/plans/2026-05-03-phase-ab-pipeline-upgrade.md) — 13-WI execution plan with TDD steps.
3. [`../install-logs/phase-a-validation.md`](../install-logs/phase-a-validation.md) — measured numbers + ship-gate verdict (read with the post-ship caveats from this file's "What we got wrong" section).
4. [`history.md`](history.md) — Phase L entry for the original 13-WI work, Phase M entry for the post-ship corrections.
5. [`../analyze/README.md`](../analyze/README.md) — driver-side reference for the new CLI flags + per-stage param model.
