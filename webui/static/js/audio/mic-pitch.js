// Main-thread coordinator for the live-mic pitch layer.
//
// Owns:
//   - the AudioWorkletNode lifecycle (start/stop, getUserMedia stream)
//   - time-alignment math between AudioContext clock and engine song-time
//   - the ring buffer of recent samples (keyed by song time)
//   - reference-stem lookup for cents-off colouring
//   - the public API consumed by main.js, mic-row.js, mic-overlay.js
//
// Designed for testability: the constructor takes `{ engine, audioContext,
// workletFactory, getUserMedia }` so node:test can wire fakes. The
// production caller passes the real engine + a default factory that uses
// `new AudioWorkletNode(ctx, "mic-yin")`.

const RING_CAPACITY = 1024;             // ~44 s at one sample per ~43 ms
const STALE_MS = 500;                   // drop messages whose ctxTime is this old

// EMA smoothing applied at WRITE time (not in MicOverlay.render). Storing
// pre-smoothed values means the ring carries stable, scroll-independent
// data — recursive smoothing in the render loop would re-seed from the
// visible window's leftmost sample every frame and shimmer the whole
// line as the viewport pans. α=0.4 kills YIN's ±5-10¢ frame-to-frame
// jitter on a held note without killing vocal vibrato.
const EMA_ALPHA = 0.4;
// Must match `MAX_SEGMENT_GAP_S` in webui/static/js/render/mic-overlay.js
// — same threshold used for both visual-segment-break and EMA reset, so
// the smoother stops blending across the same gap the renderer stops
// drawing across. Math.abs() handles backward seeks (insertion order != time order).
const EMA_GAP_S = 0.15;

export class MicPitch extends EventTarget {
  constructor({ engine, audioContext, workletFactory, getUserMedia } = {}) {
    super();
    this.engine = engine;
    this.audioContext = audioContext;
    this._workletFactory = workletFactory;
    this._getUserMedia = getUserMedia;
    this._node = null;
    this._stream = null;
    this._running = false;
    this._starting = false;

    this._offsetMs = 0;
    this._referenceStem = null;
    this._deviceId = null;
    this._trackData = null;

    // Pre-allocated ring buffer.
    this._cap = RING_CAPACITY;
    this._t = new Float32Array(this._cap);
    // Float32 — NOT Uint8 — so the ring carries continuous MIDI (e.g.
    // 60.45 for a quarter-tone-sharp C4). Storing integers here would
    // quantize every drawn pitch to the nearest semitone, producing a
    // visible staircase even when the singer's pitch slides smoothly.
    this._midi = new Float32Array(this._cap);
    this._cents = new Float32Array(this._cap);
    this._clarity = new Uint8Array(this._cap);
    // Linear RMS amplitude per sample (NOT smoothed — we want the
    // overlay's opacity to track the singer's volume instantly; EMA
    // would lag the visual response). Float32 because RMS spans a
    // wide dynamic range (0.005 gate to ~0.7 belt) and we feed it
    // into a dBFS curve in MicOverlay.
    this._rms = new Float32Array(this._cap);
    this._n = 0;                         // number of valid entries (<= cap)
    this._head = 0;                      // write index, modulo cap

    // Last-index cache for reference lookup (O(1) steady state).
    this._refLastIdx = 0;
    this._refLastStem = null;

    // EMA-smoother state for write-time smoothing (see EMA_ALPHA above).
    // Reset on first push, on tSong gaps > EMA_GAP_S, on clearBuffer, and
    // partially on setReferenceStem (cents only — midi smoothing keeps
    // going since the underlying pitch detection didn't change).
    this._emaMidi = 0;
    this._emaCents = NaN;
    this._emaLastTSong = null;
  }

  // ----- Test seam -----
  _attachForTest() {
    if (!this._workletFactory) throw new Error("workletFactory required");
    this._node = this._workletFactory();
    this._node.port.onmessage = (e) => this._onSample(e.data);
    this._running = true;
  }

