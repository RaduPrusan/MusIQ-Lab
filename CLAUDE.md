# MusIQ-Lab — Download Workflow + Music Analysis Stack

> **For contributors reading this on GitHub:** This file is the maintainer's
> working notes for Claude Code. Absolute paths (e.g. `C:\Users\<you>\...`)
> reflect the maintainer's local layout — substitute your own. Anything
> shippable lives in the `analyze/` and `webui/` packages; everything in this
> file is conventions and runbook reminders.

This project has three halves (one is a UI on top):

1. **Download workflow** (this file's main body): grabbing audio/video from YouTube via local `yt-dlp.exe`. When the user asks "download this YouTube link" / "grab the audio from..." / "save this video", follow the workflow below.

2. **webui** — local FastAPI app for browsing and chatting about analyzed tracks (piano-roll, mixer, chord/loop info; per-track chat via `claude-agent-sdk` `ClaudeSDKClient` + in-process MCP tools, see `webui/webui/chat_actor.py`). **Binds `127.0.0.1:8765`** (not 8000 — don't port-scan). Launched via `webui/run.bat`, `python -m webui` from inside `webui/.venv`, or for headless control `webui/webui.ps1 {start,stop,restart,kill,status,logs,monitor}` (idempotent; logs to `webui/webui.log` + `webui/webui.log.err`). Source in `webui/`, [`webui/README.md`](webui/README.md) for setup. Spec at [`docs/superpowers/specs/2026-04-30-webui-design.md`](docs/superpowers/specs/2026-04-30-webui-design.md).

3. **Music-analysis stack** (validated April 2026): an MIR pipeline that takes an MP3 and produces stems, beats/downbeats/tempo, key, chords, MIDI per stem, vocal F0, and a reconciled summary. See:
   - [`docs/history.md`](docs/history.md) — what's been built, what changed, why
   - [`prompts/test-stack-torch27.md`](prompts/test-stack-torch27.md) — the executable, validated runbook
   - [`docs/README.md`](docs/README.md) — architecture and per-stage docs (per-task pages have been retrofitted; the higher-level design pages remain frozen at design time, with allin1 references)
   - `cache/gorillaz_silent_running/` — example artifacts from the validation run
   - [`install-logs/batch-test-results.md`](install-logs/batch-test-results.md) — what real-world MP3s look like through the pipeline (5 mixed-genre tracks, with fixes for what surfaced)

   The stack runs inside WSL2 Ubuntu 24.04 with a project-local venv at `.venv/` (Python 3.11 via uv, Torch 2.7.1+cu126 — `deezer/skey` pins `~2.7.0`). `requirements.lock` is checked in. The production driver lives in the `analyze/` package and runs as `python -m analyze <mp3>` — see [`analyze/README.md`](analyze/README.md). ~1060 tests pass (analyze + webui); batch-validated on 5 mixed-genre MP3s (April 2026), with two real bugs found and fixed: librosa duration on malformed Xing/VBR headers (now uses ffprobe) and `vocal_range` from leaked instrumental content (now suppressed via a BS-RoFormer RMS-ratio detector).

   **Vocal consensus pipeline (Phase 0c, May 2026)** — fuses FCPE / PESTO / basic-pitch into a per-frame `consensus_f0` Hz contour with `agreement_strength ∈ [0, 1]` for confidence-bucketed UI rendering. The Step 4 Viterbi smoother (8-state candidate space, anchor-proximity emission bonus, 1200¢ Gaussian transition penalty) is the default; the Step 2 heuristic builder remains as a `viterbi_enabled=False` fallback. Spec + ship report: [`docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md`](docs/superpowers/specs/2026-05-05-vocal-consensus-improvements.md), [`install-logs/phase-0c-results-2026-05-05.md`](install-logs/phase-0c-results-2026-05-05.md). Key lesson recorded there: `frames_with_finite_consensus_f0` is **not** "higher is better" — for slow ballads the right value is ~50%, not 99%; visual review is load-bearing for any future tuning. Rec 4 (HNR voicing for the Cohen t=107.7s harmonic-lock canary) deferred.

   **Drums (Stage 9, optional)** — typed onset detection per drum-piece (kick/snare/toms/hihat/cymbals) using LarsNet drum source separation + per-substem librosa onsets. LarsNet ships separately (CC BY-NC 4.0 weights, ~562 MB); install with `bash scripts/install-larsnet.sh`. If not installed, the stage soft-fails and the rest of the pipeline still runs — the drums entry in `summary.json` falls back to `{transcribed: false}`. See [`analyze/vendor/README.md`](analyze/vendor/README.md).

   **Identify pipeline (May 2026, SCHEMA=5)** — `analyze/stages/identify.py` calls AcoustID (Chromaprint fingerprint via vendored `fpcalc`) → MusicBrainz to populate `cache/<slug>/identify.json`. After a five-round overhaul (`docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md` + per-round deltas under `docs/superpowers/identify-overhaul/`), the stage ships with: walker-based result iteration (was buggy `max()` discarding linked results), silence-strip preprocessing for YouTube-source fingerprints, MusicBrainz text-search fallback with `duration_variance < 0.03` guard, an artist-plausibility gate on the canonical AcoustID path (slug-derived artist vs MB-identified artist, with substring rescue), Unicode/smart-quote normalization in both difflib + Lucene paths, and demotion protection (`_preserve_or_write`) that keeps cached `identified=true` through transient AcoustID/MB errors but is bypassed by integrity rejections so a once-mis-identified track flips correctly. `--no-identify` CLI flag disables the stage. Webui Metadata card surfaces fallback / unenriched matches with an italic "via text-match search" trust signal.

   **WASAPI audio engine v1 (May 2026)** — Windows-side webui audio path with three selectable output modes per device (MME / WASAPI Shared / WASAPI Exclusive). PortAudio audio thread inside the webui Python process; one WebSocket at `/api/audio/control` for control + clock; `soxr` HQ resampling to device rate; server-side stem mix bus; sample-accurate loop wrap in source mode (~10 ms lag in stems mode). Exclusive-open failure falls back Shared → MME → WebAudio with a single-line toast each step. WebAudio remains the default and always-available fallback. Spec: [`docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md`](docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md). Notes on per-session PortAudio device indices in [[windows_audio_device_identity]], stem WAV format in [[audio_stem_cache_format]], soxr-on-3.13 in [[soxr_python_313]].

   **Live mic-pitch layer (May 2026)** — browser-only "Live Input" pseudo-stem above the existing six rows, showing the user's microphone pitch contour drawn in real time pinned to the song timeline. Cents-off colouring vs a user-selectable reference stem (default vocals). YIN in an AudioWorklet, ring-buffered on the main thread (Float32 MIDI so the contour shows true cents resolution, not semitone-quantized), rendered above the F0 overlay. Per-user offset slider compensates for browser mic input latency (Web Audio doesn't expose it). Sits on the same `.track-row` sidebar grid as the six regular stems for visual coherence. Spec + post-ship deltas: [`docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md`](docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md). Plan: [`docs/superpowers/plans/2026-05-22-live-mic-pitch-layer.md`](docs/superpowers/plans/2026-05-22-live-mic-pitch-layer.md). Ship report (8 bugs caught + fixed during ship): [`install-logs/live-mic-results-2026-05-23.md`](install-logs/live-mic-results-2026-05-23.md). Lessons: forcing `echoCancellation/noiseSuppression/AGC = false` in `getUserMedia` constraints is mandatory (the browser's default "voice" DSP destroys pitch information); store ring-buffer pitch as `Float32`, not `Uint8` (Uint quantizes to semitones — invisible in tests, painfully visible in the rendered contour).

   **Live mic-pitch layer — 2026-05-23 iteration** — same-day post-ship pass landed: (a) **4-bucket colour scheme** — `in` (matched ≤100¢), `off` (unmatched >100¢), `neutral` (matched-to-stem-but-silent), `no-match` (match=none), each its own theme token (`--mic-in`/`--mic-off`/`--mic-neutral`/`--mic-no-match`) defined in all 5 presets; the sidebar `.swatch` uses `--mic-no-match` as a static row identifier. `--mic-accent` retired. (b) **Settings → Pitch lines section** surfaces line widths (mic + vocals, 0.5–4 px, default 1) and colours (4 mic + 3 f0) via `theme/store.setToken`, riding `musiq:theme-changed`. (c) **EMA smoothing** (α=0.4) on rendered midi + cents kills YIN's ±5–10¢ frame-to-frame shimmer on held notes without killing vibrato. (d) **Transport correctness** — `MicPitch._onSample` gates ring writes on `engine.isPlaying === false` (else samples stack at frozen `tSong` and draw as vertical spikes at the playhead); the draw-side `MAX_SEGMENT_GAP_S` guard in `mic-overlay.js` uses `Math.abs(t1 − t0)` so backward seeks don't bridge clusters (ring is insertion-ordered, not time-ordered). (e) Mic mute-button glyph is now a stroke SVG (`currentColor`) instead of the letter "M". Memory entries: [[mic_overlay_color_buckets]], [[mic_ring_gate_isplaying]], [[feedback_surgical_changes_no_tests]].

   **Sidebar + theme polish — 2026-05-24 iteration** — three orthogonal polish passes landed in two commits (`3e50218` UI, `1e7769c` theme):
   - **Right-sidebar tabs** reordered to Track / Lyrics / Assistant (was Track / Claude / Lyrics, with "Claude" → "Assistant" rename). Tab `id`s stay `track`/`claude`/`lyrics` so persisted `localStorage["musiq:activeTab"]` state remains valid; only the display label changed.
   - **Mic row layout** — "Live Input" title is now a **collapse toggle** for the second sub-meta row (match dropdown + offset slider) via a `▾`/`▸` chevron prefix, persisted to `localStorage["musiq.mic.metaCollapsed"]`. Row is now a **boxed card** matching the Now Playing visual (`--surface-base` bg + 1 px `--surface-3` border + 6 px radius). Grid switched from `12px 1fr 96px 26px` (mic-specific) to the **stem 5-col grid** `12px 1fr 36px 56px 52px` with `margin: 0 -7px` compensating for box-padding so swatch / name / readout-right / M-button stack vertically with the stem rows below. `.mic-readout` spans cols 3–4. Lone-M button gets `padding-right: 25px` on its `.ms` cell to land at the same +5px offset within the 52-px ms cell as each stem M button (mirroring the stem's M+gap+S right-aligned gutter). Chev `margin-left: -10px` pulls "Live Input" label start back to swatch+8px so it aligns with "Vocals" / "Piano" labels.
   - **Small sliders** (stem-vol, mic-offset, zoom — share `.vol`+`.vol-fill` div pair via track.css + an inline duplicate in transport.js's `_zoomGroup`) — height tuned 4 px → 6 px with a new visual tier: **80 % border / 50 % fill / 20 % empty**, all keyed off `--text-primary` via `color-mix(in srgb, var(--text-primary) N%, transparent)`. Theme-portable: pure white in Jinn/HC, near-black ink in Studio Light. The scrub bar (`#transport .scrub`, 18 px tall) is a separate category and stays unchanged.
   - **Theme: Jinn is now `DEFAULT_PRESET_ID`** (was `classic-dark`), baked from the live customizer with 4 token updates (`stem-piano #ffb380`, `stem-other #ff80fb`, `stem-drums #ffffff`, `mic-no-match #80ff00`). Cross-theme audit of the other 4 presets fixed two HC stem↔fn hex collisions, re-derived the Studio Light drum palette (the dark defaults failed 3:1 AA-non-text on the light drum-lane), documented a structural light-theme `text-disabled` hierarchy inversion, and resolved the Midnight warm-stems-on-cool-chrome deferred minor (documented as deliberate; bass shifted to teal to break the cool-stem-vs-accent collision). Audit rules + per-token rationale: [[theme_audit_2026_05_24]].

   **Pitch-notation setting** — every pitch/chord/key surface in the webui (piano-roll chord strip, gutter highlight, sidebar Cross-check, analyze-modal stats, track-picker key column) routes through `static/js/music/notation.js` and obeys the user's **Settings → Pitch notation** choice — which has exactly **two** systems, Scientific and Solfège (there is no "Flat"/"Sharp" display mode). Don't introduce hard-coded scientific letters when adding a new pitch display — call `reformatRootedName(formatChordShorthand(label), system)` and let the central pipeline handle it. **Enharmonic spelling is decided upstream, not at display time:** the *key string* is the source of truth (notation.js deliberately does not re-spell it), and the webui derives each track's sharp/flat note-spelling bias from `summary.track.key` via `parseKey().sharpSide`. So the backend's key spelling is load-bearing — `analyze/derived/theory.py` spells keys with the conventional circle-of-fifths rule (`_MAJOR_FLAT_PCS`/`_MINOR_FLAT_PCS` in `_canonical_tonic`); changing it changes how every gutter note is spelled. The backend key strings use **Unicode** `♯`/`♭`, so the JS key parsers (`parseKey`, `pianoroll.js keyInfo`, `sidebar.js tonicFromKey`) must normalize `♯→#`/`♭→b` before matching — they once handled only ASCII `[#b]` and silently mis-parsed a Unicode tonic a semitone off (`E♭`→`E`). And: **verify any key/spelling change in the running webui with a Playwright screenshot you actually look at** — see [[feedback_verify_webui_visually]]; that regression shipped through green tests + a 60-track migration because nobody viewed the rendered gutter.

   **Don't bump Torch off 2.7** — `deezer/skey` pins `torch = "~2.7.0"`. Don't try to revive `allin1` — see history.md for the rabbit hole.

---

## Download workflow

## Tools & paths

- **yt-dlp binary:** `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe`
- **Default output folder:** `C:\Users\<you>\Videos\Any Video Converter Ultimate\Youtube`
- **FFmpeg:** assumed on PATH (yt-dlp uses it for audio extraction and muxing). Confirmed working.

> The hardcoded path above is for this agent's **conversational** download workflow on the maintainer's machine. Programmatic callers in the repo (webui `analyze_runner.py`, `scripts/fetch-test-fixtures.sh`) instead resolve the binary via `$MUSIQ_YTDLP_BIN` (default `yt-dlp` on PATH) — never hardcode the maintainer path in new scripts. See memory [[ytdlp_env_var_convention]].

Don't ask the user where to save unless they specify a different folder — the output folder above is the project default.

## Bash-on-Windows quirk

The yt-dlp path contains `$` characters (`$WinSoft`, `$tools`) that bash tries to expand as variables. **Always single-quote the path** in Bash tool calls:

```bash
'C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe' [args...]
```

Double quotes or unquoted will silently expand `$WinSoft` to empty and the binary won't be found. PowerShell tool calls don't have this issue.

## Standard commands

### Audio (MP3, highest VBR quality)

```bash
'C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe' \
  -x --audio-format mp3 --audio-quality 0 \
  --no-update \
  -o 'C:/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/%(title)s-%(id)s.%(ext)s' \
  '<URL>'
```

### Video (best quality, mp4 container)

```bash
'C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe' \
  -f 'bv*+ba/b' --merge-output-format mp4 \
  --no-update \
  -o 'C:/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/%(title)s-%(id)s.%(ext)s' \
  '<URL>'
```

### Output template rationale

`%(title)s-%(id)s.%(ext)s` — the 11-char video ID is appended so re-downloads or different videos with similar titles never collide. yt-dlp auto-substitutes `%(ext)s` with the final container extension after post-processing.

## Auto-update on the spot

YouTube rolls out anti-bot/signature changes frequently. Builds older than ~90 days routinely fail. **Update without asking the user when any of these triggers fire:**

1. **`HTTP Error 403: Forbidden`** during the download phase
2. **`Your yt-dlp version (...) is older than 90 days`** warning at the top of output
3. **`Some ... formats have been skipped as they are missing a url`** SABR warnings combined with a download failure
4. **`Requested format is not available`** with no obvious format-spec mistake
5. **`Sign in to confirm you're not a bot`** challenges on a public video

Update command:

```bash
'C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe' -U
```

Then retry the original command. Add `--no-update` to the actual download commands to suppress the staleness warning during normal runs (don't add it to the update command itself — `-U` *is* the update).

If the update succeeds but the download still fails, then surface the error to the user — don't loop on retries.

## Suppressing noise

- `--no-update` — silences the "older than 90 days" banner once you've already updated this session.
- The `No supported JavaScript runtime could be found` warning is harmless on this machine; yt-dlp falls back to `android vr` / `android sdkless` clients which work for most videos. Don't try to install deno just to silence it — only act if the download actually fails with a SABR-related error.

## What NOT to do

- Don't `pip install yt-dlp` or use any other yt-dlp install — the binary at `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe` is the canonical one.
- Don't change the output folder unless the user asks.
- Don't strip the video ID from the output template "to make filenames cleaner" — collisions are worse than visual clutter.
- Don't keep the intermediate `.webm`/`.m4a` (don't pass `-k`) unless the user asks for the original lossless source.
