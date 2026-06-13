/**
 * WasapiEngine — Phase 2 (Shared-mode source-MP3 playback).
 *
 * Talks to the server's /api/audio/control WebSocket. The server owns the
 * PortAudio stream + decoded source buffer; this engine is a thin client
 * that:
 *   - tracks the playing flag (server is authoritative via `state` messages)
 *   - extrapolates `currentTime` on requestAnimationFrame via a soft-slew
 *     anchor (matches the snapshot-interpolation pattern in the spec)
 *   - mirrors the AudioEngine contract the rest of the UI consumes
 *
 * Full playback surface: source mode, stems mix (per-stem mute/solo/volume
 * shipped as fire-and-forget WS ops), and server-side loop wrap. Local state
 * mirrors keep optimistic UI reads in lockstep with the authoritative server
 * mix.
 *
 * **Method-surface contract (broader than engine.js abstract):** Transport
 * (transport.js) + sidebar/mixer code call methods that the abstract
 * AudioEngine class doesn't declare. These MUST exist on WasapiEngine
 * because the UI calls them on every mount and on every user click —
 * throwing would brick the page. Specifically:
 *   - getMode() / getPreferredMode() / getModeAvailability() — transport
 *     mode-toggle.
 *   - setMode(mode) — user-clicked SRC/MIX toggle. Phase 2 only does
 *     source mode; "stems" is accepted (stored as preference) but
 *     ignored at the engine layer until Phase 3.
 *   - setDuration(d) — main.js sets the track duration after load.
 *   - setLoop(start, end) / clearLoop() — viewState pushes loop region.
 * Tracking the WebAudioEngine surface here keeps the two engines
 * interchangeable from the UI's point of view.
 */
import { AudioEngine, STEM_NAMES } from "./engine.js";

// Re-anchor threshold: any |delta| above 30 ms is treated as a seek / wrap
// / first-tick and hard-snaps the rAF cursor. Below it, soft-slew absorbs
// half the delta now (~25 ms convergence at the 40 Hz tick rate).
const SLEW_HARD_SNAP_SEC = 0.030;

export class WasapiEngine extends AudioEngine {
  constructor() {
    super();
    this._subs = new Map();
    this._req = 0;
    this._pending = new Map();   // req → {resolve, reject}
    // Optimistic playback flag; corrected by server `state` messages.
    this._playing = false;
    // null = no track loaded yet (mirrors WebAudioEngine). getModeAvailability
    // uses `_duration != null` to report whether source is ready.
    this._duration = null;
    // rAF anchor for currentTime extrapolation (the song-time clock).
    this._anchorSongT = 0;
    this._anchorPerfNow = performance.now() / 1000;
    this._lastSongPos = 0;
    // Per-stem state mirrors so reads (engine.muted[name], engine.soloed[name])
    // from main.js keyboard shortcuts work without round-tripping the WS.
    // Writes go through setStemVolume/Mute/Solo and ship a fire-and-forget
    // WS op — the server is authoritative on the actual mix, but local
    // mirrors keep the UI optimistic-render in lockstep with WebAudio.
    this.muted = {};
    this.soloed = {};
    this.targetVol = {};
    for (const n of STEM_NAMES) {
      this.muted[n] = false;
      this.soloed[n] = false;
      this.targetVol[n] = 1;
    }
    // True once the server has confirmed at least one stem decoded
    // successfully (via stems_loaded message). Drives getModeAvailability.
    this._stemsAvailable = false;
    // Active mode mirror — defaults to source. Server StateMsg.mode is
    // authoritative; we update from there.
    this._mode = "source";
    // Loop region — setLoop()/clearLoop() send the wrap server-side; these
    // local mirrors keep transport.js loop-band rendering in sync.
    this._loopStart = null;
    this._loopEnd = null;
    // User-pinned mode ("source" | "stems" | null). Phase 2 only ever
    // physically plays source, but we mirror WebAudioEngine's preference
    // model so the SRC/MIX toggle visually reflects the user's choice.
    this._userPreferredMode = null;
    // .catch(() => {}) silences the unhandledrejection event when the WS
    // can't open. The rejection still propagates through `await this._ready`
    // at every _send() call site — only the global console noise is suppressed.
    this._ready = this._connect().catch(() => {});
  }

