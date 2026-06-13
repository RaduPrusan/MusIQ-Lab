# Live mic-pitch layer — 2026-05-22

## Goal

Add a real-time microphone pitch contour to the webui piano-roll, rendered as a new top-row pseudo-stem labelled **Live Input**, drawn pinned to the song timeline so the user can sing or play along and see how their pitch + timing tracks the song. Reference for cents-off colouring is user-selectable (any stem, or none/neutral). No persistence — discarded on track change. Browser-only; zero server changes.

Non-goals for v1: take recording / WAV export, click-track latency calibration, alternative estimators (CREPE / FCPE / pYIN), ScriptProcessor fallback for non-AudioWorklet browsers, per-device persistent latency calibration, automatic AEC against playback bleed.

## Background

The webui already has every adjacent surface this needs:

- **Piano-roll renderer with per-frame pitch ribbon** — `webui/static/js/render/f0-overlay.js` draws the offline vocal consensus as a stroked path with confidence-bucketed opacity (`STRENGTH_BASE_OPACITY = {strong:1.0, medium:0.7, weak:0.4}`, `f0-overlay.js:21-28`). The new live ribbon copies this rendering pattern and changes the colour function.
- **Sample-accurate playback clock** — `webui/static/js/audio/wasapi-engine.js:486` exposes `currentTime` extrapolated per-rAF from server clock anchors (~1 ms precision). Emits a `"time"` event we can subscribe to.
- **Notation pipeline** — `webui/static/js/music/notation.js:165` `formatPitch(midi, keyParse, system)` and the global `musiq:notation-changed` event drive every pitch label. The Live Input readout routes through it like every other surface.
- **Stem list scaffold** — `webui/static/js/ui/sidebar.js:243-442` renders the six-stem list. The Live Input row is injected above the existing loop with no restructuring.

The only surface that does not exist yet is browser audio **input**. No `getUserMedia`, `AudioWorkletNode`, or mic-permission code anywhere in `webui/`. The whole layer is greenfield on that axis.

Reference port: a private desktop PySide6/OpenGL YIN tuner the maintainer wrote earlier. Its YIN math (`yin()`), outlier hysteresis (`apply_pitch_smoothing()`), and RMS gate are the model. Its rendering and Qt threading model are not relevant — we use AudioWorklet + canvas.

## Architectural decisions