  // ----- Lifecycle (production) -----
  // start() resolves when the mic is live and posting frames; rejects with
  // a stable error code on each known failure mode.
  async start() {
    if (this._running || this._starting) return;
    if (typeof AudioWorkletNode === "undefined") {
      const err = new Error("AudioWorklet not supported in this browser");
      err.code = "unsupported";
      this.dispatchEvent(new CustomEvent("error", { detail: { code: err.code, message: err.message }}));
      throw err;
    }
    this._starting = true;
    try {
      // Auto-create the context if the caller didn't supply one.
      if (!this.audioContext) this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (this.audioContext.state === "suspended") {
        try { await this.audioContext.resume(); }
        catch { /* fall through; we'll surface this below */ }
      }
      // Register the worklet module once per context.
      if (!this._moduleAdded) {
        const url = new URL("./mic-yin-processor.js", import.meta.url);
        await this.audioContext.audioWorklet.addModule(url);
        this._moduleAdded = true;
      }
      // Acquire the mic.
      const getUm = this._getUserMedia || ((c) => navigator.mediaDevices.getUserMedia(c));
      this._stream = await getUm({
        audio: {
          deviceId: this._deviceId ? { exact: this._deviceId } : undefined,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
        },
      });
      // Wire source → worklet sink (no output to speakers).
      this._source = this.audioContext.createMediaStreamSource(this._stream);
      this._node = new AudioWorkletNode(this.audioContext, "mic-yin", { numberOfOutputs: 0 });
      this._node.port.onmessage = (e) => this._onSample(e.data);
      this._source.connect(this._node);

      // Stream-inactive handler (USB unplug etc.).
      this._stream.oninactive = () => {
        this.dispatchEvent(new CustomEvent("error", {
          detail: { code: "disconnected", message: "Microphone disconnected" },
        }));
        this.stop();
      };

      this._running = true;
      this.dispatchEvent(new Event("started"));
    } catch (err) {
      // Normalise the error code surface.
      let code = "unknown";
      if (err && err.name === "NotAllowedError") code = "permission";
      else if (err && err.name === "NotFoundError") code = "no-device";
      else if (err && err.name === "OverconstrainedError") code = "device-constraints";
      else if (err && err.name === "NotReadableError") code = "device-busy";
      const detail = { code, message: err?.message || String(err) };
      this.dispatchEvent(new CustomEvent("error", { detail }));
      // Cleanup partial state.
      try { this._stream?.getTracks().forEach((t) => t.stop()); } catch { /* */ }
      this._stream = null;
      this._source = null;
      this._node = null;
      this._running = false;
      throw err;
    } finally {
      this._starting = false;
    }
  }

  stop() {
    try { this._stream?.getTracks().forEach((t) => t.stop()); } catch { /* */ }
    try { this._source?.disconnect(); } catch { /* */ }
    try { this._node?.disconnect(); } catch { /* */ }
    this._stream = null;
    this._source = null;
    this._node = null;
    if (this._running) {
      this._running = false;
      this.dispatchEvent(new Event("stopped"));
    }
  }

  // ----- Settings -----
  setOffsetMs(ms) {
    this._offsetMs = Number(ms) || 0;
  }
  setReferenceStem(name) {
    this._referenceStem = name || null;
    this._refLastIdx = 0;
    this._refLastStem = null;
    // Reset the cents EMA state — switching reference makes any prior
    // smoothed cents semantically wrong (different target note). Midi
    // smoothing is unaffected (pitch detection didn't change).
    this._emaCents = NaN;
    // Notify MicOverlay so it can re-bucket existing NaN-cents samples
    // between "neutral" (stem silent here) and "no-match" (no stem chosen)
    // without waiting for the next mic frame.
    this.dispatchEvent(new Event("reference-changed"));
  }
  setTrackData(td) {
    this._trackData = td;
    this._refLastIdx = 0;
    this._refLastStem = null;
  }
  setDeviceId(id) {
    this._deviceId = id || null;
  }

  // ----- Public reads -----
  isRunning() { return this._running; }
  getOffsetMs() { return this._offsetMs; }
  getReferenceStem() { return this._referenceStem; }

  getSamplesInRange(tStart, tEnd) {
    // Copy the live entries into per-call typed arrays. The number of
    // visible samples is small (a few seconds × ~23 samples/s) so this
    // is cheap — no need to expose the ring directly.
    const t = [];
    const midi = [];
    const cents = [];
    const clarity = [];
    const rms = [];
    for (let k = 0; k < this._n; k++) {
      const i = (this._head - this._n + k + this._cap) % this._cap;
      const ts = this._t[i];
      if (ts < tStart || ts > tEnd) continue;
      t.push(ts);
      midi.push(this._midi[i]);
      cents.push(this._cents[i]);
      clarity.push(this._clarity[i]);
      rms.push(this._rms[i]);
    }
    return {
      time: new Float32Array(t),
      midi: new Float32Array(midi),
      cents: new Float32Array(cents),
      clarity: new Uint8Array(clarity),
      rms: new Float32Array(rms),
    };
  }

  clearBuffer() {
    this._n = 0; this._head = 0;
    // Wipe the EMA seed too — leaving stale smoother state would blend
    // the first post-clear sample with whatever was being smoothed at
    // clear time, producing a one-segment glitch on resume.
    this._emaMidi = 0;
    this._emaCents = NaN;
    this._emaLastTSong = null;
  }

