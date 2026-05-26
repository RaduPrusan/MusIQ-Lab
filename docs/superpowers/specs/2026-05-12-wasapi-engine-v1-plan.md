# WASAPI engine v1 — execution plan (2026-05-12)

This plan is the build sequence for the WASAPI audio engine feature. It is designed to be picked up by a **fresh Claude session** with no prior conversation context — every fact needed to execute is either inlined or cited.

## Status at plan time

- **Spec**: `docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` — written 2026-05-12. Decisions locked. Requires 12 small edits from research findings (see Phase 0).
- **Research**: `docs/superpowers/specs/2026-05-12-wasapi-research-findings.md` — written 2026-05-12. Validates the spec against MSFT Learn, W3C, PortAudio docs, Context7. 3 corrections, 12 specific spec edits, 7 newly-surfaced risks. No blockers found.
- **Code**: zero lines written. The `webui/.venv` already has `sounddevice 0.5.5` installed from probing (PortAudio V19.7.0-devel, WASAPI host API confirmed working).
- **Test corpus**: `cache/baleen_unmedicated/` is a real analyzed track with full Demucs 6-stem output at `cache/baleen_unmedicated/stems_6s/*.wav` (44.1 kHz, int16, stereo, PCM_16). Use it for manual verification.
- **Branch**: main (the user commits straight to main on this project — memory note `branching_workflow`). Do not create feature branches.

## Cold-start instructions

A fresh agent picking this up should read, in this order:

1. **This file** — for the plan and phase gates.
2. **`docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md`** — for the architectural decisions (in-process audio thread, three rows per device, soft-slew clock sync, etc.). All decisions are locked; do not re-litigate.
3. **`docs/superpowers/specs/2026-05-12-wasapi-research-findings.md`** — for the evidence behind every "we know X" claim. When in doubt, the research wins over the spec; Phase 0 below brings the spec into alignment.
4. **`webui/static/js/audio/engine.js`** + **`webui/static/js/audio/web-audio-engine.js`** — the existing engine contract the new backend must mirror.
5. **`webui/CLAUDE.md`** if it exists, else **`CLAUDE.md`** — for project-wide conventions (the webui dev server is `127.0.0.1:8765`, not 8000; `webui.ps1` is the idempotent process manager; user commits straight to main).
6. **`webui/webui/server.py`** — for the existing FastAPI patterns the new WS endpoint should compose with.

Before writing any code, run:

```powershell
git fetch
git status
git log --oneline -10
```

Memory note `parallel_agents` warns that the user sometimes runs concurrent agents. If `git status` shows recent activity on `webui/static/js/audio/`, `webui/static/js/ui/menus.js`, or `webui/webui/`, stop and re-sync with the user before proceeding.

## Orchestration model

Phases are **strictly sequential** — each one builds on the previous, and acceptance gates must pass before the next starts. Within a phase, tests can be written in parallel with implementation by fanning out a `general-purpose` subagent for tests while the main agent writes implementation. Do not fan out across phases.

**Recommended subagent dispatch per phase:**

| Phase | Main agent role | Subagent fan-out |
|---|---|---|
| 0 — Pre-flight | Mechanical spec edits + memory writes | None |
| 1 — Device picker | Implementation | `general-purpose` for `test_audio_devices.py` (parallel) |
| 2 — Shared playback | Implementation (clock sync is the heavy bit) | `general-purpose` for `test_audio_clock.py` + `test_audio_ws_protocol.py` (parallel) |
| 3 — Stem mixing | Implementation | `general-purpose` for `test_audio_stream.py` mix/gain tests (parallel) |
| 4 — Exclusive + fallback | Implementation | `feature-dev:code-reviewer` after to catch error-handling gaps |
| 5 — Loop + polish | Implementation | `feature-dev:code-reviewer` after |

After each phase, run `feature-dev:code-reviewer` on the diff before declaring the phase done. The reviewer's notes feed into the next phase's "things to fix" list.

## Phase 0 — Pre-flight: apply research corrections (~30 min)

**Goal**: bring the spec into alignment with research findings; record the non-obvious findings as project memories.

### Tasks