| Decision | Choice | Rationale |
|---|---|---|
| Capture location | **Browser, AudioWorklet** | The webui is single-user localhost; no upside to routing PCM over WS to Python and back. AudioWorklet runs on a dedicated audio thread with ~3-5 ms scheduler latency. |
| Pitch estimator | **JS YIN in the worklet** | ~30 LOC of math, zero model download, deterministic, matches Tuner.2 baseline. Pluggability (CREPE / FCPE / ONNX) is purely additive later; not in v1. |
| Estimator parameters | Window 2048, hop 2048 (no overlap), `_FMIN=65 Hz`, `_FMAX=1200 Hz`, YIN threshold 0.10, RMS gate 0.005, outlier hysteresis = Tuner.2 `apply_pitch_smoothing()` (drop if new < 0.8 × prev for ≤ 2 frames, then accept) | Tighter `_FMIN` than Tuner.2's 30 Hz because voice never goes below C2; otherwise identical. One estimate per ~43 ms at 48 kHz. |
| Ribbon time-positioning | **Pinned to song time** | Each captured frame draws at the X corresponding to the song time at which it was captured. If the user sings late, the ribbon appears slightly LEFT of the targeted note. Lets the visual encode both pitch AND timing. |
| Time alignment | **Best-effort with user-controllable offset slider** (Approach B) | Compute `T_song = engine.currentTime − (audioCtx.currentTime − T_ctx) − userOffsetMs/1000`. Slider default −30 ms (typical Windows shared-WASAPI mic latency), range −150 to +50 ms, persisted to `localStorage["musiq.mic.offsetMs"]`. Web Audio does not expose `inputLatency`; the slider is the honest answer. A click-track calibration wizard is a future-only extension. |
| Browser DSP | **Force `echoCancellation=false`, `noiseSuppression=false`, `autoGainControl=false`** in the `getUserMedia` constraints | Browsers default these to *on* for the "voice" profile, which crushes pitch information (AGC modulates RMS; suppression eats sibilants; AEC eats the song if it bleeds through speakers). Non-negotiable for YIN to behave consistently. Consequence: song bleed into the mic is documented, not engineered around — "wear headphones" is the answer. |
| Accuracy colouring | **Cents-off vs user-selectable reference stem**, with a "none/neutral" mode | Default reference: `vocals`. Dropdown in the Live Input row lets the user pick any stem present in the track or "none." When set to none, ribbon renders in the row's accent colour and only confidence-modulated opacity remains. |
| Colour function | `|cents| ≤ 5 → green`, `≤ 20 → yellow`, `> 20 → red`, `ref=null → row accent`; alpha = `0.4 + 0.6 × clarity` | Reuses existing CSS tokens `--ok`, `--warn`, `--err` where present. |
| Reference lookup | Binary search on the existing `trackData.notes[stem].t[]` typed array with last-index cache | O(1) steady state. Returns `null` in note gaps → ribbon renders neutral in those gaps. |
| Ring buffer | ~30 s of samples (~700 entries), pre-allocated typed arrays, wrap index, cleared on track change | Trivial memory. Cleared but mic is not stopped on track change — the user is expected to keep singing. |
| Mute behaviour | M-button on Live Input row calls `stop()`, fully releasing the mic | Browser shows the in-use indicator; user expects M to release it. Re-enabling re-runs `getUserMedia` (no second permission prompt — browser remembers). |
| Visibility behaviour | Mic keeps running on tab-hidden / track-change | User may tab away for lyrics. Track-changes are part of normal flow. Stop on `beforeunload` only. |
| Auto-pause on silence | **Not implemented** | Silent frames simply do not push to the ring buffer; the ribbon already shows nothing during silence. Tuner.2's auto-pause UI state is one more thing to explain without payoff here. |
| Fallback to ScriptProcessor | **None** | Cut line is AudioWorklet support (Chrome 66+, Firefox 76+, Safari 14.1+ — all post-2021). Older browsers see a disabled row with tooltip. |

## File layout

New (4 files):

```
webui/static/js/
  audio/
    mic-yin-processor.js   # AudioWorkletProcessor: YIN + hysteresis + RMS gate
    mic-pitch.js           # main-thread coordinator: worklet lifecycle, time
                           #   alignment, ring buffer, reference lookup, public API
  render/
    mic-overlay.js         # new overlay canvas, draws ring buffer keyed by song time
  ui/
    mic-row.js             # the Live Input sidebar row: M, device picker, reference
                           #   dropdown, offset slider, live readout
```

Modified (surgical, 3 files):

```
webui/static/js/
  ui/sidebar.js            # inject mic-row above the STEM_ORDER loop in
                           # _buildTracksSection (~sidebar.js:261)
  main.js                  # instantiate MicPitch + MicOverlay after F0Overlay
                           # (~main.js:319), wire to engine "time" + mic-row
  audio/wasapi-engine.js   # UNCHANGED — we only consume its currentTime + "time" event
```

No HTML change needed — MicOverlay follows the F0Overlay pattern (creates its own absolutely-positioned canvas in the constructor and appends to the `.canvas-wrap` host element). PianoRoll is unchanged for the same reason.

Untouched (explicit non-changes):

- All Python (`webui/webui/`, `analyze/`, summary.json shape, stem enum in `tracks.py`).
- The six existing stem rows' DOM, M/S logic, volume sliders.
- `notation.js` — only consumed.
- `f0-overlay.js` — pattern copied, not modified.
- `pianoroll.js` and `index.html` — MicOverlay self-installs into `.canvas-wrap` like F0Overlay does (no host change required).

## Public API of `mic-pitch.js`

The seam between the coordinator and everything else.

