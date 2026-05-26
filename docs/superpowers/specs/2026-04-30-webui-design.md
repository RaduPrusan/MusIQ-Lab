# `webui/` design — local browser UI for the analysis pipeline

**Date:** 2026-04-30
**Scope:** v1 of a Windows-side web UI that consumes the artifacts in `cache/<slug>/` produced by the WSL-side `analyze` package. Library browser + per-track unified piano-roll viewer with multitrack playback. RipX-style note view (without pitch editing); harmonic analysis surfaced from the pipeline output.

## Context

The `analyze` package (validated April 2026, see `docs/history.md` Phases E–J and `analyze/README.md`) produces a stable per-track artifact set under `cache/<slug>/`:

- `<slug>.summary.json` — meta + downbeats + chords (with Roman numerals + function) + per-stem note arrays (with `scale_deg`, `in_chord`, `role` enrichment) + `analysis` block (scale, predominant loop, loop appearances, vocal range)
- `<slug>.jams` — JAMS export
- `stems_6s/*.wav` — htdemucs_6s 6-stem separation
- `stems_bsroformer/*.wav` — BS-RoFormer 2-stem (Vocals + Instrumental)
- `midi/*.mid` — basic-pitch MIDI per harmonic stem
- `vocal_f0.npz` — FCPE + PESTO F0 contours (~21k frames at 100 Hz hop)

What's missing is a UI that lets a human listen to a track while seeing the pipeline's analysis synchronized to the playhead. CLI inspection of `summary.json` works for verifying the pipeline; it doesn't work for studying a song's harmony in real time.

This document specifies the v1 web UI. It is intentionally Windows-side and self-contained, leaves a seam for a future ASIO low-latency audio backend, and reuses the existing `cache/` layout without modification. It does **not** add features to `analyze` or change any artifact format.

The brainstorm that produced this spec is recorded in `docs/webui/PROGRESS.md`; the iterated visual mockups are in `docs/webui/mockups/`. The current mockup `2026-04-30-unified-pianoroll-v3.html` is the visual ground truth this spec compiles to.

## Locked decisions (from brainstorm)

| Question | Choice | Implication |
|---|---|---|
| Scope | **Library browser + per-track viewer.** Not single-track-only; not full ingest-from-MP3. | UI scans `cache/`, lists all tracks, opens any. The `analyze` pipeline still runs in WSL by hand. |
| Playback | **True multitrack.** All 8 stems decoded into Web Audio API; per-stem volume / mute / solo. | ~50 MB initial download per track, accepted. |
| Layout | **Unified piano-roll.** All harmonic stems layered on a single Canvas; one stem highlighted, others dimmed; chord strip pinned to top of the same canvas. | Rejected three RipX-faithful stacked-lane variants (kept under `mockups/2026-04-30-three-layouts.html` for reference). |
| Cursor / scroll | **Fixed playhead at viewport center; canvas auto-scrolls under it during play.** Drag canvas to suspend auto-scroll; click ▶ AUTO badge to resume. | Standard DAW behavior. |
| Wheel bindings | Plain wheel = zoom-H; **Ctrl+wheel = pan-H**; **Shift+wheel = zoom-V**. | Matches Reaper/Cubase convention. |
| Keyboard | `Space` toggles play/pause. Full set in § *Keyboard shortcuts*. | |
| Top-bar layout | **Left:** track-picker dropdown (search + sort + filter pills + scrollable list). **Right:** Tools / Settings / ? menu. | Bar/iter/time removed from topbar (already in *Now playing* + transport); *Library* removed from menu (subsumed by dropdown). |
| Runtime | **Windows-side, self-contained `webui/` directory** with its own `.venv`. NTFS makes `cache/` visible to both WSL and Windows; the analyze pipeline writes; the webui reads. | No WSL involvement at runtime. `wsl_path`/`windows_path` fields in `summary.json` are informational; the webui resolves files via project-relative paths only. |
| Venv strategy | **`uv` + unpinned `requirements.txt` + generated `requirements.lock`.** | Matches `latest_versions_preference.md` and the analyze package's pattern. |
| Audio engine boundary | **Frontend talks to an `AudioEngine` interface.** v1 ships `WebAudioEngine`; future revision adds `AsioEngine` over WebSocket to a Python `audio_backend/` sidecar using PortAudio's ASIO host API. | Seam committed in v1 (file `js/audio/engine.js` exists, piano-roll subscribes to `engine.on('time')`, mute/solo/volume state owned by engine). No Python audio code in v1. |
| URL routing | **Single SPA, query-param routing.** `index.html` is the only HTML file; current track is `?slug=<slug>`. | No path routing; no client-side router framework. |

