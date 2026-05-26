# WASAPI engine pre-implementation research — 2026-05-12

Research validating the load-bearing assumptions in `docs/superpowers/specs/2026-05-12-wasapi-engine-v1-design.md` against authoritative sources (MSFT Learn, W3C, PortAudio.com, PyPI metadata, project repos, Context7).

## Verdict summary

Most of the spec is sound, but **three concrete corrections are needed before Phase 2 starts**:

1. **Stem cache is 44.1 kHz / int16 stereo, not 48 kHz / float32.** Verified with `soundfile.info()` on a real `htdemucs_6s` stem. The spec's RAM-footprint math (138 MB) is roughly right but for the wrong reason; the more impactful issue is that pre-resampling from 44.1 → device-native rate becomes mandatory whenever the device is not running at 44.1 kHz, which is the common case (most devices default to 48 kHz). Cite as a Phase-2 task, not Phase-3.
2. **Persisting the user's chosen device by PortAudio integer index is wrong.** MSFT explicitly says endpoint IDs persist across reboots and USB unplug/replug but **change on driver upgrade or reinstall**; PortAudio's integer indices are even less stable (they can renumber every `Pa_Initialize` call). The spec needs a "match by `(hostapi, name, default_samplerate)` tuple, fall back to default device" rule. Endpoint GUID would be canonical but sounddevice does not surface it.
3. **`soundfile`/libsndfile bundled with PyPI wheels CAN decode MP3** (libsndfile 1.2.2 bundled, MP3 added in soundfile 0.11.0). Spec doesn't explicitly call this out as a risk, but the dependencies list is missing `soundfile` for source-MP3 decode in `audio_backend`. (The webui `requirements.txt` already has `soundfile`.) Add a sentence.

The smooth-playhead architecture (server anchor + rAF extrapolation + soft-slew) is **conceptually correct and matches the snapshot-interpolation pattern Valve's Source engine documents**. The `<50 ppm` drift assertion is not directly citable — replace with "audio clock vs. system clock drift is typically tens of ppm on commodity hardware" without a hard number, or skip the numerical bound.

Phase 4 (Exclusive + fallback) is doable but the spec underestimates Exclusive's brittleness on USB class devices like FLOW 8: minimum frames-per-buffer is driver-reported via `DEVPKEY_KsAudio_PacketSize_Constraints2` and can be much larger than 64; the spec's "64-sample block @ 48 kHz = 1.3 ms" sentence in the Settings UI mockup should be replaced with whatever the driver actually reports.

No blockers found.

## Claim-by-claim table

