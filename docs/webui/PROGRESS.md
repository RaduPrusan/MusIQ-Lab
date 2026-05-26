# Web UI brainstorm — in-progress notes

> ⚠️ **SUPERSEDED — historical brainstorm, kept for provenance.** The webui was
> built and shipped long ago. The truth-of-record is now [`../../webui/README.md`](../../webui/README.md)
> (setup + lifecycle), [`../../webui/CHANGELOG.md`](../../webui/CHANGELOG.md)
> (release-by-release narrative through 2026-05-13), and the design spec
> [`../superpowers/specs/2026-04-30-webui-design.md`](../superpowers/specs/2026-04-30-webui-design.md).
> Everything below is the 2026-04-30 *pre-implementation* brainstorm — it
> predates a single line of webui code and is retained only to document how the
> design was reached. **Do not treat anything below as current**: the server
> binds `127.0.0.1:8765` (not `:8080`), the second audio engine shipped as a
> selectable **WASAPI** engine v1 (2026-05-12), not the speculative "AsioEngine",
> and every "still open" decision and "hard gate" below was resolved during the
> build (see CHANGELOG `0.1.0` → `2026-05-13` and `docs/history.md` Phases I–R).

> Status as of **2026-04-30** (historical): spec approved by user; **implementation plan written** at `docs/superpowers/plans/2026-04-30-webui.md` (23 tasks across M1–M5). Awaiting user choice of execution mode (subagent-driven vs inline).

## Goal

Build a web UI that displays the output of the music-analysis pipeline (per-track artifacts in `cache/<slug>/`) in a way that:

- Looks like RipX (without RipX's pitch-editing features).
- Plays the file with realtime analysis information synced to the playhead.
- Surfaces the harmonic analysis (chord progression, Roman numerals, key, scale, modal interchange, loop detection, vocal range) the pipeline already produces.

## Decisions locked in (user confirmed)

1. **Scope: B — Library browser.** UI scans `cache/` and lists all analyzed songs; clicking one opens the per-track viewer. (Not a single-track viewer, not full ingestion-from-MP3-button — at least not in v1.)
2. **Playback: A — True multitrack.** All 8 stem WAVs decoded into Web Audio API; per-stem volume/mute/solo; mix happens in-browser. Accept the ~50 MB initial download per track.
3. **Layout: unified piano-roll** (rejected the three RipX-faithful options A/B/C in favor of this).
   - All harmonic stems layered on a **single** piano-roll canvas, color-coded per stem.
   - **Highlighting:** one stem is "in focus" at full opacity; others dimmed.
   - **Vertical and horizontal zoom** required (independent sliders).
   - **Chord strip on the same canvas** as the piano-roll, always visible (sticky on Y axis, scrolls with notes on X axis so bar boundaries stay aligned during horizontal zoom).
   - **Right sidebar** carries track controls + harmony info.

## Decisions still open

- Color palette per stem (current mockup: vocals=pink, bass=blue, guitar=green, piano=orange, other=purple, drums=grey).
- Whether the pitch gutter shows full keyboard (88 keys) or auto-fits to range; whether to show a key-signature badge.
- Whether the chord strip should also be X-sticky (current default: no — argued in mockup commentary).
- Sidebar section ordering and which fields belong there.
- F0 contour styling — line thickness, dotted vs solid, color when vocals isn't the highlighted stem.
- Per-track-row UI in sidebar: highlight button behavior (radio vs toggle), volume slider position, M/S layout.
- Bar-number prominence on the canvas.
- Loop-iteration appearance (currently: faint orange band behind notes).
- Full keyboard-shortcut set beyond `Space` (e.g. arrows for nudging playhead by beat/bar, `+`/`-` for zoom, `M`/`S` for current-track mute/solo, `[` / `]` for loop region).
- What lives behind *Tools* and *Settings* menus.

## Tech-stack — confirmed locks-in (2026-04-30)

- **Self-contained `webui/` directory, Windows-side**, with its own `.venv` (not WSL, not the global conda env). Dep set is small: `fastapi`, `uvicorn[standard]`, `numpy`, `soundfile`.
- **Venv strategy:** `uv venv .venv` + `uv pip install -r requirements.txt` (unpinned) + `uv pip freeze > requirements.lock` (committed). Matches `latest_versions_preference.md` — pull latest at venv-create, lock for reproducibility, never pin backward.
- **Reads `cache/` via project-relative path** — never reads the `windows_path`/`wsl_path` fields from `summary.json` (those stay informational). NTFS makes the same `cache/` visible to both the WSL analyze pipeline and the Windows webui.
- **Single SPA, query-param routing.** `index.html` is the only HTML file; current track is `?slug=<slug>`. No `/track/<slug>` path routing.
- **Track picker** is a dropdown in the top-bar-left song name (search + sort + filter pills + scrollable list). The dedicated library page concept is dropped.
- **API endpoints:** `/api/tracks` (list) · `/api/tracks/{slug}` (summary) · `/api/tracks/{slug}/midi/{stem}` · `/api/tracks/{slug}/f0` (decoded JSON) · `/api/tracks/{slug}/audio/source` (Range-aware MP3) · `/api/tracks/{slug}/audio/stem/{name}` (Range-aware WAV).
- **Frontend stack:** vanilla JS ES modules, no build step, no npm. Canvas 2D for the piano-roll renderer. SVG for the F0 contour overlay. Web Audio API for multitrack.
- **Audio engine boundary.** Frontend talks to an `AudioEngine` interface (`load / play / pause / seek / setStemVolume / setStemMute / setStemSolo / on('time')`). v1 has `WebAudioEngine`. **A future revision adds `AsioEngine`** that talks over WebSocket to a Python sidecar (`webui/audio_backend/`) using `sounddevice` / PortAudio's ASIO host API. The seam is prepared in v1: `js/audio/engine.js` interface file, piano-roll subscribes to engine time events (never reads `audioElement.currentTime`), mute/solo/volume state owned by the engine.
- **Launcher:** `webui/run.bat` activates `.venv`, runs `python -m webui`, opens `http://localhost:8080`.

## How to resume after restart

### 1. Re-read context

Read these in order:

- `docs/webui/PROGRESS.md` (this file).
- `docs/webui/mockups/2026-04-30-unified-pianoroll-v1.html` (the current iteration we're refining).
- `docs/history.md` (project state — last entry: Phase J · instrumental detector).
- `cache/gorillaz_silent_running/gorillaz_silent_running.summary.json` (the data the UI consumes — top keys: `track`, `sections`, `downbeats`, `chords`, `stems`, `analysis`, `provenance`).

### 2. Re-launch the visual-companion server

```bash
'C:/Users/<you>/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/scripts/start-server.sh' \
  --project-dir '<PROJECT_PATH>'
```

Run it as a backgrounded Bash tool call (Windows path: `run_in_background: true`). After it starts, read `<session-dir>/state/server-info` to get the URL — it will be `http://localhost:<some-port>`. Each restart picks a fresh port; old session dirs persist under `.superpowers/brainstorm/`.

To re-push the latest mockup into the new session, copy `docs/webui/mockups/2026-04-30-unified-pianoroll-v1.html` into the new session's `content/` directory (rename to `unified-pianoroll.html` so it doesn't clash with old session files).

### 3. Resume the brainstorm

The remaining checklist (from `superpowers:brainstorming`):

- [ ] Iterate the unified piano-roll mockup based on user feedback (we just pushed v1; no feedback received yet).
- [ ] Confirm tech-stack assumptions (FastAPI / canvas renderer / Web Audio API multitrack).
- [ ] Present final design (architecture · components · data flow · error handling · testing) section by section, getting approval at each.
- [ ] Write the design doc to `docs/superpowers/specs/2026-04-30-webui-design.md` and commit it.
- [ ] Self-review the spec for placeholders / contradictions / scope / ambiguity.
- [ ] User reviews the written spec.
- [ ] Hand off to `superpowers:writing-plans` for implementation planning.

**Hard gate still in effect:** no implementation code, no scaffolding, no `npm init` / `pip install`, until the spec is written and approved.

## Conversation milestones (so we don't re-litigate)

1. Project context re-read; data shape confirmed (94 chords, ~1k notes per stem, 21k F0 frames per ~3.5-min track).
2. Visual companion accepted; server started on port 51449 (will change after restart).
3. Three RipX-style layouts (A/B/C) presented in `2026-04-30-three-layouts.html`. **User rejected all three** in favor of a unified-canvas layered piano-roll.
4. Unified piano-roll v1 mockup pushed (`2026-04-30-unified-pianoroll-v1.html`). User asked to save progress before giving feedback.
5. Session restart; server relaunched (port 49393); v1 re-pushed.
6. v2 pushed (`2026-04-30-unified-pianoroll-v2.html`) with these locked-in interaction decisions:
   - **Fixed playhead at viewport center**; canvas auto-scrolls under it during play (drag canvas to suspend auto-scroll).
   - **Wheel bindings:** plain wheel = zoom-H, `Ctrl+wheel` = pan-H, `Shift+wheel` = zoom-V.
   - **Keyboard:** `Space` = play/pause. (More to be defined: arrow keys, J/K/L?, `+`/`-` for zoom?)
   - **Top-bar right** is a menu group (Library · Tools · Settings · ?). Bar/iter/time was removed from the topbar — that info already lives in *Now playing* and the transport.
7. v3 pushed (`2026-04-30-unified-pianoroll-v3.html`) with track-picker dropdown in top-bar-left (search · sort · filter pills · scrollable track list with key/BPM/duration columns and warning sub-labels from `provenance.warnings`); *Library* removed from the right menu since the dropdown subsumes it.
8. Tech stack locked: Windows-side, self-contained `webui/`, `uv` + unpinned latest, `AudioEngine` interface with `WebAudioEngine` (v1) + future `AsioEngine` over WebSocket to a Python `audio_backend/` sidecar.

## File map

```
docs/webui/
├── PROGRESS.md                                       (this file)
└── mockups/
    ├── 2026-04-30-three-layouts.html                 (initial 3-option exploration · rejected)
    ├── 2026-04-30-unified-pianoroll-v1.html          (first cut · superseded)
    ├── 2026-04-30-unified-pianoroll-v2.html          (added fixed-playhead + wheel bindings · superseded)
    └── 2026-04-30-unified-pianoroll-v3.html          (current iteration · added track-picker dropdown)
```