  _connect() {
    return new Promise((resolve, reject) => {
      try {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        this._ws = new WebSocket(`${proto}//${location.host}/api/audio/control`);
      } catch (err) {
        reject(err);
        return;
      }
      this._ws.addEventListener("open", () => resolve());
      this._ws.addEventListener("error", (e) => {
        // Reject the connect promise on the first failed open; ongoing
        // request promises get rejected via close handler below.
        reject(e);
      });
      this._ws.addEventListener("message", (ev) => this._onMessage(ev));
      this._ws.addEventListener("close", () => {
        for (const p of this._pending.values()) p.reject(new Error("ws closed"));
        this._pending.clear();
        // Server is gone — flip our flag so currentTime stops extrapolating.
        if (this._playing) {
          this._playing = false;
          this._emit("pause");
        }
      });
    });
  }

  _onMessage(ev) {
    let msg;
    try { msg = JSON.parse(ev.data); }
    catch { return; }
    const req = msg.req;
    // Phase 4: engine_unavailable is a terminal error — the server's
    // open-chain orchestrator could not open any entry in the fallback
    // chain. Surface as `engineFailed` so the engine-factory listener in
    // main.js can swap us out for WebAudio. We DO NOT resolve a pending
    // request promise here because the set_device flow needs the swap
    // to drive the engine rebuild; resolving would just race with the
    // dispose() call.
    if (msg.type === "error" && msg.code === "engine_unavailable") {
      if (typeof req === "number" && this._pending.has(req)) {
        const { reject } = this._pending.get(req);
        this._pending.delete(req);
        try { reject(new Error(`engine_unavailable: ${msg.message}`)); } catch {}
      }
      this._emit("engineFailed", { reason: msg.message });
      return;
    }
    // Route request/response pairs first (devices/ack/pong/loaded all
    // carry req). Server-pushed events (state/clock/ended) have no req
    // and fall through to the broadcast handler. `state` may carry a
    // req when emitted as the play/seek confirmation, in which case we
    // both resolve the pending promise AND broadcast the state change.
    if (typeof req === "number" && this._pending.has(req)) {
      const { resolve, reject } = this._pending.get(req);
      this._pending.delete(req);
      if (msg.type === "error") reject(new Error(`${msg.code}: ${msg.message}`));
      else resolve(msg);
      // StateMsg may carry a req (set_mode echoes it) — resolve the pending
      // promise AND fall through so the state-broadcast handler below sees
      // it too. FallbackMsg always arrives after AckMsg, which already
      // cleared _pending[req]; it bypasses this block via the has-check
      // above and falls through to its handler below naturally.
      if (msg.type !== "state") return;
    }
    if (msg.type === "fallback") {
      // Server accepted set_device but the open-chain orchestrator had to
      // degrade (Exclusive → Shared, WASAPI → MME, …). Surface to main.js
      // so the user sees a toast naming the reason.
      this._emit("fallback", {
        reason: msg.reason,
        chosen_hostapi: msg.chosen_hostapi,
        chosen_exclusive: msg.chosen_exclusive,
        chosen_samplerate: msg.chosen_samplerate,
      });
      return;
    }
    if (msg.type === "state") {
      const wasPlaying = this._playing;
      this._playing = !!msg.playing;
      if (this._playing && !wasPlaying) this._emit("play");
      else if (!this._playing && wasPlaying) this._emit("pause");
      if (msg.mode) {
        const prev = this._mode;
        this._mode = msg.mode;
        if (prev !== msg.mode) this._emit("modeChanged", { mode: msg.mode });
      }
      return;
    }
    if (msg.type === "clock") {
      this._onClockTick(msg);
      return;
    }
    if (msg.type === "ended") {
      this._playing = false;
      this._emit("time", this._duration);
      this._emit("pause");
      this._emit("ended");
      return;
    }
    if (msg.type === "stream_info") {
      // Phase 5: driver-reported post-open params for the Settings UI.
      // Emitted as a follow-up to AckMsg(set_device); device-picker.js
      // subscribes to "streamInfo" and renders "Output: <kHz> · <frames>
      // frames · <ms> ms buffer" beneath the picker.
      this._emit("streamInfo", {
        samplerate: msg.samplerate,
        blocksize: msg.blocksize,
        output_latency_sec: msg.output_latency_sec,
      });
      return;
    }
    if (msg.type === "stems_loaded") {
      // Server completed the background stem decode. `results` is a
      // {stem_name: "loaded"|"missing"|"superseded"|"failed: <reason>"} map.
      // Mirror the WebAudioEngine surface: stemLoaded per-stem, stemsReady
      // aggregate, modeAvailability + modeChanged so the sidebar mixer +
      // transport mode toggle light up.
      const results = msg.results || {};
      // Generation-superseded results mean a newer load is in flight. Ignore
      // this message entirely; the newer load's stems_loaded will arrive and
      // populate the UI correctly.
      const allSuperseded =
        Object.keys(results).length > 0 &&
        Object.values(results).every((v) => v === "superseded");
      if (allSuperseded) return;
      // Partial-superseded: treat each "superseded" stem as a no-op (don't
      // fire stemFailed for it). This branch is defensive — load_stems
      // currently returns all-or-nothing for superseded.
      const failures = {};
      let anyLoaded = false;
      for (const [name, result] of Object.entries(results)) {
        if (result === "loaded") {
          anyLoaded = true;
          this._emit("stemLoaded", { name });
        } else if (result === "superseded") {
          continue;
        } else if (result === "missing") {
          // Match WebAudioEngine: store the "no url"/"missing" failure
          // so callers can introspect via stemFailures[].
          failures[name] = result;
          this._emit("stemFailed", { name, error: result });
        } else {
          // "failed: <reason>"
          failures[name] = result;
          this._emit("stemFailed", { name, error: result });
        }
      }
      this._stemsAvailable = anyLoaded;
      this._emit("stemsReady", { failures });
      this._emit("modeAvailability", this.getModeAvailability());
      // Mirror WebAudioEngine: when stems finish decoding and the user hasn't
      // pinned to "source", auto-promote the active mode to "stems". This is
      // what makes MIX the default playback mode (matches WebAudioEngine
      // _resolveStartMode + _switchToStemMode). Server `set_mode` is glitch-
      // free mid-playback and just flips the flag pre-play, so the same call
      // covers both "stems decoded before user pressed play" and "stems
      // arrived while source mode was already playing".
      if (anyLoaded
          && this._userPreferredMode !== "source"
          && this._mode !== "stems") {
        this._sendFireForget({ op: "set_mode", mode: "stems" });
      }
      return;
    }
  }

