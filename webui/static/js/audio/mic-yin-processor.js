// Live-mic pitch estimator + AudioWorkletProcessor wrapper.
//
// The Yin class is the pure-DSP core, exported separately so it can be
// instantiated in node:test without the AudioWorklet runtime. The
// MicYinProcessor at the bottom is a ~20-line shim that owns the
// accumulation buffer + RMS gate + outlier hysteresis on top of Yin.

// Defaults — chosen in the spec, identical to Tuner.2's settings except
// fmin is tightened from 30 Hz to 65 Hz (below typical voice range).
export const DEFAULT_OPTS = Object.freeze({
  sampleRate: 48000,
  windowSize: 2048,
  fmin: 65,
  fmax: 1200,
  threshold: 0.10,
});

export class Yin {
  constructor(opts = {}) {
    const o = { ...DEFAULT_OPTS, ...opts };
    this.sampleRate = o.sampleRate;
    this.windowSize = o.windowSize;
    this.threshold = o.threshold;
    // tau bounds derived from fmin/fmax (samples per period at sampleRate).
    this.tauMin = Math.max(2, Math.floor(o.sampleRate / o.fmax));
    this.tauMax = Math.min(Math.floor(o.windowSize / 2), Math.floor(o.sampleRate / o.fmin));
    // Pre-allocated difference + CMND buffers — process() never allocates.
    this._d = new Float32Array(this.tauMax + 1);
    this._cmnd = new Float32Array(this.tauMax + 1);
  }

  // Run YIN on a windowSize-length mono float32 buffer.
  // Returns { freq: Hz (>0 if voiced, 0 otherwise), clarity: in [0,1] }.
  process(buf) {
    if (buf.length < this.windowSize) return { freq: 0, clarity: 0 };
    const W = this.windowSize;
    const d = this._d;
    const cmnd = this._cmnd;

    // Step 1: difference function d(tau) for tau in [tauMin..tauMax].
    for (let tau = this.tauMin; tau <= this.tauMax; tau++) {
      let sum = 0;
      for (let i = 0; i < W - tau; i++) {
        const diff = buf[i] - buf[i + tau];
        sum += diff * diff;
      }
      d[tau] = sum;
    }

    // Step 2: cumulative mean normalized difference, computed only over the
    // [tauMin+1..tauMax] range that Step 1 actually populated. d[1..tauMin-1]
    // is stale from previous process() calls — accumulating it would pollute
    // runningSum and bias the CMND denominator. cmnd[tauMin] := 1 is a
    // sentinel so the dip search in Step 3 never selects tauMin itself
    // (the parabolic interpolation guard already excludes it).
    cmnd[this.tauMin] = 1;
    let runningSum = 0;
    for (let tau = this.tauMin + 1; tau <= this.tauMax; tau++) {
      runningSum += d[tau];
      cmnd[tau] = runningSum > 0 ? d[tau] * tau / runningSum : 1;
    }

    // Step 3: absolute threshold — first dip below `threshold` whose local
    // minimum we then refine. If none, take the global minimum.
    let tauEst = -1;
    for (let tau = this.tauMin; tau <= this.tauMax - 1; tau++) {
      if (cmnd[tau] < this.threshold) {
        // Walk down to the local minimum.
        while (tau + 1 <= this.tauMax && cmnd[tau + 1] < cmnd[tau]) tau++;
        tauEst = tau;
        break;
      }
    }
    if (tauEst < 0) {
      // No tau crossed threshold → unvoiced.
      return { freq: 0, clarity: 0 };
    }

    // Step 4: parabolic interpolation around tauEst for sub-sample accuracy.
    let betterTau = tauEst;
    // tauEst strictly interior: cmnd[tauEst-1] is valid (in [tauMin+1..tauMax-1]).
    // Do NOT relax to >= tauMin without writing cmnd[tauMin-1] first.
    if (tauEst > this.tauMin && tauEst < this.tauMax) {
      const s0 = cmnd[tauEst - 1];
      const s1 = cmnd[tauEst];
      const s2 = cmnd[tauEst + 1];
      const denom = (s0 + s2 - 2 * s1);
      if (denom !== 0) {
        betterTau = tauEst + (s0 - s2) / (2 * denom);
      }
    }

    const freq = this.sampleRate / betterTau;
    const clarity = Math.max(0, Math.min(1, 1 - cmnd[tauEst]));
    return { freq, clarity };
  }
}

