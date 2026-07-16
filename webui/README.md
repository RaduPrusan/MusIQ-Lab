# webui — MusIQ-Lab local UI

Self-contained Windows-side web UI for browsing and studying tracks analyzed by the `analyze` package.

## First-time setup

```bat
cd webui
uv venv .venv
uv pip install -r requirements.txt
uv pip freeze > requirements.lock
```

## Run

Double-click `run.bat`, or:

```bat
.venv\Scripts\python -m webui
```

Server binds `127.0.0.1:8765`. Browser opens automatically when launched via `run.bat`.

### Lifecycle (PowerShell, recommended on Windows)

`webui/webui.ps1` is a verb-dispatched manager that detaches the server,
tracks its PID + port, redirects logs to `webui/webui.log{,.err}`, polls
readiness, and provides status / monitor / log-tail commands. Run from
the `webui/` directory (or any cwd — paths are resolved relative to the
script):

```powershell
.\webui.ps1 start          # detached launch; idempotent if responsive
.\webui.ps1 status         # port owner, API health, orphans, log sizes
.\webui.ps1 monitor        # live console dashboard, refresh every 2s
.\webui.ps1 logs           # tail webui.log (Ctrl+C to exit)
.\webui.ps1 logs -Err      # tail webui.log.err
.\webui.ps1 logs -Both     # interleave with [OUT]/[ERR] prefixes
.\webui.ps1 logs -Static -Tail 200   # last 200 lines, no follow
.\webui.ps1 stop           # graceful stop; force fallback after 3s
.\webui.ps1 kill           # force-kill port owner + sweep orphans
.\webui.ps1 restart        # stop, then start
.\webui.ps1 help           # full reference
```

`start` is idempotent: no-op if our process is already responsive,
refused if a foreign process owns port 8765. Each `start` truncates
`webui.log{,.err}`. `--reload` (dev mode) is not supported via `start`
— use `run.bat` for foreground dev with reload.

If your execution policy blocks the script, run it once via
`powershell -ExecutionPolicy Bypass -File .\webui.ps1 start`, or set
the per-user policy with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### Lifecycle scripts (Git Bash) — removed

The previous `scripts/webui-{start,stop,kill}.sh` shell scripts used
Linux-only primitives (`lsof`, `nohup`, `kill -TERM`) that don't resolve
a real port-owner PID on Windows. They've been deleted in favor of the
PowerShell script above.

## Develop

```bat
.venv\Scripts\python -m webui --reload
```

> `--reload` is **auto-disabled on Windows** (claude-agent-sdk needs the
> ProactorEventLoop, which uvicorn's reloader doesn't preserve) — the process
> runs without it; restart to pick up backend changes. Backend Python is 3.13
> (`pyproject.toml` pins `requires-python >=3.13`).

Tests:

```bat
.venv\Scripts\python -m pytest
```

Frontend pure-logic tests (Node 20+):

```bat
node --test tests-js\*.test.js
```

(Run from `webui/` — verified 279/279 in ~4 s.)

## Spec

See `../docs/superpowers/specs/2026-04-30-webui-design.md`.

The sidebar redesign is specified in
`../docs/superpowers/specs/2026-05-02-sidebar-tabs-claude-lyrics-design.md`.

## Sidebar tabs

The sidebar has three tabs, left→right: **Track / Lyrics / Assistant**.

- **Track** — the existing analysis sidebar (Now playing, Stems, Loop, Function, Harmony stats).
- **Lyrics** — synced lyrics from LRCLIB with karaoke-style auto-scroll. Click any line to seek. Stored under `cache/<slug>/lyrics/`.
- **Assistant** — chat with an in-app music tutor. (The tab was renamed from "Claude"; its internal `id` is still `claude`, so a persisted `localStorage["musiq:activeTab"] = "claude"` stays valid.) Authenticates via your existing `claude /login` (Pro/Max subscription); no API key required. Conversations are persisted per-track at `cache/<slug>/chat.json`.

The active tab is remembered in `localStorage` (`musiq:activeTab`). Both `chat.json` and `lyrics/` are preserved across re-analysis — the Reanalyze action only wipes the pipeline-derived artifacts.

If the Assistant tab shows "signed out", run `claude /login` in a terminal and click Retry.

## Live input (microphone pitch)

A browser-only **Live Input** pseudo-stem lets you sing along and see your pitch
contour drawn in real time, pinned to the song timeline above the F0 overlay.

- YIN pitch detection runs in an `AudioWorklet` (`static/js/audio/mic-yin-processor.js`),
  ring-buffered as `Float32` MIDI (`static/js/audio/mic-pitch.js`) and rendered by
  `static/js/render/mic-overlay.js`.
- Colouring uses four buckets — `in` (≤100¢), `off` (>100¢), `neutral`
  (matched-to-stem-but-silent), `no-match` (no reference) — each its own theme
  token (`--mic-in/-off/-neutral/-no-match`); tune them under **Settings → Pitch lines**.