1. Edit `docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` to apply the 12 changes enumerated in the research doc's "Recommended spec changes" section. Specifically:

   - **Sample-rate row in Architectural decisions table**: stems are cached at the source-MP3 rate (44.1 kHz for current corpus), not 48 kHz. The 138 MB number stays but the derivation changes. Resample to device rate is **mandatory** when device rate ≠ stem rate.
   - **Resampler row**: pin `soxr.resample(..., quality='HQ')`. Bump `soxr>=0.5` → `soxr>=1.0`.
   - **Dependencies section**: list `soundfile>=0.13` explicitly.
   - **Wire-protocol `set_device`**: persist `(hostapi_name, device_name, exclusive, samplerate)` only — not `device_index`. Re-resolve index on each page load; if no match, fall back to default + emit toast.
   - **Wire-protocol `devices`**: keep the live `id` string with the index but document it as session-scoped.
   - **"Numerical bound on visible drift" section**: drop the `<50 ppm` and `64-sample block = 1.3 ms` hard numbers. Replace with "audio-vs-system-clock drift is typically tens of ppm; the 25 ms soft-slew loop absorbs it" and "Exclusive block size is driver-reported via `DEVPKEY_KsAudio_PacketSize_Constraints2` (MSFT Low-Latency Audio); USB-class devices like FLOW 8 typically report 128–256 frames @ 48 kHz."
   - **Settings UI**: display actual `stream.latency` post-open, not `default_samplerate` from `query_devices`.
   - **Risks table — add row** "Bluetooth / consumer USB DAC Exclusive instability" → toast: "This device type often does not support Exclusive; falling back to Shared."
   - **Risks table — add row** "Saved device gone after driver upgrade" → match by `(hostapi, name)`; if missing, default + toast.
   - **Tests section — add**:
     - `test_audio_clock.py`: soft-slew converges within 200 ms for 20 ms anchor delta; snaps for >30 ms delta.
     - `test_audio_devices.py`: persistence round-trip uses `(hostapi, name)` not index.
     - Lifespan-shutdown test asserts `sd.Stream.close()` is called on app context exit.
   - **Phase 2 acceptance**: load a 5-min, 44.1 kHz cache and produce 48 kHz audio in < 3 s warm-cache.
   - **Snapshot-interpolation citation**: replace "the same trick networked games use" with "the snapshot-interpolation pattern documented by Valve for Source-engine multiplayer (developer.valvesoftware.com/wiki/Source_Multiplayer_Networking)."

