# WASAPI audio engine v1 — 2026-05-12

## Goal

Add a low-latency Windows audio engine to the webui playback layer, selectable from Settings, with an output-device combobox that lists every available device under three host APIs each: **MME**, **WASAPI Shared**, **WASAPI Exclusive**. WebAudio remains the default and the always-available fallback.

Non-goal for v1: full ASIO. (The reservation in `webui/static/js/audio/engine.js:2-3` stays; ASIO becomes a later sibling backend that uses the same WS protocol defined here.)

The playhead must remain visually smooth — no jitter, no drift visible over a 5-minute track — and must stay sample-accurate with the audio output across `seek`, `pause`, `play`, loop wraps, and mute/solo changes.

## Background

The browser cannot speak WASAPI directly. The existing `WebAudioEngine` (`webui/static/js/audio/web-audio-engine.js`) goes through Chromium's audio output, which on Windows is WASAPI Shared with a buffer of ~30–80 ms. That is fine for casual playback but it (a) is not configurable per-device, (b) cannot reach Exclusive mode, and (c) gives no way to choose the output device from inside the app — users have to use the OS sound panel.

The codebase has been engineered for this addition since day one:

- `engine.js:11-23` defines the abstract `AudioEngine` contract (load/play/pause/seek/setStemVolume/setStemMute/setStemSolo/currentTime/isPlaying/on/off).
- `engine.js:30` defines `STEM_NAMES` — the canonical 6-stem order used by every layer.
- `transport.js:74-78` subscribes to `modeChanged` / `modeAvailability` and is agnostic to the engine implementation.
- `menus.js:560-568` already renders an "Audio engine" radio group with a disabled `ASIO (low-latency) — coming r1` row.

The new engine is therefore an *additive* module, not a refactor. The web-audio engine is not modified.

## Architectural decisions

| Decision | Choice | Rationale |
|---|---|---|
| Process model | **In-process audio thread** inside the webui Python process | One process to launch / monitor (`webui/webui.ps1`), no second port, lowest control-path latency. PortAudio callbacks run on a dedicated OS thread, not the asyncio loop, so they do not block FastAPI. Crash risk accepted; mitigated by exception isolation and a hard fall-back to WebAudio. |
| Device-list shape | **Two WASAPI entries per device** (Shared + Exclusive) plus one MME entry | Explicit, unambiguous. Power users can pin Shared even when Exclusive is available (e.g., to keep system sounds working). Matches the JS engine's `getMode` / `setMode` "honor the user even when auto would differ" pattern (`web-audio-engine.js:207-217`). |
| Settings persistence | **`localStorage`** (global per browser) | Matches the existing `localStorage["musiq.theme"]` convention (memory: [[ui_polish_themable_tokens]]). Engine + device + exclusive flag stored under `localStorage["musiq.audio"]`. |
| Wire transport | **Single WebSocket** at `/api/audio/control`, JSON both directions | Loopback round-trip is sub-millisecond. One connection per page load; reconnects on drop. Clock ticks ride the same socket. |
| Sample-rate handling | **Pre-resample on load**, cache resampled float32 in RAM | Stems are cached at the **source MP3 rate** (44.1 kHz for the current corpus — confirmed by `soundfile.info()` on `cache/baleen_unmedicated/stems_6s/*.wav`, PCM_16 stereo). Resampling to device rate is **mandatory whenever device rate ≠ stem rate** (i.e., the common case where the device is at 48 kHz). RAM footprint at 48 kHz float32: 6 stems × 5 min × 48000 × 2 ch × 4 B ≈ 138 MB — fits comfortably in 96 GB RAM. `summary.json` does NOT carry `sample_rate`; the backend must call `soundfile.info()` on the stem WAV at load time. Confirmed by 2026-05-12 probe: `check_output_settings(samplerate=44100, exclusive=True)` returns `PaErrorCode -9997` on a 48 kHz device — Exclusive bypasses the OS mixer and requires the device's hardware-set rate. |
| Resampler | **`soxr>=1.0`** with `quality='HQ'` | Polyphase, high quality, small dep. soxr 1.1.0 ships a `cp312-abi3-win_amd64` wheel that works on Python 3.13. HQ preset: ~10.8 ms per 10 s of 48→44.1 kHz conversion (verified PyPI benchmark) — 5-min stereo stem loads in ~0.5–1 s single-thread, six stems ≈ 3–6 s warm-cache. VHQ adds ~30–40% runtime for negligible perceptual gain on already-separated stems. Falls back to `scipy.signal.resample_poly` if `soxr` is unavailable. |
| Stem mix bus | **Server-side**, in the audio callback | One PortAudio output stream, internally summing the six stem buffers with per-stem gain. Mirrors `_applyGain`'s 10 ms time-constant ramps (`web-audio-engine.js:194-201`) using a one-pole filter on the gain value to avoid clicks. |
| Loop semantics | **Sample-accurate wrap inside the callback** | Block boundaries are split if a loop point lies inside; two copies issued back-to-back into the same output block. No 1-block latency at the wrap. |
| Failure fallback | Exclusive open fails → re-attempt Shared → re-attempt MME → emit `engineFailed` and let UI revert to WebAudio | Surfaces a single-line toast: "WASAPI Exclusive unavailable (device in use). Falling back to Shared." Same UX as autoplay-blocked. |