// ----- AudioWorkletProcessor wrapper ---------------------------------------
//
// Loaded via `audioWorklet.addModule()`. Runs on the audio thread.
// Accumulates inputs (which arrive in 128-sample blocks) into a `windowSize`
// frame, runs Yin per frame, applies RMS gate + Tuner.2-style outlier
// hysteresis, posts {freq, clarity, rms, ctxTime} to the main thread.
//
// `registerProcessor` is only defined inside an AudioWorkletGlobalScope,
// so we guard the call — Node + jsdom won't run this branch.

if (typeof registerProcessor !== "undefined") {
  class MicYinProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const o = (options && options.processorOptions) || {};
      this.windowSize = o.windowSize || DEFAULT_OPTS.windowSize;
      this.rmsGate = o.rmsGate ?? 0.005;
      this.yin = new Yin({
        sampleRate,                                  // global in worklet scope
        windowSize: this.windowSize,
        fmin: o.fmin ?? DEFAULT_OPTS.fmin,
        fmax: o.fmax ?? DEFAULT_OPTS.fmax,
        threshold: o.threshold ?? DEFAULT_OPTS.threshold,
      });
      this._buf = new Float32Array(this.windowSize);
      this._idx = 0;                                 // next write index in _buf
      this._lastFreq = 0;                            // for hysteresis
      this._outlierHold = 0;                         // 0..2
      this.port.onmessage = (e) => {
        if (e.data?.type === "set-rms-gate") this.rmsGate = Number(e.data.value) || 0.005;
      };
    }

    process(inputs) {
      const ch = inputs[0]?.[0];
      if (!ch) return true;
      // Append into the ring; when full, run Yin and reset.
      let i = 0;
      while (i < ch.length) {
        const want = this.windowSize - this._idx;
        const take = Math.min(want, ch.length - i);
        this._buf.set(ch.subarray(i, i + take), this._idx);
        this._idx += take;
        i += take;
        if (this._idx >= this.windowSize) {
          this._runFrame();
          this._idx = 0;
        }
      }
      return true;
    }

    _runFrame() {
      // RMS over the full window.
      let sumSq = 0;
      for (let n = 0; n < this.windowSize; n++) sumSq += this._buf[n] * this._buf[n];
      const rms = Math.sqrt(sumSq / this.windowSize);
      let out = { freq: 0, clarity: 0 };
      if (rms >= this.rmsGate) out = this.yin.process(this._buf);

      // Outlier hysteresis. Three rules layered:
      //   (1) Tuner.2's drop-rejection: new freq < 80% of prev → suspicious
      //       (covers small fifth/sixth dips during attack transients).
      //   (2) Octave-error rejection in EITHER direction: ratio outside
      //       [0.55, 1.82] (~±10 semitones) is almost certainly a YIN
      //       sub-harmonic or super-harmonic lock, since the voice cannot
      //       physically jump >10 semitones in a 43 ms frame.
      //   (3) When suspicious, hold prev for ≤2 consecutive frames, then
      //       accept the new (sustained change → real). A single rogue
      //       frame is now squashed instead of escaping for one block.
      let freq = out.freq;
      const ratio = (this._lastFreq > 0 && freq > 0) ? freq / this._lastFreq : 1;
      const isSlightDrop = ratio < 0.8 && ratio >= 0.55;
      const isOctaveJump = ratio < 0.55 || ratio > 1.82;
      if (this._lastFreq > 0 && freq > 0 && (isSlightDrop || isOctaveJump)) {
        if (this._outlierHold < 2) {
          this._outlierHold++;
          freq = this._lastFreq;
        } else {
          this._outlierHold = 0;          // sustained → accept the new
        }
      } else {
        this._outlierHold = 0;
      }
      this._lastFreq = freq;

      this.port.postMessage({
        freq,
        clarity: out.clarity,
        rms,
        ctxTime: currentTime,             // global in worklet scope
      });
    }
  }
  registerProcessor("mic-yin", MicYinProcessor);
}