```js
class MicPitch extends EventTarget {
  constructor(engine);                          // engine = WasapiEngine instance

  async start();                                // getUserMedia + worklet up
  async stop();                                 // releases the mic, frees the indicator
  isRunning(): boolean;

  setReferenceStem(name: string | null);        // 'vocals' | 'piano' | … | null
  setOffsetMs(ms: number);                      // −150..+50, persisted to localStorage
  setDeviceId(id: string | null);               // null = system default

  getSamplesInRange(tStart: number, tEnd: number):
    { time: Float32Array, midi: Float32Array,
      cents: Float32Array, clarity: Uint8Array };
    // NOTE (2026-05-23): midi is Float32, not Uint8. The original design
    // doc above said Uint8; that was changed during ship — see "Post-ship
    // deltas" at the end of this spec.

  clearBuffer();                                // called on track change

  // Events:
  //   "started" / "stopped" — lifecycle
  //   "sample"   { time, midi, cents, clarity, freq } — latest accepted sample
  //   "error"    { code: 'permission' | 'no-device' | 'unsupported' | … , message }
}
```

`pianoroll.js`'s rAF calls `getSamplesInRange(viewState.tStart, viewState.tEnd)`. `mic-row.js` calls everything else. Nothing else touches `mic-pitch.js`.

## Data flow (per ~43 ms block)

```
1. Mic hardware captures 2048 samples (mono float32, 48 kHz typical)
   │
   ▼
2. AudioWorkletProcessor.process(inputs[0][0])
   - YIN with parabolic interpolation
   - RMS gate (< 0.005 → freq = 0)
   - outlier hysteresis (Tuner.2 rule)
   - postMessage({ freq, clarity, rms, ctxTime: currentTime })
   │
   ▼
3. mic-pitch.js onmessage (main thread)
   - T_song = engine.currentTime
            − (audioCtx.currentTime − T_ctx)        // age of block
            − userOffsetMs / 1000                    // user nudge
   - if freq > 0 and engine.currentTime is anchored:
        midi   = 69 + 12 · log2(freq / 440)
        refMidi = referenceStem
                    ? lookupMidiAtTime(referenceStem, T_song)
                    : null
        cents  = refMidi !== null ? 100 · (midi − refMidi) : null
        ringBuffer.push({ T_song, midi, cents, clarity })
   - emit 'sample' for the readout (always, even unanchored, so the row works
     as a pure live tuner when no track is loaded)
   │
   ▼
4. pianoroll.js rAF (already running)
   - mic-overlay._draw(ctx):
        samples = micPitch.getSamplesInRange(viewState.tStart, viewState.tEnd)
        for each consecutive pair (s_i, s_{i+1}):
            stroke = colourFor(s_i.cents, s_i.clarity)
            ctx.moveTo(timeToX(s_i.t),   midiToY(s_i.midi))
            ctx.lineTo(timeToX(s_{i+1}.t), midiToY(s_{i+1}.midi))
```

Staleness clamp: if a message's `T_ctx` is `>500 ms` older than `audioCtx.currentTime` on arrival, drop it. Paranoia for main-thread stalls; should never fire.

## UI: the Live Input row

Layout, top-to-bottom inside the row (mirrors existing stem-row anatomy from `sidebar.js`):

- **Row 1 (always visible):** colour swatch (single accent colour, distinct from the six stems) · label "Live Input" · M-button (enable/disable mic) · status dot (off / mic-permission-pending / live / error) · live readout `F♯4 −12¢` (note name via `formatPitch`, cents-off with sign, both empty when off).
- **Row 2 (visible only when enabled):** reference-stem dropdown ("Match against: vocals ▾", auto-populated with stems present in the current track + "none") · device picker (system default + enumerated audio inputs) · offset slider ("Mic offset: −30 ms").

When disabled: row 1 only, faded.

Persistent settings (`localStorage`):

- `musiq.mic.enabled`: boolean (remembers last state, but **does not auto-start** — start requires a click for the permission gesture).
- `musiq.mic.deviceId`: string | null.
- `musiq.mic.referenceStem`: string | null, default `'vocals'` (auto-falls-back to first non-empty stem if vocals stem has zero notes).
- `musiq.mic.offsetMs`: number, default −30.

## Failure modes