## Dependencies

Added to `webui/requirements.txt`:

```
sounddevice>=0.5
soxr>=1.0
```

Already in `webui/requirements.txt` and required by `audio_backend` for source-MP3 decode:

```
soundfile>=0.13
```

`sounddevice` ships PortAudio with WASAPI support enabled in its official Windows wheels (verified 2026-05-12: sounddevice 0.5.5 with PortAudio V19.7.0-devel exposes MME, DirectSound, WASAPI, WDM-KS — no native compile). `soxr>=1.0` is required for the Python-3.13-compatible abi3 wheel. `soundfile>=0.13` bundles libsndfile 1.2.2 with MP3 decode support (added in soundfile 0.11.0).

## File layout

New code (all additive — nothing in the existing audio path is touched):

```
webui/webui/
  audio_backend/
    __init__.py
    devices.py        # enumeration, hostapi grouping, default-device probing
    stream.py         # PortAudio stream lifecycle, callback, gain mixer
    clock.py          # song-time ↔ audio-time anchor, tick emitter
    protocol.py       # pydantic models for WS messages
    ws.py             # FastAPI WS endpoint + per-connection session
  tests/
    test_audio_devices.py
    test_audio_clock.py
    test_audio_stream.py
    test_audio_ws_protocol.py

webui/static/js/audio/
  wasapi-engine.js    # WS-driven AudioEngine implementation
  device-picker.js    # combobox + device list fetcher
  engine-factory.js   # localStorage → engine instance switchboard

webui/static/js/ui/
  menus.js            # MODIFY: enable the engine radio + insert device picker
```

## Wire protocol

### Endpoint
`GET ws://127.0.0.1:8765/api/audio/control`

One WS connection per page. The session is single-tenant — opening a second WS while one is active closes the first (toast: "Audio control reconnected on this tab").

### Messages — client → server

All messages have a `op` string field and a monotonic `req` integer for correlation:

```jsonc
{ "op": "list_devices", "req": 1 }
{ "op": "set_device",   "req": 2, "hostapi": "wasapi", "device_name": "Speakers (Realtek)", "exclusive": true, "samplerate": 48000 }
{ "op": "load",         "req": 3, "slug": "gorillaz_silent_running" }
{ "op": "play",         "req": 4 }
{ "op": "pause",        "req": 5 }
{ "op": "seek",         "req": 6, "song_t": 12.345 }
{ "op": "stem",         "req": 7, "name": "vocals", "vol": 0.8, "muted": false, "soloed": false }
{ "op": "loop",         "req": 8, "start": 4.0, "end": 8.0 }
{ "op": "loop_clear",   "req": 9 }
{ "op": "set_mode",     "req": 10, "mode": "stems" }   // "source" | "stems" | null (= auto)
{ "op": "ping",         "req": 11, "perf_t_client": 1234567.89 }
```

### Messages — server → client

