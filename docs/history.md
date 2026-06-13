# Project history

A chronological account of how the music-analysis stack went from a design document to a validated end-to-end pipeline. Written as a successor's guide: read this before re-architecting anything, because most of the surprising decisions on disk have a story behind them.

---

## 2026-05-11 — Metadata + MIR cross-check integration (Plans A / B / C)

Three independent integrations shipped today, all subagent-driven from
`docs/superpowers/plans/2026-05-11-*.md`. Working tree was 2 commits
behind these plans at the start; net 25 task-commits later, the cache
gains three new JSON artifacts per track and the sidebar shows three
new cards.

**Plan A — AcoustID + MusicBrainz canonical identity (11 tasks):**

Chromaprint `fpcalc` binary vendored at `analyze/vendor/chromaprint/`
(install via `scripts/install-chromaprint.sh`). New optional pipeline
stage `analyze/stages/identify.py` runs early in `_STAGE_EXECUTION_ORDER`
and writes `cache/<slug>/identify.json` with canonical title / artist /
release / year / ISRC / MBIDs from AcoustID-via-MusicBrainz. Webui
`tracks.py` consults `identify.json` and prefers `<artist> — <title>`
over the YT-ID-stripped slug heuristic. Sidebar "Metadata" card
renders the canonical fields when identified. Generic `skip_stages`
kwarg + `--no-identify` CLI flag.

**Plan B — Last.fm tags + similar artists (5 tasks):**

Webui-side fetcher at `webui/webui/lastfm.py` keyed by Plan A's MBIDs.
New FastAPI endpoint `GET /api/track/<slug>/lastfm` returns
`{available, tags?, similar_artists?}`. Disk cache at
`cache/<slug>/lastfm.json` with 7-day TTL (overridable via
`LASTFM_TTL_DAYS`). Sidebar "Tags & Similar" card mounts below the
analysis cards. Soft-fails when no MBID is on disk or Last.fm API key
is missing — section hidden gracefully.

**Plan C — Essentia second opinion (9 tasks):**

Essentia installed in the WSL .venv (manylinux wheel, no C++ compile).
New optional stage `analyze/stages/essentia_extract.py` runs last with
deps `{beats, key}`. Cross-check function `compute_agreement` compares
the analyze pipeline's tempo + key against Essentia's via ±1 BPM
tolerance and 2-of-3 estimator consensus (krumhansl/temperley/edma).
Sidebar "Acoustic Profile" card shows LUFS / range / dynamic complexity;
reanalyze-modal stats panel grows a "Essentia cross-check" block.

**Gotcha — Essentia high-level SVMs are dead weight on the PyPI build.**
The 10 `.history` model files in `analyze/vendor/essentia-models/` need
`gaia2` at runtime, which isn't on PyPI. Pure-PyPI Essentia gives us
the genuinely useful cross-check (tempo / key / loudness) but no
danceability / mood / voice-instrumental. The Acoustic Profile card
degrades cleanly — loudness rows always render; danceability bar +
mood pills only show when `high_level.available !== false`. To unlock
the SVMs, build gaia2 from source (https://github.com/MTG/gaia,
requires Qt5 + swig) and rebuild Essentia `--with-gaia`. Deferred.

**Smoke test:** ran `python -m analyze <fixture>` end-to-end against
`tests/mp3/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3`;
the new `identify` and `essentia_extract` stages ran fresh, all other
stages re-used cache, and `summary.json` grew the new sections:

- Pipeline tempo: 107.14 BPM. Essentia tempo: 107.05 BPM. Δ 0.10, agreement: **ok**.
- Pipeline key: F minor. Essentia consensus: Ab major. Agreement: **warn**
  (note: these are relative-key pairs sharing the same diatonic content; the
  ±1-BPM/2-of-3-estimator agreement function does not know about
  relative-key equivalence — flagging this as a follow-up).
- Loudness: −8.04 LUFS integrated, 1.26 LU dynamic range,
  2.29 dynamic complexity. High-level SVMs absent as expected (no gaia2).
- AcoustID identification: `identified=false`, reason `"AcoustID error:
  HTTP 400: invalid API key"` — soft-fail path is working; user has not
  configured an AcoustID key, so Plan B's Last.fm card will also stay
  hidden until the key lands.

Webui `/api/tracks/<slug>` response confirmed to surface `essentia`,
`essentia_agreement`, and `identify` keys against the live process.

**Tests:** 461 → ~505 unit + integration, 158 → ~173 JS. No regressions
in the pre-existing test suite. The single pre-existing JS failure
(`menus.test.js` Analyze-stale color token mismatch) was untouched.

**Plans:** `docs/superpowers/plans/2026-05-11-{metadata-cross-check-orchestration,acoustid-musicbrainz,lastfm-tags,essentia-second-opinion}.md`.

**Post-ship arc, same day:**