## Architecture

### Package layout

```
MusIQ-Lab/
├── analyze/                 (existing)
├── cache/                   (existing — read-only from webui)
└── webui/                   (NEW — Windows-only, self-contained)
    ├── pyproject.toml
    ├── requirements.txt          # unpinned: fastapi, uvicorn[standard], numpy, soundfile
    ├── requirements.lock         # generated: uv pip freeze, committed
    ├── run.bat                   # double-click launcher
    ├── README.md
    ├── webui/                    # the Python package
    │   ├── __init__.py
    │   ├── __main__.py           # uvicorn entry: python -m webui
    │   ├── server.py             # FastAPI app, route table, static mount
    │   ├── tracks.py             # cache scan, summary loader, mtime-keyed cache
    │   ├── audio.py              # Range-aware streaming for MP3 + WAV
    │   ├── f0.py                 # vocal_f0.npz → JSON decoder
    │   └── _paths.py             # project-root + cache-dir resolution
    ├── tests/
    │   ├── conftest.py           # synthetic-cache fixture
    │   ├── test_tracks.py
    │   ├── test_audio.py
    │   ├── test_f0.py
    │   └── test_server.py        # FastAPI TestClient e2e
    └── static/
        ├── index.html            # the SPA — one HTML file
        ├── css/
        │   ├── reset.css
        │   ├── theme.css         # CSS custom properties: --c-vocals etc.
        │   └── track.css
        └── js/
            ├── main.js           # bootstrap; URL ↔ state sync
            ├── api.js            # typed fetch wrappers
            ├── data/
            │   └── track-data.js # buildTrackData() transform
            ├── view/
            │   └── view-state.js # zoom, scroll, highlightedStem, autoScroll, change events
            ├── audio/
            │   ├── engine.js     # AudioEngine interface (see § Audio engine)
            │   └── web-audio-engine.js
            ├── render/
            │   ├── coords.js     # pure: time→x, midi→y, with zoom/scroll
            │   ├── pianoroll.js  # Canvas 2D renderer (the hot loop)
            │   └── f0-overlay.js # SVG F0 contour
            └── ui/
                ├── topbar.js
                ├── track-picker.js
                ├── sidebar.js
                ├── transport.js
                ├── minimap.js
                └── inspector.js  # hover tooltip with per-note enrichment
```

The package is named `webui` (the directory) and contains a Python package also called `webui` (so `python -m webui` works). The `pyproject.toml` declares `webui` as the import name.

### Backend

**FastAPI app, served by uvicorn**, binds `127.0.0.1:8080` by default. CLI flags: `--host`, `--port`, `--reload` (dev only), `--cache-dir` (override the auto-resolved cache path). All routes are registered on a single `app` instance in `webui/server.py`.

**`webui/_paths.py`:**

```python
from pathlib import Path

def project_root() -> Path:
    """Resolve to MusIQ-Lab/ assuming webui/ is a sibling of cache/."""
    return Path(__file__).resolve().parent.parent.parent

def cache_dir() -> Path:
    return project_root() / "cache"
```

This means the server only works when launched from inside the project tree. That's a feature: it makes the runtime location unambiguous. If the user moves `webui/` elsewhere, `--cache-dir` CLI flag overrides.

**`webui/tracks.py`:**

```python
@dataclass(frozen=True)
class TrackEntry:
    slug: str
    title: str
    duration_sec: float
    tempo_bpm: float
    key: str
    scale: str
    has_vocals: bool
    warnings: list[str]
    summary_mtime_ns: int

def list_tracks(cache: Path = ...) -> list[TrackEntry]: ...
def get_summary(slug: str, cache: Path = ...) -> dict: ...  # full summary.json

# Module-level mtime cache:
_cache: dict[str, tuple[int, TrackEntry]] = {}  # slug → (mtime_ns, entry)
```