| Situation | Behaviour |
|---|---|
| Permission denied | Row shows "Microphone access denied — click M to retry". Single retry per click. |
| No mic device | Row disabled, tooltip "No microphone found". |
| Device unplugged mid-session | Stop worklet, toast "Microphone disconnected", flip M to off, refresh device list. |
| Browser without AudioWorklet | Row disabled, tooltip "Your browser does not support live microphone input". |
| AudioContext suspended (autoplay policy) | M-click is the user gesture; we `audioContext.resume()` inside the handler. If resume rejects, toast "Click anywhere first, then try again." |
| Track change | Clear ring buffer. Mic stays on. |
| Tab hidden | Mic stays on. |
| Page unload | `stop()` so the mic indicator releases cleanly. |
| Engine has no clock anchor (no track playing) | Worklet runs, readout works, ring-buffer pushes skipped — row functions as a pure live tuner. |
| Reference stem empty / has no notes | `lookupMidiAtTime` returns `null` → ribbon neutral. Dropdown greys-out stems with zero notes. |
| Reference stem muted in mixer | We don't care — we read `trackData.notes`, not the audio bus. Cents colouring still works. |
| Song bleeds from speakers into mic | **Documented, not engineered around.** First-time enable shows a one-time helper text recommending headphones. |

## Testing

### Unit (`node:test` + `jsdom`, `webui/tests-js/`)

Test runner is Node's built-in `node:test` (existing pattern, see e.g. `webui/tests-js/notation.test.js`, `wasapi-engine.test.js`). DOM tests bring up `JSDOM` and shim `globalThis.document` / `globalThis.window`. Invocation: `node --test "tests-js/*.test.js"` from inside `webui/`.



| File | Coverage |
|---|---|
| `mic-yin-processor.test.js` | Synthetic PCM (sines at 110/220/440/880 Hz, sweeps, silence, white noise). Assert returned `freq` within ±2 cents of expected. Outlier hysteresis kicks in on injected drop. RMS gate produces `freq=0` below threshold. Tests run by instantiating the YIN class directly — the AudioWorklet wrapper is a thin shim around an exportable plain class. |
| `mic-pitch.test.js` | Fake engine, fake audioContext, fake worklet. Time-alignment math across offset values; ring buffer wrap; `getSamplesInRange` window selection; `lookupMidiAtTime` against synthetic stem data including gaps; signed cents calc. |
| `mic-overlay.test.js` | Spy on `CanvasRenderingContext2D`. Correct segment count, correct stroke styles for in-tune / slight / off / neutral, alpha from clarity. Not pixel snapshots. |
| `mic-row.test.js` | jsdom. M-button toggles state; reference dropdown enumerates non-empty stems; offset slider persists to localStorage; readout formats via `notation.js` for both scientific & solfège. |

### Integration (`node:test`)

| File | Coverage |
|---|---|
| `mic-pitch-integration.test.js` | Real `MicPitch` against fake engine + fake `getUserMedia` returning a `MediaStream` synthesized from an `OfflineAudioContext` playing a known melody. Assert ring buffer ends with the expected (time, midi) pairs within ±2 cents and ±50 ms. Catches breakage at the worklet ↔ coordinator seam. |

### E2E (playwright, `webui/tests-e2e/`)

| File | Coverage |
|---|---|
| `live-mic.spec.js` | Open a track. `context.grantPermissions(['microphone'])`. Click M → row enables, readout updates within 2 s, overlay canvas has non-zero stroke draws (peek via `page.evaluate`). Click M again → disabled, readout cleared. Chrome launch args: `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<synthetic.wav>`. |

### Manual smoke (in this spec, not automated — runs on JINN before "done")

1. Sing C4, C5 — ribbon at the right pitch on the roll.
2. Switch reference stem — colour bands shift accordingly.
3. Slide offset — ribbon translates horizontally.
4. Switch notation system — readout updates.
5. Switch tracks — ribbon clears, mic stays on.
6. Hit M — browser mic indicator releases.
7. Deny permission once — observe error state — click M — grant — recover.

### Coverage bar

Not a percent. Bar is: every `MicPitch` public method has a test, and YIN has known-input/known-output assertions at ±2 cents. That's the surface that matters.

## Out of scope (v1) — listed so they don't drift in

- Take recording / WAV export / per-track persistence.
- Click-track latency calibration wizard.
- CREPE / FCPE / pYIN alternative estimators (the YIN class is structured to allow swap-in later, but no UI / settings hook in v1).
- ScriptProcessorNode fallback for older browsers.
- Server-side mic capture via PortAudio.
- Acoustic echo cancellation against song bleed.
- Auto-pause on silence (the Tuner.2 SILENT_DURATION rule).
- Multi-mic capture / channel selection beyond `channelCount:1`.
- Live FFT / spectrogram visualisation.
- Sensitivity slider (RMS gate is fixed at 0.005 in v1).
- Cross-browser CI (Chrome on JINN is the only platform tested).