2. Save the following project memories (write to `C:\Users\<you>\.claude\projects\<CLAUDE_PROJECT_ID>\memory\` and index in `MEMORY.md`):

   - `audio_stem_cache_format.md` — type: project. Body: Demucs htdemucs_6s stems are written at the **source MP3 rate** (44.1 kHz for the current corpus), 16-bit PCM, stereo WAV. `summary.json` does **not** carry `sample_rate` — the audio backend must call `soundfile.info()` on a stem WAV at track-load time. **Why**: discovered during 2026-05-12 WASAPI engine pre-flight research; spec had assumed 48 kHz float32. **How to apply**: any new audio code that needs the cache rate reads it from the stem header, not from summary.json.
   - `windows_audio_device_identity.md` — type: project. Body: PortAudio integer device indices are session-scoped and can renumber on every `Pa_Initialize`. MSFT MMDevice endpoint IDs are persistent across reboot and USB replug but change on driver upgrade; PortAudio does not surface them. **Why**: persisting `device_index: 14` is wrong; tested device disappears or wrong-routes after driver updates. **How to apply**: persist `(hostapi_name, device_name)` tuple; re-resolve index on each session; on miss, fall back to default device + toast.
   - `soxr_python_313.md` — type: reference. Body: `soxr 1.1.0` (PyPI, May 2026) ships `cp312-abi3-win_amd64` wheel that works on Python 3.13.x. Use `quality='HQ'` preset for stem-rate conversion (~10.8 ms per 10 s of 48→44.1 kHz). **Why**: needed for WASAPI Exclusive on devices not at 44.1 kHz.

3. Update `MEMORY.md` index with the three new entries.

### Phase 0 acceptance

- [ ] Spec doc reflects all 12 research corrections; no `<50 ppm` or `64-sample = 1.3 ms` hard numbers remain; persistence rule says `(hostapi, name)`.
- [ ] Three memory files created; `MEMORY.md` index updated.
- [ ] `git diff` shows only documentation changes; no code changes yet.

## Phase 1 — Device picker scaffold (~0.5 day)

**Goal**: enumerate Windows output devices and surface them in Settings as MME + WASAPI Shared + WASAPI Exclusive rows. No audio playback yet. Selecting a row stores it in `localStorage` but does nothing audible.

### Files to create

- `webui/webui/audio_backend/__init__.py` — public exports.
- `webui/webui/audio_backend/devices.py` — `list_output_devices() -> list[DeviceEntry]` and `find_device_by_identity(hostapi, name) -> int | None`.
- `webui/webui/audio_backend/protocol.py` — pydantic models for WS messages (start with `ListDevices`, `Devices`, `Error`, `Pong`).
- `webui/webui/audio_backend/ws.py` — FastAPI WebSocket endpoint at `/api/audio/control`. Phase 1 implements only `list_devices` and `ping`.
- `webui/static/js/audio/device-picker.js` — combobox component.
- `webui/static/js/audio/wasapi-engine.js` — stub that implements the `AudioEngine` contract with all methods throwing `NotImplemented` except `dispose()`. Wire `list_devices` through. **No playback in Phase 1.**
- `webui/static/js/audio/engine-factory.js` — reads `localStorage["musiq.audio"]`, returns `WebAudioEngine` if `engine !== "wasapi"`, returns `WasapiEngine` stub otherwise.

### Files to modify

- `webui/requirements.txt` — add `sounddevice>=0.5` and `soxr>=1.0`.
- `webui/static/js/main.js:124` — replace `const engine = new WebAudioEngine();` with `const engine = createAudioEngine();` (from `engine-factory.js`).
- `webui/static/js/ui/menus.js:561-568` — enable the engine radio group; on `wasapi` selection, show the device picker below it. On change, write `localStorage["musiq.audio"]` and re-init the engine. (Phase 1: re-init is a no-op for wasapi; user sees an "audio engine pending implementation" toast.)
- `webui/webui/server.py` — register the new WS endpoint via `from webui.audio_backend.ws import router as audio_router; app.include_router(audio_router)`. Verify `_NoCacheDevMiddleware` does not interfere (it only handles `scope["type"]=="http"` — confirmed in research).

### Implementation notes

- `DeviceEntry` shape:
  ```python
  @dataclass
  class DeviceEntry:
      id: str              # session-scoped: "wasapi-ex:Speakers (Realtek):14"
      label: str           # "Speakers (Realtek) — WASAPI Exclusive"
      hostapi: str         # "mme" | "wasapi"
      device_name: str     # raw name from sounddevice
      device_index: int    # session-scoped
      exclusive: bool
      default_samplerate: int
  ```
- Enumeration filters: skip devices with `max_output_channels < 1`; skip DirectSound and WDM-KS host APIs.
- For each WASAPI output device emit **two** rows (Shared + Exclusive). For each MME output device emit **one** row.
- The "Refresh devices" button calls `sd._terminate(); sd._initialize()` server-side before re-enumerating — newly-plugged-in devices won't appear otherwise (research finding).
- localStorage key: `musiq.audio`. Shape: `{engine: "webaudio"|"wasapi", device: {hostapi, name, exclusive, samplerate} | null}`.

### Tests to add (parallel via subagent)

`webui/tests/test_audio_devices.py`:
- Mock `sd.query_devices` and `sd.query_hostapis`; assert three rows per WASAPI device, one per MME device, no rows for DirectSound/WDM-KS.
- Round-trip a `(hostapi, name)` identity through `find_device_by_identity` against a mocked device list; assert correct index returned; assert `None` when name absent.
- Edge case: two devices with the same name (e.g., two USB headsets). Assert resolver returns first-match deterministically; document this behavior.

`webui/tests/test_audio_ws_protocol.py`:
- Use `httpx.AsyncClient` + `websockets` to connect to the test FastAPI app; send `{op:"list_devices",req:1}`, assert `type:"devices"` response shape against pydantic model.
- Send `{op:"ping", perf_t_client: 1.0, req:2}`, assert `type:"pong"` with `req:2` echoed.

### Phase 1 acceptance

Run from project root in PowerShell:

```powershell
cd webui
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest tests/test_audio_devices.py tests/test_audio_ws_protocol.py -v
.\webui.ps1 restart
```

- [ ] `pytest` for the two new files passes.
- [ ] `pytest tests/` overall still passes (no regressions in the ~25 existing test files).
- [ ] Open `http://127.0.0.1:8765/` → Settings → Audio engine. Both radios are enabled.
- [ ] Selecting "WASAPI" reveals a device combobox populated with the expected entries on JINN: at minimum one MME entry and two WASAPI entries (Shared + Exclusive) for the BEHRINGER FLOW 8 (or whatever output device the running user has).
- [ ] Selecting a device writes `localStorage["musiq.audio"]` (verify via DevTools).
- [ ] Switching back to "WebAudio" restores normal playback. **Regression-test by playing the `baleen_unmedicated` track end-to-end on WebAudio.**
- [ ] `feature-dev:code-reviewer` run on the diff returns no high-priority findings.

## Phase 2 — WASAPI Shared playback in source mode (~1.5 days)

**Goal**: full playback of the source MP3 through WASAPI Shared, with the smooth-playhead architecture working end-to-end. No stem mixing yet; no Exclusive mode yet.

### Files to create

- `webui/webui/audio_backend/clock.py` — `Anchor` dataclass + `song_t_from_audio_t(anchor, audio_t)` function. Pure, no side effects.
- `webui/webui/audio_backend/stream.py` — `AudioSession` class:
  - Owns a single `sd.OutputStream`.
  - Methods: `open(device_index, samplerate, exclusive)`, `close()`, `load_source(path)`, `play()`, `pause()`, `seek(song_t)`.
  - PortAudio callback: reads from a pre-resampled float32 buffer, advances `play_offset`, updates anchor on play/seek/loop-wrap.
  - Resampling: `soxr.resample(audio, src_rate, dst_rate, quality='HQ')`; cached float32 stereo.
  - MP3 decode: `soundfile.read(path, dtype='float32')` — confirmed working since soundfile 0.11.0.
  - Source MP3 mono-or-stereo handling: replicate mono to stereo with `np.broadcast_to` before resampling.

### Files to modify

- `webui/webui/audio_backend/ws.py` — implement `load`, `play`, `pause`, `seek`, `set_device`, `set_mode` ops; emit `state` and 40 Hz `clock` ticks via an asyncio task.
- `webui/webui/audio_backend/protocol.py` — add the new message models.
- `webui/webui/server.py` — add a FastAPI `lifespan` handler that closes the active `AudioSession` on app shutdown. **Don't rely solely on atexit** (research finding — atexit fires after asyncio loop closure and can race with pending WS sends).
- `webui/static/js/audio/wasapi-engine.js` — implement the full `AudioEngine` contract. `currentTime` uses rAF extrapolation with soft-slew.
- `webui/static/js/audio/engine-factory.js` — switch logic for live engine swap.

### Implementation notes — clock sync (the heavy bit)

The PortAudio callback signature is:

```python
def callback(outdata, frames, time_info, status):
    # time_info.outputBufferDacTime is the estimated DAC time of the first
    # sample in outdata, in the stream-internal monotonic clock domain.
    # Use it (not stream.time) for the anchor update on a play() that
    # starts inside this very block.
```

**Anchor update rules:**
- On `play()`: schedule `stream.start()`, capture `time_info.outputBufferDacTime` from the first callback that fires after `play()`, set `anchor = Anchor(song_t=pause_offset, audio_t=that_dac_time)`.
- On `pause()`: read `stream.time` immediately, freeze `last_song_pos = anchor.song_t + (stream.time - anchor.audio_t)`, stop the stream.
- On `seek(t)`: pause, set `pause_offset = t`, play.
- On loop wrap (Phase 5): inside the callback, after the wrap split, set `anchor = Anchor(song_t=loop_start_sample / sr, audio_t=time_info.outputBufferDacTime + (wrap_position_in_block / sr))`.

**Clock-tick coroutine:**

```python
async def _tick_loop(self):
    while self._stream is not None and self._stream.active:
        if self._playing:
            song_t = self._anchor.song_t + (self._stream.time - self._anchor.audio_t)
            await self._ws.send_json({
                "type": "clock",
                "song_t": song_t,
                "audio_t": self._stream.time,
                "perf_t_server": time.perf_counter(),
                "playing": True,
            })
        await asyncio.sleep(0.025)
```

The coroutine reads `self._stream.time` from outside the callback — sounddevice docs confirm this is valid for the life of the stream. Guard with `if self._stream.active` (research finding: `stream.time` after close is undefined).

**Client extrapolation (`wasapi-engine.js`):**

```js
get currentTime() {
  if (!this._playing) return this._lastSongPos;
  const now = performance.now() / 1000;
  return this._anchorSongT + (now - this._anchorPerfNow);
}

_onClockTick(msg) {
  const arrivePerf = performance.now() / 1000;
  const extrap = this._anchorSongT + (arrivePerf - this._anchorPerfNow);
  const delta = msg.song_t - extrap;
  if (Math.abs(delta) > 0.030) {
    // hard re-anchor: seek, loop wrap, or first tick after play
    this._anchorSongT = msg.song_t;
    this._anchorPerfNow = arrivePerf;
  } else {
    // soft slew: absorb half the delta now
    this._anchorSongT = msg.song_t - delta * 0.5;
    this._anchorPerfNow = arrivePerf;
  }
  this._lastSongPos = msg.song_t;
  this._emit("time", msg.song_t);
}
```

### Tests (parallel via subagent)

`webui/tests/test_audio_clock.py`:
- Construct an anchor at `(song_t=10.0, audio_t=100.0)`. Assert `song_t_from_audio_t(anchor, 100.5) == 10.5`.
- Reset anchor on a simulated seek. Assert continuity.
- Loop-wrap simulation: given a wrap at `loop_end=15.0` with block crossing it, assert the post-wrap anchor produces `song_t == loop_start + remainder`.

`webui/tests/test_audio_stream.py`:
- Mock `sd.OutputStream`. Drive the callback with synthetic `time_info` and assert `play_offset` advances by `frames` per call.
- Assert seek resets `play_offset` to the new sample.
- Assert pause stops calling the callback (mock should not be invoked).

`webui/tests/test_audio_ws_protocol.py` (extend):
- Send `load`, then `play`, assert receipt of `state {playing:true}` and at least one `clock` message within 50 ms.

### Phase 2 acceptance

Manual:
- [ ] Load `baleen_unmedicated`. Switch to WASAPI engine. Hit play.
- [ ] Audio plays through the BEHRINGER FLOW 8 (or default output) via WASAPI Shared.
- [ ] Cursor moves smoothly — no visible stutter at zoom = 200 px/sec for the full track.
- [ ] Seek by clicking the scrub bar: cursor jumps and audio follows; no glitch sound on resume.
- [ ] Pause + replay-from-end + replay-from-middle all work.
- [ ] Switching back to WebAudio mid-track works (track restarts on the WebAudio engine).
- [ ] Page refresh while playing: server stops the stream on WS disconnect; no orphaned audio.
- [ ] Warm-cache load of the resampled buffer completes in < 3 s.
- [ ] `pytest tests/test_audio_*.py -v` all green.
- [ ] `feature-dev:code-reviewer` returns no high-priority findings.

Latency measurement (optional but recommended):
- [ ] Patch headphone-out into mic-in. Generate a click track via the source MP3. Measure click-to-sample latency. Target: < 50 ms WASAPI Shared. (Real number worth recording in the spec for future comparison.)

## Phase 3 — Stem mixing (~1 day)

**Goal**: full parity with WebAudio engine — six stems mixable with mute/solo/volume, mode toggle works.

### Files to modify

- `webui/webui/audio_backend/stream.py` — extend `AudioSession`:
  - `load_stems(stem_paths: dict[str, Path])` — load and resample all six stems to device rate; cache float32 stereo.
  - Per-stem `gain: float`, `target_gain: float`, `muted: bool`, `soloed: bool`.
  - One-pole gain smoothing: `α = 1 - exp(-frames / (sr × 0.010))` (10 ms time constant; identical to `setTargetAtTime(_, _, 0.01)` in WebAudio).
  - Callback uses `np.multiply` + `np.add` in-place; **no allocations in steady state**. Pre-allocate `out`, `tmp`, `mix_accumulator`.
  - Mode `"source"` vs `"stems"` swap: changes which buffer set is being summed. Same anchor; no glitch.

- `webui/webui/audio_backend/ws.py` — handle `stem` op (`{name, vol, muted, soloed}`) and `set_mode` op.

- `webui/static/js/audio/wasapi-engine.js` — `setStemVolume`, `setStemMute`, `setStemSolo`, `setMode`, `getModeAvailability`, `getMode` — all ship WS ops; UI state mirrors are local-optimistic, server confirms via `state`.

### Implementation notes

- **No allocation in callback**: pre-allocate `_mix_buf = np.zeros((max_blocksize, 2), dtype=np.float32)` at stream open. Reuse it each callback. Same for `_tmp_stem`. Allocation in the callback (e.g., `np.zeros(frames, ...)`) is the #1 cause of underruns in real-time Python audio.
- **No logging in callback**: emit events via a `queue.SimpleQueue` (thread-safe, non-blocking) drained by the asyncio loop. The callback only ever does `_event_queue.put_nowait((kind, payload))` and never `await` / `logging` / `print` (research finding — sounddevice docs forbid these).
- **Mute/solo truth table** — copy from `web-audio-engine.js:194-201`:
  ```
  effective_gain = SOLO_DUCK if (muted or (any_soloed and not self.soloed)) else target_vol
  ```
- **Stem load happens off the audio thread**: when `load` op arrives, launch a background asyncio task that reads each WAV with `soundfile.read(dtype='float32')`, resamples with soxr HQ, then atomically swaps the new buffers into the AudioSession. The callback continues playing source mode until the swap completes; then on the next `play()` after stems are ready, stems mode is available.
- **Stem rate vs. device rate** — read each stem's rate from `soundfile.info(path).samplerate` (memory note `audio_stem_cache_format`). Do not assume 44.1 kHz; the corpus is currently 44.1 but different tracks could differ.

### Tests

Add to `test_audio_stream.py`:
- Gain smoothing: starting from `gain=0`, target `1.0`, after a 480-sample callback @ 48 kHz (10 ms), assert `gain > 0.6` (one time-constant) and `< 1.0`.
- Mute toggle: with `target_vol=1.0`, set `muted=True`; after one callback, assert `gain < 0.1` (ramp toward 0).
- Solo truth table: 6 stems; solo vocals; assert all other stems' effective gain drops to SOLO_DUCK; vocals stays at its target.

### Phase 3 acceptance

- [ ] Stem mute/solo/volume sliders in the sidebar mixer behave identically to WebAudio engine.
- [ ] Mode toggle between source and stems works mid-playback with no audible glitch.
- [ ] No clicks on mute/unmute (10 ms ramp working).
- [ ] No allocations in the steady-state callback — verify by `tracemalloc.start(); play 10 s; tracemalloc.get_traced_memory()` shows < 1 MB delta.
- [ ] All existing tests + new tests pass.

## Phase 4 — WASAPI Exclusive + fallback chain (~0.5 day)

**Goal**: Exclusive mode works on supported devices; clean fallback to Shared on failure; clean fallback to WebAudio on total failure.

### Files to modify

- `webui/webui/audio_backend/stream.py`:
  - `AudioSession.open(...)` takes `exclusive: bool`. If True, pass `extra_settings=sd.WasapiSettings(exclusive=True)` to `sd.OutputStream`.
  - Try-except around `stream.start()`. On `sd.PortAudioError` with the device-in-use code (`-9985 paDeviceUnavailable`) or `paInvalidSampleRate (-9997)`, raise `ExclusiveUnavailable(device, reason)`.
  - `AudioSession.open_with_fallback(...)` wrapper: try Exclusive → fall back to Shared → fall back to MME → raise `EngineUnavailable`.

- `webui/webui/audio_backend/ws.py` — on `EngineUnavailable`, emit `{type:"error", code:"engine_unavailable", fallback:"webaudio"}`. UI catches and reverts.

- `webui/static/js/audio/wasapi-engine.js` — on `engine_unavailable`, dispose self and emit `engineFailed` so `engine-factory.js` swaps to WebAudio.

- `webui/static/js/audio/engine-factory.js` — listen for `engineFailed`, swap engines in place, show toast: "WASAPI Exclusive unavailable for {device}; falling back to {Shared|WebAudio}."

### Implementation notes

- **Bluetooth heuristic**: not worth detecting form factor (not surfaced by sounddevice). Just catch the error and show a useful message.
- **Preemption**: if another app holds Exclusive *and* "Give exclusive-mode applications priority" is on, our Exclusive grab will preempt them. The toast wording should not promise to never preempt — Windows handles the contention, we just show what happened.
- **Sample-rate auto-negotiation**: do NOT pass `auto_convert=True` for Exclusive (defeats the purpose). If the device's current rate doesn't match the stem rate, the resampler in Phase 3 handles it.

### Tests

- Mock `sd.OutputStream` to raise `PortAudioError(-9985)` on first open with `exclusive=True`. Assert `open_with_fallback` retries with Shared and succeeds. Assert no double-close.
- Same with `-9997` — assert the same fallback path.
- Assert the WS `error` message carries the right `code` and `fallback` fields.

### Phase 4 acceptance

- [ ] Select Exclusive mode for the BEHRINGER FLOW 8; audio plays.
- [ ] Open Foobar2000 (or any other app) in Exclusive on the same device; switch webui to WASAPI Exclusive; observe clean fallback to Shared with toast.
- [ ] Disconnect the device entirely; assert the engine falls back to WebAudio with a clear toast.
- [ ] Measure Exclusive latency (mic loopback); record number in the spec. Expected: ~10–20 ms on FLOW 8.
- [ ] All tests pass; reviewer happy.

## Phase 5 — Loop wrap + polish (~0.5 day)

**Goal**: sample-accurate loop wraps inside the audio callback; hotplug-refresh button; latency display in Settings.

### Files to modify

- `webui/webui/audio_backend/stream.py`:
  - `set_loop(start_song_t, end_song_t)` / `clear_loop()`.
  - Callback splits a block when `play_offset` crosses `loop_end_sample`: write `[play_offset:loop_end_sample]` first, then re-anchor and write `[loop_start_sample:loop_start_sample + remainder]` into the same block.
  - Anchor update on wrap: `anchor = Anchor(song_t=loop_start_song_t, audio_t=time_info.outputBufferDacTime + (samples_before_wrap / sr))`.

- `webui/webui/audio_backend/ws.py` — `loop` and `loop_clear` ops.
- `webui/webui/audio_backend/devices.py` — add `refresh_devices()` that calls `sd._terminate(); sd._initialize()` and re-enumerates (research finding).
- `webui/static/js/audio/wasapi-engine.js` — `setLoop`/`clearLoop` ship WS ops.
- `webui/static/js/audio/device-picker.js` — "Refresh devices" button calls `refresh_devices` op.
- `webui/static/js/ui/menus.js` — display `stream.latency` from the most recent `loaded` message in the device-picker section.

### Tests

`test_audio_clock.py`:
- Loop split inside a 512-sample block: `play_offset = loop_end - 100`, write a 512-frame block, assert exactly 100 frames written from pre-loop region and 412 frames from post-loop region; assert anchor `song_t == loop_start`.

`test_audio_stream.py`:
- Set loop, play through wrap, assert no allocations in the callback during the wrap.

### Phase 5 acceptance

- [ ] Set a loop region. Play through it. Loop wraps sample-accurately (no audible click; cursor wraps at exactly `_loopEnd`).
- [ ] Pull a USB device, click Refresh devices, plug it back, click Refresh — device reappears.
- [ ] Settings shows actual `stream.latency` (e.g., "Output: 48 kHz · 192 frames · 4.0 ms buffer").
- [ ] All tests pass; reviewer happy.
- [ ] Update `webui/CHANGELOG.md` with the feature entry.

## Cross-cutting concerns

### Tests overall

- All new tests live under `webui/tests/test_audio_*.py`.
- Use `httpx.AsyncClient` for FastAPI; `pytest-asyncio` is already in `requirements.txt`.
- WS tests use `httpx`'s WebSocket support OR import `websockets` directly if simpler.
- Mock `sd.OutputStream` everywhere — don't open real PortAudio in CI. (Memory-only PortAudio is not portable.)
- A *single* manual smoke-test script `webui/scripts/smoke_audio.py` opens a real stream on the local default device, plays 500 ms of silence, asserts callback ran. Documented as manual, not run in CI.

### Documentation

- After Phase 5, write `webui/README.md` updates (or `webui/docs/audio.md`) covering: how to switch engines, how to pick a device, the smooth-playhead architecture, known limitations (Bluetooth Exclusive).
- Update `webui/CHANGELOG.md` per phase.

### Memory updates after completion

After Phase 5 ships, write one final project memory:
- `wasapi_engine_v1_shipped.md` — type: project. Body: shipped 2026-MM-DD. Key non-obvious facts to remember: callback uses `time_info.outputBufferDacTime` not wall-clock; soft-slew threshold is 30 ms; `_NoCacheDevMiddleware` passes WS through unmodified; sounddevice's `_terminate()/_initialize()` is required for hotplug refresh.

## Verification gates between phases

Do **not** start phase N+1 until phase N's acceptance checklist is fully green. If a checklist item is impossible (e.g., user has no second app to test Exclusive preemption), document the deferral in the spec's "verified vs. deferred" appendix and proceed only with user signoff.

After every phase:
1. Run `pytest webui/tests/ -v` — full suite must be green.
2. Run `feature-dev:code-reviewer` on the diff; address any high-priority findings before declaring done.
3. Commit to main with conventional-commit prefix (`feat(audio)`, `test(audio)`, etc.). User commits straight to main on this project.
4. Restart webui via `webui/webui.ps1 restart` and verify the UI loads cleanly. Check `webui/webui.log.err` for stack traces.

## Don'ts (guardrails)

- **Do not** try to surface the Windows endpoint GUID. PortAudio doesn't expose it; doing it via raw ctypes to `MMDeviceEnumerator` is out of scope.
- **Do not** use `auto_convert=True` on `WasapiSettings` for Exclusive. It defeats the bit-perfect contract.
- **Do not** allocate, log, or `print` inside the PortAudio callback. Use a queue + an asyncio drainer.
- **Do not** persist `device_index` to localStorage. Persist `(hostapi, name, exclusive, samplerate)`.
- **Do not** assume any track's stems are 44.1 kHz. Read the WAV header.
- **Do not** ship Phase 4 without manual Exclusive testing on the real BEHRINGER FLOW 8 hardware — the research surfaced that USB-class device behavior is driver-dependent, and `check_output_settings` is not the same as `start()`.
- **Do not** modify `WebAudioEngine`. The contract is the contract; the new engine is a parallel implementation.
- **Do not** create a new branch. User commits straight to main.
- **Do not** bypass the verification gates. Each phase ships independently and reversibly via the localStorage flip.

## Effort estimate

| Phase | Estimate | Notes |
|---|---|---|
| 0 — Pre-flight spec edits + memories | 30 min | Mechanical |
| 1 — Device picker scaffold | 0.5 day | + parallel tests |
| 2 — Shared playback (source mode + clock sync) | 1.5 days | The heavy bit |
| 3 — Stem mixing | 1 day | |
| 4 — Exclusive + fallback | 0.5 day | |
| 5 — Loop + polish | 0.5 day | |
| **Total** | **~4 days focused** | With ~1 day of tests in flight |

## Cited evidence

Every load-bearing claim in this plan traces back to either:
- `docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` (the spec — decisions)
- `docs/superpowers/specs/2026-05-12-wasapi-research-findings.md` (the research — evidence with URLs)

Do not invent new facts. If a phase surfaces a claim not covered in either doc, stop and run a targeted research subagent before proceeding.