  // ----- Internal -----
  _onSample(d) {
    if (!d) return;
    const { freq, clarity = 0, rms = 0, ctxTime } = d;
    // Staleness clamp.
    if (typeof ctxTime === "number" && this.audioContext) {
      const age = this.audioContext.currentTime - ctxTime;
      if (age * 1000 > STALE_MS) return;
    }
    // Compute song time.
    let tSong = null;
    if (this.engine && typeof this.engine.currentTime === "number") {
      const age = this.audioContext
        ? this.audioContext.currentTime - ctxTime
        : 0;
      tSong = this.engine.currentTime - age - this._offsetMs / 1000;
    }

    // Voicing.
    const voiced = freq > 0;
    const midiF = voiced ? 69 + 12 * Math.log2(freq / 440) : 0;
    // Clamp into the MIDI range but keep the continuous (float) value —
    // the ring buffer stores Float32 so quarter-tone-flat C4 renders at
    // 60-ish instead of snapping to 60.
    const midi = voiced ? Math.max(0, Math.min(127, midiF)) : 0;

    // Reference + cents.
    let centsVal = 0;
    let hasCents = false;
    if (voiced && this._referenceStem && tSong !== null) {
      const refMidi = this._lookupRefMidi(tSong);
      if (refMidi !== null) {
        centsVal = 100 * (midiF - refMidi);
        hasCents = true;
      }
    }

    // Emit "sample" regardless of song-time anchor (the readout works
    // even when no track is loaded).
    this.dispatchEvent(new CustomEvent("sample", { detail: {
      freq, midi: midiF, cents: hasCents ? centsVal : null, clarity, rms,
    }}));

    // Only push voiced samples with a song-time anchor.
    if (!voiced || tSong === null) return;

    // Gate ring writes on play state. When the engine is paused,
    // engine.currentTime is frozen, so every YIN frame (~23 Hz) produces a
    // sample with the same tSong but different midi/cents — they stack at
    // a single X coordinate and the overlay draws them as a vertical spike
    // at the playhead. Skipping the write here means: when paused, the
    // readout still updates from the dispatched "sample" event above
    // (useful for warming up your voice), but nothing lands on the
    // timeline ribbon. Resume play and capture continues cleanly.
    //
    // No seek-detect / ring-clear in this layer. A Δt check here would
    // conflate "user was silent for 3 s" (legitimate ring continuation
    // — both wall clock and song time advanced) with "user seeked by
    // 3 s" (genuine discontinuity), since both produce the same gap
    // between consecutive pushes. The MAX_SEGMENT_GAP_S guard in
    // MicOverlay already breaks the drawn segment across any gap >150 ms
    // (silence OR seek), so stale ring samples can never be visually
    // bridged — they're either offscreen (viewport followed playhead)
    // or drawn as a separate cluster at their original tSong (which is
    // correct: that's where the user actually sang).
    if (this.engine && this.engine.isPlaying === false) return;

    // EMA-smooth midi and cents at WRITE time so the ring carries stable,
    // pan-independent values. Reset on first push, on tSong gaps >
    // EMA_GAP_S (silence or seek), and when prior cents state is NaN
    // (e.g. after setReferenceStem switched the reference). Math.abs on
    // the delta catches backward jumps (ring is insertion-ordered).
    const rawCents = hasCents ? centsVal : NaN;
    const reset = this._emaLastTSong === null ||
                  Math.abs(tSong - this._emaLastTSong) > EMA_GAP_S;
    let smMidi, smCents;
    if (reset) {
      smMidi = midi;
      smCents = rawCents;
    } else {
      smMidi = EMA_ALPHA * midi + (1 - EMA_ALPHA) * this._emaMidi;
      // Only carry cents EMA forward when both the prior smoothed value
      // and the new raw value are finite. NaN on either side restarts
      // the cents chain — necessary so a stem-silent gap or a
      // reference-stem switch doesn't poison the next valid sample.
      if (Number.isFinite(this._emaCents) && Number.isFinite(rawCents)) {
        smCents = EMA_ALPHA * rawCents + (1 - EMA_ALPHA) * this._emaCents;
      } else {
        smCents = rawCents;
      }
    }
    this._emaMidi = smMidi;
    this._emaCents = smCents;
    this._emaLastTSong = tSong;

    const i = this._head;
    this._t[i] = tSong;
    this._midi[i] = smMidi;
    // NaN signals "no reference active" to downstream consumers. The earlier
    // "0 = no ref" convention collided with "perfectly in tune" (also 0¢),
    // which would have made MicOverlay paint both as in-tune green.
    this._cents[i] = smCents;
    this._clarity[i] = Math.max(0, Math.min(255, Math.round(clarity * 255)));
    this._rms[i] = rms;
    this._head = (this._head + 1) % this._cap;
    if (this._n < this._cap) this._n++;
  }

  _lookupRefMidi(tSong) {
    const stem = this._referenceStem;
    const td = this._trackData;
    if (!stem || !td?.notes?.[stem]) return null;
    const pack = td.notes[stem];
    const arr = pack.t;
    const dur = pack.dur;
    const midi = pack.midi;
    if (!arr || !arr.length) return null;

    // Reset cache if the reference changed.
    if (this._refLastStem !== stem) {
      this._refLastIdx = 0;
      this._refLastStem = stem;
    }
    let i = this._refLastIdx;
    // If we've moved past the cached note, advance.
    while (i + 1 < arr.length && arr[i + 1] <= tSong) i++;
    // If we've moved backwards, rewind.
    while (i > 0 && arr[i] > tSong) i--;
    this._refLastIdx = i;

    if (arr[i] <= tSong && tSong <= arr[i] + dur[i]) return midi[i];
    return null;
  }
}