## Open questions for the plan / implementation phase

None blocking. The implementation plan should pick the rendering Z-order (mic above or below F0 — current intent: above), the exact CSS variable name for the row accent colour, and the precise wording of the first-time helper text.

## Post-ship deltas (2026-05-23)

Shipped 2026-05-22 in 24 commits, then four follow-up commits over the next day after the user smoke-tested. Recording the deltas here so the spec stays usable as a reference doc rather than getting silently mis-aligned from the code.

**API-shape change:**
- `getSamplesInRange().midi` is `Float32Array`, **not** `Uint8Array`. The original choice quantized every drawn pitch to the nearest semitone — producing a visible staircase even when the singer's pitch slid smoothly. The "sample" event detail was already a float; only the ring was wrong. Storage cost difference is ~3 KB across the 1024-entry ring — negligible. Fix in `13f717d`; regression-tested with a 452 Hz (47¢-sharp A4) input asserting the ring stores ~69.47, not 69.

**Semantic change:**
- `cents` in the ring buffer is `NaN` (not `0`) when no reference is active. `0` collided with "perfectly in tune" — the downstream overlay would have rendered no-reference samples in the in-tune green colour instead of neutral. The `"sample"` event detail uses `null` for the same case (unchanged). `Float32Array` preserves NaN losslessly. Fix in `653311f`.

**Rendering corrections:**
- MicOverlay's `midiToY(...)` calls were missing the `+ CHORD_H` offset that F0Overlay applies (`f0-overlay.js:183, 262`). Without it the ribbon floated 48 px above the note grid, overlapping the chord strip. Fix in `a434616`.
- MicOverlay now skips any segment whose time gap exceeds `MAX_SEGMENT_GAP_S = 0.15 s` (~3 missed worklet blocks). The previous polyline drew a long diagonal across silences, visually implying a slide that never happened. Fix in `dcd5c56`.

**DSP corrections:**
- The YIN CMND loop now starts at `tauMin + 1` (not `1`) so stale `d[1..tauMin-1]` from previous `process()` calls doesn't pollute the denominator. First-call was masked by `Float32Array` zero-init; every subsequent call biased the CMND. Fix in `abbb3e9`.
- Outlier hysteresis is now symmetric: rejects any ratio outside `[0.55, 1.82]` (~±10 semitones) in EITHER direction. The original spec inherited Tuner.2's down-only rule, which let octave-UP errors (super-harmonic lock) through unfiltered. Fix in `dcd5c56`.

**Lifecycle corrections:**
- `MicPitch.start()` is now reentrancy-safe via a `_starting` sentinel. The original `_running`-only guard let a double-click on M acquire two concurrent `getUserMedia` streams. Fix in `39fc974`.
- `MicOverlay` exposes `destroy()` that removes the `"sample"` listener + cancels pending rAF. Without it, every track change leaked one subscriber on the long-lived `window.__musiqMic` singleton. Same class of bug, same fix-shape as MicRow's `mount()` self-cleanup. Fix in `a8c5034`.
- `MicPitch.start()` error-code ladder now also maps `NotReadableError → "device-busy"` (was `"unknown"`), important for WASAPI Exclusive conflicts on this machine.

**UI:**
- MicRow rebuilt on the existing `.track-row` 5-column grid instead of a custom `side-stem-row` anatomy. The original two-row layout (Row 1 header + Row 2 controls) was visually out of place — oversized text, M button as a standalone block, controls overflowing the panel. Now the row sits inside the same grid as the six regular stems with: 12px swatch (with status-dot inside) | name | 96px readout cell | M only (no S — solo of mic input is meaningless). Match dropdown + Offset slider moved to a `.mic-meta` sub-row spanning grid-columns 2/-1, mirroring the existing `.f0-meta` and `.drum-tight` sub-line pattern. Fix in `041674c`.
- `--mic-accent` retuned from purple `#a48cff` to the project's `--ok` green. Live/recording semantic, matches the pulse colour, distinct from `other`'s purple. Fix in `041674c`.
- New `.mic-on` row modifier + `.btn.m.mic-live` button modifier drive the active-state visuals. Deliberately NOT the existing `.btn.m.on` (which is the muted-with-strikethrough state for regular stems and would mean the opposite for mic input).
- `.status-dot` CSS rules scoped to `.mic-row-host` so they don't leak into any future `.status-dot` elsewhere. Fix in `7dda1bd`.