  async _send(payload) {
    await this._ready;
    if (!this._ws || this._ws.readyState > 1) {
      throw new Error("WasapiEngine: ws not open");
    }
    const req = ++this._req;
    return new Promise((resolve, reject) => {
      this._pending.set(req, { resolve, reject });
      try {
        this._ws.send(JSON.stringify({ ...payload, req }));
      } catch (err) {
        this._pending.delete(req);
        reject(err);
      }
    });
  }

  async listDevices() {
    const msg = await this._send({ op: "list_devices" });
    return msg.list || [];
  }

  async refreshDevices() {
    const msg = await this._send({ op: "refresh_devices" });
    return msg.list || [];
  }

  async setDevice({ hostapi, device_name, exclusive, samplerate }) {
    return this._send({
      op: "set_device", hostapi, device_name, exclusive, samplerate,
    });
  }

  // Fire-and-forget variant for play/pause/seek where confirmation comes
  // via a server-pushed state/clock message rather than the request
  // response. The op still carries a req so the server can echo it in
  // StateMsg.req for tracing, but no promise is awaited.
  _sendFireForget(payload) {
    if (!this._ws || this._ws.readyState > 1) return;
    const req = ++this._req;
    try {
      this._ws.send(JSON.stringify({ ...payload, req }));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("WasapiEngine: fire-and-forget send failed", err);
    }
  }

  // --- AudioEngine contract -----------------------------------------------

