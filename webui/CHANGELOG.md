# Changelog

## 2026-07-05 — Live Input transpose + reanalyze-stream fix

### Live Input semitone transpose

Both Live Input rows (Track sidebar + compact Lyrics strip) gain a **transpose
spinner** (± semitones, clamped [−24, +24], signed display, default 0) that shifts
where the live-mic pitchline draws on the piano roll. The shift is applied to the
detected pitch *before* the cents-vs-reference computation, so line position,
in/off/neutral colouring, and the row readout stay mutually consistent; buffered
trail samples back-shift immediately on change (no glide). Persisted under
`localStorage["musiq.mic.transpose"]`; the two surfaces sync via a
`musiq:mic-transpose-changed` document event. +6 tests (suite: 278/278).

### Reanalyze modal ticker leak (JS suite hung forever)

A reanalyze/analyze-stale stream that ended without a terminal done/error event
never called `finish()`, leaving the elapsed tickers running — in the browser the
modal ticked forever with Close disabled after a connection drop, and under
`node:test` the fallback ticker kept `menus.test.js` alive so the full suite never
exited. `finish()` is now also reached via a finished-flag guard when the stream
ends with no result. Also pinned 3 stale tests to current intentional behaviour
(themed Reanalyze entry colour, renamed track-picker buttons, WASAPI `setMode`
deferring `modeChanged` until the server's `StateMsg` confirms).

## 1.0.0 and later (2026-05-22 → 2026-06-13)

Roll-up of work after the 2026-05-13 entry, through the public v1.0.0 release.

### Public release

- **v1.0.0 — repo went public 2026-05-26** under **AGPL-3.0-or-later** (`LICENSE`). Public-repo hygiene: loopback-only `OriginGuard`, `validate_slug`/`validate_stem` path-param gates, no `shell=True`, maintainer PII replaced with `<maintainer-email>`/`<PROJECT_PATH>` placeholders. Lightweight public CI checks added for the webui.

### Live mic-pitch layer (2026-05-22 → 05-24)

- Browser-only **Live Input** pseudo-stem: YIN in an `AudioWorklet` → `Float32` MIDI ring buffer → `mic-overlay.js`, drawn in real time over the F0 contour and pinned to the song timeline.
- 4-bucket colouring (`in` ≤100¢ / `off` >100¢ / `neutral` matched-but-silent / `no-match`), each a theme token (`--mic-in/-off/-neutral/-no-match`); widths + colours tunable under **Settings → Pitch lines**. Reference-stem dropdown + per-user latency-offset slider. EMA (α=0.4) smoothing at write time. Live Input strip also surfaced on the Lyrics tab.

### Sidebar / theme polish (2026-05-24)

- Right-sidebar tabs reordered to **Track / Lyrics / Assistant** ("Claude" → "Assistant"; tab `id`s unchanged so persisted state stays valid).
- **Jinn** became `DEFAULT_PRESET_ID` (was Classic Dark); cross-theme audit fixed stem↔function hue collisions and re-derived the Studio Light drum palette.
- Mic row boxed-card layout on the stem grid; small sliders (stem-vol / mic-offset / zoom) retuned to an 80/50/20% token tier.

### Analyze-workflow + piano-roll polish (2026-05 → 06)

- Configurable piano-roll **grid colour** and **drum-hit lane height** in Settings.
- Analyze-workflow top-bar pills + missing-stage chips.
- Sidebar tab strip pinned while content scrolls; single scroll region per tab; raised scrollbar contrast.
- WASAPI: removed stale "Phase-1 stub" comments from the shipped engine.
- Key parsers now handle **Unicode** accidentals (`♯`/`♭`); backend key spelling moved to the conventional circle-of-fifths rule (`analyze/derived/theory.py`).

## 2026-05-13 — Notation coherence + default-to-MIX + auto-scroll pill

### Notation coherence

Every pitch/chord/key display in the UI now obeys the user's **Settings → Pitch notation** choice. Previously, several surfaces rendered raw analyzer spellings (e.g. `Bb:major`, `A:minor`) or hard-coded scientific letters regardless of the setting. Routed every site through the central notation pipeline:

- Piano-roll chord strip — `ctx.fillText(c.label)` → `reformatRootedName(formatChordShorthand(c.label), system)`, so canvas labels match the sidebar's Now-card chord display.
- Inspector gutter highlight — replaced the hard-coded sharp-only chromatic array lookup with a `data-midi` attribute on each gutter row; the row's MIDI number is canonical, the rendered label is presentation.
- Sidebar Cross-check card + analyze-modal Cross-check row — humanize + reformat both sides of the Key value (`Bb:major` → "Si♭ major" in Solfège, etc.).
- Analyze-modal stats panel — Key, Scale, chord-loop labels, and vocal-range pitches.
- Track-picker dropdown key column.

`formatChordShorthand` and `humanizeKeyString` hoisted into `notation.js` (were duplicated in `sidebar.js` / `topbar.js`). One canonical pipeline: raw label → shorthand-or-humanized → `reformatRootedName`. 72/72 tests pass across `notation`, `crosscheck-{card,row}`, `analyze-shared`, `track-picker`, `analyze-modal`.

### Default-to-MIX

Stem-mix becomes the default playback mode the moment any stem decodes (both engines). A stem mute/solo press while in SRC auto-promotes to MIX so the gesture isn't a silent no-op. WASAPI mirrors this via a server `set_mode` round-trip; WebAudio promotes locally on first `stemLoaded`.

### CENTER / EDGE auto-scroll pill + smooth glide

- Auto-scroll anchor (center vs edge) is now a user-visible **CENTER/EDGE** pill in the transport, persisted to `localStorage["musiq.scrollAnchor"]`. Anchor is no longer silently overridden by canvas drag or scrub release.
- Edge band tightened from `[20%, 80%]` to `[30%, 70%]`.
- Scroll transitions glide instead of snapping: when the gap between current scroll and the auto-scroll target exceeds 80 ms, lerp 30%/frame until the gap drops under 5 ms, then snap-lock for zero steady-state lag. Triggered by anchor toggle, edge crossings, seeks, and scrub-bar releases.
- Scrub bar height bumped 6 px → 18 px to match the AUTO/MIX/SRC pills so it's a real click target.

14/14 coords tests pass on the new 30–70% band.

### Identify pipeline — trust signaling (R4 D3)

Sidebar **Metadata** card now distinguishes canonical AcoustID + MusicBrainz matches from text-search fallback matches and unenriched (AcoustID-only) matches. Fallback rows render an italic "via text-match search" note with a hover tooltip showing the `duration_variance` and `title_similarity` numbers that cleared the guard. Unenriched matches (AcoustID hit, but MB returned no recording metadata) show a similar low-trust signal. The post-Round-5 corpus puts 14/30 tracks in canonical, 1/30 in fallback, and the rest unidentified — the UI carries those tiers visibly. See [`../docs/superpowers/identify-overhaul/round-4-final-review.md`](../docs/superpowers/identify-overhaul/round-4-final-review.md).

### Stale-stage detection + selective re-analyze UI

The Tools menu's **Reanalyze** action now shows a per-stage stale chip when a stage's params or schema-version on disk no longer match the live pipeline. Click the chip to selectively re-run that stage (and downstream) instead of wiping the whole cache. Powered by `webui/webui/stage_manifest.py`, which mirrors the analyze package's per-stage schema-version + params declarations so the webui can read them without importing the analyze venv.

### Claude tab — tool-chip rendering + stop endpoint

In-app chat actor now surfaces a compact chip for each tool call the model makes (`set_loop_region`, `set_highlighted_stem`, etc.) inside the Assistant tab — previously these were silent. A `POST /api/chat/<slug>/stop` endpoint cancels an in-flight `ClaudeSDKClient.query()` so the user can interrupt a long generation. Last.fm card font dropped to 75% so the tag cloud doesn't dominate the sidebar.

## WASAPI audio engine v1 (2026-05-12)

Selectable low-latency Windows audio engine in Settings → Audio engine.
Three output paths per device: MME, WASAPI Shared, WASAPI Exclusive.

### Architecture

- New `webui/webui/audio_backend/` Python package with PortAudio output stream,
  soxr HQ resampling, smooth-cursor clock sync via authoritative server clock
  + client-side rAF extrapolation with 30 ms hard-snap / half-delta soft-slew
  at 40 Hz tick rate.
- New `webui/static/js/audio/wasapi-engine.js` ships the AudioEngine contract
  over a single WebSocket (`/api/audio/control`).
- Engine swap is opt-in via Settings; WebAudio remains the default and the
  always-available fallback.

### Features

- Per-device picker showing MME / WASAPI Shared / WASAPI Exclusive entries.
- 6-stem mixing with per-stem mute/solo/volume and 10 ms gain smoothing
  matching the WebAudio engine.
- Source/stems mode toggle.
- Exclusive-mode opens with `WasapiSettings(exclusive=True)`. On failure:
  fallback to Shared on the same device, then to MME on the same-named
  device, then back to WebAudio — each step surfaces a clear toast.
- Sample-accurate loop wrap inside the audio callback (source mode); stems
  mode wraps at the next block boundary (~10 ms lag).
- Device hotplug refresh button (re-initializes PortAudio's device cache).
- Live output-latency display in Settings.

Tested end-to-end on JINN (BEHRINGER FLOW 8 over USB Audio Class 2.0).
~360 unit + integration tests.

## 0.3.0 — 2026-05-10

UI polish + themable design tokens. Most of the work landed via a 5-iteration ralph-loop polish run on 2026-05-09 (`scripts/ui-polish-loop.py` + axe-core verifier); the Jinn preset and the spread→enumerate cleanup landed 2026-05-10.

### Theme system

- **Design tokens** (`static/css/tokens.css`) for surfaces, text, accents, status, stem colors, function colors, chord-strip / drum-lane backgrounds, surface chrome, soft semantic badges, alphas, F0-overlay strokes, radii, and motion. Canvas-side reads via `static/js/theme/css-tokens.js` (`readToken` / `readAlpha` / `subscribe`) and rebind on `musiq:theme-changed` (`pianoroll.js`, `f0-overlay.js`).
- **Five presets**: Classic Dark, Midnight, Studio Light, High Contrast, **Jinn** (user-saved palette). Every preset enumerates every token explicitly — no `...spread` from another preset — so edits stay scoped (convention as of 2026-05-10; see `theme/presets.js` header). 
- **Settings → Appearance** UI: preset cards + per-token color pickers + alpha sliders + Reset/Copy theme JSON. Edits apply live and persist via `localStorage["musiq.theme"]` (schema v1, full resolved token map). Pre-paint hydration script in `<head>` of `static/index.html` prevents FOUC.
- **Accent derivation:** `--accent-on` is auto-derived per preset by picking the higher-contrast of `#1a1a25` or `#ffffff` against `--accent` (WCAG luminance), with `--accent-emphasis` similarly tuned.

### Tokenized literals

Several rendering paths previously held hardcoded color literals; these were tokenized so each preset can repaint them without touching JS:

- Canvas chord-strip + drum-lane backgrounds (`chord-default-bg`, `chord-no-bg`, `drum-lane-bg`).
- Drum sub-stem colors (`drum-kick`, `drum-snare`, `drum-toms`, `drum-hihat`, `drum-cymbals`) — previously the `DRUM_COLORS_LITERAL` map in `render/pianoroll.js`; now read live via `readToken` and rebound on theme switch. All 5 presets ship the same starting values; per-preset tuning deferred to a future polish pass. Customizable via Settings → Appearance.
- Playback-loop band fill + stroke alphas (`alpha-play-band-fill`, `alpha-play-band-stroke`) and analyzed loop bands (`alpha-loop-band-fill`, `alpha-loop-band-stroke`).
- Bar-number opacity (`alpha-bar-number`) — Studio Light overrides to 0.78 because dark-on-cream reads lighter than light-on-near-black.
- F0 overlay strokes (`f0-consensus-stroke`, `f0-pesto-stroke`).
- Surface chrome (selected / hover / pill-hover / picker-divider / gutter / volume-track-fill).
- Soft semantic badge bg/fg pairs (`accent-soft-*`, `success-soft-*`, `info-soft-*`, `warn-soft-*`, `modal-soft-*`).

### Other visual

- **Drum lane always renders at full alpha**, exempt from the playback-loop band alpha multiplier — the lane was washing out behind a dim play-band, hiding kick/snare hits.
- **Studio Light contrast pass**: text-disabled `#5e5e6a → #4d4d52` (5.07:1 on `--surface-selected`), surface-selected darkened to `--surface-3` (~13% luminance delta) for at-a-glance row distinction, function-fg colors darkened to clear 4.5:1 on their soft-bg tiles, accent-on flipped from `#fff → #1a1a25` (WCAG-derived against `#d97706`).
- **Midnight cool-tint pass**: previously inherited warm `--*-soft-bg` from Classic Dark via spread; now defines its own cool desaturated soft-bg + soft-fg pairs.

### Tests + verification

- `webui/tests-e2e/visual-review.spec.js` — 5 presets × 6 scenes + axe-core; per-preset verdict files merged via `node scripts/merge-verdicts.js`.
- 5-iteration polish loop converged 2026-05-09 (cost: $31.82); ship report at `install-logs/ui-polish-2026-05-09-results.md`.
- **Retired** `webui/tests-e2e/visual-baseline.spec.js` and its `fixtures/baseline/` PNGs. The Phase-1 pixel-diff guardrail covered Classic Dark only and required re-baselining at every visual change; `visual-review.spec.js` (5 presets × 6 scenes + axe-core) now provides strictly broader, more deterministic coverage. Removing the guardrail eliminates the "rebaseline-or-retire" maintenance dilemma at every UI change.

### Validator coverage

`store.js` `COLOR_KEYS_PREFIX` extended with `drum-`, `chord-`, `f0-`, `picker-`, `gutter-`, `vol-`. `RADIUS_KEYS_PREFIX` extended with `t-` (typography tokens share the radii's `Npx|rem|em` syntax). Previously, customize-time edits to tokens like `drum-lane-bg`, `chord-default-bg`, `f0-consensus-stroke`, `gutter-bg`, etc. were silently dropped on reload because they didn't match any prefix in the validator. With the wider prefix list every color and size token in the taxonomy round-trips through `localStorage` correctly.

### Settings → Appearance — sectioned Customize panel

Replaced the flat 6-group + 12-alpha Customize layout with a data-driven **17-section** panel. Each section has an uppercase header + a "?" help button (native `title=` tooltip + `aria-label`) explaining what those tokens do. All **94** preset tokens are now surfaced and customizable.

Sections, in display order:
- **Surfaces** (9 tokens) · **Borders** (2) · **Text** (4) · **Accent** (4) · **Status** (9) · **Stems (full)** (6) · **Drum pieces** (5 — newly tokenized) · **Piano roll** (3) · **Function colors** (9) · **Keyboard gutter** (4 — the piano-key column on the left of the roll) · **F0 overlay** (2) · **Volume controls** (2) · **Soft tags** (10) · **Transparencies** (13 alpha sliders, +`alpha-bar-number`) · **Sizing** (5 radii) · **Motion** (3 motion durations) · **Typography** (4 type-size tiers — newly added to all 5 presets).

New helpers `buildSizeRow(name, {min, max, step})` and `buildMotionRow(name)` parse off unit suffixes (`px`/`s`), clamp to range, and write back via `setToken()`. Reset and Copy theme JSON buttons preserved verbatim.

### Typography tokens in presets

`--t-micro` (10px), `--t-body` (11px), `--t-prose` (13px), `--t-display` (24px) were previously declared in `tokens.css :root` only — not in any preset map, so users couldn't customize them. Now enumerated in all 5 presets at the same defaults; per-preset tuning deferred until requested. All 5 presets now ship 94 tokens (was 89, plus the 5 drum-substems = 94).

### Theme bug fixes

- **Jinn `accent-emphasis`** was stored as a `color-mix(in srgb, ...)` expression (captured from a fresh `deriveAccentEmphasis()` call before being baked). The hex-color validator rejected this string, and the Settings color-picker fell back to `#000000` when editing it. Baked to `#efeefe` (the exact computed-mix value) so the picker round-trips correctly.

## 0.2.0 — 2026-04-30

UI polish pass after first hands-on use of v0.1.0.

### Playback / navigation

- **Single-click canvas to seek.** Clicking on the piano-roll moves the playhead to the cursor's time and updates the sidebar Now Playing, transport label, minimap, and chord highlight. A 3px slop window distinguishes a click from the start of a drag, so taps no longer kick the viewer out of follow-playback mode.
- **Two auto-scroll modes.** `edge` (default) pins the playhead inside `[20%, 80%]` of the viewport — no scroll while drifting in the band, snap to the matching edge when crossing out. `center` (used after scrubbing) pins the playhead at viewport midpoint. Codified in `static/js/render/coords.js::autoScrollFor` with 6 unit tests covering both modes plus clamp-to-zero near song start.
- **Scrub recenters the canvas.** Clicking the bottom transport scrubber recenters the canvas under the cursor and switches `scrollAnchor` to `center`, so playback continues centered.
- **Wheel bindings inverted to match expectation.** Plain wheel = horizontal scroll. `Ctrl+wheel` = horizontal zoom (anchored at cursor X). `Shift+wheel` = vertical zoom.
- **Vertical canvas drag.** Drag canvas vertically to move pitch center (hand-tool convention: drag down → higher pitches scroll into view). Cursor switches to `grabbing` only after movement passes the click slop.

### Visual / rendering

- **Key-aware octave gridlines.** Dotted amber horizontal lines drawn at every tonic-octave row, derived from `meta.key`.
- **Currently-playing note is white.** On the highlighted stem, the note containing `currentTime` renders white-filled with a stem-coloured outline. Other notes dim to 32 % opacity.
- **Pitch hover band + tooltip.** DOM overlay highlights the hovered MIDI row across the canvas and shows a mouse-attached tooltip with the note name. Re-applies after gutter rebuilds on view-state change.
- **Chord strip highlight.** 2 px amber outline on the chord cell containing `currentTime`; brighter function backgrounds for I/IV/V; default neutral background for chords without a function tag.
- **Gutter labels.** Naturals + tonic-class rows only; tonic rows get an amber border + bold weight. Range-clipped so labels never bleed into the transport.
- **F0 contour.** Stroked at `#ff7eaa`, width 1.6, with rounded line joins; opacity drops to 0.35 when a non-vocals stem is highlighted.
- **Auto-scroll badge.** Moved to bottom-left of the canvas to free up the top-right corner.

### Sidebar / transport / minimap

- **Minimap viewport drag.** Click on the minimap viewport rectangle and drag to scroll; the offset under the cursor is preserved (vs. clicking the track, which centers on the cursor). `grab` / `grabbing` cursor.
- **Now Playing row stable.** Always renders a `.now-meta` element with `min-height` so the sidebar stops jumping vertically when chord/note metadata appears or disappears.
- **Stems section heading.** Renamed from "Tracks · click to highlight" to "Stems · click to highlight" — the prior wording collided with the song-list "Tracks" picker.
- **Per-stem volume sliders.** Inline next to the M/S buttons.
- **Zoom slider fills update live.** Both H and V transport sliders now subscribe to `viewState` change events and reflect current zoom.

### State / lifecycle

- **AudioContext leak fixed.** `WebAudioEngine.dispose()` now stops sources, closes the `AudioContext`, and clears subscribers. Track switching tears down the prior engine before mounting the next, so Space and other shortcuts no longer trigger play/pause on the previous track. Solves the v0.1.0 "6-context-limit" known issue.
- **Unified listener teardown.** Per-track listeners attach with `{ signal: currentAbort.signal }`; one `AbortController.abort()` cleans them all up on track change.
- **Source-load is best-effort.** When a track has no in-cache MP3, the server falls back to `track.windows_path` from `summary.json`; if both are missing, playback continues from stems alone instead of failing the whole load.

### Server / config

- **Default port: 8765** (was 8080). Updated in `webui/__main__.py`, `run.bat`, `README.md`, and `tests-e2e/playwright.config.js`.

### Tests

- 6 new `coords.test.js` tests covering edge-mode scroll thresholds and center-mode pinning. All 14 tests pass.

## 0.1.0 — 2026-04-30

Initial release.

- Library browser via top-bar-left dropdown (search, sort, filter pills).
- Per-track unified piano-roll viewer:
  - All five harmonic stems layered on a single Canvas.
  - One stem highlighted at full opacity; others dimmed.
  - Chord strip pinned to top of the canvas (Roman numerals + chord labels + function background).
  - F0 contour overlay (FCPE).
  - Beat / downbeat grid; loop-appearance bands.
- Multitrack Web Audio playback with per-stem volume / mute / solo.
- Fixed-playhead-with-scrolling-canvas (auto-scroll); drag canvas to suspend.
- Wheel zoom-H, Ctrl+wheel pan-H, Shift+wheel zoom-V; full keyboard shortcut set; shortcuts modal.
- Hover inspector showing per-note name / scale-degree / role.
- Settings panel with placeholder for r1 ASIO backend.
- Tools menu: open `<stem>.mid` in Windows default handler; reveal `cache/<slug>/` in Explorer.
- Self-contained `webui/` directory with `uv`-managed venv (FastAPI · uvicorn · numpy · soundfile).
- Tests: backend pytest (paths, tracks, audio, f0, server), frontend `node:test` (track-data, view-state, coords, picker filter), Playwright integration spec against the Gorillaz fixture.

## Known issues

- **`?t=` and `?stem=` URL params are spec'd but not implemented.** `?slug=` is fully wired; the other deep-link params land in v2.

### Resolved in 0.2.0

- ~~AudioContext leak on track switch~~ — `WebAudioEngine.dispose()` now closes the context and tears down listeners on every track change.
- ~~Transport zoom sliders are static~~ — fills now subscribe to view-state change events and update live.