**v1.5 follow-ups (explicitly out of v1):**
- Per-device picker UI in the row. `setDeviceId()` is callable + persisted, but a proper picker needs the post-permission `enumerateDevices()` refresh dance (labels are anonymized before permission). v1 uses the system default device.
- Click-track latency calibration wizard. Offset slider is the v1 answer.
- Hop-overlap (halve hop to 1024 for ~47 Hz estimate rate). Currently 1 estimate per 43 ms block.

**Validated by:** unit suite (29 mic-related tests, 0 failures), one integration test (synthetic melody through the coordinator), one Playwright e2e (passes against the running webui with a fake 440 Hz mic stream), and manual smoke on JINN by the project owner. Two real visual bugs (staircase + silence-bridging) surfaced in manual smoke after unit/e2e were green and were fixed within the same day.

## Post-ship deltas — 2026-05-23 iteration

A second pass on the same day, driven entirely by user manual smoke as the singer exercised the feature. Recording here so the spec keeps tracking the shipped behaviour.

**Colour model — 4-bucket scheme, all theme-driven:**
- Cents bucket logic split into four states, each backed by its own theme token (defined in all 5 presets):
  - `in` → `--mic-in` (green default) — matched, `|cents| ≤ 100¢`
  - `off` → `--mic-off` (red default) — unmatched, more than a semitone off
  - `neutral` → `--mic-neutral` (blue default) — matched to a stem, stem silent at this song time (between vocal phrases)
  - `no-match` → `--mic-no-match` (purple default) — match dropdown set to "none"
