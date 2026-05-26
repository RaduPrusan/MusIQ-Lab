import { AudioEngine, STEM_NAMES } from "./engine.js";

const SOLO_DUCK = 0;       // gain when another stem is soloed
const PRE_ROLL = 0.05;     // start latency in seconds

export class WebAudioEngine extends AudioEngine {
  constructor() {
    super();
    this.ctx = null;
    this.sourceBuffer = null;
    this.stemBuffers = {};
    this.stemFailures = {};
    this.gains = {};
    this.targetVol = {};
    this.muted = {};
    this.soloed = {};
    this.currentSources = [];      // active AudioBufferSourceNodes
    this._mode = "source";         // "source" | "stems" — currently active
    this._userPreferredMode = null; // null = auto (prefer stems if ready); "source" | "stems" pin
    this._playing = false;
    this._t0 = 0;                  // ctx.currentTime when play() started
    this._offset = 0;              // song-time at _t0
    this._pausedAt = 0;
    this._duration = null;         // set by setDuration(); null = unbounded
    this._loopStart = null;
    this._loopEnd = null;
    this._subs = new Map();
    for (const n of STEM_NAMES) {
      this.targetVol[n] = 1; this.muted[n] = false; this.soloed[n] = false;
    }
  }

  setDuration(d) { this._duration = d > 0 ? d : null; }

  setLoop(start, end) {
    this._loopStart = (typeof start === "number" && start >= 0) ? start : null;
    this._loopEnd = (typeof end === "number" && end > (this._loopStart ?? 0)) ? end : null;
    if (this._loopStart === null) this._loopEnd = null;
  }
  clearLoop() { this._loopStart = null; this._loopEnd = null; }

  async load({ sourceUrl, stemUrls }) {
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this._masterGain = this.ctx.createGain();
    this._masterGain.connect(this.ctx.destination);
    this._sourceMonoGain = this.ctx.createGain();
    this._sourceMonoGain.connect(this._masterGain);
    try {
      this.sourceBuffer = await this._fetchAndDecode(sourceUrl);
    } catch (err) {
      this.sourceBuffer = null;
      this._emit("sourceFailed", { error: err?.message ?? "source decode failed" });
    }
    this._emit("modeAvailability", this._availability());
    // kick off stems in the background; resolve immediately
    this._loadStems(stemUrls).catch(() => {});
    if (this.ctx.state === "suspended") this._emit("autoplayBlocked");
  }

  async _loadStems(stemUrls) {
    const tasks = STEM_NAMES.map(async (name) => {
      const url = stemUrls[name];
      if (!url) { this.stemFailures[name] = "no url"; return; }
      try {
        this.stemBuffers[name] = await this._fetchAndDecode(url);
        const g = this.ctx.createGain();
        g.connect(this._masterGain);
        this.gains[name] = g;
        this._applyGain(name);
        this._emit("stemLoaded", { name });
        // Promote to stems mode as soon as the FIRST stem is decoded so the
        // SRC/MIX pill flips to MIX without waiting ~5s for the slowest stem.
        // _readyToMix() returns true on the first decoded stem, so the pill +
        // MIX-button-enabled state both light up immediately.
        this._emit("modeAvailability", this._availability());
        if (this._mode === "source"
            && this._userPreferredMode !== "source"
            && !this._playing) {
          this._mode = "stems";
          this._emit("modeChanged", { mode: this._mode });
        }
      } catch (err) {
        this.stemFailures[name] = err?.message ?? "decode failed";
        this._emit("stemFailed", { name, error: this.stemFailures[name] });
      }
    });
    await Promise.allSettled(tasks);
    this._emit("stemsReady", { failures: { ...this.stemFailures } });
    this._emit("modeAvailability", this._availability());
    if (this._playing) this._switchToStemMode();
  }