```jsonc
{ "type": "devices", "req": 1, "list": [
    { "id": "wasapi:Speakers (Realtek):14",    "label": "Speakers (Realtek) — WASAPI Shared",    "hostapi": "wasapi", "device_name": "Speakers (Realtek)", "exclusive": false, "default_samplerate": 48000 },
    { "id": "wasapi-ex:Speakers (Realtek):14", "label": "Speakers (Realtek) — WASAPI Exclusive", "hostapi": "wasapi", "device_name": "Speakers (Realtek)", "exclusive": true,  "default_samplerate": 48000 },
    { "id": "mme:Speakers (Realtek):3",        "label": "Speakers (Realtek) — MME",              "hostapi": "mme",    "device_name": "Speakers (Realtek)", "exclusive": false, "default_samplerate": 48000 }
] }

// The `id` field embeds the session-scoped device_index and is convenient for
// the dropdown's <option value="...">, but it is NOT persisted to localStorage.
// On set_device the server uses (hostapi, device_name) to re-resolve the index
// from the current `query_devices()` snapshot. See "Device identity" section.

{ "type": "loaded",    "duration": 247.32, "sample_rate": 48000, "stems_available": ["vocals","piano","other","guitar","bass","drums"], "source_available": true }
{ "type": "ack",       "req": 4 }
{ "type": "state",     "playing": true, "mode": "stems" }
{ "type": "clock",     "song_t": 12.345, "audio_t": 12.350, "perf_t_server": 1234567.89, "playing": true }
{ "type": "ended" }
{ "type": "error",     "code": "device_in_use", "message": "WASAPI Exclusive: device locked by another process", "fallback": "shared" }
{ "type": "pong",      "req": 11, "perf_t_client": 1234567.89, "perf_t_server": 1234567.90 }
```

### Tick cadence

`clock` messages are emitted at **40 Hz** (every 25 ms) while playing. At rest one final `clock` is sent on `pause`/`seek`/`ended` and the stream then idles. This is the central knob for smoothness: too low and the rAF extrapolator drifts visibly between ticks; too high and JSON encoding eats CPU. 40 Hz × ~140 bytes = ~5 KB/s — negligible.

## Clock sync — the smooth-playhead architecture

This is the part the user flagged as critical. The plan in detail:

### Server-side authoritative clock

PortAudio's stream callback provides `time_info.outputBufferDacTime`, the audio device's monotonic clock at the *first sample of the block leaving the DAC*. The session keeps an anchor:

```python
class Anchor:
    song_t: float       # song-time at the anchor
    audio_t: float      # outputBufferDacTime at the same instant
    playing: bool
```

Anchor updates only on play / seek / loop wrap — three discrete events. Between updates, `song_t(audio_t) = anchor.song_t + (audio_t - anchor.audio_t)`. No drift can accumulate; the audio device's own clock *is* the song clock.

### Clock-tick emitter