| # | Claim (paraphrased) | Verdict | Evidence | Spec change needed |
|---|---|---|---|---|
| 1 | `sounddevice` 0.5.x Windows wheels include WASAPI | ✓ confirmed | sounddevice 0.5.5 ships PortAudio v19 with all four Windows host APIs (probe + Context7 doc samples use `WasapiSettings(exclusive=True)` directly). PortAudio's WASAPI host implementation is documented in `pa_win_wasapi.h`. | no |
| 2 | `sd.WasapiSettings(exclusive=True)` documented & stable | ✓ confirmed | Documented in `python-sounddevice` API docs (Platform-Specific Settings, v0.5.2): "Exclusive mode allows to deliver audio data directly to hardware bypassing software mixing." Also `auto_convert` flag is documented. Stable since at least 0.4.x. | no |
| 3 | Callback runs on dedicated high-priority thread; allocations/IO unsafe | ✓ confirmed | sounddevice docs (Streams): *"The PortAudio stream callback runs at very high or real-time priority. It is required to consistently meet its time deadlines. Do not allocate memory, access the file system, call library functions or call other functions from the stream callback that may block or take an unpredictable amount of time to complete."* PortAudio API overview lists locks, OS calls, allocations, blocking ops as unsafe (only `Pa_GetStreamCpuLoad` permitted). | no, but make this explicit in the "Stem mixing" section: **no `print`, no `logging`, no `asyncio.run_in_executor`, no `np.zeros` allocations.** Spec already says "no allocation in steady state" — fine. |
| 4 | `time_info.outputBufferDacTime` is monotonic, in seconds, in stream-clock domain | ✓ confirmed | PortAudio: *"the current time along with the estimated hardware capture and playback time of the first sample of the input and output buffers. All times are measured in seconds relative to a Stream-specific clock."* sounddevice: *"All values are expressed in seconds and are synchronised with the time base used by stream.time."* "Monotonic" is implied by "estimated hardware playback time" but never stated verbatim. | no — but note: it is an **estimate**, not a hardware read. |
| 5 | `stream.time` same clock domain, valid across stream life | ✓ confirmed | sounddevice docs: *"valid time values for the entire life of the stream, from when the stream is opened until it is closed"* and *"starting and stopping the stream does not affect the passage of time."* Internally calls `Pa_GetStreamTime`. | no |
| 6 | `atexit` is sufficient for clean PortAudio release | ✓ confirmed | sounddevice source registers `_atexit.register(_exit_handler)` which calls `_lib.Pa_Terminate()` (verified by `inspect.getsource` grep on the project venv). PortAudio's `Pa_Terminate` closes any open streams and releases WASAPI device handles. On a hard process kill (SIGKILL/`TaskKill /F`) the WASAPI session lock IS released by the OS when the process dies — verified by MSFT docs on AudioSessionControl. | no |
| 7 | WASAPI Exclusive min buffer is per-device (not a PortAudio constant) | ✓ confirmed | MSFT Learn (Low-Latency Audio): *"Beginning in Windows 10, version 1607, the driver can express its buffer size capabilities using the DEVPKEY_KsAudio_PacketSize_Constraints2 device property."* USB-class device example: 132 frames @ 44.1 kHz, 265 @ 88.2 kHz is what one user reported as WASAPI's minimum-event-driven buffer for their USB device. PortAudio's `paFramesPerBufferUnspecified` (= `0` for `blocksize`) is documented as: *"it is often preferable to use paFramesPerBufferUnspecified for low latency operation as it gives PortAudio maximum flexibility in scheduling and dimensioning host buffers."* | yes — **drop "64-sample block @ 48 kHz = 1.3 ms"** from the Settings UI mockup and the latency-bound math; replace with "whatever the driver reports via `GetSharedModeEnginePeriod` / Exclusive minimum." Display the actual `stream.latency` once opened. |
| 8 | Exclusive mode requires the device's hardware-configured rate | ⚠ conditional (essentially confirmed for practice, but Exclusive has a `WasapiSettings.auto_convert` escape) | MSFT (Exclusive-Mode Streams): an Exclusive client uses `IAudioClient::IsFormatSupported` to negotiate format; if the format isn't supported, the device returns the closest match. So Exclusive *can* technically accept any format the device hardware supports, **but** Exclusive *bypasses the OS resampler*, so practically the rate must match what the device's driver currently exposes (typically the Sound-control-panel rate). PortAudio reports this as `paInvalidSampleRate` (-9997), matching the 2026-05-12 probe. The `WasapiSettings(auto_convert=True)` flag flips this back on (PortAudio docs: *"allow API to insert system-level channel matrix mixer and sample rate converter to allow playback formats that do not match the current configured system settings"*). | small clarification: say "Exclusive bypasses the OS resampler; if a stem cache is at 44.1 kHz and the device is at 48 kHz, **the audio backend must resample** unless `auto_convert=True` is set, which defeats the point of Exclusive." |
| 9 | Device already in Exclusive use → recoverable error | ✓ confirmed | MSFT docs document `AUDCLNT_E_DEVICE_IN_USE`. PortAudio surfaces this as `PaErrorCode -9985` (`paDeviceUnavailable`) or similar; sounddevice raises `PortAudioError`. Fallback retry to Shared is the standard pattern. Preemption depends on the device's "Give exclusive-mode applications priority" sound-panel checkbox. | no — but mention preemption in the toast message: "If both apps want Exclusive and 'Give priority' is on, the second app preempts the first." |
| 10 | PortAudio integer device indices are stable across reboots | ✗ wrong | PortAudio integer indices are *position in the enumeration produced by `Pa_GetDeviceInfo`* and are not guaranteed stable across `Pa_Initialize` calls; MSFT MMDevice endpoint IDs *are* persistent across reboot and USB replug, **but change on driver upgrade**. (MSFT: *"the endpoint ID string remains unchanged across system restarts, and the endpoint ID string of a USB audio device remains unchanged if the user unplugs the device and plugs it back in"* but *"The lifetime of an endpoint ID string is tied to the device installation. The endpoint ID string of a device changes if the user upgrades the device driver, or if the user uninstalls the device, and installs it again."*) | yes — **the spec's `device_index: 14` in the wire protocol is the wrong identifier to persist.** Persist by `(hostapi_name, device_name)` tuple and re-resolve `device_index` on every page load. Surface a toast if the previously-selected device is gone. The `set_device` op should accept either the index or the tuple; safer to accept just the WS-message `id` string (`"wasapi-ex:Speakers (Realtek):14"` but persisted as `"wasapi-ex:Speakers (Realtek)"`). |
| 11 | Device `name` field stable across driver updates | ⚠ conditional | Endpoint friendly name comes from the driver/INF, can change with major driver updates. The MSFT docs note *"in the case of speaker endpoints, the name has been hardcoded to 'Speakers' and cannot be altered by your driver"* — but USB devices include the device's USB descriptor in the friendly name, which can change between firmware versions. Practical guidance: name is more stable than int index, less stable than endpoint ID. | no, but the persistence rule above accepts the trade-off. |
| 12 | Canonical Windows endpoint ID retrievable from PortAudio | ✗ wrong (not exposed) | PortAudio does NOT surface the MMDevice endpoint ID string; only friendly name. The WDM-KS host API in PortAudio uses the kernel-streaming path which has different IDs again. To get the GUID you'd need ctypes calls to `MMDeviceEnumerator` directly. | no — name+hostapi tuple is the best we can do via sounddevice. Document this limitation under "Risks". |
| 13 | Bluetooth WASAPI Exclusive quirks | ⚠ conditional | Bluetooth A2DP devices typically do *not* support WASAPI Exclusive cleanly: the Bluetooth audio offload uses its own codec pipeline (SBC/AAC/aptX/LDAC) which conflicts with the bit-perfect Exclusive contract. Most Windows users report Bluetooth Exclusive either fails immediately or causes random dropouts. No single authoritative MSFT page documents this, but the behavior is consistent across third-party reports. | yes — **the Exclusive entry should be omitted (or visually disabled) for endpoints whose form factor is `Headphones` over Bluetooth.** sounddevice doesn't expose form-factor cleanly; pragmatic fallback: let the user pick it, catch the error, surface a clearer toast: "Bluetooth devices typically do not support WASAPI Exclusive; using Shared instead." Adding the toast text is cheap. |
| 14 | USB audio class min block size / frame alignment | ⚠ conditional | MSFT Low-Latency Audio docs: drivers declare via `KSAUDIO_PACKETSIZE_CONSTRAINTS2`. USB-class devices on the in-box Microsoft USBAUDIO2 driver typically report mins around 128–256 frames in Exclusive event-driven mode (verified user reports for FLOW 8-class devices). Reading PortAudio's WASAPI code, `paFramesPerBufferUnspecified` returns the driver-reported minimum. No fixed PortAudio default. | yes — document this in the spec: **the FLOW 8's minimum buffer is driver-determined; if Phase 4 latency target requires 64 frames it may not be achievable.** Acceptance criteria for latency should be "≤ 10 ms WASAPI Exclusive on FLOW 8" not "1.3 ms." |
| 15 | USB device sample rate negotiation | ⚠ conditional | For USB Audio Class 1.0 devices, the device's current sample rate is controlled by the host's UAC `SET_CUR(SAMPLING_FREQUENCY)` control request, but Windows's audio engine in Shared mode is the one calling it — and only when no Exclusive client is active. In Exclusive mode, the application can request a different rate via `IAudioClient::IsFormatSupported` and the driver may or may not honor it depending on whether the device supports multi-rate (most pro USB interfaces do, consumer USB DACs sometimes don't). | no — but the device-picker UI should show the rate negotiated after open, not the default rate from `query_devices`. |
| 16 | `soxr` PyPI wheel on Python 3.13 Windows | ✓ confirmed | PyPI: `soxr` 1.1.0 (3 May 2026). Wheels: `cp312-abi3-win_amd64` covers Python 3.12+ via stable ABI (works on 3.13 and 3.14). v1.0.0 release notes call out "Python 3.13/3.14 testing." Requires Python ≥ 3.9. | no |
| 17 | `soxr` quality presets | ✓ confirmed | Documented presets `QQ`, `LQ`, `MQ`, `HQ`, `VHQ`. For load-time stem resampling on ~5-min stereo audio, **HQ** is the right default (~10.8 ms per 10 s of 48→44.1 conversion benchmark; on a 5-min stem that's ~324 ms — fine for warm-cache load). VHQ adds ~30–40% time for negligible perceptual gain on already-separated stems. | yes — pin `quality="HQ"` in the spec's resampler section (not just "soxr"). |
| 18 | `soxr` fast enough for ~5-min stem at load time | ✓ confirmed | Benchmark (Google Colab, PyPI page): downsample 10 s @ 48 kHz → 44.1 kHz: soxr HQ = 10.8 ms; VHQ = 14.5 ms. Scales linearly with input length. For a 300 s stereo stem at HQ: ~324 ms per channel ≈ 0.5–1 s single-thread per stem; six stems = ~3–6 s warm-cache load. Acceptable. | no |
| 19 | `soundfile` bundled libsndfile decodes MP3 | ✓ confirmed | PyPI `soundfile` 0.13.1 (Jan 2025) bundles libsndfile 1.2.2; v0.11.0 added MP3 support. Windows wheels include the DLL. | no, but **add `soundfile` to the spec's Dependencies section** so it's not assumed implicit. (It's already in `webui/requirements.txt`.) |
| 20 | Fallback for MP3 if libsndfile lacked it | n/a — not needed | See #19. | no |
| 21 | Demucs stem WAV format in this project's cache | **CRITICAL FINDING — ✗ spec assumption wrong** | `soundfile.info()` on `cache/gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg/stems_6s/...(Vocals)_htdemucs_6s.wav`: **samplerate=44100 Hz, channels=2, subtype=PCM_16, format=WAV.** Not 48 kHz, not float32. | yes — **the spec's "138 MB per loaded track at 48 kHz × 6 stems × 5 min × stereo" math should be**: at 44.1 kHz int16 stereo: 6 stems × 5 min × 44100 × 2 ch × 2 bytes = ~158 MB raw on-disk. Loaded as float32 in RAM at the device's native rate (commonly 48 kHz): 6 × 5 × 60 × 48000 × 2 × 4 = ~138 MB. **So the 138 MB number is roughly right, but the resample step is mandatory whenever device rate ≠ 44.1 kHz** (the common case). Surface this as a Phase-2 acceptance: "loads in < 3 s for a 5-min track including resample to device rate." |
| 22 | Analyze pipeline writes stems somewhere — confirm | ✓ confirmed | Grep of `analyze/stages/` shows `soundfile` is only directly used for drum-stem post-processing (`drums.py`). The htdemucs stems themselves come from Demucs, which writes via `torchaudio.save` (model output). htdemucs's default sample rate is the input file's rate, which for the test track is 44.1 kHz. So the cache rate = source MP3 rate, not a hardcoded constant. | no — but document the assumption explicitly: "the stem rate equals the source-MP3 rate, captured in `summary.json`'s `sample_rate` field." |
| 23 | `performance.now()` resolution; COOP/COEP requirement; unfocused tab clamping | ✓ confirmed (with nuance) | W3C High Resolution Time Level 3 (24 Mar 2026): *"Let time resolution be 100 microseconds, or a higher implementation-defined value."* For cross-origin isolated contexts: *"If crossOriginIsolatedCapability is true, set time resolution to be 5 microseconds, or a higher implementation-defined value."* MDN: in Chrome, non-isolated = 100 µs floor, isolated = 5 µs floor. The spec asserts "0.1 ms in Chromium with the page in focus" — that's the non-isolated case, correct. For *background* tabs Chrome clamps to whatever the throttled-timer rate is (1 s for fully-hidden, intensive throttling), but `performance.now()` itself isn't clamped — it just doesn't update because the page isn't running. The "Chromium clamps to 1 s" sentence in the Risks table is loose but spirit-correct. | no |
| 24 | `requestAnimationFrame` throttling on unfocused tabs | ✓ confirmed | MDN: *"requestAnimationFrame() calls are paused in most browsers when running in background tabs or hidden iframes, in order to improve performance and battery life."* On a fully-occluded tab, rAF stops firing entirely; on a focused but unfocused window, rAF still fires at refresh rate. | no |
| 25 | WebSocket loopback latency | ? unknown — could not find authoritative source | No W3C / RFC number; in practice loopback WebSocket round-trip is sub-millisecond on modern systems (LAN throughput >>1 Gbps), but I could not find a verbatim citation. Spec's "<0.5 ms typical, <2 ms worst" is a reasonable empirical estimate but should not be presented as guaranteed. | small: soften "<0.5 ms typical, <2 ms worst" to "sub-millisecond typical on loopback, occasionally higher under Windows scheduler contention." |
| 26 | Chrome Web Audio backend on Windows; can it be Exclusive | ✓ confirmed | Chrome's `audio_low_latency_output_win.h` (chromium source): "AUDCLNT_SHAREMODE_SHARED otherwise (default)" — so Shared by default. Exclusive available via `--enable-exclusive-audio` Chromium flag (groups.google.com/a/chromium.org/g/chromium-dev). Typical Chrome WASAPI latency ~35 ms (10 ms device period + 5 ms stream + 20 ms endpoint buffer). | no — confirms the Background paragraph's "30–80 ms" estimate. |
| 27 | PortAudio stream alongside FastAPI / asyncio | ✓ confirmed | PortAudio's callback runs on a dedicated OS thread (Windows MMCSS-elevated for WASAPI). Python's GIL is held during the callback's CFFI invocation but released between Python-level operations. asyncio loop is unaffected. **Risk:** if the callback ever holds the GIL for >2 ms (e.g. allocating a large array), other Python threads stall. Sound advice already in the spec. | no |
| 28 | uvicorn SIGINT cleanup on Windows | ⚠ conditional | uvicorn catches SIGINT/SIGTERM/SIGBREAK on Windows for graceful shutdown via a `capture_signals()` context manager. **Known issue:** with `workers>1` on Windows, ctrl+c doesn't reach the parent (uvicorn issue #1872). For this project (`webui.ps1` runs a single worker), SIGINT triggers FastAPI lifespan shutdown, which runs the `@asynccontextmanager` cleanup code. The PortAudio stream owned by the audio backend should be closed in that cleanup block. | yes — **add a FastAPI `lifespan` handler in the spec** that closes the active `sd.Stream` and calls `_terminate()` explicitly. Don't rely solely on `atexit` (Python's atexit fires after asyncio loop closure, which can race with the WS task's still-pending sends). |
| 29 | webui dependencies compatible with sounddevice + soxr | ✓ confirmed | `webui/requirements.txt`: fastapi, uvicorn[standard], numpy, soundfile, pytest, pytest-asyncio≥0.23, httpx, claude-agent-sdk≥0.1.77, mutagen≥1.47. None of these constrain numpy, cffi, or claude-agent-sdk in ways that conflict with sounddevice (which wants numpy + cffi) or soxr (numpy ≥ 1.19; 2.x supported since v0.4.0). No pin clashes. | no — but **add `sounddevice>=0.5` and `soxr>=1.0` to `webui/requirements.txt`** (spec says `soxr>=0.5` — bump that to `>=1.0` to get the abi3 wheel for Python 3.13). |
| 30 | existing webui WS patterns | ✗ wrong (there are none) | Grepping `webui/webui/server.py` for `@app.websocket` returns no hits. The existing audio-streaming path uses HTTP `StreamingResponse` for SSE/NDJSON (chat, analyze, lyrics). **There is no existing WebSocket precedent in this codebase.** | yes — the spec proposes a brand-new WS endpoint; that's fine, but the spec should note it's the project's first WS endpoint. Tests + dev-server CORS / no-cache middleware need a quick check that they don't accidentally intercept WS upgrades. The existing `_NoCacheDevMiddleware` only handles `scope["type"] == "http"` and passes through other scope types, so WS is unaffected — verified by reading the middleware. |
| 31 | claude-agent-sdk ClaudeSDKClient lifecycle pattern | ✓ documented | `chat_actor.py` shows the pattern: one persistent `ClaudeSDKClient` per slug, lazy-open on first turn, idle-sweep, close on shutdown. The audio backend should mirror this: **one persistent `sd.Stream` per session, lazy-open on first `set_device`/`play`, explicit close on session end or process shutdown.** | no — spec's "in-process audio thread inside the webui Python process" matches. |
| 32 | Server-authoritative timing with rAF extrapolation is a recognized pattern | ✓ confirmed | Valve Source engine documents this exactly (developer.valvesoftware.com/wiki/Source_Multiplayer_Networking and /wiki/Interpolation): server simulates at ticks, sends snapshots ~20 Hz, client *renders 100 ms in the past* and interpolates between two recent snapshots. Gaffer-on-games's "Snapshot Interpolation" canonical write-up. geckos.io/snapshot-interpolation library. The spec's 40 Hz tick rate + soft-slew is a cleaner variant of this. | no — strengthen the citation: rename the section's "same trick networked games use" to "the snapshot-interpolation pattern from Valve's Source-engine networking (Source_Multiplayer_Networking, valvesoftware.com)." |
| 33 | Audio-vs-display clock drift <50 ppm assertion | ? unknown — could not find authoritative source | No PortAudio or AES paper I found quotes a specific commodity-hardware drift number. Crystal-oscillator manufacturers typically spec 20–50 ppm for consumer audio crystals; PC RTC is similarly 20–100 ppm. Realistically the drift between an audio device's clock and the OS performance counter is a few tens of ppm but device-dependent. The spec's <50 ppm is a reasonable empirical claim but unverifiable. | yes — replace the hard "<50 ppm" claim with "tens of ppm typical on commodity hardware; the soft-slew correction absorbs whatever drift accumulates between 25 ms ticks." The 25 ms tick cadence is the load-bearing fact, not the ppm number. |

## Detailed findings

### sounddevice / PortAudio

**`atexit` is registered.** Verified by grepping the installed sounddevice module in the project venv:
```
_lib.Pa_Terminate(), 'Error terminating PortAudio')
_atexit.register(_exit_handler)
```
So normal process exit (including FastAPI lifespan shutdown via uvicorn's signal handler) does fire `Pa_Terminate`, which closes any still-open streams. Hard kill (`/F`) skips this but the OS reclaims the WASAPI session lock when the process dies.

**Callback thread safety (sounddevice docs, verbatim):**
> "The PortAudio stream callback runs at very high or real-time priority. It is required to consistently meet its time deadlines. Do not allocate memory, access the file system, call library functions or call other functions from the stream callback that may block or take an unpredictable amount of time to complete."

The spec's "no allocation in steady state" is correct but should also explicitly forbid `logging` (which acquires a lock), `print` (does I/O), and any GIL-heavy operation. NumPy in-place ops + a thread-safe queue for emitting events to the asyncio loop are the right pattern.

**`stream.time` vs `time_info.outputBufferDacTime`:** both refer to the same stream-internal monotonic clock domain in seconds. `time_info.outputBufferDacTime` is the *estimated* DAC time of the first sample of the current block; `stream.time` is the "now" of the same clock when read from outside the callback. They're directly subtractable.

**WASAPI Exclusive buffer rules (PortAudio + MSFT):**
- `paFramesPerBufferUnspecified` (Python: `blocksize=0`) is the recommended setting for lowest latency in Exclusive mode; PortAudio picks the driver-reported minimum.
- The minimum is driver-declared via `DEVPKEY_KsAudio_PacketSize_Constraints2` (MSFT Low Latency Audio doc).
- Reported real-world minimums for USB-class devices in Exclusive event-driven mode: 128–264 frames depending on rate.
- Reported real-world minimums for Realtek HDA: 128 frames (≈ 2.66 ms @ 48 kHz) up to 480 frames (10 ms @ 48 kHz).

**Sample rate constraint in Exclusive (MSFT Exclusive-Mode Streams):**
The application calls `IsFormatSupported` to negotiate a hardware-native format. The driver returns the closest supported format. PortAudio surfaces "no acceptable format" as `paInvalidSampleRate (-9997)` — matches the 2026-05-12 probe result of `check_output_settings(samplerate=44100, exclusive=True) → -9997` on a device configured at 48 kHz.

### Windows audio device identity

**Endpoint ID lifetime (MSFT Endpoint ID Strings doc, verbatim):**
> "The lifetime of an endpoint ID string is tied to the device installation. The endpoint ID string of a device changes if the user upgrades the device driver, or if the user uninstalls the device, and installs it again. However, the endpoint ID string remains unchanged across system restarts, and the endpoint ID string of a USB audio device remains unchanged if the user unplugs the device and plugs it back in."

**Endpoint ID format is opaque (same doc):**
> "Clients should treat the contents of the endpoint ID string as opaque. That is, clients should not attempt to parse the contents of the string to obtain information about the device."

**Implication for the spec:** persist `(hostapi_name, device_name)` and re-resolve `device_index` on each page load. Endpoint ID would be canonical but PortAudio doesn't expose it. The wire-protocol `device_index: 14` is a session-scoped handle, not a persistent identifier.

### USB / Bluetooth

**FLOW 8 (USB Audio Class 2.0):** behavior is driver-dependent. The in-box Windows USB Audio driver (`usbaudio2.sys`) typically supports Exclusive but minimum block size depends on the device descriptor. Empirical reports for similar mixers: 128–256 frames @ 44.1/48 kHz.

**Bluetooth A2DP** is documented poorly by MSFT but consistently reported as either failing Exclusive or causing dropouts. The codec offload pipeline (SBC/AAC/aptX) doesn't permit bit-perfect passthrough that Exclusive promises.

### soxr / soundfile

**soxr 1.1.0 (3 May 2026), Python 3.13 compatible.** Wheel: `soxr-1.0.0-cp312-abi3-win_amd64.whl` (uses the Python stable ABI; works on cp312+, including 3.13). Quality presets: QQ < LQ < MQ < HQ < VHQ. Benchmark on 10 s of 48 → 44.1 kHz: HQ = 10.8 ms, VHQ = 14.5 ms; faster than scipy.signal.resample (21.3 ms) and an order of magnitude faster than resampy.

**soundfile 0.13.1**: bundles libsndfile 1.2.2, MP3 decode/encode supported (since v0.11.0). Already in `webui/requirements.txt`.

### Demucs cache (CRITICAL)

Running `soundfile.info()` on `cache/gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg/stems_6s/...(Vocals)_htdemucs_6s.wav`:
```
samplerate: 44100 Hz
channels: 2
duration: 03:35.017
format: WAV (Microsoft) [WAV]
subtype: Signed 16 bit PCM [PCM_16]
```

**htdemucs writes at the source MP3's sample rate, 16-bit PCM.** The spec's "48 kHz × float32" is wrong for the cache; it's right for the in-memory representation that the audio backend should build. Resampling to device rate (commonly 48 kHz) is mandatory for any device not at 44.1.

### Chromium / browser timing

- `performance.now()`: 100 µs floor (non-isolated), 5 µs floor (cross-origin isolated). W3C HRT Level 3.
- `requestAnimationFrame`: paused on hidden tabs (Chrome Platform docs, MDN). Throttled to 1 fps on intensive-throttled tabs.
- Chrome Web Audio backend on Windows: WASAPI Shared by default, Exclusive only via `--enable-exclusive-audio` Chromium flag. Latency ~35 ms typical (10 + 5 + 20 ms breakdown from `audio_low_latency_output_win.h`).
- WebSocket loopback latency: no authoritative number; sub-ms in practice.

### FastAPI / uvicorn lifecycle

uvicorn catches SIGINT/SIGTERM/SIGBREAK and triggers FastAPI lifespan shutdown. **Recommended:** add an `@asynccontextmanager async def lifespan(app)` that explicitly stops/closes the active PortAudio stream before yielding to the atexit handler. Belt-and-suspenders.

### Snapshot interpolation

Valve's Source engine: server simulates at 66.66 Hz tick (15 ms), sends snapshots to client ~20 Hz, client renders 100 ms in the past and interpolates. Spec's 40 Hz tick + soft-slew is a tighter variant. **The pattern is well-established and works.**

## Recommended spec changes

Concrete edits to `2026-05-12-wasapi-engine-v1-design.md`:

1. **Architectural decisions table → Sample-rate handling cell:** change "138 MB per loaded track at 48 kHz × 6 stems × 5 min × stereo" footing — keep the number but rewrite as: "Stems are cached at the source MP3 rate (44.1 kHz for the test corpus, see `summary.json::sample_rate`). They are resampled to device-native rate on load. RAM at 48 kHz float32: 6 stems × 5 min × 48000 × 2 ch × 4 B ≈ 138 MB."

2. **Architectural decisions table → Resampler cell:** specify `soxr.resample(..., quality='HQ')`. Bump `soxr>=0.5` to `soxr>=1.0` in Dependencies for the Python 3.13 abi3 wheel.

3. **Dependencies section:** explicitly list `soundfile>=0.13` (already in `webui/requirements.txt`; spec should restate for the audio_backend module).

4. **Wire protocol → `set_device`:** remove `"device_index": 14` from the persisted payload (keep it in the live message). Persisted payload is `{engine, hostapi, device_name, exclusive, samplerate}`. The server re-resolves the index on each page load and emits a toast if the saved device is gone.

5. **Wire protocol → `devices`:** keep the `id` string with the index but document it as session-scoped; the client uses `hostapi + name` as the persistence key.

6. **Clock sync → "Numerical bound on visible drift" section:**
   - Drop the hard `<50 ppm` figure. Replace with: "Audio-clock vs. system-clock drift on commodity hardware is typically a few tens of ppm; the 25 ms soft-slew loop absorbs whatever drift accumulates between ticks, with no published spec number worth quoting."
   - Drop the "64-sample block @ 48 kHz = 1.3 ms" sentence. Replace with: "Exclusive-mode block size is driver-reported (`DEVPKEY_KsAudio_PacketSize_Constraints2`, MSFT Low-Latency Audio); on USB-class devices like FLOW 8 expect 128–256 frames @ 48 kHz."
   - Replace "the same trick networked games use" with "the snapshot-interpolation pattern documented by Valve for Source-engine multiplayer."

7. **Settings UI → sample-rate display:** display the rate negotiated *after* stream open, not the `default_samplerate` from `query_devices`. Show actual `stream.latency` from sounddevice.

8. **Risks table → add row:** "Bluetooth A2DP / consumer USB DAC Exclusive instability" → mitigation: surface a clearer toast on Exclusive failure that says "This device type often does not support Exclusive; falling back to Shared."

9. **Risks table → add row:** "Saved device gone after driver upgrade" → mitigation: match by `(hostapi, name)` tuple; if no match, fall back to default device + toast.

10. **Tests section → add:**
   - `test_audio_clock.py`: verify soft-slew converges within 200 ms for a 20 ms anchor delta and snaps for >30 ms delta.
   - `test_audio_devices.py`: assert persistence round-trip uses `(hostapi, name)` not index.
   - Lifespan-shutdown test: assert `sd.Stream.close()` is called when the FastAPI app context exits.

11. **Phased rollout → Phase 2:** add resampling to the acceptance criteria. Phase-2 should load a 5-min, 44.1 kHz cache and produce 48 kHz audio in < 3 s warm-cache.

12. **CLAUDE.md memory note (post-implementation):** worth recording the persistent-device-identity rule and the "stems are cached at source-MP3 rate, not 48 kHz" finding as project memory.

## Newly-discovered risks / unknowns

- **Multi-rate stem cache.** Different cached tracks have different source rates. The audio backend must read each track's `summary.json::sample_rate` to know what to feed `soxr`. The spec assumes one rate per backend, not per track. **Document this.**
- **soxr LGPL.** `libsoxr` is LGPL-2.1-or-later. Static-link via the wheel is allowed; dynamic-link via pip wheel is the default and trivially compliant. No license action needed but the project should record the dependency in a NOTICES file if one exists.
- **PortAudio reinit on hot-add devices.** sounddevice's `_initialize()` reads the device list once; new devices plugged in after process start won't appear unless `sd._terminate(); sd._initialize()` is called. The spec's "small refresh button" is the right UX but the implementation needs the explicit terminate/init dance; document this.
- **Asyncio + WS during a stream callback underrun.** If the callback's `_outbound` queue blocks (because the WS task isn't draining), the callback can't enqueue an `ended` event. Use a non-blocking `put_nowait` with a bounded queue and a drop-oldest policy.
- **`stream.time` after `stream.close()`** is undefined. The clock-tick coroutine must check `stream.active` before reading `stream.time`.
- **Test environment for `test_audio_stream.py`.** PortAudio's "dummy" / null host API is not a documented public feature on Windows; sounddevice doesn't expose it. Tests will need to mock `sd.OutputStream` rather than use a real null backend, or rely on the WASAPI loopback device.
- **There are no existing WS endpoints in `webui/webui/server.py`.** The new `/api/audio/control` is the project's first WebSocket route. Verify uvicorn's `ws_max_size` default and `--ws` flag at startup (`websockets` lib is in the `[standard]` extras and is fine).
- **First-load JSON cost.** A 5-min stem at 44.1 kHz stereo PCM_16 reads in ~50–80 MB float64; reading via `soundfile.read(dtype='float32')` is twice as fast and half the RAM. Spec it.

## Source citations

- MSFT, Exclusive-Mode Streams — learn.microsoft.com/en-us/windows/win32/coreaudio/exclusive-mode-streams
- MSFT, Endpoint ID Strings — learn.microsoft.com/en-us/windows/win32/coreaudio/endpoint-id-strings
- MSFT, Audio Endpoint Builder Algorithm — learn.microsoft.com/en-us/windows-hardware/drivers/audio/audio-endpoint-builder-algorithm
- MSFT, Low-Latency Audio — learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio
- python-sounddevice 0.5.2 docs (Platform-Specific Settings, Streams) — python-sounddevice.readthedocs.io/en/0.5.2
- python-sounddevice source (`atexit.register`, `_terminate`) — github.com/spatialaudio/python-sounddevice/blob/master/src/sounddevice.py
- PortAudio v19 API overview — files.portaudio.com/docs/v19-doxydocs/api_overview.html
- PortAudio WASAPI header — portaudio.com/docs/v19-doxydocs/pa__win__wasapi_8h_source.html
- PortAudio Wiki, BufferingLatencyAndTimingImplementationGuidelines — github.com/PortAudio/portaudio/wiki/BufferingLatencyAndTimingImplementationGuidelines
- W3C High Resolution Time Level 3 — w3.org/TR/hr-time-3
- MDN Performance.now() — developer.mozilla.org/en-US/docs/Web/API/Performance/now
- MDN requestAnimationFrame — developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame
- Chrome timer throttling — developer.chrome.com/blog/timer-throttling-in-chrome-88
- Chromium audio_low_latency_output_win.h — chromium.googlesource.com (Shared by default, `--enable-exclusive-audio` flag)
- soxr PyPI — pypi.org/project/soxr (1.1.0, 3 May 2026, cp312-abi3-win_amd64)
- python-soxr releases — github.com/dofuuz/python-soxr/releases
- soundfile PyPI — pypi.org/project/soundfile (0.13.1, libsndfile 1.2.2, MP3 since 0.11.0)
- uvicorn signal handling — github.com/encode/uvicorn (PRs #1600, #2317; issue #1872)
- FastAPI lifespan — fastapi.tiangolo.com/advanced/events
- Valve Source Multiplayer Networking — developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
- Gaffer-on-games Snapshot Interpolation — gafferongames.com/post/snapshot_interpolation