  async _fetchAndDecode(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url} -> ${r.status}`);
    const buf = await r.arrayBuffer();
    return await this.ctx.decodeAudioData(buf);
  }

  play() {
    if (!this.ctx) return;
    if (this._playing) return;
    if (this.ctx.state === "suspended") this.ctx.resume();
    // Replay-from-start if pressing play when paused at end of track.
    if (this._duration != null && this._pausedAt >= this._duration - 1e-3) {
      this._pausedAt = 0;
    }
    const offset = this._pausedAt;
    const startAt = this.ctx.currentTime + PRE_ROLL;
    this._t0 = startAt;
    this._offset = offset;
    this.currentSources = [];
    const target = this._resolveStartMode();
    if (target === "stems") {
      this._mode = "stems";
      for (const n of STEM_NAMES) {
        const buf = this.stemBuffers[n];
        if (!buf) continue;
        const src = this.ctx.createBufferSource();
        src.buffer = buf;
        src.connect(this.gains[n]);
        src.start(startAt, offset);
        this.currentSources.push(src);
      }
    } else if (target === "source") {
      this._mode = "source";
      const src = this.ctx.createBufferSource();
      src.buffer = this.sourceBuffer;
      src.connect(this._sourceMonoGain);
      src.start(startAt, offset);
      this.currentSources.push(src);
    } else {
      // no source AND no stems yet — wait for stems to arrive
      this._playing = false;
      this._emit("waitingForStems");
      return;
    }
    this._playing = true;
    this._tick();
    this._emit("play");
    this._emit("modeChanged", { mode: this._mode });
  }

  // Decide which mode play() should start in. User preference wins if the
  // requested buffers are loaded; otherwise fall back to "stems if ready
  // else source", which is the original auto behaviour.
  _resolveStartMode() {
    const pref = this._userPreferredMode;
    if (pref === "stems" && this._readyToMix()) return "stems";
    if (pref === "source" && this.sourceBuffer) return "source";
    if (this._readyToMix()) return "stems";
    if (this.sourceBuffer) return "source";
    return null;
  }

  // Public: pin the engine to a mode. null restores auto. If currently
  // playing, swaps at currentTime. Returns the mode actually chosen
  // (may differ from `mode` if the requested buffers aren't loaded yet).
  setMode(mode) {
    if (mode !== null && mode !== "source" && mode !== "stems") {
      throw new Error(`setMode: invalid mode ${mode}`);
    }
    this._userPreferredMode = mode;
    if (this._playing) {
      const t = this.currentTime;
      this.pause();
      this._pausedAt = t;
      this.play();
    } else {
      // Not playing — emit so UI reflects the new preferred mode even
      // though the active mode hasn't physically changed yet.
      this._emit("modeChanged", { mode: this._resolveStartMode() ?? this._mode });
    }
    return this._mode;
  }

  getMode() { return this._mode; }
  getPreferredMode() { return this._userPreferredMode; }
  _availability() {
    return { source: !!this.sourceBuffer, stems: this._readyToMix() };
  }
  getModeAvailability() { return this._availability(); }

  pause() {
    if (!this._playing) return;
    this._pausedAt = this.currentTime;
    for (const s of this.currentSources) try { s.stop(); } catch {}
    this.currentSources = [];
    this._playing = false;
    this._emit("pause");
  }

  seek(t) {
    const wasPlaying = this._playing;
    if (wasPlaying) this.pause();
    this._pausedAt = Math.max(0, t);
    if (wasPlaying) this.play();
    else this._emit("time", this._pausedAt);
  }

  setStemVolume(name, vol01) { this.targetVol[name] = Math.max(0, Math.min(1, vol01)); this._applyGain(name); }
  setStemMute(name, bool)    { this.muted[name] = !!bool; this._applyGains(); this._promoteToStemsOnMixGesture(); }
  setStemSolo(name, bool)    { this.soloed[name] = !!bool; this._applyGains(); this._promoteToStemsOnMixGesture(); }

  // Touching a stem mute/solo while playing SRC is itself a "I want to hear
  // the mix" gesture. Switch to stems mode (and unpin any prior "source"
  // pin so the gesture isn't immediately negated). No-op if stems aren't
  // ready or we're already in stems mode.
  _promoteToStemsOnMixGesture() {
    if (this._mode === "stems") return;
    if (!this._readyToMix()) return;
    if (this._userPreferredMode === "source") this._userPreferredMode = null;
    if (this._playing) this._switchToStemMode();
    else this._mode = "stems";
    this._emit("modeChanged", { mode: this._mode });
  }

  _applyGain(name) {
    const g = this.gains[name];
    if (!g) return;
    const anySolo = STEM_NAMES.some((n) => this.soloed[n]);
    const v = (this.muted[name] || (anySolo && !this.soloed[name])) ? SOLO_DUCK : this.targetVol[name];
    g.gain.setTargetAtTime(v, this.ctx.currentTime, 0.01);
  }
  _applyGains() { for (const n of STEM_NAMES) this._applyGain(n); }

  _readyToMix() {
    return STEM_NAMES.some((n) => this.stemBuffers[n]);   // mix whatever stems decoded
  }

  _switchToStemMode() {
    // called when stems finished after play() started in source mode.
    // Only auto-swap if the user hasn't pinned to "source" — pinning is
    // a deliberate "I want to compare", honor it.
    if (this._mode !== "source") return;
    if (this._userPreferredMode === "source") return;
    const t = this.currentTime;
    this.pause();
    this._pausedAt = t;
    this.play();
  }

  get currentTime() {
    if (!this._playing) return this._pausedAt;
    return this._offset + Math.max(0, this.ctx.currentTime - this._t0);
  }
  get isPlaying() { return this._playing; }

  _tick() {
    if (!this._playing) return;
    const t = this.currentTime;
    if (this._loopEnd != null && t >= this._loopEnd) {
      // Wrap to loop start. seek() handles pause/restart of audio sources.
      this.seek(this._loopStart);
      return;
    }
    if (this._duration != null && t >= this._duration) {
      // Audio buffers ended naturally a moment ago. Snap the playhead to
      // exactly duration, pause, and let the UI fall back to its idle state.
      this._emit("time", this._duration);
      for (const s of this.currentSources) try { s.stop(); } catch {}
      this.currentSources = [];
      this._playing = false;
      this._pausedAt = this._duration;
      this._emit("pause");
      this._emit("ended");
      return;
    }
    requestAnimationFrame(() => this._tick());
    this._emit("time", t);
  }

  on(event, fn)  { if (!this._subs.has(event)) this._subs.set(event, new Set()); this._subs.get(event).add(fn); }
  off(event, fn) { this._subs.get(event)?.delete(fn); }
  _emit(event, payload) {
    const set = this._subs.get(event);
    if (!set) return;
    for (const fn of set) fn(payload);
  }

  dispose() {
    for (const s of this.currentSources) try { s.stop(); } catch {}
    this.currentSources = [];
    this._playing = false;
    this._subs.clear();
    if (this.ctx && this.ctx.state !== "closed") {
      try { this.ctx.close(); } catch {}
    }
    this.ctx = null;
    this.sourceBuffer = null;
    this.stemBuffers = {};
  }
}