`list_tracks()` walks `cache/*/`, locates `<slug>.summary.json`, checks the cached entry's mtime, re-reads only if changed. Skip-and-warn on parse errors. Title derivation strips `.mp3` and a trailing `-<11char-YouTube-id>` suffix when present (regex: `r"-[A-Za-z0-9_-]{11}\.mp3$"`).

**`webui/audio.py`:**

Helper for Range-aware streaming. Parses `Range: bytes=<start>-<end>`, returns either `Response(content, status=206, headers={'Content-Range': ..., 'Accept-Ranges': 'bytes'})` or `416` on out-of-bounds. Used by both source-MP3 and stem-WAV endpoints.

**`webui/f0.py`:**

```python
def decode_f0(npz_path: Path) -> dict:
    """Decode vocal_f0.npz to a JSON-friendly dict.
    Returns {'fcpe': [...], 'pesto': [...], 'hop_sec': 0.01, 'n_frames': N}."""
```

Hop is hard-coded to 0.01 s (matches torchfcpe + pesto outputs from `analyze/stages/vocal_f0.py`). If a future stage emits a different hop, this becomes a metadata read.

**API table:**

| Method | Path | Returns |
|---|---|---|
| `GET` | `/` (with optional `?slug=`, `?t=`, `?stem=`) | `static/index.html` |
| `GET` | `/api/tracks` | `[TrackEntry, ...]` JSON |
| `GET` | `/api/tracks/{slug}` | full `summary.json` |
| `GET` | `/api/tracks/{slug}/midi/{stem}` | `.mid` file (download); 404 if missing |
| `GET` | `/api/tracks/{slug}/f0` | decoded F0 JSON |
| `GET` | `/api/tracks/{slug}/audio/source` | source MP3, Range-aware |
| `GET` | `/api/tracks/{slug}/audio/stem/{name}` | stem WAV, Range-aware (`name` ∈ `{vocals, bass, guitar, piano, other, drums, instrumental}`) |
| `GET` | `/static/...` | static asset mount |

### Frontend

**Vanilla JS ES modules.** No build step, no npm, no TypeScript transpile. `<script type="module" src="/static/js/main.js">` loads everything. Browsers used: latest Chromium (Edge / Chrome / Brave). The Web Audio + Canvas + ES-modules surfaces are stable in all of them. Firefox not a target for v1.

**Styling:** CSS custom properties in `theme.css` define the color palette (the per-stem colors, background tones, accent color). One `track.css` file per page (only one page in v1). No CSS framework.

**State zones (§ 2.C of the brainstorm):**

| Zone | Owner | Lifetime |
|---|---|---|
| Server | `tracks.py` mtime cache | Process lifetime |
| Track data | `js/data/track-data.js` `trackData` | Once per track-load; frozen after build |
| View | `js/view/view-state.js` `viewState` | Page lifetime; mutated by user input |
| Engine | `js/audio/engine.js` `engine` | Page lifetime; owns currentTime, isPlaying, per-stem audio gain/mute/solo |

**The renderer is a pure function of `(trackData, viewState, engine.currentTime)`.** Every animation frame, it reads those three sources and draws. No internal state, no animation queues.

**Hot-path note packing** (in `track-data.js`):

```js
notes.vocals = {
  t:    Float32Array,  // start times (sec)
  dur:  Float32Array,  // durations  (sec)
  midi: Uint8Array,    // pitch
  vel:  Float32Array,  // velocity
  meta: Array,         // [{name, scale_deg, in_chord, role}, ...] — inspector only
}
```

Per-stem object built once at track-load. The renderer iterates `i = 0 ... N-1` over the four typed arrays. The `meta[]` array is consulted only by the hover inspector.

### Audio engine

**v1: `WebAudioEngine` only.** The interface contract:

```js
// js/audio/engine.js
export class AudioEngine {
  /** @returns {Promise<void>} resolves when all sources can play */
  async load({ sourceUrl, stemUrls /* {vocals, bass, ...} */ }) {}
  play() {}
  pause() {}
  /** @param {number} timeSec */
  seek(timeSec) {}
  /** @param {string} name @param {number} vol01 */
  setStemVolume(name, vol01) {}
  setStemMute(name, bool) {}
  setStemSolo(name, bool) {}
  /** @returns {number} */
  get currentTime() { throw new Error("abstract"); }
  /** @returns {boolean} */
  get isPlaying() { throw new Error("abstract"); }
  /** @param {'time'|'ready'|'ended'|'error'} event */
  on(event, callback) {}
  off(event, callback) {}
}
```