  async load({ sourceUrl, stemUrls: _stemUrls }) {
    // Extract slug from the existing API URL pattern
    // /api/tracks/{slug}/audio/source. The factory passes us the URL the
    // WebAudio engine uses; we re-derive the slug rather than threading a
    // new arg through.
    const m = /\/api\/tracks\/([^/]+)\/audio\/source/.exec(sourceUrl || "");
    const slug = m ? decodeURIComponent(m[1]) : null;
    if (!slug) {
      throw new Error(`WasapiEngine.load: could not parse slug from ${sourceUrl}`);
    }
    let stored = null;
    try {
      const raw = localStorage.getItem("musiq.audio");
      if (raw) stored = JSON.parse(raw);
    } catch { /* empty / corrupt — ignore */ }
    const device = stored && stored.device;
    if (!device) {
      // No device yet — surface a clear signal but don't throw. main.js's
      // loadTrack() should be able to mount the UI cleanly; the user
      // picks a device and the device-picker's change handler fires
      // window.__musiqEngineRebuild() to retry the load with a device
      // in place. Throwing here would bubble up through main.js and
      // brick the page on initial mount.
      this._emit("sourceFailed", { error: "WASAPI: no device chosen — pick one in Settings → Audio engine" });
      this._emit("modeAvailability", { source: false, stems: false });
      return;
    }
    // set_device first (idempotent if already set this session). Then load.
    await this._send({
      op: "set_device",
      hostapi: device.hostapi,
      device_name: device.device_name,
      exclusive: !!device.exclusive,
      samplerate: device.samplerate | 0,
    });
    const loaded = await this._send({ op: "load", slug });
    if (typeof loaded.duration === "number" && !this._duration) {
      this._duration = loaded.duration;
    }
    // Reset stems-loaded mirror — a new load supersedes any previously
    // decoded stem set; server will send a fresh StemsLoadedMsg when its
    // background task completes.
    this._stemsAvailable = false;
    // Mirror WebAudioEngine: report mode availability so the UI can enable
    // the source/stems toggle. Source flips on now; stems flips on when
    // the stems_loaded message arrives.
    this._emit("modeAvailability", { source: !!loaded.source_available, stems: false });
    return loaded;
  }

  play() {
    if (this._playing) return;
    // Optimistically flip the flag; server `state` will confirm. This
    // mirrors WebAudioEngine's behaviour of returning synchronously and
    // emitting 'play' from the same call.
    this._playing = true;
    // Reset anchor so rAF starts extrapolating from the last known
    // position. The first server clock tick will hard-snap if the gap is
    // larger than the 30 ms threshold.
    this._anchorSongT = this._lastSongPos;
    this._anchorPerfNow = performance.now() / 1000;
    this._sendFireForget({ op: "play" });
    this._emit("play");
  }

  pause() {
    if (!this._playing) return;
    this._playing = false;
    // Freeze the cursor at the current extrapolated position; the server
    // will follow up with a final ClockMsg that hard-snaps to the true
    // PortAudio-clock time.
    this._lastSongPos = this.currentTime;
    this._sendFireForget({ op: "pause" });
    this._emit("pause");
  }

  seek(t) {
    const target = Math.max(0, +t || 0);
    this._lastSongPos = target;
    this._anchorSongT = target;
    this._anchorPerfNow = performance.now() / 1000;
    this._sendFireForget({ op: "seek", song_t: target });
    // Don't emit 'time' yet — the server's post-seek ClockMsg does the
    // hard-snap. But for non-playing seeks, UI cursor needs to move now.
    if (!this._playing) this._emit("time", target);
  }

  setDuration(d) {
    // Mirror WebAudioEngine: null means unbounded. Both 0 and bad values
    // collapse to null so the rAF tick never falls into the duration-clamp
    // branch with stale data.
    this._duration = (typeof d === "number" && d > 0) ? d : null;
  }

  // Phase 3: stems mode wired through. The server is authoritative — we
  // mirror the active mode from StateMsg.mode and re-emit modeChanged from
  // _onMessage when it actually flips.
  getMode() { return this._mode || "source"; }
  getPreferredMode() { return this._userPreferredMode; }
  getModeAvailability() {
    // Source available once `loaded` arrived (non-null _duration); stems
    // available once at least one stem decoded server-side
    // (StemsLoadedMsg). Mirrors WebAudioEngine._availability.
    return {
      source: this._duration != null,
      stems: this._stemsAvailable === true,
    };
  }
  setMode(mode) {
    if (mode !== null && mode !== "source" && mode !== "stems") {
      throw new Error(`setMode: invalid mode ${mode}`);
    }
    this._userPreferredMode = mode;
    if (mode != null) {
      // Fire-and-forget — server replies with StateMsg(mode=…) which we
      // route in _onMessage and emit modeChanged from when it actually
      // changes. Mid-playback the source/stems toggle is glitch-free at
      // the next callback boundary modulo the 10 ms gain ramp.
      this._sendFireForget({ op: "set_mode", mode });
    }
    // Return the optimistic best-guess: pinning to "stems" only works if
    // stems are loaded. Local mirror flips once StateMsg confirms.
    if (mode === "stems" && !this._stemsAvailable) return this._mode || "source";
    return mode || (this._mode || "source");
  }