- `18ba418` — relative-key cross-check fix. Plan C's Gorillaz smoke
  flagged "F minor vs Ab major ⚠" as a likely false-positive; the
  follow-up teaches `compute_agreement` that minor↔relative-major share
  the same diatonic content. Now `ok: True` for that case (and
  Nightbus D#-major↔C-minor too).

- `2a43fc8` — AcoustID retry-on-5xx + MusicBrainz 301-follow. Reduces
  transient outages turning into permanent cache stubs.

- `09fd726` — **demotion protection**. Discovered during an autopilot
  sweep verification when MB started serving broad 503s: a bulk
  `--stages-only identify` rerun (driven by a one-off sweep script,
  never checked into the repo) overwrote 12 of 21 known-good identifications with HTTP 503
  stubs before the bug was caught. The script invokes the pipeline with
  `--stages-only identify`, which by design (`pipeline.py:565-570`)
  *forces* the stage to re-run regardless of cache. The stage itself
  was naively writing whatever payload came out of the AcoustID+MB
  round-trip, demoting identified=true → identified=false on transient
  error. Fixed by routing all writes through `_preserve_or_write()`:
  when the incoming payload is identified=false AND the cached payload
  is identified=true, keep the cached payload and refresh only the
  sidecar. 5 new unit tests cover the demotion-protection cases plus
  the overwrite paths that should still work. That sweep script was
  also fixed to skip already-identified tracks before the
  pipeline gets a chance to re-touch them. The 12 wiped tracks will
  auto-restore on the next post-recovery sweep.

- `cfee215` — half/double-tempo annotation. The 4 BPM cross-check
  warnings on the cache split 50/50 between exact 2× ratios (moderat
  157.89 vs 79.93; sting 84.51 vs 172.27 — both well-known metric-
  level ambiguities) and genuine small disagreements (awolnation
  Δ1.78, beatles Δ3.46). UI now suffixes "(half-tempo)" or
  "(double-tempo)" so the user can tell the two cases apart at a
  glance; the cross-check still flags ⚠ — Plan C's raw-agreement
  semantics intentionally preserved.

---

## Phase A — Design (early April 2026)

The project started as a YouTube-downloader workflow built around `yt-dlp.exe` (see `CLAUDE.md` and the `prompts/` folder for the original brief). The natural next step was: now that we're capturing audio cheaply, can we *analyze* it?

The design was researched in `docs/` against a neutral prompt run independently across three engines (Claude, OpenAI Codex, Google Gemini). Where the three converged, the recommendation was treated as high-confidence:

| Stage | Picked tool | Rationale |
|---|---|---|
| Stems | `audio-separator[gpu]` (UVR ecosystem, BS-RoFormer / htdemucs_6s) | All three engines converged |
| Joint beats / downbeats / tempo / **sections** | `allin1` (mir-aidj/all-in-one) | Joint inference advantage |
| Beat cross-check | `beat-this` (final0 checkpoint) | Strong on its own benchmarks |
| Key | `deezer/skey` (S-KEY, ICASSP 2024) | Self-supervised, modern |
| Chords | `lv-chordia` (170–600 vocab) | Best-of-class for full chord vocabulary |
| Polyphonic transcription | `basic-pitch[onnx]` per stem | ONNX path avoids numpy 2.x / TF clash |
| Vocal F0 | `torchfcpe` primary, `pesto-pitch` cross-check | Both modern, GPU-friendly |
| Output | JAMS + `summary.json` | Archival schema + Claude-readable digest |

Underlying machine: WSL2 Ubuntu 24.04 on JINN, RTX 3090 24 GB, project at `<PROJECT_WSL_PATH>`.

---

## Phase B — First install attempt (failed)

The first attempt at building the venv (Torch 2.5 / cu121 lane) hit two predictable mistakes. They are saved as durable memories so we don't repeat them:

1. **Reflex `numpy<2.0` pin.** Carried over from a 2018-era madmom/essentia world. Modern MIR is intentionally numpy 2.x (skey actually pins `numpy>=2.2,<2.3`). The reflex pin *causes* a conflict instead of preventing one.
2. **`basic-pitch[tf]` instead of `basic-pitch[onnx]`.** The TF backend pulls TensorFlow 2.14 (numpy 1.x ABI; CUDA conflict with Torch). The ONNX backend uses ONNX Runtime, which we already have via `audio-separator`.

Captured in `~/.claude/projects/.../memory/install_lessons.md`. The user was direct: *"delete everything you did and start over clean"* — patching forward through a half-broken venv is a worse use of time than wiping `.venv/` and restarting.

---

## Phase C — Torch 2.7 pivot

The venv was rebuilt against Torch 2.7 / cu126 because `deezer/skey`'s `pyproject.toml` pins `torch = "~2.7.0"` (i.e. `>=2.7.0,<2.8.0`). Resolving the older Torch 2.5 lane meant fighting skey on every install.

This was captured as `prompts/test-stack-torch27.md` — the runbook this history references. The runbook went through several drafts before becoming the executed-and-validated artifact it is today.

---

## Phase D — The allin1 / NATTEN crisis

The retry of the runbook surfaced a much bigger problem than the first attempt. Diagnosis took most of one session:

### What broke

1. **NATTEN's prebuilt `+torch270cu126` wheel would not load.** The C++ extension `natten.libnatten.so` had undefined symbols against our installed Torch:
   - Torch 2.7.0+cu126's `libc10.so` exports `c10::detail::torchInternalAssertFail(..., std::__cxx11::basic_string)` (CXX11 ABI).
   - NATTEN's wheel referenced `c10::detail::torchInternalAssertFail(..., std::basic_string)` (pre-CXX11 ABI).
   - `torch.compiled_with_cxx11_abi() == True` confirmed the mismatch.
   - All NATTEN `+torch270cu126` wheels (0.20.0, 0.20.1, 0.21.0) at `whl.natten.org` have this issue. Pytorch.org's cu126 wheels flipped to CXX11 ABI at some point and NATTEN's 2.7-targeted wheels never followed.

2. **`allin1` 1.1.0 hardcodes a NATTEN API that no longer exists.**
   - `dinat.py` imports `natten1dav, natten1dqkrpb, natten2dav, natten2dqkrpb` from `natten.functional`.
   - These names were removed in NATTEN ≥0.20 (replaced with fused `na1d` / `na2d` / `na3d`).
   - **More importantly: RPB (relative positional bias) was deprecated in NATTEN 0.17 and is now completely absent from the source tree.** allin1's pretrained checkpoint encodes RPB tensors in `nn.Parameter` slots; without RPB support, the weights have no place to plug in.

3. **`allin1` is effectively unmaintained.**
   - Last release: 2023-10-10 (v1.1.0).
   - Last code commit: 2024-05-09 (a single `pad` fix).
   - 17 open issues, 9 on NATTEN/torch/CUDA compatibility, including #30 (May 2025) "not compatible with latest NATTEN" and #36 (Aug 2025) — community work that never landed.

### Why no escape via newer Torch

skey hard-pins `torch = "~2.7.0"`. We can't bump to Torch 2.10/2.11 (where modern NATTEN wheels exist) without forking skey. NATTEN 0.21.5+ explicitly requires Torch ≥2.8.

### Forward path C ("rewrite allin1 + build NATTEN from source") was investigated and rejected

Three independent walls:
- Build NATTEN from source against Torch 2.7 — tractable (~1 hour with CUDA toolkit install).
- Rewrite `dinat.py` to use modern `na2d` — tractable for inference.
- **Reproduce RPB semantics on top of fused `na2d`** — not solvable without research-grade work (custom Flex Attention `score_mod`), and even then, no guarantee the pretrained checkpoint produces correct outputs.

The user's *"latest versions, no downgrades"* preference was respected by **dropping allin1 instead of rolling back NATTEN or Torch**.

### Decision

Drop `allin1` from the stack. Recompose its responsibilities from already-installed parts:

| allin1 responsibility | Replacement |
|---|---|
| Beats | `beat-this` (now canonical, not a cross-check) |
| Downbeats | `madmom` `RNNDownBeatProcessor + DBNDownBeatTrackingProcessor` |
| Tempo | derived from madmom beats (median inter-beat interval) |
| Sections | **deferred** — no segmenter installed |

Section detection is the only real loss. msaf, librosa-recurrence, or a custom small model are future options. For the validation, sections are explicitly skipped.

---

## Phase E — Successful validation

After the runbook was rewritten to drop allin1 and add madmom-from-git + `setuptools<81` (needed because setuptools 81 removed `pkg_resources`, which `basic_pitch.inference` and `resampy<0.4.3` still import), the pipeline ran end-to-end on `Gorillaz - Silent Running` (215 s).

### Per-stage results

| Stage | Tool | Output | Result |
|---|---|---|---|
| 1 | `audio-separator` | 6 + 2 stem WAVs | htdemucs_6s + BS-Roformer ✅ |
| 2a | `madmom` | `madmom_downbeats.json` | **107.14 BPM**, 379 beats, 95 downbeats |
| 2b | (deferred) | `sections.json` | `{"status": "deferred", ...}` |
| 3 | `beat-this` | `beat_this.json` | 374 beats, 94 downbeats; agrees with madmom within 20 ms |
| 4 | `skey` | `skey.json` | **F minor** via `skey.key_detection.detect_key(audio, device="cuda", cli=False)` |
| 5 | `lv-chordia` | `chords.json` | 94 chord events; F-minor diatonic progression |
| 6 | `basic-pitch` | `midi/*.mid` | 5 stems → MIDI, 567–1092 notes each |
| 7 | `torchfcpe` + `pesto` | `vocal_f0.npz`, `vocal_f0_summary.json` | 21502 frames, 87.7% voiced, 80.0% agree within 50¢ |
| 8 | reconciliation | `reconciliation_preview.json` | Snapped first 12 chords to madmom downbeats |

### Cross-tool consistency check

- skey says **F minor**.
- lv-chordia's progression is **F:min → C:min → C#:maj (≈Db) → Ab:maj → Eb:maj → F:min** — the diatonic chords of F natural minor (i, v, ♭VI, III, ♭VII).
- madmom and beat-this agree on **107 BPM** with downbeats matching to within 20 ms across the whole track.

The stack is consistent with itself. That's stronger evidence the install is correct than any single tool's success.

---

## Phase F — API drifts patched

Two real API mismatches surfaced during the run and were corrected in the runbook:

1. **skey** — runbook initially used `skey.inference.predict_key` (does not exist). Real entry point is `skey.key_detection.detect_key(audio, device, cli=False)`. The skey CLI takes only `audio_dir [--checkpoint X] [--device Y]` and prints to stdout — there is no `--output` flag.

2. **lv-chordia** — kwarg is `chord_dict_name=`, not `chord_dict=`. Return-dict keys are `start_time` / `end_time` / `chord`, not `start` / `end` / `label`. There is no `__main__.py`, so `python -m lv_chordia` fails. Only the Python API works.

Both fixes are now in `prompts/test-stack-torch27.md` and recorded in `~/.claude/projects/.../memory/mir_api_quirks.md`.

---

## Phase G — Current state

- `requirements.lock` written (131 packages).
- `prompts/test-stack-torch27.md` is reproducible end-to-end.
- Validation artifacts live at `cache/gorillaz_silent_running/`.
- One-off helper scripts the validation produced live at `.research/stage{1..8}_*.sh` — these are the bash bodies that drove each stage when running via PowerShell+WSL (a known arg-passing quirk made the inline `bash -lc 'multi-statement'` form unreliable for stages with heredocs + sourcing; script files invoked as `wsl -- bash /path/to/script.sh` are the robust pattern).

What's *not* done at this point:
- `analyze.py` (the production driver mentioned in `docs/README.md`'s quick-start) doesn't exist yet. The runbook stops at the per-stage validation level.
- Section detection is unfilled. Acceptable for current validation; a future addition.
- The per-task docs in `docs/research/tasks/` were written before the allin1 drop — `02-beats-downbeats-tempo.md` and `07-section-analysis.md` describe the original allin1-centric design and have not been retrofitted. See `prompts/test-stack-torch27.md` for the current truth on each stage.

---

## Phase H — `analyze` package landed (subagent-driven build)

Brainstormed via `superpowers:brainstorming` → spec `docs/superpowers/specs/2026-04-29-analyze-py-design.md` → plan `docs/superpowers/plans/2026-04-29-analyze-py.md` (23 tasks) → executed via `superpowers:subagent-driven-development` (fresh implementer + spec reviewer + code-quality reviewer per task).

Architecture decisions made during brainstorming:
- **Package, not a single file.** `analyze/` with `stages/`, `derived/`, `writers/` subpackages. `analyze.py` would have hit ~2000 lines.
- **CLI is `python -m analyze`**, slug auto-derived from full filename (e.g. `Charlie Puth - Attention.mp3` → `charlie_puth_attention`). `--force` is the only invalidation knob; `--quiet` suppresses per-stage progress.
- **Hybrid error policy.** Required stages (stems, beats, key, chords, transcription) hard-fail; optional stages (beats_xcheck, vocal_f0) soft-fail with a warning entry. Sections always emits an empty list + `"sections deferred — no segmenter installed"` warning.
- **Outputs go in `cache/<slug>/` only.** No separate output dir.
- **Per-stage cache contract:** stage is "fresh" iff its primary output file exists *and* is newer than the source MP3.

Music-theory derivation lives in `analyze/derived/`:
- `theory.py` — Roman numeral generation (uppercase major / lowercase minor / `°` dim / `+` aug, with `/n` inversions; quality-aware inversion intervals — minor-third for min/dim chords, major-third for maj/aug), diatonic function (tonic/predominant/dominant/modal_interchange), scale name, scale-degree mapping (always major-scale-relative regardless of key mode).
- `loop_detect.py` — predominant chord loop with primitive-period reduction (so `[F:min, C:min, F:min, C:min]` reduces to `[F:min, C:min]` rather than scoring the longer repeat).
- `note_enrichment.py` — per-note `chord_tone` / `passing` / `neighbor` classification using `find_chord_at(time)`.
- `vocal_range.py` — low/high pitch from vocals MIDI with `♯`/`♭` Unicode rendering.

Two real bugs surfaced and got fixed during implementation review:
1. **Quality-aware inversion intervals** (Task 5). The naive "bass = root + 4 semitones for `/3`" formula is wrong for minor and diminished chords (their third is 3 semitones above the root). The fix lives in `roman_for()` and is tested in `tests/unit/test_theory_roman.py`.
2. **Loop primitive-period reduction** (Task 8). Without `_primitive_period()`, longer repetitions of the same loop (e.g. 4-bar `[i, v, i, v]`) outscore the actual primitive (2-bar `[i, v]`) on the same chord sequence. Tested in `tests/unit/test_loop_detect.py`.

JAMS writer surfaced four schema bugs that the JAMS library only catches at `j.save()` time (not `validate()` time):
- Tempo namespace requires a numeric `confidence`, not `None`.
- `j.save(path)` re-validates internally — must pass `strict=False` if any annotation has been added without going through full schema validation.
- Chord duration after snap-to-downbeat can be negative (snap moves start past the original end). Clamped with `max(0.0, ...)`.
- `pitch_contour` value dicts require an `index: integer` field per the JAMS schema (undocumented in the namespace docstring).

Validated against the Phase E reference: 9 integration tests in `tests/integration/test_gorillaz.py` consume the existing `cache/gorillaz_silent_running/` artifacts and assert the derived fields match. **96 tests pass** (87 unit + 9 integration). Cached re-runs are ~10–30 s; cold runs are ~6–10 min on the RTX 3090.

---

## Phase I — Batch validation on 5 mixed-genre MP3s

Five tracks from `C:\Users\<you>\Videos\Any Video Converter Ultimate\MP3\` covering jazz, pop, classical, rock ballad, and a labelled backing track (the script that drove this is `install-logs/batch-test.sh`; full per-track output and scratch notes are in `install-logs/batch-test-results.md`). Headline: 5/5 ran end-to-end with exit=0.

The clearest validation came from the labelled track *"The Autumn leaves - Gm (130bpm) - Backing Track.mp3"*. The pipeline returned **G minor / 130.4 BPM** with the canonical Autumn-Leaves chord loop (`Gm7 → Cm7 → F7`, `i7 - iv7 - ♭VII7`) — filename ground truth, exact match. *Lou Reed - Perfect Day* came back as B♭ Major / 73.2 BPM with `vi-V-IV` (Gm-F-E♭), which matches the well-known harmony.

Two upstream-model limits surfaced (not pipeline bugs):
- **Jazz tempo doubling.** *Chet Baker / Paul Desmond - Autumn Leaves* came back as 187.5 BPM (real tempo ≈93). Both `madmom` and `beat-this` lock onto the 8th-note swing pulse on jazz — a classic MIR failure mode.
- **Instrumental "vocals" stems.** htdemucs_6s always emits a vocals stem even on instrumental pieces. Bach's *Air on G String* (cello quintet) reported `vocal_range = D♯2–F♯7` from cello bleed; the Chet Baker track reported `G7` (saxophone misclassified). The pipeline reports faithfully — fixing this would mean adding a "purely instrumental" detector that suppresses `vocal_range` when the vocals stem RMS is far below the others.

### Real bug found and fixed: librosa duration on malformed Xing/VBR headers

*Charlie Puth - Attention.mp3* reported `duration_sec = 1711.96` for a 5:01 track — a **5.67× inflation**. Diagnosis:

| Source | Value | Mechanism |
|---|---|---|
| `librosa.get_duration(path=…)` | 1711.96 s ❌ | reads `soundfile.info` (75,497,472 frames @ 44.1 kHz from the Xing header — the header lies) |
| `librosa.load(sr=None)` then `len/sr` | 220.79 s ❌ | trusts the decoder but stops early when it sees the header mismatch |
| `ffprobe` | **301.73 s** ✓ | scans the actual container |

Stderr from the load attempt: `Xing stream size off by more than 1%, fuzzy seeking may be even more fuzzy than by design!`

**Fix:** replaced `librosa.get_duration` with a small `_probe_duration_sec()` ffprobe wrapper in `analyze/pipeline.py`. ffmpeg is a hard system dependency anyway (per CLAUDE.md "FFmpeg: assumed on PATH"), so a missing/failing ffprobe surfaces as a `CalledProcessError` rather than being papered over with a fallback to a worse data source. After the fix, re-running with `--force` produced `duration_sec = 301.73` ✓. All 96 tests still pass.

---

## Phase J — Instrumental detector (2026-04-30)

The Phase I batch validation surfaced a recurring failure on instrumental tracks: `htdemucs_6s` always emits a `vocals` stem, and on purely instrumental pieces (Bach's cello quintet, jazz-saxophone-led tracks) the leaked content gets transcribed into nonsensical vocal ranges (Bach reached `F♯7`, Chet Baker reached `G7` from saxophone). The pipeline reported faithfully — the upstream model is what's coloring outside the lines — but a downstream consumer reading `summary.json` has no way to know the `vocal_range` field is actually a cello.

**First attempt (rejected): RMS ratio against the other htdemucs stems.** Compared the htdemucs vocals stem RMS against the median of `bass / guitar / piano / other` (drums excluded as percussion-band). Empirical ratios on the validation set:

| Track | htdemucs vocals / median(others) |
|---|---|
| Gorillaz (real vocal) | 2.18 |
| Charlie Puth (real vocal) | 1.88 |
| Lou Reed (real vocal) | 2.07 |
| Bach cello quintet | **0.379** |
| Chet Baker / Paul Desmond | **0.132** |
| Backing track (no vocals) | **0.004** |

A single threshold cleanly separated the silent backing track from everything else, but Bach (0.38) sat too close to a hypothetical "soft folk vocal way below the band" failure mode to set a threshold that catches it without false positives. htdemucs's general-purpose 6-stem separator leaks too much voice-band content into the vocals slot.

**Final approach: BS-RoFormer's vocals/instrumental ratio.** BS-RoFormer is trained specifically for vocal/instrumental separation, so its vocals stem on truly instrumental material is near-silent. Same six tracks:

| Track | bsroformer vocals / instrumental |
|---|---|
| Gorillaz | 0.66 |
| Charlie Puth | 0.57 |
| Lou Reed | 0.71 |
| Bach cello quintet | **0.057** |
| Chet Baker / Paul Desmond | **0.030** |
| Backing track | **0.002** |

Clean ~10× gap between the lowest vocal (0.57) and the highest instrumental (0.057). A threshold of 0.15 puts ~3.8× margin to the vocal floor and ~2.6× margin to the instrumental ceiling.

**Implementation:**
- `analyze/derived/vocal_range.py` — new `is_instrumental(bsroformer_stems_dir)` function. Streams stem WAVs in 64K blocks via `soundfile.SoundFile.blocks` (a 5-min stereo stem decoded fully would be ~211 MB; six stems would blow memory).
- `analyze/pipeline.py` — calls `is_instrumental()` before `vocal_range_from_midi()`. If True, sets `vocal_range = None` and adds the warning `"vocal_range suppressed (track appears instrumental — BS-RoFormer vocals stem RMS << instrumental stem)"`.
- 7 new unit tests (synthetic sine-wave stems with controlled amplitudes), bringing the suite to **103 tests passing**.

**One self-inflicted incident worth recording.** The first attempt at re-running the batch test inline used `wsl -- bash -lc 'for slug in ...; do ... case "$slug" in ...'`. msys2 (Git Bash on Windows, the parent shell of these tool calls) silently expanded `$slug` and `$mp3` to empty strings *before* the command reached WSL — bypassing the `MSYS_NO_PATHCONV=1` envvar fix that handles the path-translation half of msys2's interference. The result was `python -m analyze --quiet ""` running on `.` (the cache root), which triggered audio-separator on the existing stem WAVs found by recursive directory scan. It ran for 41 minutes spawning nested `(Bass)_htdemucs_6s_(Bass)_htdemucs_6s_(Drums)_htdemucs_6s.wav` outputs in a rogue `cache/stems_6s/` at the project root before being killed. Fix: never use inline multi-line `bash -lc 'for ... do $var ... done'` from msys2; always write to a `.sh` file and invoke as `bash /path/to/script.sh`. This is the same lesson recorded in `wsl_bash_dollar_quoting.md`, applied at a different scope. The fix script is `install-logs/rederive-batch.sh`.

---

## Phase L — Specialist models + selective re-run (May 2026)

The Phase H `analyze` package shipped with basic-pitch doing all polyphonic transcription regardless of stem type — a generalist applied uniformly to piano, vocals, guitar, bass, and other. The stems stage ran a single htdemucs_6s pass. And every cache miss triggered a full-pipeline re-run, which meant iterating on transcription quality required re-separating stems (6–10 min on the RTX 3090). These three gaps — generalist transcription, one-model stems, and all-or-nothing cache — were the explicit motivation for Phase A+B. The spec is at [`docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md`](superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md); the implementation plan at [`docs/superpowers/plans/2026-05-03-phase-ab-pipeline-upgrade.md`](superpowers/plans/2026-05-03-phase-ab-pipeline-upgrade.md).

### What shipped

13 work items (WI-1 through WI-13) implementing:

- **WI-1** — per-stage params sidecar + `cached()` schema-version invalidation.
- **WI-2** — `--stages-only` and `--from-stage` selective re-run flags.
- **WI-3** — `--params-json` override injection + `summary.provenance.per_stage_params`.
- **WI-4** — multi-model stems orchestrator (htdemucs_6s + htdemucs_ft + BS-RoFormer per preset); `stems_routing.json`.
- **WI-5** — transcription router (`transcription.py` dispatches to per-stem specialists).
- **WI-6** — `transcription_basic.py` (basic-pitch for bass/guitar/other).
- **WI-7** — `transcription_vocals.py` (FCPE+PESTO F0→notes for vocals stem).
- **WI-8** — `transcription_piano.py` (ByteDance HR-Piano for piano stem).
- **WI-9** — ADTOF drums transcription (full-mix onset detection).
- **WI-10** — LarsNet substem WAVs (per-piece onset: kick/snare/toms/hihat/cymbals).
- **WI-11** — test suite expansion (103 → 211 tests).
- **WI-12** — validation gate (Gorillaz integration; ship-gate report at `install-logs/phase-a-validation.md`).
- **WI-13** — this documentation pass.

### Two ship-blocking bugs found at the validation gate

**Bug 1 — jams_writer.py shape mismatch.** The transcription router now produces per-stem MIDI dicts with a different key schema than the original basic-pitch path. The JAMS writer was indexing into the old shape and failing with a `KeyError` at save time. The integration tests that ran before WI-11 mocked the JAMS writer entirely, so this never fired in CI. Fix: updated `writers/jams_writer.py` to consume the new router output shape.

**Bug 2 — TF_USE_LEGACY_KERAS env var set too late.** `transcription_piano.py` imports ByteDance HR-Piano, which imports Keras 3 internally. ADTOF (TensorFlow-based) also imports TF. Whichever fires second hits an already-initialised Keras backend. The fix is to set `os.environ["TF_USE_LEGACY_KERAS"] = "1"` *before* any TF/Keras import — i.e., at the top of the module, not inside a function. This is a general TF/Keras 3 ordering hazard: setting the env var after the first `import tensorflow` is a no-op.

### Surprising discoveries

Three findings worth recording for future work (ADTOF-specific details in `~/.claude/projects/<CLAUDE_PROJECT_ID>/memory/adtof_install_facts.md`):

1. **ADTOF is GitHub-only and TensorFlow-based.** The spec anticipated a potential Torch 2.7 conflict. In practice ADTOF is not on PyPI at all — install via `git+https://github.com/MZehren/ADTOF.git` — and it uses TensorFlow, not Torch, so the version conflict was a false alarm. It does need the `tf_keras` shim package and `TF_USE_LEGACY_KERAS=1`.

2. **htdemucs_ft pre-warm requires a sine tone, not silence.** `audio-separator` rejects all-zero audio during model pre-warm (raises `AssertionError: audio must not be silent`). The pre-warm input must contain an audible tone — a short sine wave at any frequency works.

3. **ByteDance HR-Piano takes an np.float32 array, not a file path.** The spec template used `piano_model.transcribe(wav_path)`. The actual API is `piano_model.transcribe(audio_array)` where the array is `np.float32` at the model's expected sample rate (16 kHz). Passing a path raises a `TypeError` with no hint about the expected type.

### Corpus-validation TODO

Full ship gates 2/3/4 are blocked on the user populating `tests/corpus/sources.txt` (one MP3 slug per line) and `tests/corpus/labels/<slug>.json` (ground-truth key/tempo/chord annotations). The harness scripts added in WI-12 make the full-corpus validation run a single bash command once those label files exist. Until then, the integration test suite covers the Gorillaz reference track only.

---

## Phase M — Post-ship corrections (May 2026)

Phase L's "code-correctness APPROVED" ship verdict turned out to be overconfident. The unit tests passed and the pipeline ran end-to-end without crashing, but the validation harness had a structural blind spot: every transcription test used synthetic or mocked inputs. None of them looked at the actual MIDI output against the actual audio source. The first time anyone did that — by opening the piano roll in the webui — the WI-7 vocals specialist's failures were immediately obvious. A handful of related issues surfaced during the same debugging arc.

### Bugs found post-ship

These all snuck through Phase L because tests + integration smoke + "no crash" was the entire validation surface. Each is fixed in main; each represents a category of test the validation harness should grow:

1. **`vocal_f0` ran AFTER `transcription`** in the literal loop order (it sat in `OPTIONAL_STAGES` after `transcription` in `REQUIRED_STAGES`). The WI-7 vocals specialist needed `vocal_f0.npz` and crashed when the file didn't exist yet. The router caught the error per-stem and the pipeline kept going, so no test failed — but the vocals MIDI was empty. Fixed by introducing `_STAGE_EXECUTION_ORDER` that respects `STAGE_DEPS`. Commit `6db29ea`.

2. **`jams_writer.py` consumed the pre-WI-9 transcription shape.** The router output `{"schema_version": 1, "stems": {…}}`; the JAMS writer indexed `results["transcription"][stem_name]["midi"]` directly and crashed with `Path(1["midi"]) → TypeError` because the first key it iterated was the integer `schema_version`. Integration tests mocked the JAMS writer entirely so the bug rode through 11 work items. Fixed by adding the same shape-tolerance the summary writer already had. Commit `bd7f7b8`.

3. **`TF_USE_LEGACY_KERAS=1` was set inside `drums._run_adtof()`.** That's too late: `basic-pitch` (called from the transcription router) imports TensorFlow transitively before drums runs. By the time drums tries to set the env var, Keras is already initialised in v3 mode and the legacy-optimizer import inside ADTOF crashes. Drums silently soft-failed for several WIs because it's an OPTIONAL_STAGE. Fixed by moving the env-var set to `analyze/__init__.py` so it's the very first thing on `python -m analyze`. Commit `1e5a5f1`.

4. **`--from-stage X` and `--stages-only X` honored `cached()`** instead of forcing the named stage to re-run. The user-facing semantic was "invalidate this stage and re-run," but the implementation called `module.cached(cache_dir, ...)` first; if the stage's own router-level params hadn't changed (even when an internal sub-transcriber's schema bumped) it returned True and the run was skipped. Symptom: a "selective re-run of vocals" took 45s instead of the expected 3 minutes and produced no MIDI changes. Fixed by bypassing the cached() check when a stage is explicitly in `run_set`. Commit `5ecf760`.

### The vocals fix-then-revert arc

The user reported off-by-semitone vocal notes. Four iterative fix attempts each broke something different:

1. **`003ae86` — re-derive note pitch from window median at emit time.** Fixed: notes locked to attack-transient pitches were now correctly labeled. Broke: median is the *midpoint* of a bimodal distribution. A D#/F alternation (singer bouncing between two adjacent semitones) got labeled E — a pitch barely present in the audio. Not visible in the unit tests because they used unimodal synthetic input.

2. **`2441335` — split `smooth_window_ms` (50ms boundary detection) from `snap_window_ms` (200ms vibrato median).** Fixed: brief intermediate notes between two longer notes (e.g. F → 150ms D# → C#) were now caught by the short window. Broke: 50ms is short enough that F0-estimator octave-glitches (FCPE+PESTO occasionally both glitch the same way and pass the agree-gate) surfaced as spurious notes — visible as tall thin spikes in the piano roll, far from the actual melody.

3. **`dcb0ea3` — `smooth_window_ms` 50→100ms + `melody_coherence_max_jump_semitones=7` post-filter.** Fixed: the spike artifacts (≥7-semitone outliers from both neighbors got dropped). Didn't fix: the underlying `note_pitch != cur_pitch` boundary check. When an alternation bounces back through the opening pitch (F → D# → F → D# → F), the boundary detector fires only when `cur_pitch != note_pitch`, which never happens since `cur_pitch` keeps returning to `note_pitch`. The whole alternation gets emitted as a single note labeled with whatever the median is.

4. **(uncommitted attempt — mode instead of median)** would have addressed the bimodal-label issue but not the missing note-split — would still have been a single note, just labeled with the dominant pitch rather than the midpoint. Better but still wrong about the note count.

After the fourth attempt the user — correctly — said the problem was the design, not the patches. The homegrown algorithm had four accumulated bugs and the right move was to revert. Commit `574f3ab` deletes `transcription_vocals.py` and routes vocals through basic-pitch (the pre-WI-7 baseline). The router architecture made this a clean ~50-line change touching one stage. A proper F0→notes specialist (crepe-notes, pyin's note transcription) is deferred as a Phase A+B follow-up, gated on real validation against ground truth.

### Lessons recorded

These are the durable things this phase taught us:

- **A homegrown algorithm with synthetic-input unit tests is worse than a known-mediocre library.** WI-7 was 50 lines that passed 7 unit tests and broke on every realistic case the user opened in the piano roll. basic-pitch on vocals is mediocre on sustained vibrato — but it's *known* mediocre, and it doesn't make up notes from F0-estimator artifacts. The "spec said do better" goal isn't worth four sessions of debugging if the better implementation is a homegrown algorithm.
- **Tests passing + no crash ≠ correct output for any stage that produces audio/MIDI.** The validation surface needs a cross-reference against something: ground-truth labels (manual), web-sourced metadata (Spotify/songbpm/etc. for popular tracks), or another independent algorithm. The Phase L ship gate was a vibe check.
- **Integration tests that mock peer writers can't catch shape drift.** The `jams_writer.py` bug existed for 11 work items because every "integration test" mocked the JAMS write. Real end-to-end validation has to actually call the writer.
- **Env-var ordering for ML libraries is a real category.** TF/Keras, CUDA visible devices, MKL threading — anything that's read at import time has to be set in `__init__.py` or earlier, not inside a function called later in the pipeline.
- **`--from-stage` semantics need to bypass cache.** "Invalidate and re-run" should mean exactly that. The cached() check belongs to the default no-flag path, not the explicit selective-rerun path.

A reflection on the larger picture is at the end of `docs/pipeline-changes-phase-ab.md` ("What we got wrong, and what's next"). The proposed Phase G work — a pre-analysis web-research + post-analysis agreement-check layer — is intended to make the validation surface load-bearing instead of vibe-based, without requiring you to hand-label a corpus.

---

## Phase N — Vocal consensus pipeline (Phase 0c, May 2026)

A four-step program to make the vocal F0 contour trustworthy for the webUI's piano-roll overlay. The pre-existing pipeline produced a fragmented, octave-glitching line on bass-baritone material; for Cohen specifically only 36.5% of voted-voiced frames carried a value because of a hidden contract bug between the voicing layer and the renderer-feeding line builder.

Spec: [`superpowers/specs/2026-05-05-vocal-consensus-improvements.md`](superpowers/specs/2026-05-05-vocal-consensus-improvements.md). Ship report (canonical): [`../install-logs/phase-0c-results-2026-05-05.md`](../install-logs/phase-0c-results-2026-05-05.md).

### What landed (eight commits, 2026-05-05)

1. **Step 0** (`8ea89d0`) — spec + baseline diagnostics on three benchmark vocal-heavy tracks (Sting / Radiohead / Cohen).
2. **Step 1** (`7ac29c3`) — plumbed `fcpe_conf` + `pesto_conf` per-frame confidence arrays through `vocal_f0.npz` (PESTO emits real values; FCPE binary mask). `vocal_f0` schema 1→2.
3. **Step 2** (`5139044`) — replaced `_build_consensus_f0` with the (consensus_f0, agreement_strength) returning version. Three SVG paths in the renderer, smoothing-within-bucket invariant. `vocal_consensus_contour` schema 2→3. **Headline result on Cohen: 36.5% → 93.8% finite consensus_f0, 38.2% → 8.0% kill rate.**
4. **Step 3** (`0f2e435`) — anchor pre-validation against F0 medians. The committed validator diverged from the spec's pseudocode after empirical iteration: drops Cohen anchors at 16% (vs naive 39%) by adding asymmetric octave correction (downward only — F0 estimators rarely sub-harmonic-lock), a harmonic-ratio guard for cross-PC agreement, and a 7-semitone delta threshold that keeps small disagreements (likely note-boundary timing artifacts).
5. **Step 4** (`3b0d8b7`) — Viterbi smoothing as the default consensus builder. New `analyze/derived/vocal_consensus/viterbi.py` (~280 LOC). 8-state candidate space (FCPE / PESTO / ×½ / ×2 each + anchor + unvoiced); transition cost quadratic-in-cents with Gaussian bump at 1200¢; anchor-proximity Gaussian emission bonus.
6. **Silence-gate fix** (`413fa02`) — the lesson commit. The first Step 4 iteration pushed `frames_with_finite_consensus_f0` to ~99% on all three tracks and was *worse in practice* than the pre-Step-4 pipeline. Visual review caught Viterbi extending the contour through silence between phrases. Root cause: PESTO has no internal voicing detector, the RMS-floor veto rarely fires on bleed-heavy stems, so `vote_count` stayed ≥1 throughout silence; anchor candidates beat the unvoiced state (em ≈ 0.36 vs 4.6) and Viterbi smoothed a wandering F0 through the gaps. Fix: silence gate triggers on `vote_count == 0 OR fcpe_corrected == 0` — FCPE has a real internal voicing detector. Post-fix benchmark numbers settle at Sting 64.8% / Radiohead 67.8% / Cohen 49.4%, matching what the tracks actually contain.
7. **Canvas refactor + RMS opacity** (`06a34e3`) — F0 overlay refactored from SVG to canvas to support per-frame variable opacity along the contour. Vocals-stem RMS modulates opacity (louder → bright, softer → fade); strength-bucket info preserved as line-width modulation.

### Lessons recorded

- **`frames_with_finite_consensus_f0` is NOT a "higher is better" metric.** For a slow ballad like Cohen, ~50% is right; 99% means the line is wandering through silence. Successive runs without visual cross-checking would have drifted further from ground truth while looking better and better in the receipts. Visual review is load-bearing for any future tuning of the consensus pipeline.
- **The canonical "this frame is silent" signal in this stack is `vote_count == 0 OR fcpe_corrected == 0`.** PESTO has no internal voicing detector and the −45 dBFS RMS-floor veto rarely fires on bleed-heavy BS-RoFormer-cleaned vocal stems. FCPE's internal voicing is the cleanest silence gate without HNR.
- **F0 estimators on bass voices fail UP, not DOWN.** They harmonic-lock on the 2nd / 3rd / 5th partial; basic-pitch (which sees spectrum) usually gets the fundamental right on low voices. The Step 3 validator's asymmetric octave correction (only fold downward) and harmonic-ratio guard encode this domain truth — the spec's "F0 ≥ basic-pitch reliability" assumption inverts on bass-baritone.
- **Spec pseudocode is a sketch, not a contract.** The Step 3 and Step 4 implementations both diverged from the spec's pseudocode after empirical iteration. The committed code is the authority; spec §3 of the Phase 0c spec carries the final rule shapes for both. The historical pseudocode in spec §4 is preserved for the *why* but not for reference.

### Known limit

Cohen t=107.7s (target 87 Hz / F2) is architecturally unfixable in Step 4 alone. Inspection shows basic-pitch hallucinates three simultaneous notes at the 3rd / 4th / 5th harmonics, FCPE locks at the 2nd, PESTO at the 4th — every input stream is above the true fundamental. No Viterbi state-space path reaches truth without auxiliary voicing information. Rec 4 (HNR-based voicing) is the right venue, deferred per spec §7 resolution.

---

## Phase O — webui SDK bundling note (2026-05-09)

A small but useful architectural fact discovered during a routine `claude-agent-sdk` upgrade in the webui:

- Bumped `webui/requirements.lock` from `claude-agent-sdk==0.1.72` → `==0.1.77` (commit `5062536`).
- The 0.1.77 wheel is **platform-specific** (`claude_agent_sdk-0.1.77-py3-none-win_amd64.whl`, ~71 MB) and **bundles `claude.exe` inside the wheel** at `claude_agent_sdk/_bundled/claude.exe`. The SDK's subprocess transport uses that bundled binary directly — no PATH lookup, no `npx @anthropic-ai/claude-code` shell-out.
- This **refutes** [issue #208](https://github.com/anthropics/claude-agent-sdk-python/issues/208) ("ClaudeSDKClient hangs on Windows during initialization") on this codebase. Smoke-tested end-to-end via the chat actor in 7s, with the `init` SystemMessage arriving the same second `query()` returned. The original hang's root cause (anyio.open_process()-spawned subprocess never receiving the `control_response` to `subtype:initialize` on Windows) was structurally side-stepped — Anthropic now ships a known-good `claude.exe` inside the wheel and no longer depends on whatever the user's PATH provides. The original issue was closed-as-stale rather than closed-as-fixed; the bundling architecture is the de facto fix.
- **Operational consequence:** if you debug a future SDK hang, check first whether the running SDK is using its bundled binary. The webui log line `Using bundled Claude Code CLI: …\_bundled\claude.exe` confirms it is. If you see PATH-discovery logs or a fallback to `npx`, you may be on an older SDK and #208's failure mode could re-emerge.
- **Same-day housekeeping:** stale doc references to `scripts/webui-{start,stop,kill}.sh` (already replaced by `webui/webui.ps1` weeks earlier) were patched in `CLAUDE.md` and `docs/superpowers/plans/2026-05-03-track-rename.md`; `webui/requirements.txt` floor was tightened from `>=0.0.16` to `>=0.1.77`; 18 PNG screenshots from the modal-polish + Phase 0c arcs were archived under `tests/screenshots/` (commits `2cf7e20`, `84b9339`). Repo pushed to `github.com/RaduPrusan/MusIQ-Lab` (private) the same day.

---

## Phase P — WASAPI audio engine v1 (2026-05-12)

The webui shipped with a single audio path: Chromium's WebAudio over WASAPI Shared, with no per-device choice, no Exclusive mode, and no way to select the output device from inside the app. v1 of a selectable Windows audio engine landed today across five subagent-driven phases on a worktree branch (`worktree-wasapi-engine-v1`). Spec + plan: [`superpowers/specs/2026-05-12-wasapi-engine-v1-design.md`](superpowers/specs/2026-05-12-wasapi-engine-v1-design.md), [`superpowers/specs/2026-05-12-wasapi-engine-v1-plan.md`](superpowers/specs/2026-05-12-wasapi-engine-v1-plan.md). Empirical research that informed the architectural decisions: [`superpowers/specs/2026-05-12-wasapi-research-findings.md`](superpowers/specs/2026-05-12-wasapi-research-findings.md).

### Architecture in one paragraph

In-process Python audio thread (PortAudio via `sounddevice` 0.5.5, libportaudio V19.7.0-devel with WASAPI/MME enabled) inside the webui FastAPI process. One WebSocket at `/api/audio/control` carries control + clock messages JSON both directions. Stems are loaded on demand (44.1 kHz int16 stereo from `cache/<slug>/stems_6s/*.wav`, decoded with `soundfile`, resampled with `soxr` HQ to whatever the device wants — including 48 kHz on the FLOW 8 test rig). Stem mix bus is server-side: one PortAudio output stream sums the six stems with per-stem gain (10 ms one-pole smoothing matching `_applyGain` on the WebAudio side). The frontend ships an `AudioEngine`-contract-conformant `WasapiEngine` (`webui/static/js/audio/wasapi-engine.js`); the existing `WebAudioEngine` is unchanged and remains the always-available fallback.

### Phases 1–5 (ship order)

| Phase | What landed | Key commits |
|---|---|---|
| **1** | Device-picker scaffold; `AckMsg(set_device)` followed by `StreamInfoMsg` on the wire | `50c2201`, `9ed0c0a`, `48ed743` |
| **2** | WASAPI Shared playback + clock sync; smooth-cursor server clock + client-side rAF extrapolation with 30 ms hard-snap / half-delta soft-slew at 40 Hz tick rate | `8828b9e`, `e51ea20`, `d7d5c6c` |
| **3** | 6-stem mixing with mute/solo/volume; source/stems mode toggle. `play/pause/seek` now echo current mode in `StateMsg` so the client doesn't desync | `04d1e68`, `1bc90ab`, `5159a15` |
| **4** | WASAPI Exclusive mode + fallback chain (Exclusive → Shared on same device → MME on same-named device → WebAudio). Each step surfaces a single-line toast with the root cause | `d0d992a`, `c0dab69` |
| **5** | Sample-accurate loop wrap inside the audio callback (source mode); next-block-boundary wrap (~10 ms lag) for stems mode. Device hotplug refresh; live output-latency display in Settings; final docs | `d082fc1`, `c5993ab`, `43015cf` |

### Decisions worth recording

- **Stem WAVs are at the source MP3 rate (44.1 kHz int16 stereo), not 48 kHz.** `summary.json` does NOT carry a `sample_rate` field — the backend reads it via `soundfile.info()` on the stem WAV at load time. Memory: [[audio_stem_cache_format]].
- **PortAudio integer device indices are session-scoped.** The backend persists `(hostapi, device_name)` and re-resolves to a fresh integer index per session. Endpoint IDs change on driver upgrade and PortAudio doesn't expose them. Memory: [[windows_audio_device_identity]].
- **soxr 1.x ships a cp312-abi3 wheel** that works on the project's Python 3.13. Use `quality='HQ'` — VHQ adds 30–40% runtime for negligible perceptual gain on already-separated stems. Memory: [[soxr_python_313]].
- **Exclusive open on a device whose hardware rate ≠ requested rate returns `PaErrorCode -9997`**, not a silent fallback. Verified 2026-05-12 with `check_output_settings(samplerate=44100, exclusive=True)` on a 48 kHz device. The Phase 4 fallback chain handles this by stepping down to Shared on the same device.
- **`StreamInfoMsg` always follows `AckMsg(set_device)` on the wire**, never standalone — the frontend uses this invariant to know when an open has reached steady state. Memory: [[wasapi_engine_v1_shipped]].

End-to-end test on JINN: BEHRINGER FLOW 8 over USB Audio Class 2.0, 5-minute reference track, no audible jitter or drift across the full range of transport gestures. ~360 unit + integration tests across the new module.

---

## Phase Q — Identify pipeline overhaul, Rounds 1–5 (2026-05-12 → 13)

> **Trigger:** "I can't believe that Sting - Shape of My Heart is not found."

A round-based execution overhaul of `analyze/stages/identify.py` after a 17-track corpus probe revealed three distinct failure modes hiding behind a single "no AcoustID match above threshold" error string. Spec is the resumable round-based plan at [`superpowers/specs/2026-05-12-identify-pipeline-overhaul.md`](superpowers/specs/2026-05-12-identify-pipeline-overhaul.md); per-round delta + review reports live under [`superpowers/identify-overhaul/`](superpowers/identify-overhaul/). All five rounds shipped on `worktree-identify-overhaul` and were merged in `c75c9e6`. Corpus reference: [`superpowers/specs/2026-05-12-identify-corpus.md`](superpowers/specs/2026-05-12-identify-corpus.md).

### Three failure buckets, three fixes

The corpus probe (`scripts/probe_acoustid.py`) sorted the 17 unmatched tracks into:

- **Bucket A — zero AcoustID results.** YouTube source adds 1–4 s of leading silence/label slate, shifting Chromaprint's 6 s rolling windows out of phase with the canonical CD master.
- **Bucket B — high-score AcoustID, recordings: [] (unlinked to MusicBrainz).** Someone submitted a YouTube-source fingerprint and got an AcoustID ID but never linked it to a MusicBrainz recording. The old code took `max(results, key=score)`, found no recordings, returned None — discarding correct lower-scored results.
- **Bucket C — real match buried under unlinked higher score.** Same bug as B but the second-best result *is* the right one. The `max-then-check` shape threw it away.

### What landed across Rounds 1–5

| Round | Headline | Commits |
|---|---|---|
| **R1** | Spec + corpus + evidence; static analysis of `acoustid_client.lookup`; key-spelling audit | `151c2ec`, `7ffa254` |
| **R2** | Walker fix (iterate `results` until linked recording found), atomicity (write-to-tmp-then-rename), structured logging, observability, `SCHEMA_VERSION` bumped to 2 | `baa991b`, `19f60aa`, `90d60be` |
| **R3** | Silence-strip preprocessing (BS-RoFormer-derived gate trims leading audio under −45 dBFS before fpcalc); `SCHEMA_VERSION 2 → 3` | `ea7ab72`, `1bc90ab`, `e0f70f8` |
| **R4** | MusicBrainz text-search fallback (when AcoustID returns nothing, query MB by slug-derived artist/title with `duration_variance < 0.03` guard); reason-code disambiguation; webui Metadata-card trust signaling (italic "via text-match search" note) for fallback / unenriched matches | `c0b2b98`, `149deb0`, `dc2c52a`, `fcc4352`, `d3a2039` |
| **R5** | Artist-plausibility gate on the canonical AcoustID path; slug parser update + Unicode/smart-quote normalization in difflib + Lucene paths; `SCHEMA_VERSION 4 → 5`; spec §2 calibration amendment | `d0b2b51`, `56c0367`, `aea7b01` |

### The Gorillaz win

Pre-R5, the Gorillaz reference track was being identified by AcoustID at `score=0.99` as "DJ Allan McLoud — Silent Running / 100% Eurotrance 3 (2001)" — fabricated metadata served to the user for months. The artist-plausibility gate caught this:

```
slug-derived artist = "Gorillaz"
acoustid-proposed artist = "DJ Allan McLoud"
difflib.SequenceMatcher ratio = 0.2609   < threshold
→ identified=false, reason=acoustid_artist_mismatch
```

The rejection bypasses `_preserve_or_write` because it's an integrity decision, not a transient error — the cached identified=true must flip. Round 5 also added a "substring rescue" branch (`56c0367`) that catches legitimate matches where the slug-derived artist string is contained in (or contains) the identified artist string — this saved two tracks (Buddha Bar, Notre-Dame) that the initial 0.50 threshold had transiently demoted.

### Final corpus results (30 tracks)

| Source | Count | Notes |
|---|---:|---|
| `acoustid` (canonical) | 13 | All verified plausible via artist-plausibility gate |
| `fallback` (MB text-search) | 1 | nightbus — R4's only fallback win |
| `none` (unidentified) | 16 | 13 `fallback_no_match`, 1 `fallback_ambiguous`, 1 `acoustid_artist_mismatch`, 1 skipped (mp3 missing) |

14/30 identified (47%). Below the spec §2 target of 75%, but the Round 4 final review (`round-4-final-review.md`, Gemini independent) reframed the target as a Round-1 framing error — many corpus slugs are niche live performances that AcoustID will never have a fingerprint for, and text-search fallback can't recover them without a lower bar on title similarity, which would re-introduce false positives. The Round 5 delta records the trade explicitly.

### Lessons recorded

- **Round 4's "code-correctness APPROVED" verdict survived to the user-driven scrutiny test.** Unlike Phase L's overconfident "APPROVED" → Phase M correction arc, the identify overhaul shipped the Gorillaz fix verified by visual diff against the cache.
- **`max(results, key=score)` is a bug shape**, not a one-line fix. It throws away every result except the top, and when the top is unlinked, the whole call returns None. The right shape is iterate-until-linked-recording-found. Caught in R1's static-analysis pass, fixed in R2.
- **`_preserve_or_write` is for transient errors only.** Integrity demotions (artist-plausibility rejection) must bypass it and flip the cache, otherwise a once-mis-identified track stays wrong forever. Memory updated at [[identify_demotion_protection]].
- **Threshold-tuning has a ceiling.** Round 5's Item 2 (lower the title-similarity threshold from 0.85 to 0.75) did not recover Charlie Puth / Moderat / Balthazar. The root cause is deeper than the threshold — `clean_title` noise-token stripping is the next lever, or AcoustID's `releasegroups` metadata when present. Documented as Round 6+ scope in `round-5-delta.md` §9.

---

## Phase R — Notation coherence + default-to-MIX + auto-scroll pill (2026-05-13)

Three small but UX-load-bearing shipping items landed the same day as Round 5, all on `main` after the worktree merges. No worktree, no spec — these were direct-to-main polish commits driven by hands-on use.

### 1. Notation coherence (`11dfe3c`)

The Pitch notation Settings option (Scientific / Solfège / Flat / Sharp / etc.) was respected in *some* surfaces but not others — the piano-roll chord strip, inspector gutter highlight, Cross-check card key value, analyze-modal stats panel, and track-picker key column all rendered raw analyzer spellings or hard-coded scientific letters. Fixed by routing every site through the central notation pipeline (`notation.js → reformatRootedName(formatChordShorthand(label), system)`). `formatChordShorthand` and `humanizeKeyString` hoisted into `notation.js` from the per-file duplicates in `sidebar.js` / `topbar.js`. The inspector-gutter highlight specifically replaced its hard-coded sharp-only chromatic array lookup with a `data-midi` attribute on each gutter row — the row's MIDI number is the canonical thing; the rendered label is presentation. 72/72 tests pass across `notation`, `crosscheck-{card,row}`, `analyze-shared`, `track-picker`, `analyze-modal`.

A separate analyze-side prompt (`fb39a1f`, `prompts/fix-key-scale-enharmonic-coherence.md`) was filed for the backend key/scale enharmonic coherence question — when the librosa K-S fallback emits `D#:major` while the chord stage emits flats consistent with `Eb:major`, the WebUI's notation switch can't fully fix the disagreement. That fix is queued, not yet executed.

### 2. Default-to-MIX (`fc31619`)

Stem-mix becomes the default playback mode the moment any stem decodes — both engines. A stem mute/solo press while in SRC mode now auto-promotes to MIX so the gesture isn't a silent no-op (was a frequent confusion). WASAPI mirrors this via a server `set_mode` round-trip; WebAudio promotes locally on first `stemLoaded`.

### 3. CENTER/EDGE auto-scroll pill + smooth glide (`fc31619`)

The auto-scroll anchor (center vs edge) is now a user-visible pill in the transport, persisted to `localStorage["musiq.scrollAnchor"]`. Anchor is no longer silently overridden by canvas drag or scrub release — it stays where the user put it. Edge band tightened from `[20%, 80%]` to `[30%, 70%]` after empirical use felt the old band wandered too far before snapping.

Scroll transitions now glide instead of snapping: when the gap between current scroll and the auto-scroll target exceeds 80 ms, lerp 30%/frame until the gap drops under 5 ms, then snap-lock for zero steady-state lag. Triggered by anchor toggle, edge crossings, seeks, and scrub-bar releases. Scrub bar height bumped 6 px → 18 px to match the AUTO/MIX/SRC pills so it's a real click target. 14/14 coords tests pass against the new 30–70% band.

---

## Appendix — Memory anchors

Living memories that govern future work on this project (under `~/.claude/projects/<CLAUDE_PROJECT_ID>/memory/`):

- `install_lessons.md` — don't pin `numpy<2`, use `basic-pitch[onnx]`, audit pins, restart-don't-patch.
- `latest_versions_preference.md` — fix MIR-stack version clashes by updating downstream / patching, not by pinning newer packages backward.
- `mir_api_quirks.md` — verified entry points for skey, lv-chordia, madmom.
- `wsl_bash_dollar_quoting.md` — msys2-from-Git-Bash eats `$VAR` in single-quoted args (escape with `\$`) and rewrites `/mnt/...` paths (`MSYS_NO_PATHCONV=1`).
- `codex_cli_usage.md` — Codex CLI gotchas (unrelated to MIR but on this project's index).
- `adtof_install_facts.md` — install via `git+https://github.com/MZehren/ADTOF.git` (NOT PyPI); uses TensorFlow not Torch (spec's Torch 2.7 conflict is moot).

---

## Reading order for a successor

1. `CLAUDE.md` — what the project is and the YouTube-download workflow that feeds it.
2. `docs/README.md` — the original design intent.
3. `docs/history.md` (this file) — what changed and why.
4. `prompts/test-stack-torch27.md` — the executable, validated runbook for the per-stage stack.
5. `analyze/README.md` + `docs/superpowers/specs/2026-04-29-analyze-py-design.md` — the production driver and its design spec.
6. `cache/gorillaz_silent_running/` — reference end-to-end artifacts (drives the integration tests).
7. `install-logs/batch-test-results.md` — what real-world MP3s look like through the pipeline (incl. known upstream-model limits).
8. `docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md` — the design spec for the Phase A+B specialists + selective re-run.
9. `install-logs/phase-a-validation.md` — Phase A+B ship-gate report (Gorillaz partial; full-corpus blocked on user labels).
10. `docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md` + the round-delta + final-review pages under `docs/superpowers/identify-overhaul/` — the identify pipeline's R1–R5 arc (Phase Q above) end-state.
11. `docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` + `webui/CHANGELOG.md` "WASAPI audio engine v1" entry — the Windows audio engine v1 (Phase P).