**`WebAudioEngine` implementation:**

1. On `load()`, fetch source MP3 first (~5 MB) → `decodeAudioData` → ready to play. UI usable.
2. In parallel, kick off 8 stem fetches + decodes (~50 MB total). When all 8 complete, internally swap from source-only playback to per-stem mix at `currentTime`.
3. Each stem becomes an `AudioBufferSourceNode` → `GainNode` → master `GainNode` → destination. `play()` `start()`s all source nodes at `audioContext.currentTime + 0.05` (50 ms latency buffer for sample-aligned start). `pause()` stops them and remembers position.
4. `setStemMute(name, true)` sets the stem's `GainNode.gain` to 0. `setStemSolo(name, true)` sets all *other* stems' gains to 0 and remembers their pre-solo gains.
5. `'time'` event fires from `requestAnimationFrame`-driven currentTime publication (~60 Hz). The piano-roll renderer subscribes here.

**Future `AsioEngine`** (deferred; do not implement in v1): same interface, internally a WebSocket to `ws://127.0.0.1:8080/audio-backend` served by a Python `webui/audio_backend/` sidecar that owns a `sounddevice`-driven PortAudio stream with the ASIO host API. v1 must not preclude this — concretely:

- `engine.js` interface is shipped in v1.
- The piano-roll renderer reads `engine.currentTime` and subscribes to `engine.on('time')` — never `audioElement.currentTime` directly.
- Mute / solo / volume state lives only in the engine; UI components issue `setStemMute(...)` calls and re-read engine state, never maintain their own copy.

### URL state

The URL serializes a subset of state for shareability and back/forward:

| Param | Type | Meaning |
|---|---|---|
| `slug` | string | Loaded track. Optional in URL; defaults to most-recent (by `summary_mtime_ns`) on first load. |
| `t` | number | Seek to this seconds-offset, paused. Optional. |
| `stem` | enum | Initial highlighted stem. Optional. |

`history.pushState` on dropdown selection; `popstate` listener triggers re-load. URL is the source of truth at boot.

## Data flow

### Boot sequence

1. `main.js` reads `location.search` → optional `slug`, `t`, `stem`.
2. Fetch `/api/tracks` (always, for the dropdown).
3. If no `slug` in URL, pick `tracks[0]` (sorted by `summary_mtime_ns` desc) and `pushState({slug})` to set it.
4. Fetch `/api/tracks/{slug}` and `/api/tracks/{slug}/f0` in parallel.
5. `buildTrackData(summary, f0)` → `trackData` (frozen, shared).
6. Initialize `viewState` (default zoom = fit ~8 bars to viewport; default highlightedStem = `vocals` if `has_vocals` else `piano`; `autoScroll = true`).
7. Initialize `engine = new WebAudioEngine()`. Call `engine.load({sourceUrl, stemUrls})`. Don't await — let UI render now, audio readies in the background.
8. Mount UI components (topbar, sidebar, transport, minimap), pass them references to `trackData`, `viewState`, `engine`.
9. Start the render loop: `requestAnimationFrame(draw)`, where `draw` reads from the three zones and calls `pianoroll.render(ctx, trackData, viewState, engine.currentTime)`.
10. If `?t=N` was present, `engine.seek(N)`.

### State events

```
User clicks stem row    → viewState.highlightedStem = "bass"   → next frame redraws
User wheels (no mod)    → viewState.zoomH *= 1.1               → next frame redraws
User wheels Ctrl        → viewState.scrollSec += dx*pxToSec    → next frame redraws
User wheels Shift       → viewState.zoomV *= 1.1               → next frame redraws
User drags canvas       → viewState.autoScroll = false         → next frame redraws
User clicks AUTO badge  → viewState.autoScroll = true          → next frame redraws
User presses Space      → engine.play() / engine.pause()
Engine fires 'time'     → if autoScroll: viewState.scrollSec = engine.currentTime - viewportSec/2
```