  setLoop(start, end) {
    // Phase 5: ships server-side wrap. Local mirrors are kept so UI reads
    // (e.g. transport.js loop-band rendering) match without round-tripping.
    this._loopStart = (typeof start === "number" && start >= 0) ? start : null;
    this._loopEnd = (typeof end === "number" && end > (this._loopStart ?? 0)) ? end : null;
    if (this._loopStart === null) this._loopEnd = null;
    if (this._loopStart != null && this._loopEnd != null) {
      this._sendFireForget({
        op: "loop",
        start: this._loopStart,
        end: this._loopEnd,
      });
    } else {
      this._sendFireForget({ op: "loop_clear" });
    }
  }
  clearLoop() {
    this._loopStart = null;
    this._loopEnd = null;
    this._sendFireForget({ op: "loop_clear" });
  }

  // Phase 3: per-stem mixer ships fire-and-forget WS ops. Local mirrors
  // (this.muted/.soloed/.targetVol) are updated optimistically so reads
  // from main.js keyboard shortcuts and the sidebar UI stay consistent
  // without round-tripping. The server runs a 10 ms gain ramp on the
  // audio thread so changes are audible within ~10 ms + WS roundtrip.
  setStemVolume(name, vol01) {
    const v = Math.max(0, Math.min(1, +vol01 || 0));
    this.targetVol[name] = v;
    this._sendFireForget({ op: "stem", name, vol: v });
  }
  setStemMute(name, bool) {
    const b = !!bool;
    this.muted[name] = b;
    this._sendFireForget({ op: "stem", name, muted: b });
    this._promoteToStemsOnMixGesture();
  }
  setStemSolo(name, bool) {
    const b = !!bool;
    this.soloed[name] = b;
    this._sendFireForget({ op: "stem", name, soloed: b });
    this._promoteToStemsOnMixGesture();
  }

  // Touching a stem mute/solo while in SRC is itself a "I want to hear the
  // mix" gesture. Ask the server to switch to stems mode (and unpin any
  // prior "source" pin so the gesture isn't immediately negated by the
  // stems_loaded auto-promote guard). Server's `set_mode` is glitch-free
  // mid-playback (10 ms gain ramp at the next callback boundary) and a
  // flag flip pre-play. No-op if stems aren't ready or we're already in
  // stems mode.
  _promoteToStemsOnMixGesture() {
    if (this._mode === "stems") return;
    if (!this._stemsAvailable) return;
    if (this._userPreferredMode === "source") this._userPreferredMode = null;
    this._sendFireForget({ op: "set_mode", mode: "stems" });
  }

  get currentTime() {
    if (!this._playing) return this._lastSongPos;
    const now = performance.now() / 1000;
    const t = this._anchorSongT + (now - this._anchorPerfNow);
    if (this._duration > 0 && t >= this._duration) return this._duration;
    return Math.max(0, t);
  }

  get isPlaying() { return this._playing; }

  // ----- Clock-tick soft-slew --------------------------------------------
  _onClockTick(msg) {
    const arrivePerf = performance.now() / 1000;
    const extrap = this._anchorSongT + (arrivePerf - this._anchorPerfNow);
    const delta = msg.song_t - extrap;
    if (Math.abs(delta) > SLEW_HARD_SNAP_SEC) {
      // Hard re-anchor — first tick after play, post-seek snap, or
      // anything else where the server told us we're far off.
      this._anchorSongT = msg.song_t;
      this._anchorPerfNow = arrivePerf;
    } else {
      // Soft slew: absorb half the delta now; the other half is absorbed
      // over the next ~25 ms tick window.
      this._anchorSongT = msg.song_t - delta * 0.5;
      this._anchorPerfNow = arrivePerf;
    }
    this._lastSongPos = msg.song_t;
    // Mirror playing state from the server tick (cheap consistency check).
    if (msg.playing !== undefined) this._playing = !!msg.playing;
    this._emit("time", msg.song_t);
  }

  // --- pub/sub mirror of WebAudioEngine -----------------------------------
  on(event, fn) {
    if (!this._subs.has(event)) this._subs.set(event, new Set());
    this._subs.get(event).add(fn);
  }
  off(event, fn) { this._subs.get(event)?.delete(fn); }
  _emit(event, payload) {
    const set = this._subs.get(event);
    if (!set) return;
    for (const fn of set) fn(payload);
  }

  dispose() {
    for (const p of this._pending.values()) {
      try { p.reject(new Error("disposed")); } catch {}
    }
    this._pending.clear();
    this._subs.clear();
    this._playing = false;
    if (this._ws && this._ws.readyState <= 1) {
      try { this._ws.close(); } catch {}
    }
    this._ws = null;
  }
}