A dedicated `asyncio.Task` (started from the FastAPI WS handler) wakes every 25 ms while playing. Each wake calls `sd.Stream.time` (PortAudio's `Pa_GetStreamTime`) and the current `song_t` from the anchor function, then sends:

```python
await ws.send_json({
    "type": "clock",
    "song_t": song_t,
    "audio_t": audio_t,
    "perf_t_server": time.perf_counter(),
    "playing": True,
})
```

`perf_t_server` is included for future round-trip latency estimation but not used in v1.

### Client-side rAF extrapolation

The `WasapiEngine.currentTime` getter, called once per rAF frame by `transport.js` and the piano-roll, returns:

```js
get currentTime() {
  if (!this._playing) return this._lastSongPos;
  const now = performance.now() / 1000;
  return this._anchorSongT + (now - this._anchorPerfNow);
}
```

When a `clock` message arrives:

```js
_onClock(msg) {
  const arrivePerf = performance.now() / 1000;
  // Compare extrapolated position to the new anchor. If the difference is
  // small (< 30 ms), smoothly slew the anchor toward the message over the
  // next ~200 ms so the cursor never visibly snaps. If the difference is
  // large (seek, loop wrap), snap immediately.
  const extrap = this._anchorSongT + (arrivePerf - this._anchorPerfNow);
  const delta = msg.song_t - extrap;
  if (Math.abs(delta) > 0.030) {
    // hard re-anchor
    this._anchorSongT = msg.song_t;
    this._anchorPerfNow = arrivePerf;
  } else {
    // soft slew: bias the anchor by half the delta now, half over next tick
    this._anchorSongT = msg.song_t - delta * 0.5;
    this._anchorPerfNow = arrivePerf;
  }
  this._lastSongPos = msg.song_t;
}
```

This is the **snapshot-interpolation pattern documented by Valve for Source-engine multiplayer networking** (developer.valvesoftware.com/wiki/Source_Multiplayer_Networking, /wiki/Interpolation): the authoritative clock lives on the server, snapshots arrive at a fixed rate, the client renders by interpolating between them. The 40 Hz tick + 30 ms soft-slew threshold is a tighter variant of Valve's 20 Hz / 100 ms render-behind approach — appropriate because our "latency" budget is sub-frame, not multiplayer-round-trip.

### Visible-drift behavior (bounds)

- **WS one-way latency over loopback:** sub-millisecond typical on Windows, occasionally higher under scheduler contention. No authoritative W3C/RFC number; empirically negligible vs. the 25 ms tick interval.
- **`performance.now()` resolution:** 100 µs floor in Chromium without cross-origin isolation, 5 µs floor with COOP/COEP enabled (W3C High Resolution Time Level 3). Webui is not COOP/COEP-isolated, so 100 µs is the working number.
- **Audio-clock vs. system-clock drift:** typically tens of ppm on commodity hardware (consumer audio crystals 20–50 ppm, PC RTC 20–100 ppm). No single authoritative source quotes a hard bound; the 25 ms soft-slew loop absorbs whatever drift accumulates between ticks regardless of the device.
- **Per-rAF visible jitter:** dominated by `performance.now()` quantisation (~100 µs) — at 60 px/sec zoom that's ~0.006 pixels per frame, well below perceptual threshold.
- **Exclusive-mode block size:** driver-reported via `DEVPKEY_KsAudio_PacketSize_Constraints2` (MSFT Low-Latency Audio). USB-class devices like the BEHRINGER FLOW 8 typically report 128–256 frames @ 48 kHz, not 64. The Settings UI must display the actual `stream.latency` post-open rather than a hard-coded number.
- **Start latency (Exclusive):** ~5–15 ms for click-to-first-sample on USB-class devices, dominated by the driver-reported minimum buffer + PortAudio scheduling. Browser sees the first `clock` tick within 25 ms. Measure on real hardware (acceptance criterion in Phase 4) — do not promise a number ahead of measurement.

### Why 25 ms and not 50 ms

A 50 ms tick means the rAF extrapolator runs for up to three frames (at 60 Hz) before correcting. The soft-slew above keeps that invisible *most* of the time but can produce a one-frame stutter if the OS scheduler hiccups the WS task. 25 ms is comfortably faster than rAF (16.7 ms), so every frame has either a fresh anchor or one ≤1 frame old. CPU cost is ~0.04% of one core.

## Stem mixing inside the callback

The audio callback receives an output buffer of `frames × 2` float32 stereo samples. The session holds:

```python
buffers: dict[str, np.ndarray]   # name → (n_samples, 2) float32
gains: dict[str, float]          # smoothed gain target
target_gains: dict[str, float]   # set by 'stem' op
play_offset: int                 # sample index into buffers, advanced per callback
```

Each callback:

1. Compute effective gain per stem from `(muted, anySoloed, soloed[name], targetVol[name])` using the existing `_applyGain` truth table (`web-audio-engine.js:194-201`).
2. One-pole smooth `gains[name]` toward the new effective gain with `α = 1 - exp(-frames / (sr × 0.010))` (10 ms time constant — identical to `setTargetAtTime(_, _, 0.01)`).
3. `out = sum(gains[n] * buffers[n][offset:offset+frames] for n in STEM_NAMES if buffers.get(n) is not None)`.
4. Advance `play_offset` by `frames`. If `play_offset` would cross `loop_end_sample`, split the block: first half from current offset to `loop_end_sample`, second half from `loop_start_sample`. Update anchor with the loop-start instant.
5. If `play_offset` reaches `n_samples`, set `playing=False`, post `{type:"ended"}` to the WS via a thread-safe queue (the callback itself must not touch asyncio).

No allocation in steady state — `out` is pre-allocated and reused. NumPy in-place operations (`np.multiply(buf, g, out=tmp); np.add(out, tmp, out=out)`) keep the callback under a few hundred microseconds per block.

## Device enumeration

`audio_backend/devices.py`:

```python
def list_output_devices() -> list[DeviceEntry]:
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    out: list[DeviceEntry] = []
    for i, dev in enumerate(devices):
        if dev["max_output_channels"] < 1:
            continue
        api_name = hostapis[dev["hostapi"]]["name"]
        if "MME" in api_name:
            out.append(DeviceEntry(id=f"mme:{dev['name']}:{i}", label=f"{dev['name']} — MME", index=i, hostapi="mme", exclusive=False, default_sr=int(dev["default_samplerate"])))
        elif "WASAPI" in api_name:
            out.append(DeviceEntry(id=f"wasapi:{dev['name']}:{i}",    label=f"{dev['name']} — WASAPI Shared",    index=i, hostapi="wasapi", exclusive=False, default_sr=int(dev["default_samplerate"])))
            out.append(DeviceEntry(id=f"wasapi-ex:{dev['name']}:{i}", label=f"{dev['name']} — WASAPI Exclusive", index=i, hostapi="wasapi", exclusive=True,  default_sr=int(dev["default_samplerate"])))
    return out
```

WDM-KS, DirectSound, ASIO host APIs are filtered out for v1.

The device list is fetched once on page load (`op:"list_devices"`). It is **not** auto-refreshed when devices hotplug; the Settings panel has a small refresh button that re-sends `list_devices`.

## Settings UI changes

In `webui/static/js/ui/menus.js` (the only modified UI file):

1. Enable the engine radio group; add a `change` handler that calls `engineFactory.switchTo("webaudio" | "wasapi")` and rebuilds playback for the current track.
2. Insert a device-picker section visible only when `engine === "wasapi"`. The section renders:
   - One `<select>` with all `DeviceEntry` rows.
   - A small "Refresh devices" button.
   - A read-only latency display populated from the active `sd.Stream.latency` after open (e.g., "Output: 48 kHz · 192 frames · 4.0 ms buffer"). This is the driver-reported number, not a guess.
3. Persist `{engine, device: {hostapi, device_name, exclusive, samplerate}}` to `localStorage["musiq.audio"]` on every change. Read on engine boot; if a saved device cannot be resolved via `(hostapi, device_name)` (driver upgrade, device removed), fall back to the system default + surface a toast.

The Customize tokens / Appearance section (memory: [[ui_polish_themable_tokens]]) is untouched.

## Engine factory

`engine-factory.js` reads `localStorage["musiq.audio"]` and returns either a `WebAudioEngine` or a `WasapiEngine`. The factory also subscribes to engine `engineFailed` events and transparently swaps to `WebAudioEngine` mid-session, then surfaces a toast.

The engine instance is created in `main.js` (the existing site) where `new WebAudioEngine()` is constructed today. Only that one line changes:

```js
// before
const engine = new WebAudioEngine();
// after
const engine = createAudioEngine();   // from engine-factory.js
```

## Mode toggle (source vs stems)

The existing source/stems mode toggle in `transport.js` continues to work unchanged. The WASAPI engine implements `setMode`/`getMode`/`getModeAvailability` with identical semantics:

- "source" mode: feed only the source MP3 to the mixer; gain bus is the single `_sourceMonoGain`.
- "stems" mode: feed the six stem buffers; the source buffer is held but not mixed.
- "auto": stems if all loaded; else source.

This means the user-visible behavior of the mode toggle, of stem mute/solo, of the loop chip, of seek-during-play, of replay-from-end, of "waiting for stems" — all of it — is identical to WebAudio. The engine swap is invisible above the engine layer.

## Tests

### Python (server-side)

- `test_audio_devices.py` — mocks `sd.query_devices` / `sd.query_hostapis`, asserts that each output device produces one MME row and two WASAPI rows; non-output devices and WDM-KS are filtered. Asserts persistence round-trip uses `(hostapi, device_name)` not `device_index` — given a saved tuple, `find_device_by_identity` returns the current index; given a missing tuple, returns `None`.
- `test_audio_clock.py` — given a synthetic stream of `(audio_t, frames)` tuples, asserts the anchor function produces monotonic `song_t` across play / seek / loop-wrap, with sample-accurate alignment at loop boundaries. Asserts soft-slew converges within 200 ms for a 20 ms anchor delta and snaps for >30 ms delta.
- `test_audio_stream.py` — mocks `sd.OutputStream` (PortAudio's null host is not portable on Windows). Drives the callback with synthetic `time_info`; asserts (a) `play_offset` advances by `frames` per call, (b) seek resets `play_offset`, (c) gain smoothing reaches target within 15 ms, (d) loop wrap is sample-accurate, (e) no allocations in steady state (verify via `tracemalloc`).
- `test_audio_ws_protocol.py` — pytest async client, sends each op, asserts the corresponding ack/state/clock message shape against pydantic models. Uses `httpx.AsyncClient` with WS support (or `websockets` direct). Includes a lifespan-shutdown test asserting `sd.Stream.close()` is called when the FastAPI app context exits.

### JS (client-side)

- `wasapi-engine.test.js` — fake WS, asserts: `play()` sends `{op:"play"}`, `seek(t)` updates `_anchorSongT` only after `state`/`clock` confirmation, `setStemMute` ships a `stem` op, `currentTime` extrapolates correctly between clock messages with `performance.now()` mocked.
- `device-picker.test.js` — renders given a fixture device list, asserts the three rows per device, asserts `change` event ships `set_device`.
- Existing `engine.test.js` contract tests run against both engines (parameterised).

### Manual / not in CI

- Latency measurement: physical loopback from headphone out into mic in; click track, measure samples to first audible sample. Target: < 15 ms WASAPI Shared, < 10 ms WASAPI Exclusive.
- Cursor smoothness A/B: load Gorillaz "Silent Running" cache, play through the entire track on each engine, eyeball at zoom = 200 px/sec for stutter. Acceptance: no human-visible stutter at 60 Hz refresh.
- Device-in-use: open Foobar holding WASAPI Exclusive, switch webui to the same device's Exclusive entry — assert clean error toast + fallback.

## Phased rollout

Each phase is independently shippable, mergeable to main (memory: [[branching_workflow]]), and reversible by a localStorage flip back to WebAudio. The user always has the safe path.

**Phase 1 — Device picker only (no audio yet)**
- `audio_backend/devices.py` + WS endpoint with just `op:"list_devices"`.
- Settings UI: engine radio enabled but selecting WASAPI is a no-op; device dropdown populates.
- Acceptance: dropdown shows expected entries on JINN (Realtek, Focusrite, etc.).

**Phase 2 — WASAPI Shared playback (source mode only)**
- Full `audio_backend/stream.py` with source-MP3 playback.
- `wasapi-engine.js` with play/pause/seek/currentTime.
- Clock sync + rAF extrapolator wired into transport.
- FastAPI `lifespan` handler that closes the active `sd.Stream` on shutdown (don't rely solely on `atexit` — it can race with asyncio loop closure).
- Acceptance: load track, hit play, hear source through WASAPI Shared, cursor smooth. **Warm-cache load of a 5-min 44.1 kHz track resampled to 48 kHz completes in < 3 s.**

**Phase 3 — Stem mixing**
- Stem buffers loaded, mute/solo/volume routed through the mix bus.
- Mode toggle works end-to-end.
- Acceptance: parity with WebAudio engine for all transport / mixer interactions.

**Phase 4 — WASAPI Exclusive + fallback chain**
- `extra_settings=sd.WasapiSettings(exclusive=True)`, error catch → reopen Shared, surface toast.
- MME entry works as a final fallback.
- Acceptance: device-in-use case lands cleanly on Shared without crashing playback.

**Phase 5 — Loop wrap sample-accuracy + polish**
- Loop split inside callback.
- Hotplug-refresh button.
- Latency display in Settings.
- Acceptance: piano-roll cursor wraps at the exact sample of `_loopEnd` even at 64-sample blocks; ear-test for clicks.

## Risks and open items

| Risk | Mitigation |
|---|---|
| `sounddevice` wheel on this Python (3.13.12) — verify WASAPI support compiled in | **Resolved 2026-05-12** by probe: `sounddevice 0.5.5` with PortAudio V19.7.0-devel exposes `MME`, `Windows DirectSound`, `Windows WASAPI`, `Windows WDM-KS`. `WasapiSettings(exclusive=True)` constructs and `check_output_settings` accepts it on the test device at native 48 kHz. No build needed. |
| Chromium grabs Exclusive when we don't expect | Exclusive is opt-in by user choice; Chromium uses Shared by default. Not a concern unless a future Chromium flag changes that. |
| `perf.now()` quantisation in unfocused tabs (Chromium clamps to 1 s) | Acceptable — UI is only meaningful when focused. The clock-tick stream continues; on refocus the next tick re-anchors. |
| Audio glitch when changing mute/solo at extreme gain steps | 10 ms one-pole smoothing matches WebAudio behavior; user reports of clicks → bump time constant to 20 ms. |
| Drum stem missing (`{transcribed: false}` from Stage 9) | Same as today — that stem just isn't in the mixer. UI grays the drum row. |
| Memory footprint with multiple tracks pre-loaded | Engine pre-loads only the *current* track. Switch tracks → discard buffers, reload. 138 MB × 1 = bounded. |
| WS reconnect mid-playback (browser tab refresh) | Audio keeps playing on the server; reconnecting browser sees the next `clock` tick within 25 ms and resyncs. Acceptable. If the user wants playback to *stop* on tab close, add a `beforeunload` handler to send `pause`. |
| Settings written to `localStorage` by another tab | Last writer wins; engine factory re-reads on `storage` event. Same behavior as the theme system. |
| Bluetooth / consumer USB DAC Exclusive instability | Bluetooth A2DP and some consumer USB DACs do not cleanly support WASAPI Exclusive (codec offload conflicts with bit-perfect contract). On Exclusive open failure, surface a clearer toast: "This device type often does not support Exclusive; using Shared instead." Then fall back per the standard chain. |
| Saved device gone after driver upgrade | MSFT endpoint IDs change on driver upgrade and PortAudio doesn't surface them — we persist `(hostapi, device_name)` and re-resolve on each session. If the tuple no longer matches any device, fall back to the system default + emit a toast "Previously selected output not found; using default." |
| Hotplug device discovery requires PortAudio reinit | `sounddevice` reads the device list once at module import; new devices plugged in after process start won't appear unless `sd._terminate(); sd._initialize()` is called. The "Refresh devices" button must do this dance before re-enumerating. |
| `stream.time` after close is undefined | The clock-tick coroutine must check `stream.active` before reading `stream.time`. |
| Callback queue blocking on backed-up WS task | Use `queue.SimpleQueue.put_nowait` with a bounded queue + drop-oldest policy for event emission from the callback. Never `await`, `print`, or `logging.*` inside the callback. |

## Out of scope for v1

- ASIO. The reservation comment in `engine.js:2-3` stays; an `AsioEngine` can be added later sharing this same WS protocol with `hostapi: "asio"`.
- MIDI output device selection (separate concern, deferred).
- Per-stem effect inserts, panning, EQ. v1 mirrors WebAudio exactly: gain + mute + solo.
- Multi-track / playlist crossfade.
- Telemetry / latency-stat reporting in Settings (only the static block-size display in Phase 5).

## Effort estimate

| Phase | Effort | Notes |
|---|---|---|
| 1 — Device picker | ~0.5 day | WS scaffold + 1 endpoint + dropdown |
| 2 — Shared playback (source) | ~1.5 days | Stream callback, clock sync, rAF extrapolator |
| 3 — Stem mixing | ~1 day | Gain bus + mute/solo parity |
| 4 — Exclusive + fallback | ~0.5 day | Mostly error handling + toast |
| 5 — Loop wrap + polish | ~0.5 day | Sample-accurate loop split |
| **Total** | **~4 days focused** | Plus tests in flight — add ~1 day for CI tests. |

## Acceptance checklist (rollup)

- [ ] Settings → Audio engine radio switches without page reload.
- [ ] Device combobox shows MME + WASAPI Shared + WASAPI Exclusive per output device.
- [ ] Cursor is visually indistinguishable in smoothness between WebAudio and WASAPI engines at any zoom.
- [ ] Cursor position at sample N matches the audible sample N within ±1 sample (measured via mic loopback, ±20 µs tolerance at 48 kHz).
- [ ] Seek-during-play, pause, replay-from-end, mode toggle, mute, solo, volume, loop set/clear/wrap — all behave identically to WebAudio.
- [ ] WASAPI Exclusive denied by device-in-use → user sees toast, playback continues on Shared.
- [ ] Closing the browser tab while playing leaves no orphan audio (WS disconnect → stream.stop).
- [ ] All existing webui tests pass; new audio_backend tests added; the `engine.js` contract tests pass against both engines.