`viewState` is a thin pub-sub that emits `change` on any mutation; the render loop reads on every frame regardless, so the events are mostly informational (used for sidebar updates that don't run every frame, like the "Now playing" card).

## Components & build sequence

Five demoable milestones. Each is shippable on its own.

### M1 — Server skeleton + `/api/tracks`

- `webui/` directory, `pyproject.toml`, `uv` venv, `run.bat`.
- FastAPI app serving `index.html` (placeholder body).
- `tracks.py` cache scan with mtime caching.
- `pytest webui/tests/test_tracks.py` and `test_server.py` green.

**Demoable as:** double-click `run.bat` → browser opens → `/api/tracks` returns the cache list.

### M2 — Track-picker shell

- `index.html` skeleton (topbar + empty body).
- `track-picker.js` reads `/api/tracks`; in-memory search/sort/filter on the result.
- `topbar.js` renders title pill, key/tempo/scale badges from a `?slug=` URL.
- URL routing wired (pushState/popstate).

**Demoable as:** open browser; topbar reads from URL; dropdown switches tracks; URL updates; back-button works. No piano-roll; no audio.

### M3 — Static piano-roll renderer

- `track-data.js`, `coords.js`, `pianoroll.js`, `f0-overlay.js`, `view-state.js`.
- Sidebar (`sidebar.js`): track rows, harmony info, now-playing card.
- Minimap (`minimap.js`).
- Wheel bindings on the canvas: zoom-H / Ctrl-pan-H / Shift-zoom-V.
- Stem-row click → highlight state.

**No audio yet.** Playhead is fixed at center; scroll is user-driven only. Auto-scroll badge present but inert.

**Demoable as:** the v3 mockup, but live, against any cached track. Look at chord progressions and note overlays for any of your six tracks.

### M4 — Audio engine + auto-scroll

- `engine.js` interface, `web-audio-engine.js` implementation.
- Source-first load; stem-lazy decode; mute/solo/volume.
- `Space` key binding (`document.addEventListener('keydown', ...)`).
- `engine.on('time', ...)` drives `viewState.scrollSec` when `autoScroll`.
- Drag-canvas suspends auto-scroll; clicking the AUTO badge resumes.

**Demoable as:** the full RipX-style experience. Press play, listen, watch the chord ribbon scroll under the playhead.

### M5 — Polish + integration tests

- Full keyboard set (§ *Keyboard shortcuts*).
- `Settings` panel: Audio engine selector with WebAudio (default) and **ASIO (coming r1 — disabled with tooltip)**.
- `Tools` menu: open `.mid` in default Windows handler (`os.startfile`-equivalent via a backend endpoint), reveal cache folder.
- Error states (§ *Error handling*).
- Inspector tooltip on hover.
- Playwright integration test file driving the Gorillaz fixture end-to-end.

**Demoable as:** shippable v1.

### Future revisions (out of v1 scope)

- **r1 · ASIO backend.** `webui/audio_backend/` Python sidecar over WebSocket; `AsioEngine` JS implementation; `Settings` toggle activated.
- **r2 · Annotations.** User-drawn loop-region markers; per-chord study notes; custom stem coloring.
- **r3 · Compare mode.** Two tracks side by side (e.g. cover vs original).

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `←` / `→` | Nudge playhead by one beat (Shift = one bar) |
| `Home` | Seek to 0 |
| `End` | Seek to end |
| `+` / `-` | Zoom-H step |
| `Shift+` / `Shift-` | Zoom-V step |
| `0` | Reset zoom and scroll to defaults |
| `M` | Mute the highlighted stem |
| `S` | Solo the highlighted stem |
| `1`–`6` | Highlight stem 1–6 (vocals, bass, guitar, piano, other, drums) |
| `L` | Open track picker dropdown |
| `?` | Open keyboard-shortcuts modal |
| `Esc` | Close any open dropdown / modal |

The shortcut modal is rendered from this same table (single source of truth — the keymap binds keys *and* generates the help UI).

## Error handling

### Server

| Condition | Response |
|---|---|
| `cache/*/` directory without `*.summary.json` | Skip silently in `/api/tracks` (probably an in-progress analyze run) |
| Malformed `summary.json` | Skip + log; **don't fail the whole list** |
| `/api/tracks/{slug}` for unknown slug | 404 with `{"error": "unknown_slug", "available": [...first 10 slugs]}` |
| `/api/tracks/{slug}/audio/stem/{name}` for missing stem file | 404 with `{"error": "missing_stem", "name": "drums", "reason": "drums skipped per Stage 6"}` (re-uses `transcribed: false` reason from the summary) |
| Range request out of bounds | 416 with `Content-Range: bytes */<size>` |
| Range request without `Range` header | 200 + full body (no streaming) |

### Client

| Condition | UX |
|---|---|
| `/api/tracks` empty | Dropdown header → CTA: *"No analyzed tracks. Run `python -m analyze` in WSL."* |
| `?slug=X` for unknown slug | Topbar shows error pill; dropdown opens with focus in search box |
| F0 endpoint missing | Renderer skips F0 overlay; no error UI |
| Source MP3 decode fails | Viewer-only mode (renderer + scrubbing, no playback) + toast |
| Single stem decode fails | That stem's audio disabled (S/M/volume hidden); other stems play; toast |
| `AudioContext` blocked by autoplay policy | Centered overlay: *"Click anywhere to enable audio"* — single user-gesture unlocks `AudioContext.resume()` |

## Testing

### Backend (pytest in `webui/tests/`)

- `test_tracks.py` — synthetic-`cache/` fixture in `tmp_path`; tests scan happy-path, mtime cache invalidation, malformed-JSON skip, title-derivation regex, `has_vocals` logic, warning surfacing.
- `test_audio.py` — Range header parser edge cases.
- `test_f0.py` — `.npz` decode roundtrip on a tiny fixture.
- `test_server.py` — FastAPI `TestClient` end-to-end against the synthetic fixture.

Reference fixture: `tests/conftest.py` builds a minimal cache dir with one fake track from a JSON template; the real `cache/gorillaz_silent_running/` is **not** used in unit tests (it's heavy and shared with the analyze test suite).

### Frontend (vitest, isolated to pure-function modules)

- `track-data.test.js` — input `summary.json` fixture, assert `trackData` shape (typed-array lengths, F0 frame count).
- `coords.test.js` — `time→x` and `midi→y` arithmetic at various zoom/scroll values; auto-scroll arithmetic.
- `view-state.test.js` — change-event subscribe/unsubscribe contract; no leaks.

DOM-touching components (`track-picker.js`, `pianoroll.js`, etc.) are exercised only via the Playwright integration test — keeping unit-test scope tight to pure logic.

### Integration (Playwright, single spec)

Run against the real `cache/gorillaz_silent_running/` fixture:

1. Load `/?slug=gorillaz_silent_running`; assert topbar reads "F minor / 107 BPM."
2. Open dropdown, type "Lou", expect 1 result.
3. Click result; assert URL updated; assert topbar updated; assert canvas redrawn.
4. Click bass row in sidebar; assert highlight class on canvas wrapper.
5. Press Space; assert engine state, playhead at center, canvas auto-scrolling.
6. Press Space again; assert paused.
7. Press `?`; assert shortcuts modal opens.

The Gorillaz fixture is also the substrate for `analyze`'s integration tests — a single ground-truth artifact set tested by both suites.

## Out of scope (v1)

- ASIO audio backend (deferred to r1; seam preserved).
- Annotations / loop markers / study notes (deferred to r2).
- Compare-two-tracks mode (deferred to r3).
- Run-analyze-from-UI button (the analyze pipeline still runs in WSL by hand; cross-OS process invocation is not in scope).
- Mobile / responsive layouts.
- Firefox / Safari support (latest Chromium only).
- Multi-user / network access (binds `127.0.0.1`).
- Dark/light theme toggle (dark only).
- Internationalization.

## References

- `docs/webui/PROGRESS.md` — brainstorm log
- `docs/webui/mockups/2026-04-30-unified-pianoroll-v3.html` — visual ground truth
- `docs/webui/mockups/2026-04-30-unified-pianoroll-v2.html`, `v1.html`, `2026-04-30-three-layouts.html` — earlier iterations
- `analyze/README.md` — pipeline that produces the consumed artifacts
- `cache/gorillaz_silent_running/<slug>.summary.json` — canonical schema
- `docs/superpowers/specs/2026-04-29-analyze-py-design.md` — sibling spec
- `~/.claude/projects/.../memory/latest_versions_preference.md` — venv strategy lineage