- `centsToColourBucket(cents, hasReference = true)` takes a second arg so NaN cents can route to `neutral` vs `no-match` based on the current dropdown. `MicOverlay.render()` reads `micPitch.getReferenceStem?.()` once per draw; `MicPitch.setReferenceStem` dispatches a `"reference-changed"` event so the overlay re-buckets the visible ribbon without waiting for the next mic frame.
- `--mic-accent` retired (was the sidebar swatch's green). Swatch now uses `var(--mic-no-match)` as a static row identifier — matches the pitch line when the user picks "match: none". The `.status-dot` recording indicator and `.btn.m.mic-live` still use `--ok` directly (semantically: "live recording", a separate concept from row identity).
- The earlier `--mic-neutral` collision with `--mic-accent` (both resolved to `--ok` green, making silent stretches indistinguishable from in-tune) was the trigger for the full token split. Memory: [[mic_overlay_color_buckets]].

**Configurable line widths:**
- New `webui/static/js/ui/line-width-prefs.js` exposes `getMicLineWidth()` + `getVocalsLineWidth()` (range 0.5–4 px, default 1, step 0.25, persisted via `localStorage["musiq.lineWidth"]`, dispatched on `musiq:line-width-changed`).
- MicOverlay uses the mic value directly; F0Overlay scales `STRENGTH_STROKE_WIDTH` by `userWidth / VOCALS_BUCKET_BASE (1.5)` so the bucket gradient (strong/medium/weak = 1.8/1.5/1.2) compresses or expands proportionally at default 1 px.

**EMA smoothing kills frame-to-frame shimmer — applied at WRITE time:**
- `MicPitch._onSample` runs an EMA pass (α=0.4) on `midi` and `cents` BEFORE writing to the ring. The ring carries pre-smoothed values; `MicOverlay.render()` reads them directly with no per-frame transformation.
- Earlier attempt: run EMA inside `MicOverlay.render()` (in-window per frame). That introduced a ~1 px shimmer on near-horizontal sections as the user scrubbed or autoScroll panned the viewport. Cause: EMA is recursive (`sm[i] = α·raw[i] + (1−α)·sm[i−1]`), so the chain re-seeds from the visible window's leftmost sample every render — when the leftmost shifts (pan), every downstream smoothed value shifts too. F0Overlay doesn't have this because its smoother is a median over a fixed window of array indices, non-recursive.
- Reset condition (write-time): `Math.abs(tSong − _emaLastTSong) > EMA_GAP_S (0.15s)`. Matches the draw-side `MAX_SEGMENT_GAP_S` so the smoother stops blending across the same gap the renderer stops drawing across.
- EMA state also resets on `setReferenceStem` (cents only — switching reference makes any prior smoothed cents semantically wrong) and on `clearBuffer` (full wipe).

**Settings → Pitch lines section in the Settings modal:**
- Two width sliders (Live Input + Vocals) and seven colour pickers (4 mic + 3 f0).
- All colour pickers write through the theme store (`theme/store.setToken`), so picks ride `musiq:theme-changed`, follow preset switches, and live in the same persistence blob as the rest of the theme. `webui/static/js/ui/color-prefs.js` is a thin wrapper that maps pref-keys → theme token names.
- Per-row "Reset" snaps that row's colours back to the active preset's defaults (the closest behaviour the theme store affords — `resetTokens()` wipes everything).
- Required `theme/store.js` extension: `mic-` added to `COLOR_KEYS_PREFIX` so `setToken` validates and accepts the new tokens.

**Transport correctness — playback-state-aware ring buffer:**
- `MicPitch._onSample` skips ring writes when `engine.isPlaying === false`. Without this, every YIN frame during pause lands at the frozen `tSong = engine.currentTime - age - offsetMs/1000`, stacking many samples at one X coordinate and producing vertical-spike artifacts at the playhead.
- The readout event still fires for `match=none`/silence/pause (so the user sees their pitch while warming up); only the ring write is gated.
- **No** Δt-based seek-detect in MicPitch. Tried `delta > 1.0 || delta < -0.2 → clearRing()` and it false-fired on "sing → 3 s silence → sing" and "pause → wait → resume → wait → sing": both produce a large gap between *pushes* even though `tSong` advanced naturally. The draw-side `MAX_SEGMENT_GAP_S` guard handles every gap correctly — storage and presentation are different layers. Memory: [[mic_ring_gate_isplaying]].
- `MAX_SEGMENT_GAP_S` check in `MicOverlay` (and the EMA reset) is `Math.abs(t1 - t0) > THRESHOLD`. The ring is keyed by insertion order, not time order — a backward seek (playhead moved back, user sang) yields adjacent entries with `t1 < t0`, and a one-sided check would silently bridge them as a long horizontal line.

**UI polish:**
- Mic mute toggle: glyph changed from the letter "M" to an inline stroke SVG mic icon (`stroke="currentColor"`), inheriting the existing button colour states (idle muted-grey → hover near-white → live-state black-on-green) without a new CSS rule.
- Stem volume + zoom + mic-offset + scrub sliders unified on one visual (`.vol` / `.vol-fill` 4 px track, 2 px radius, `--text-primary` fill); old `--vol-track-bg` / `--vol-fill-bg` tokens retired.
- Zoom H/V sliders made click-and-drag (in addition to ctrl+wheel / ⇧wheel) via `attachDrag`. H drag clears `viewState.autoScroll` to match the wheel handler.
- Selected stem's slider fill stays the same colour as unselected (was being overridden to `--text-secondary`).

**Memory entries added during this iteration:**
- `mic_overlay_neutral_token.md` — keep `--mic-neutral` distinct from `--mic-accent` *(retired 2026-06-13; folded into `mic_overlay_color_buckets.md`)*
- `mic_ring_gate_isplaying.md` — gate ring writes on `isPlaying`; don't add Δt clear; use `Math.abs` for gap guards
- `mic_overlay_color_buckets.md` — 4-bucket design + theme integration constraint
- `feedback_surgical_changes_no_tests.md` — don't `node --test` after single-line cosmetic edits

**Validated by:** 29/29 mic-related unit tests pass after the iteration (no count change — assertions strengthened in-place); ~30 small commits over the day; manual smoke on JINN by the project owner with the singer running through the full transport (play / pause / silence / backward seek / loop wrap / match=none ↔ match=stem cycles).