- A reference-stem dropdown (default vocals) and a per-user latency-offset slider
  compensate for browser mic input delay (Web Audio doesn't expose it).
- A per-user **transpose spinner** (± semitones, clamped [−24, +24], signed display,
  default 0) shifts where the live pitchline draws — sing an octave down and still
  land on the melody. Lives on the Live Input row on both the Track sidebar and the
  compact Lyrics strip (the two stay in sync), persisted under
  `localStorage["musiq.mic.transpose"]`.
- `getUserMedia` forces `echoCancellation/noiseSuppression/AGC = false` — the
  browser's "voice" DSP otherwise destroys pitch information.

## Loop region

A playback loop region (in addition to the analyzed song-structure loops) can be set via Claude (`set_loop_region` tool) or programmatically via `viewState.setLoop(start, end)`. While a loop is set:

- A translucent orange band appears on the pianoroll canvas and the minimap track.
- A `Loop M:SS.s–M:SS.s ✕` chip appears in the transport bar; clicking it clears the loop.
- The audio engine wraps the playhead from `loopEnd` back to `loopStart` automatically (re-using the existing `seek()` path).

## Testing matrix

| Suite | Command | What it covers |
|---|---|---|
| Backend unit | `python -m pytest` | tracks scan, audio range parser, f0 decoder, FastAPI routes |
| Frontend pure-logic | `node --test tests-js/*.test.js` (from `webui/`) | track-data transform, view-state pub-sub, coords math, picker filter |
| Integration | `cd tests-e2e && npm test` | end-to-end browser flow against Gorillaz fixture |

Run all three before tagging a release.

## Tools menu

Topbar **⚒ Tools** opens a modal with per-track actions:

| Action | What it does |
|---|---|
| `Open <stem>.mid in default Windows handler` | `os.startfile()` on the per-stem MIDI |
| `Reveal cache/<slug>/ in Explorer` | Opens the cache folder in Windows Explorer |
| `Reanalyze (clear cache + re-run pipeline)` | **Destructive.** Wipes `cache/<slug>/` and runs the full analyze pipeline in WSL, streaming stage progress + a final stats panel into a modal |

Reanalyze prefers `track.windows_path` (the original source) and falls back to the cache MP3 mirror when the original is gone. Source is staged to a tempdir before the cache wipe, so the in-cache copy is safe to lose. Only one reanalysis runs at a time across the process — concurrent requests get an "another reanalysis is already running" error event without disturbing the in-flight job.

The pipeline runs in WSL (`wsl -- bash -c '... python -m analyze ...'`) using the project's `.venv` at `/mnt/.../MusIQ-Lab/.venv`. The endpoint streams NDJSON (`{type:"stage"|"log"|"done"|"error", ...}`) so the modal can show a live stage badge + scrolling log + post-run stats (duration, tempo, key+confidence, scale, chord/downbeat/note counts, drum hit breakdown, predominant loop with roman numerals, vocal range, and pipeline warnings).

## Mouse / wheel reference

| Gesture | Action |
|---|---|
| Click on canvas | Seek to clicked time (3 px slop distinguishes click from drag) |
| Click on minimap track | Center viewport on cursor |
| Click + drag on minimap viewport rect | Scroll preserving cursor offset |
| Click on transport scrubber | Seek + recenter canvas at midpoint (auto-scroll mode = `center`) |
| Drag canvas | Scroll horizontally + vertically (hand-tool: down → higher pitches) |
| Wheel | Scroll horizontally |
| `Ctrl + Wheel` | Zoom horizontally, anchored at cursor |
| `Shift + Wheel` | Zoom vertically |
| Hover over canvas | Show pitch tooltip + row band overlay |

Auto-scroll has two modes. **Edge** (default during normal playback): playhead is pinned inside `[20%, 80%]` of the viewport — no scroll while drifting in the band, snap to the matching edge when crossing out. **Center** (entered after using the bottom scrubber): playhead is pinned at viewport midpoint. Any manual canvas drag pauses auto-scroll until the user re-engages it from the badge in the bottom-left.

## Theming

A full design-token theme system (shipped 2026-05-09) lives under `static/js/theme/` and `static/css/tokens.css`. Five presets ship: **Jinn** (default — the maintainer's baked palette, `DEFAULT_PRESET_ID` since 2026-05-24), **Classic Dark**, **Midnight**, **Studio Light**, and **High Contrast**. Pick or customize them via **Settings → Appearance**.

- Every preset enumerates every token explicitly — no `...spread` inheritance — so edits to one preset don't leak into the others (convention since 2026-05-10).
- User selection + per-token customization persist in `localStorage["musiq.theme"]` (schema v1, full resolved token map).
- A pre-paint hydration script in `<head>` of `static/index.html` applies the saved theme before first render to prevent FOUC.
- Canvas-side colors (piano-roll, F0 overlay) are read via `static/js/theme/css-tokens.js` (`readToken` / `readAlpha` / `subscribe`) and rebound on `musiq:theme-changed`.
- Adding a new preset → enumerate every token in `static/js/theme/presets.js`. Adding a new token → declare default in `static/css/tokens.css`, add to all 5 presets, add a validator prefix in `static/js/theme/store.js` if it's a new category.

## Architecture notes

The frontend talks to an `AudioEngine` interface (`static/js/audio/engine.js`). Two engines implement it: `WebAudioEngine` (default, always-available fallback) and `WasapiEngine` (`static/js/audio/wasapi-engine.js`, shipped 2026-05-12) which drives a Python PortAudio sidecar in `webui/webui/audio_backend/` over a single WebSocket (`/api/audio/control`) for low-latency MME / WASAPI Shared / WASAPI Exclusive output. The engine is selected in **Settings → Audio engine**; on any exclusive-open failure the chain falls back Shared → MME → WebAudio. The piano-roll renderer subscribes to `engine.on('time')` and never reads `audioElement.currentTime` directly; mute/solo/volume state lives only in the engine. See `../docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` and the CHANGELOG "WASAPI audio engine v1" entry.

State zones:

- **Server** (`tracks.py` mtime cache) — process lifetime
- **Track data** (`buildTrackData`) — frozen post-load, shared by all UI components
- **View state** (`createViewState`) — zoom, scroll, highlightedStem, autoScroll
- **Engine state** (`WebAudioEngine`) — currentTime, isPlaying, per-stem mute/solo/volume

The renderer is a pure function of `(trackData, viewState, engine.currentTime)`.
