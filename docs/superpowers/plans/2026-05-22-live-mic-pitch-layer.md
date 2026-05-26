# Live Mic-Pitch Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-only real-time microphone pitch contour to the MusIQ Lab webui piano-roll, rendered as a new "Live Input" pseudo-stem row above the existing six stems, drawn pinned to song time with cents-off colouring vs a user-selectable reference stem.

**Architecture:** Four new browser modules: an `AudioWorkletProcessor` (YIN DSP), a main-thread coordinator (`MicPitch`) that owns getUserMedia + time-alignment + ring buffer + reference lookup, a canvas overlay (`MicOverlay`, mirroring `F0Overlay`'s self-install pattern), and a sidebar row (`MicRow`). Wired into `main.js` after the existing `F0Overlay`. Zero Python changes.

**Tech Stack:** Vanilla JS ES modules · Web Audio API (AudioContext, AudioWorkletNode, MediaStream) · Canvas 2D · `node:test` + `jsdom` for unit tests · Playwright for one e2e.

**Spec:** [`docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md`](../specs/2026-05-22-live-mic-pitch-layer-design.md)

---

## File map (locked-in before any task)

**New (4):**
- `webui/static/js/audio/mic-yin-processor.js` — AudioWorkletProcessor + exported `Yin` class for direct testing.
- `webui/static/js/audio/mic-pitch.js` — main-thread coordinator.
- `webui/static/js/render/mic-overlay.js` — canvas overlay.
- `webui/static/js/ui/mic-row.js` — sidebar row.

**Modified (3):**
- `webui/static/js/ui/sidebar.js` — inject MicRow above the `_buildTracksSection` stem loop.
- `webui/static/js/main.js` — instantiate `MicPitch` + `MicOverlay` after the existing `F0Overlay`; subscribe to `engine.on("time", …)` indirectly (already done — `MicPitch` reads `engine.currentTime` on demand).
- `webui/static/index.html` — no edit if MicOverlay self-installs (it does — see Task 14). Single-line theme token addition lives in CSS, see Task 17.

**Tests (5 unit/integration + 1 e2e):**
- `webui/tests-js/mic-yin.test.js`
- `webui/tests-js/mic-pitch.test.js`
- `webui/tests-js/mic-overlay.test.js`
- `webui/tests-js/mic-row.test.js`
- `webui/tests-js/mic-pitch-integration.test.js`
- `webui/tests-e2e/live-mic.spec.js`

---

## Task 0: Verify baseline — webui dev server runs and tests pass

**Files:** none modified.

- [ ] **Step 1: Confirm we're on `main` and clean.**

```bash
cd "<PROJECT_PATH>"
git status
git log -1 --oneline
```
Expected: `On branch main`, clean working tree, latest commit `9436b38 docs(spec): correct test runner...`.

- [ ] **Step 2: Run the existing JS unit suite to confirm a green baseline.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/*.test.js"
```
Expected: all tests pass (count varies — the file list ends with `wasapi-engine.test.js`, `xcheck.test.js`). If anything fails, **stop and fix the baseline before continuing** — do not write new tests on top of a broken suite.

- [ ] **Step 3: No commit. This task is a gate, not a change.**

---

## Task 1: YIN core — failing test for monophonic sine detection

**Files:**
- Test: `webui/tests-js/mic-yin.test.js` (create)

- [ ] **Step 1: Write the failing test.**

Create `webui/tests-js/mic-yin.test.js`:

```js
// Tests for the YIN pitch estimator used by the live mic worklet.
// We test the exportable Yin class directly — the AudioWorkletProcessor
// wrapper is a thin shim around it and is exercised by the e2e test.
import { test } from "node:test";
import assert from "node:assert/strict";

import { Yin } from "../static/js/audio/mic-yin-processor.js";

// Generate a windowSize-sample mono float32 sine at `freqHz` and `sampleRate`.
function sine(freqHz, sampleRate, windowSize, amp = 0.5) {
  const buf = new Float32Array(windowSize);
  const w = (2 * Math.PI * freqHz) / sampleRate;
  for (let i = 0; i < windowSize; i++) buf[i] = amp * Math.sin(w * i);
  return buf;
}

// Convert two frequencies to a cents difference (signed: positive = sharper).
function cents(actual, expected) {
  return 1200 * Math.log2(actual / expected);
}

test("Yin detects pure sines within ±5 cents (110, 220, 440, 880 Hz)", () => {
  const sampleRate = 48000;
  const windowSize = 2048;
  const yin = new Yin({ sampleRate, windowSize, fmin: 65, fmax: 1200, threshold: 0.10 });
  for (const f of [110, 220, 440, 880]) {
    const buf = sine(f, sampleRate, windowSize);
    const out = yin.process(buf);
    assert.ok(out.freq > 0, `expected a voiced result for ${f} Hz, got freq=${out.freq}`);
    const dev = cents(out.freq, f);
    assert.ok(Math.abs(dev) < 5, `±5¢ violated at ${f} Hz: got ${out.freq.toFixed(3)} Hz, ${dev.toFixed(2)}¢`);
  }
});
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/mic-yin.test.js"
```
Expected: FAIL with `Cannot find module '../static/js/audio/mic-yin-processor.js'`.

- [ ] **Step 3: No commit yet — the test will be committed alongside the implementation in Task 2.**

---

## Task 2: YIN core — implementation that makes Task 1 pass

**Files:**
- Create: `webui/static/js/audio/mic-yin-processor.js`

- [ ] **Step 1: Implement `Yin` class with the bare minimum to pass Task 1's test.**

Create `webui/static/js/audio/mic-yin-processor.js`:

```js
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

    // Step 2: cumulative mean normalized difference. cmnd[0] := 1.
    cmnd[0] = 1;
    let runningSum = 0;
    for (let tau = 1; tau <= this.tauMax; tau++) {
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

      // Tuner.2 outlier hysteresis: if the new freq is < 80% of prev, hold
      // the prev for up to 2 consecutive frames, then accept the new.
      let freq = out.freq;
      if (this._lastFreq > 0 && freq > 0 && freq < 0.8 * this._lastFreq) {
        if (this._outlierHold < 2) {
          this._outlierHold++;
          freq = this._lastFreq;
        } else {
          this._outlierHold = 0;          // accept the new
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
```

- [ ] **Step 2: Run Task 1's test, confirm it passes.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/mic-yin.test.js"
```
Expected: PASS (`# pass 1`).

- [ ] **Step 3: Commit.**

```bash
cd "<PROJECT_PATH>"
git add webui/static/js/audio/mic-yin-processor.js webui/tests-js/mic-yin.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): YIN pitch estimator + worklet wrapper

Pure-DSP Yin class (sample-rate-agnostic, fixed-window) with cumulative
mean normalized difference + parabolic sub-sample interpolation.
AudioWorkletProcessor shim accumulates 128-sample blocks into 2048-frame
windows, applies RMS gate + Tuner.2 outlier hysteresis, posts {freq,
clarity, rms, ctxTime} to the main thread.

Test: known-input/known-output at ±5 cents on 110/220/440/880 Hz sines.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: YIN core — RMS gate + silence + noise tests

**Files:**
- Test: `webui/tests-js/mic-yin.test.js` (append)

- [ ] **Step 1: Append tests for silence and noise.**

Append to `webui/tests-js/mic-yin.test.js`:

```js
test("Yin returns freq=0 on pure silence", () => {
  const sampleRate = 48000;
  const windowSize = 2048;
  const yin = new Yin({ sampleRate, windowSize });
  const silence = new Float32Array(windowSize); // all zeros
  const out = yin.process(silence);
  assert.equal(out.freq, 0);
  assert.equal(out.clarity, 0);
});

test("Yin returns low-clarity (or freq=0) on white noise", () => {
  const sampleRate = 48000;
  const windowSize = 2048;
  const yin = new Yin({ sampleRate, windowSize });
  const noise = new Float32Array(windowSize);
  // Deterministic RNG so this test never flakes.
  let s = 0x12345678;
  for (let i = 0; i < windowSize; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    noise[i] = ((s >>> 0) / 0xffffffff) * 2 - 1;   // [-1, 1]
    noise[i] *= 0.1;                                // amp 0.1 (well above the RMS gate)
  }
  const out = yin.process(noise);
  // YIN may still pick a tau on noise — but clarity must be modest. The
  // contract is: clarity = 1 - cmnd[tauEst]; on noise cmnd is high so
  // clarity is low. We assert clarity < 0.9 (in-tune sines hit > 0.95).
  if (out.freq > 0) {
    assert.ok(out.clarity < 0.9, `expected low clarity on noise, got ${out.clarity}`);
  }
});
```

- [ ] **Step 2: Run, confirm both pass.**

```bash
node --test "tests-js/mic-yin.test.js"
```
Expected: PASS — 3 tests (the original + 2 new).

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-yin.test.js
git commit -m "test(webui/mic): silence + white-noise sanity checks for Yin

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: MicPitch coordinator — failing test for time-alignment math

**Files:**
- Test: `webui/tests-js/mic-pitch.test.js` (create)

- [ ] **Step 1: Write failing test.**

Create `webui/tests-js/mic-pitch.test.js`:

```js
// Tests for the MicPitch main-thread coordinator: time-alignment math,
// ring buffer, reference-stem lookup, public API surface.
//
// We do NOT spin up a real AudioContext or AudioWorklet here. MicPitch
// is constructor-injected with the engine + audioContext + a "worklet
// factory" so we can inject a stub that lets the test drive messages.

import { test } from "node:test";
import assert from "node:assert/strict";

import { MicPitch } from "../static/js/audio/mic-pitch.js";

// Fake engine: exposes currentTime as a settable property.
function fakeEngine(initial = 0) {
  return {
    _t: initial,
    get currentTime() { return this._t; },
    isPlaying: true,
    _listeners: {},
    on(name, fn) { (this._listeners[name] ||= []).push(fn); },
    off(name, fn) {
      const a = this._listeners[name];
      if (!a) return;
      const i = a.indexOf(fn);
      if (i >= 0) a.splice(i, 1);
    },
    _fire(name, payload) { (this._listeners[name] || []).forEach((fn) => fn(payload)); },
  };
}

// Fake audioContext: settable currentTime.
function fakeCtx(initial = 0) {
  return { _t: initial, get currentTime() { return this._t; } };
}

// Fake worklet factory: returns a "node" with a port.onmessage assignable
// hook and a `_push(msg)` helper the test calls to simulate the worklet
// posting a sample.
function fakeWorkletFactory() {
  const node = { port: { onmessage: null, postMessage: () => {} } };
  const factory = () => node;
  factory.push = (msg) => node.port.onmessage && node.port.onmessage({ data: msg });
  return factory;
}

test("MicPitch.T_song = engine.currentTime - block age - offset", () => {
  const engine = fakeEngine(10.0);            // song is at 10 s
  const ctx = fakeCtx(5.0);                   // audioCtx at 5 s
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();                       // wire the fake worklet without getUserMedia

  mic.setOffsetMs(-30);                       // user nudge
  // Worklet posts: sample was processed at ctxTime=4.9, so block age = 0.1 s.
  factory.push({ freq: 440, clarity: 0.95, rms: 0.1, ctxTime: 4.9 });

  const samples = mic.getSamplesInRange(0, 100);
  assert.equal(samples.time.length, 1);
  // T_song = 10.0 - (5.0 - 4.9) - (-30/1000) = 10.0 - 0.1 + 0.030 = 9.930
  assert.ok(Math.abs(samples.time[0] - 9.930) < 1e-6, `got ${samples.time[0]}`);
  // 440 Hz → MIDI 69. cents = null (no reference set).
  assert.equal(samples.midi[0], 69);
});
```

- [ ] **Step 2: Run, confirm FAIL with "Cannot find module".**

```bash
node --test "tests-js/mic-pitch.test.js"
```
Expected: FAIL.

- [ ] **Step 3: No commit — committed in Task 5.**

---

## Task 5: MicPitch coordinator — minimal implementation

**Files:**
- Create: `webui/static/js/audio/mic-pitch.js`

- [ ] **Step 1: Implement just enough to pass Task 4's test.**

Create `webui/static/js/audio/mic-pitch.js`:

```js
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

    this._offsetMs = 0;
    this._referenceStem = null;
    this._deviceId = null;
    this._trackData = null;

    // Pre-allocated ring buffer.
    this._cap = RING_CAPACITY;
    this._t = new Float32Array(this._cap);
    this._midi = new Uint8Array(this._cap);
    this._cents = new Float32Array(this._cap);
    this._clarity = new Uint8Array(this._cap);
    this._n = 0;                         // number of valid entries (<= cap)
    this._head = 0;                      // write index, modulo cap

    // Last-index cache for reference lookup (O(1) steady state).
    this._refLastIdx = 0;
    this._refLastStem = null;
  }

  // ----- Test seam -----
  _attachForTest() {
    if (!this._workletFactory) throw new Error("workletFactory required");
    this._node = this._workletFactory();
    this._node.port.onmessage = (e) => this._onSample(e.data);
    this._running = true;
  }

  // ----- Lifecycle (production) -----
  // start() / stop() will be filled in by Task 8. Tests don't need them yet.

  // ----- Settings -----
  setOffsetMs(ms) {
    this._offsetMs = Number(ms) || 0;
  }
  setReferenceStem(name) {
    this._referenceStem = name || null;
    this._refLastIdx = 0;
    this._refLastStem = null;
  }
  setTrackData(td) {
    this._trackData = td;
    this._refLastIdx = 0;
    this._refLastStem = null;
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
    for (let k = 0; k < this._n; k++) {
      const i = (this._head - this._n + k + this._cap) % this._cap;
      const ts = this._t[i];
      if (ts < tStart || ts > tEnd) continue;
      t.push(ts);
      midi.push(this._midi[i]);
      cents.push(this._cents[i]);
      clarity.push(this._clarity[i]);
    }
    return {
      time: new Float32Array(t),
      midi: new Uint8Array(midi),
      cents: new Float32Array(cents),
      clarity: new Uint8Array(clarity),
    };
  }

  clearBuffer() { this._n = 0; this._head = 0; }

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
    const midi = voiced ? Math.max(0, Math.min(127, Math.round(midiF))) : 0;

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
    const i = this._head;
    this._t[i] = tSong;
    this._midi[i] = midi;
    this._cents[i] = hasCents ? centsVal : 0;       // 0 = "no ref" by convention
    this._clarity[i] = Math.max(0, Math.min(255, Math.round(clarity * 255)));
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
```

- [ ] **Step 2: Run Task 4's test, confirm it passes.**

```bash
node --test "tests-js/mic-pitch.test.js"
```
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/static/js/audio/mic-pitch.js webui/tests-js/mic-pitch.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): MicPitch coordinator skeleton + time-alignment math

Public API: constructor + setOffsetMs / setReferenceStem / setTrackData
/ getSamplesInRange / clearBuffer / "sample" event. Test seam
(_attachForTest + injectable workletFactory) lets node:test exercise
the message path without a real AudioWorklet.

T_song = engine.currentTime - (audioCtx.currentTime - ctxTime)
       - userOffsetMs / 1000.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: MicPitch — ring-buffer wrap test + reference lookup test

**Files:**
- Test: `webui/tests-js/mic-pitch.test.js` (append)

- [ ] **Step 1: Append tests.**

Append to `webui/tests-js/mic-pitch.test.js`:

```js
test("MicPitch ring buffer wraps after RING_CAPACITY samples", () => {
  const engine = fakeEngine(0);
  const ctx = fakeCtx(0);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  for (let i = 0; i < 1500; i++) {
    engine._t = i * 0.04;
    ctx._t = i * 0.04;
    factory.push({ freq: 440, clarity: 0.9, rms: 0.1, ctxTime: i * 0.04 });
  }
  // After wrap, getSamplesInRange should return at most RING_CAPACITY entries.
  const s = mic.getSamplesInRange(-1, 1e6);
  assert.ok(s.time.length <= 1024, `expected <= 1024, got ${s.time.length}`);
  // Newest sample should be at the latest pushed song time.
  const latest = s.time[s.time.length - 1];
  assert.ok(Math.abs(latest - 1499 * 0.04) < 1e-4, `latest=${latest}`);
});

test("MicPitch.lookupRefMidi returns the active note or null in gaps", () => {
  const engine = fakeEngine(0);
  const ctx = fakeCtx(0);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  // Synthetic stem: three notes at t=0..1, t=2..3, t=4..5 with MIDI 60, 62, 64.
  mic.setTrackData({
    notes: {
      vocals: {
        t: new Float32Array([0, 2, 4]),
        dur: new Float32Array([1, 1, 1]),
        midi: new Uint8Array([60, 62, 64]),
      },
    },
  });
  mic.setReferenceStem("vocals");

  assert.equal(mic._lookupRefMidi(0.5), 60);
  assert.equal(mic._lookupRefMidi(1.5), null);  // gap
  assert.equal(mic._lookupRefMidi(2.5), 62);
  assert.equal(mic._lookupRefMidi(4.5), 64);
  assert.equal(mic._lookupRefMidi(99),  null);
});

test("MicPitch computes signed cents against reference", () => {
  const engine = fakeEngine(0.5);   // inside note 1 (t=0..1, midi=60)
  const ctx = fakeCtx(0.5);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  mic.setTrackData({
    notes: { vocals: {
      t: new Float32Array([0]),
      dur: new Float32Array([1]),
      midi: new Uint8Array([60]),   // C4
    }},
  });
  mic.setReferenceStem("vocals");

  // 440 Hz = MIDI 69 = A4. Cents vs C4 = 100 * (69 - 60) = +900 cents.
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.5 });
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 1);
  assert.ok(Math.abs(s.cents[0] - 900) < 1e-3, `got ${s.cents[0]}`);
});
```

- [ ] **Step 2: Run, confirm all four tests in mic-pitch.test.js pass.**

```bash
node --test "tests-js/mic-pitch.test.js"
```
Expected: 4 PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-pitch.test.js
git commit -m "test(webui/mic): ring-buffer wrap + reference-lookup + cents-calc

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: MicPitch — staleness clamp + unanchored-engine behaviour

**Files:**
- Test: `webui/tests-js/mic-pitch.test.js` (append)

- [ ] **Step 1: Append tests.**

```js
test("MicPitch drops stale messages (>500 ms old)", () => {
  const engine = fakeEngine(0);
  const ctx = fakeCtx(2);              // audioCtx at 2 s
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 1.4 }); // age = 0.6 s → drop
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 1.9 }); // age = 0.1 s → keep
  const s = mic.getSamplesInRange(-1e6, 1e6);
  assert.equal(s.time.length, 1);
});

test("MicPitch still emits 'sample' when engine has no anchor (no track playing)", () => {
  const ctx = fakeCtx(1);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine: null, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();
  let lastSample = null;
  mic.addEventListener("sample", (e) => { lastSample = e.detail; });
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 1.0 });
  assert.ok(lastSample);
  assert.ok(Math.abs(lastSample.midi - 69) < 1e-6);
  // But nothing in the ring buffer (no song-time anchor).
  assert.equal(mic.getSamplesInRange(-1e6, 1e6).time.length, 0);
});
```

- [ ] **Step 2: Run, confirm pass.**

```bash
node --test "tests-js/mic-pitch.test.js"
```
Expected: 6 PASS total.

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-pitch.test.js
git commit -m "test(webui/mic): staleness drop + unanchored-engine readout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: MicPitch — real start()/stop() with getUserMedia + worklet

**Files:**
- Modify: `webui/static/js/audio/mic-pitch.js`

- [ ] **Step 1: Append production-path lifecycle.**

Insert after the `_attachForTest` method (keep `_attachForTest` for tests):

```js
  // ----- Lifecycle (production) -----
  // start() resolves when the mic is live and posting frames; rejects with
  // a stable error code on each known failure mode.
  async start() {
    if (this._running) return;
    if (typeof AudioWorkletNode === "undefined") {
      const err = new Error("AudioWorklet not supported in this browser");
      err.code = "unsupported";
      this.dispatchEvent(new CustomEvent("error", { detail: { code: err.code, message: err.message }}));
      throw err;
    }
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
      const detail = { code, message: err?.message || String(err) };
      this.dispatchEvent(new CustomEvent("error", { detail }));
      // Cleanup partial state.
      try { this._stream?.getTracks().forEach((t) => t.stop()); } catch { /* */ }
      this._stream = null;
      this._source = null;
      this._node = null;
      this._running = false;
      throw err;
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

  setDeviceId(id) {
    this._deviceId = id || null;
  }
```

- [ ] **Step 2: Append a failure-mode test that exercises the production path WITHOUT a real getUserMedia.**

Append to `webui/tests-js/mic-pitch.test.js`:

```js
test("MicPitch.start emits 'error' with code=permission when getUserMedia denies", async () => {
  const errors = [];
  const fakeGetUserMedia = () => {
    const e = new Error("denied");
    e.name = "NotAllowedError";
    return Promise.reject(e);
  };
  // Stub AudioWorkletNode existence + a minimal audioContext.
  globalThis.AudioWorkletNode = class {};
  const ctx = {
    state: "running",
    audioWorklet: { addModule: async () => {} },
    createMediaStreamSource: () => ({ connect: () => {} }),
  };
  const mic = new MicPitch({
    engine: fakeEngine(0),
    audioContext: ctx,
    getUserMedia: fakeGetUserMedia,
  });
  mic.addEventListener("error", (e) => errors.push(e.detail));
  await assert.rejects(() => mic.start());
  assert.equal(errors.length, 1);
  assert.equal(errors[0].code, "permission");
});

test("MicPitch.start emits 'error' code=unsupported when AudioWorkletNode is missing", async () => {
  const orig = globalThis.AudioWorkletNode;
  delete globalThis.AudioWorkletNode;
  try {
    const mic = new MicPitch({ engine: fakeEngine(0) });
    const errors = [];
    mic.addEventListener("error", (e) => errors.push(e.detail));
    await assert.rejects(() => mic.start());
    assert.equal(errors[0].code, "unsupported");
  } finally {
    if (orig) globalThis.AudioWorkletNode = orig;
  }
});
```

- [ ] **Step 3: Run, confirm pass.**

```bash
node --test "tests-js/mic-pitch.test.js"
```
Expected: 8 PASS total.

- [ ] **Step 4: Commit.**

```bash
git add webui/static/js/audio/mic-pitch.js webui/tests-js/mic-pitch.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): MicPitch.start/stop with getUserMedia + worklet

Production path. Forces echoCancellation/noiseSuppression/AGC = false.
Normalises errors to {code: permission|no-device|unsupported|disconnected|
device-constraints|unknown, message}. Stream-inactive fires "error" +
auto-stop. Test-mode left intact via injectable getUserMedia + workletFactory.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: MicOverlay — failing test for colour function

**Files:**
- Test: `webui/tests-js/mic-overlay.test.js` (create)

- [ ] **Step 1: Write failing test.**

Create `webui/tests-js/mic-overlay.test.js`:

```js
// Tests for the live mic canvas overlay. We test the pure colour function
// directly + the draw method via a spy on CanvasRenderingContext2D calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.HTMLCanvasElement = dom.window.HTMLCanvasElement;
globalThis.ResizeObserver = class { observe() {} disconnect() {} };

import { centsToColourBucket, MicOverlay } from "../static/js/render/mic-overlay.js";

test("centsToColourBucket returns 'in' / 'slight' / 'off' / 'neutral' by threshold", () => {
  assert.equal(centsToColourBucket(0),    "in");
  assert.equal(centsToColourBucket(5),    "in");
  assert.equal(centsToColourBucket(-5),   "in");
  assert.equal(centsToColourBucket(15),   "slight");
  assert.equal(centsToColourBucket(-20),  "slight");
  assert.equal(centsToColourBucket(40),   "off");
  assert.equal(centsToColourBucket(-100), "off");
  assert.equal(centsToColourBucket(null), "neutral");
  assert.equal(centsToColourBucket(NaN),  "neutral");
});
```

- [ ] **Step 2: Run, confirm FAIL with "Cannot find module".**

```bash
node --test "tests-js/mic-overlay.test.js"
```
Expected: FAIL.

- [ ] **Step 3: No commit — implemented in Task 10.**

---

## Task 10: MicOverlay — implementation

**Files:**
- Create: `webui/static/js/render/mic-overlay.js`

- [ ] **Step 1: Implement.**

Create `webui/static/js/render/mic-overlay.js`:

```js
// Live-mic canvas overlay. Self-installs into the same .canvas-wrap host
// as F0Overlay (see f0-overlay.js:88-105 for the pattern we mirror).
// Drawn ABOVE F0Overlay in the layer stack.
//
// The renderer is pulled (not pushed): it owns no timer of its own — main.js
// calls `render()` whenever it needs a refresh (currently: when MicPitch
// emits 'sample', plus on viewState changes). For tear-free updates on
// fast scrolls, we also kick a one-shot rAF inside render() if dirty.

import { timeToX, midiToY } from "./coords.js";
import { CHORD_H, drumLaneHeight } from "./layout.js";

// Bucket thresholds. The neutral case fires when cents is null/NaN (no
// reference active, or the reference stem has no note at this song time).
const IN_CENTS = 5;
const SLIGHT_CENTS = 20;

export function centsToColourBucket(c) {
  if (c === null || c === undefined || Number.isNaN(c)) return "neutral";
  const a = Math.abs(c);
  if (a <= IN_CENTS) return "in";
  if (a <= SLIGHT_CENTS) return "slight";
  return "off";
}

// Resolve a bucket to an rgba string. Reads CSS tokens for theme parity
// (--ok / --warn / --err / --mic-accent); falls back to hex defaults.
function readToken(name, fallback) {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function strokeFor(bucket, clarity) {
  // alpha = 0.4 .. 1.0 from clarity.
  const alpha = 0.4 + 0.6 * Math.max(0, Math.min(1, clarity));
  const colour = ({
    in:      readToken("--ok", "#7fdc20"),
    slight:  readToken("--warn", "#e7c84a"),
    off:     readToken("--err", "#e7574a"),
    neutral: readToken("--mic-accent", "#a48cff"),
  })[bucket];
  return { colour, alpha };
}

export class MicOverlay {
  constructor(host, micPitch) {
    this.canvas = document.createElement("canvas");
    this.canvas.classList.add("mic");
    Object.assign(this.canvas.style, {
      position: "absolute",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      pointerEvents: "none",
      // Layer above F0Overlay (which has no explicit z-index, so any
      // positive value here wins in DOM order, but be explicit).
      zIndex: "3",
    });
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.dpr = window.devicePixelRatio || 1;
    this.canvasWrap = host;

    this.micPitch = micPitch;
    this.viewState = null;
    this.trackData = null;
    this._raf = 0;

    if (micPitch) {
      micPitch.addEventListener("sample", () => this._scheduleDraw());
    }
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => this._scheduleDraw()).observe(host);
    }
  }

  setViewState(vs) { this.viewState = vs; this._scheduleDraw(); }
  setTrackData(td) { this.trackData = td; this._scheduleDraw(); }

  _scheduleDraw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this.render();
    });
  }

  render() {
    const ctx = this.ctx;
    if (!this.micPitch || !this.viewState) return;

    const rect = this.canvasWrap.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;
    const targetW = Math.max(1, Math.round(cssW * this.dpr));
    const targetH = Math.max(1, Math.round(cssH * this.dpr));
    if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
      this.canvas.width = targetW;
      this.canvas.height = targetH;
    }
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const vs = this.viewState;
    const drumH = drumLaneHeight(this.trackData);
    const innerH = cssH - CHORD_H - drumH;

    // Visible song-time window.
    const tStart = vs.scrollSec - 1;
    const tEnd = vs.scrollSec + cssW / vs.zoomH + 1;
    const s = this.micPitch.getSamplesInRange(tStart, tEnd);
    if (s.time.length < 2) return;

    // Draw segment by segment so each segment can carry its own colour.
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let i = 0; i < s.time.length - 1; i++) {
      const t0 = s.time[i],     t1 = s.time[i + 1];
      const m0 = s.midi[i],     m1 = s.midi[i + 1];
      const c0 = s.cents[i],    cl0 = s.clarity[i] / 255;
      const bucket = centsToColourBucket(c0);
      const { colour, alpha } = strokeFor(bucket, cl0);
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = colour;
      ctx.beginPath();
      ctx.moveTo(timeToX(t0, vs), midiToY(m0, vs, innerH));
      ctx.lineTo(timeToX(t1, vs), midiToY(m1, vs, innerH));
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
}
```

- [ ] **Step 2: Run the colour-function test, confirm pass.**

```bash
node --test "tests-js/mic-overlay.test.js"
```
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/static/js/render/mic-overlay.js webui/tests-js/mic-overlay.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): MicOverlay canvas + cents bucket colouring

Self-installs into .canvas-wrap above F0Overlay (z-index 3). Segment-by-
segment stroke so each segment carries its own bucket colour (in/slight/
off/neutral) and clarity-modulated alpha. Reads --ok/--warn/--err/
--mic-accent CSS tokens with hex fallbacks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: MicOverlay — draw-pipeline spy test

**Files:**
- Test: `webui/tests-js/mic-overlay.test.js` (append)

- [ ] **Step 1: Append a test that verifies render() makes the expected canvas calls.**

```js
test("MicOverlay.render calls beginPath/moveTo/lineTo/stroke for each consecutive pair", () => {
  // Fake host with getBoundingClientRect.
  const host = document.createElement("div");
  Object.defineProperty(host, "getBoundingClientRect", {
    value: () => ({ width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600 }),
  });
  document.body.appendChild(host);

  // Stub MicPitch.
  const fakeSamples = {
    time:    new Float32Array([1.0, 1.1, 1.2]),
    midi:    new Uint8Array([60, 62, 60]),
    cents:   new Float32Array([0, 30, -3]),
    clarity: new Uint8Array([255, 200, 100]),
  };
  const fakeMic = new (class extends EventTarget {
    getSamplesInRange() { return fakeSamples; }
  })();

  const overlay = new MicOverlay(host, fakeMic);

  // Spy on ctx.
  let beginCount = 0, strokeCount = 0;
  const ctx = overlay.canvas.getContext("2d");
  // jsdom's CanvasRenderingContext2D is a stub; we monkey-patch counters.
  const origBegin = ctx.beginPath.bind(ctx);
  const origStroke = ctx.stroke.bind(ctx);
  ctx.beginPath = () => { beginCount++; origBegin(); };
  ctx.stroke = () => { strokeCount++; origStroke(); };

  overlay.setViewState({ scrollSec: 0, zoomH: 100, zoomV: 8, scrollMidi: 60 });
  overlay.render();
  // 3 samples → 2 segments → 2 beginPath / 2 stroke.
  assert.equal(beginCount, 2);
  assert.equal(strokeCount, 2);
});
```

- [ ] **Step 2: Run, confirm pass.**

```bash
node --test "tests-js/mic-overlay.test.js"
```
Expected: 2 PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-overlay.test.js
git commit -m "test(webui/mic): MicOverlay render() segment-count spy

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: MicRow — failing test for row DOM + reference dropdown

**Files:**
- Test: `webui/tests-js/mic-row.test.js` (create)

- [ ] **Step 1: Write failing test.**

Create `webui/tests-js/mic-row.test.js`:

```js
// Tests for the Live Input sidebar row.
import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;

import { MicRow } from "../static/js/ui/mic-row.js";

function fakeMic() {
  return new (class extends EventTarget {
    _ref = null; _off = 0; _dev = null; _running = false;
    setReferenceStem(s) { this._ref = s; }
    setOffsetMs(n) { this._off = n; }
    setDeviceId(d) { this._dev = d; }
    getOffsetMs() { return this._off; }
    getReferenceStem() { return this._ref; }
    isRunning() { return this._running; }
    async start() { this._running = true; this.dispatchEvent(new Event("started")); }
    stop() { this._running = false; this.dispatchEvent(new Event("stopped")); }
  })();
}

function fakeTrackData(notesPresent = ["vocals", "piano"]) {
  const td = { notes: {} };
  for (const name of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
    td.notes[name] = notesPresent.includes(name)
      ? { t: new Float32Array([0]), dur: new Float32Array([1]), midi: new Uint8Array([60]), transcribed: true }
      : { t: new Float32Array(), dur: new Float32Array(), midi: new Uint8Array(), transcribed: false };
  }
  return td;
}

test("MicRow renders label 'Live Input' + an M button", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const row = new MicRow({ host, micPitch: fakeMic(), trackData: fakeTrackData() });
  row.mount();
  assert.match(host.textContent, /Live Input/);
  assert.ok(host.querySelector(".btn.m"), "expected .btn.m mute button");
});

test("MicRow reference dropdown lists only stems with notes (plus 'none')", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const row = new MicRow({
    host,
    micPitch: fakeMic(),
    trackData: fakeTrackData(["vocals", "bass"]),
  });
  row.mount();
  const opts = [...host.querySelectorAll("select.mic-ref option")].map((o) => o.value);
  assert.deepEqual(opts.sort(), ["bass", "none", "vocals"]);
});
```

- [ ] **Step 2: Run, confirm FAIL.**

```bash
node --test "tests-js/mic-row.test.js"
```
Expected: FAIL.

- [ ] **Step 3: No commit — implemented in Task 13.**

---

## Task 13: MicRow — implementation

**Files:**
- Create: `webui/static/js/ui/mic-row.js`

- [ ] **Step 1: Implement.**

Create `webui/static/js/ui/mic-row.js`:

```js
// "Live Input" pseudo-stem row in the sidebar, sitting above the existing
// six stem rows. Mirrors the visual anatomy of the regular stem rows
// (colour swatch + label + M button + status dot) plus an expanded
// control sub-row (reference dropdown + device picker + offset slider).
//
// Settings persisted to localStorage under "musiq.mic.*". No auto-start
// on page load — start() requires the M-click user gesture for the
// browser permission flow.

import { el, clear } from "./dom.js";

const STEM_LABEL = {
  vocals: "Vocals", piano: "Piano", other: "Other",
  guitar: "Guitar", bass: "Bass", drums: "Drums",
};

const LS_OFFSET = "musiq.mic.offsetMs";
const LS_REF    = "musiq.mic.referenceStem";
const LS_DEVICE = "musiq.mic.deviceId";

function loadOffset() {
  const n = Number(localStorage.getItem(LS_OFFSET));
  return Number.isFinite(n) ? n : -30;
}
function loadRef() {
  const v = localStorage.getItem(LS_REF);
  return v == null ? "vocals" : v;     // default reference is vocals
}
function loadDevice() {
  return localStorage.getItem(LS_DEVICE) || null;
}

function availableStems(trackData) {
  const present = [];
  for (const name of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
    const pack = trackData?.notes?.[name];
    if (pack && (pack.t?.length > 0 || pack.drums)) present.push(name);
  }
  return present;
}

export class MicRow {
  constructor({ host, micPitch, trackData }) {
    this.host = host;
    this.mic = micPitch;
    this.trackData = trackData;
    this._readoutEl = null;
    this._statusDotEl = null;
    this._refSelectEl = null;
    this._offsetInputEl = null;
    this._mBtnEl = null;
    this._onSample = (e) => this._updateReadout(e.detail);
    this._onError = (e) => this._showError(e.detail);
    this._onStarted = () => this._setEnabled(true);
    this._onStopped = () => this._setEnabled(false);
  }

  mount() {
    clear(this.host);

    // Apply persisted settings.
    const offset = loadOffset();
    const ref = loadRef();
    const dev = loadDevice();
    this.mic.setOffsetMs(offset);
    // Reference is only honoured if it exists in this track; else fall back to first present stem.
    const present = availableStems(this.trackData);
    const refToUse = ref === "none" || present.includes(ref)
      ? ref
      : (present[0] ?? "none");
    this.mic.setReferenceStem(refToUse === "none" ? null : refToUse);
    if (dev) this.mic.setDeviceId(dev);

    // ----- Row 1: always-visible header -----
    const swatch = el("div", {
      class: "stem-swatch mic-swatch",
      attrs: { title: "Live microphone input. Tip: wear headphones — speaker playback will bleed into the mic and confuse the pitch detector." },
    });
    const label = el("div", { class: "stem-label", text: "Live Input" });
    const mBtn = el("div", { class: "btn m", text: "M", onClick: () => this._toggle() });
    this._mBtnEl = mBtn;
    const statusDot = el("div", { class: "status-dot status-off" });
    this._statusDotEl = statusDot;
    const readout = el("div", { class: "mic-readout", text: "—" });
    this._readoutEl = readout;
    const row1 = el("div", { class: "side-stem-row mic-row" }, [
      swatch, label, mBtn, statusDot, readout,
    ]);

    // ----- Row 2: controls (reference / device / offset) -----
    const refSelect = el("select", { class: "mic-ref" });
    const optsForRef = ["none", ...present];
    for (const v of optsForRef) {
      const opt = el("option", { attrs: { value: v }, text: v === "none" ? "none" : STEM_LABEL[v] });
      if (v === refToUse) opt.selected = true;
      refSelect.appendChild(opt);
    }
    refSelect.addEventListener("change", () => {
      const v = refSelect.value;
      localStorage.setItem(LS_REF, v);
      this.mic.setReferenceStem(v === "none" ? null : v);
    });
    this._refSelectEl = refSelect;

    const offsetInput = el("input", {
      class: "mic-offset",
      attrs: { type: "range", min: "-150", max: "50", step: "1", value: String(offset) },
    });
    const offsetLabel = el("span", { class: "mic-offset-label", text: `${offset} ms` });
    offsetInput.addEventListener("input", () => {
      const n = Number(offsetInput.value) || 0;
      offsetLabel.textContent = `${n} ms`;
      localStorage.setItem(LS_OFFSET, String(n));
      this.mic.setOffsetMs(n);
    });
    this._offsetInputEl = offsetInput;

    const row2 = el("div", { class: "mic-controls" }, [
      el("label", { text: "Match: " }), refSelect,
      el("label", { text: " Offset: " }), offsetInput, offsetLabel,
    ]);

    const wrap = el("div", { class: "mic-row-wrap" }, [row1, row2]);
    this.host.appendChild(wrap);

    // Subscribe.
    this.mic.addEventListener("sample", this._onSample);
    this.mic.addEventListener("error", this._onError);
    this.mic.addEventListener("started", this._onStarted);
    this.mic.addEventListener("stopped", this._onStopped);

    this._setEnabled(this.mic.isRunning());
  }

  unmount() {
    this.mic.removeEventListener("sample", this._onSample);
    this.mic.removeEventListener("error", this._onError);
    this.mic.removeEventListener("started", this._onStarted);
    this.mic.removeEventListener("stopped", this._onStopped);
    clear(this.host);
  }

  setTrackData(td) {
    this.trackData = td;
    // Re-mount to refresh the reference dropdown's options.
    this.mount();
  }

  async _toggle() {
    if (this.mic.isRunning()) {
      this.mic.stop();
    } else {
      try { await this.mic.start(); }
      catch { /* error event already dispatched */ }
    }
  }

  _setEnabled(on) {
    this._mBtnEl?.classList.toggle("on", on);
    this._statusDotEl?.classList.toggle("status-off", !on);
    this._statusDotEl?.classList.toggle("status-live", on);
    if (!on) this._readoutEl && (this._readoutEl.textContent = "—");
  }

  _updateReadout(detail) {
    if (!this._readoutEl) return;
    const { midi, cents } = detail;
    if (!midi || !Number.isFinite(midi)) { this._readoutEl.textContent = "—"; return; }
    // formatPitch dependency is wired in Task 15 (which adds the import +
    // key/notation hookup). For now: integer MIDI + cents readout.
    const intMidi = Math.round(midi);
    const noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
    const name = noteNames[((intMidi % 12) + 12) % 12];
    const oct = Math.floor(intMidi / 12) - 1;
    let txt = `${name}${oct}`;
    if (cents !== null && Number.isFinite(cents)) {
      const sign = cents >= 0 ? "+" : "−";
      txt += `  ${sign}${Math.abs(cents).toFixed(0)}¢`;
    }
    this._readoutEl.textContent = txt;
  }

  _showError(detail) {
    if (!this._readoutEl) return;
    const code = detail?.code ?? "unknown";
    const msg = {
      permission: "Mic access denied",
      "no-device": "No microphone found",
      unsupported: "Browser unsupported",
      disconnected: "Mic disconnected",
    }[code] ?? detail?.message ?? "Mic error";
    this._readoutEl.textContent = msg;
  }
}
```

- [ ] **Step 2: Run, confirm Task 12's tests pass.**

```bash
node --test "tests-js/mic-row.test.js"
```
Expected: 2 PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/static/js/ui/mic-row.js webui/tests-js/mic-row.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): MicRow sidebar row (M, reference picker, offset slider)

Persists offsetMs / referenceStem / deviceId under localStorage musiq.mic.*.
Default reference = vocals (auto-falls-back to first non-empty stem if
vocals is empty). M-click toggles start/stop. Subscribes to MicPitch's
"sample" / "error" / "started" / "stopped" events.

Notation hookup deferred to Task 15.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: MicRow — offset persistence + M-toggle behaviour tests

**Files:**
- Test: `webui/tests-js/mic-row.test.js` (append)

- [ ] **Step 1: Append tests.**

```js
test("MicRow persists offset slider changes to localStorage", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData() });
  row.mount();
  const input = host.querySelector("input.mic-offset");
  input.value = "-50";
  input.dispatchEvent(new dom.window.Event("input"));
  assert.equal(localStorage.getItem("musiq.mic.offsetMs"), "-50");
  assert.equal(mic.getOffsetMs(), -50);
});

test("MicRow M-button toggles mic.start/stop and updates status dot", async () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData() });
  row.mount();
  const btn = host.querySelector(".btn.m");
  const dot = host.querySelector(".status-dot");
  assert.ok(dot.classList.contains("status-off"));
  btn.click();
  // start() is async; wait a microtask.
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(dot.classList.contains("status-live"));
  btn.click();
  assert.ok(dot.classList.contains("status-off"));
});

test("MicRow reference falls back to first present stem if persisted ref is missing", () => {
  localStorage.clear();
  localStorage.setItem("musiq.mic.referenceStem", "guitar");  // not present
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData(["vocals", "bass"]) });
  row.mount();
  // Fell back to "vocals" (first present).
  assert.equal(mic.getReferenceStem(), "vocals");
});
```

- [ ] **Step 2: Run, confirm pass.**

```bash
node --test "tests-js/mic-row.test.js"
```
Expected: 5 PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-row.test.js
git commit -m "test(webui/mic): MicRow offset persistence + M toggle + ref fallback

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: MicRow — wire `formatPitch` for notation-aware readout

**Files:**
- Modify: `webui/static/js/ui/mic-row.js`

- [ ] **Step 1: Replace the placeholder note-name code with the real notation pipeline.**

In `webui/static/js/ui/mic-row.js`, add imports at top:

```js
import { formatPitch, parseKey } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";
```

Then replace the body of `_updateReadout` with:

```js
  _updateReadout(detail) {
    if (!this._readoutEl) return;
    const { midi, cents } = detail;
    if (!midi || !Number.isFinite(midi)) { this._readoutEl.textContent = "—"; return; }
    const intMidi = Math.round(midi);
    const keyParse = parseKey(this.trackData?.meta?.key ?? "");
    const system = getNotationSystem();
    let name;
    try {
      name = formatPitch(intMidi, keyParse, system);
    } catch {
      // formatPitch may not exist in jsdom test envs; fall back.
      const noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
      const oct = Math.floor(intMidi / 12) - 1;
      name = `${noteNames[((intMidi % 12) + 12) % 12]}${oct}`;
    }
    let txt = name;
    if (cents !== null && Number.isFinite(cents)) {
      const sign = cents >= 0 ? "+" : "−";
      txt += `  ${sign}${Math.abs(cents).toFixed(0)}¢`;
    }
    this._readoutEl.textContent = txt;
  }
```

Also subscribe to notation changes in `mount()`, just after the other subscriptions:

```js
    this._onNotationChanged = () => {
      // Re-render the last seen sample (cheap — _lastReadoutDetail is set on every sample).
      if (this._lastReadoutDetail) this._updateReadout(this._lastReadoutDetail);
    };
    window.addEventListener("musiq:notation-changed", this._onNotationChanged);
```

And cache the last detail in `_updateReadout`:

```js
    this._lastReadoutDetail = detail;
```

And remove the listener in `unmount()`:

```js
    window.removeEventListener("musiq:notation-changed", this._onNotationChanged);
```

- [ ] **Step 2: Append a test that asserts readout flips with notation system.**

Append to `webui/tests-js/mic-row.test.js`:

```js
test("MicRow readout reformats on musiq:notation-changed", () => {
  localStorage.clear();
  // Default notation = scientific.
  localStorage.setItem("musiq.notation", "scientific");
  const host = document.createElement("div");
  const mic = fakeMic();
  const td = fakeTrackData();
  td.meta = { key: "C major" };
  const row = new MicRow({ host, micPitch: mic, trackData: td });
  row.mount();
  // Push a sample with MIDI 69 (A4).
  mic.dispatchEvent(new CustomEvent("sample", { detail: { midi: 69, cents: 0, freq: 440, clarity: 1, rms: 0.1 }}));
  const readout = host.querySelector(".mic-readout");
  // Scientific: should contain "A4".
  assert.match(readout.textContent, /A4/);
  // Switch to solfège.
  localStorage.setItem("musiq.notation", "solfege");
  window.dispatchEvent(new dom.window.Event("musiq:notation-changed"));
  assert.match(readout.textContent, /La4|La/);
});
```

- [ ] **Step 3: Run, confirm pass.**

```bash
node --test "tests-js/mic-row.test.js"
```
Expected: 6 PASS.

- [ ] **Step 4: Commit.**

```bash
git add webui/static/js/ui/mic-row.js webui/tests-js/mic-row.test.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): MicRow readout uses formatPitch + listens to notation-changed

Pitch labels now obey the user's notation preference (Scientific / Solfège /
Sharp / Flat / etc.) via the existing static/js/music/notation.js
pipeline. The readout re-renders on musiq:notation-changed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Sidebar wiring — inject MicRow above the stem loop

**Files:**
- Modify: `webui/static/js/ui/sidebar.js`

- [ ] **Step 1: Add the import + injection.**

Read `webui/static/js/ui/sidebar.js` around line 243 (`_buildTracksSection`) and around line 252 (`heading = el("h4", { text: "Stems" })`).

Add at the top of the file (alongside existing imports):

```js
import { MicRow } from "./mic-row.js";
```

Modify `_buildTracksSection` to inject the MicRow right after the header row, before the stem loop. Find:

```js
    const heading = el("h4", { text: "Stems" });
    const headerRow = el("div", { class: "side-section-header" }, [heading]);
    sect.appendChild(headerRow);
```

Replace with:

```js
    const heading = el("h4", { text: "Stems" });
    const headerRow = el("div", { class: "side-section-header" }, [heading]);
    sect.appendChild(headerRow);

    // Live Input pseudo-stem row — sits above the regular six. Only mounted
    // if the page has a MicPitch instance attached to window.__musiqMic
    // (wired in main.js). Falling back to "not mounted" keeps existing
    // tests + headless renders unaffected.
    if (window.__musiqMic) {
      const micHost = el("div", { class: "mic-row-host" });
      sect.appendChild(micHost);
      if (this._micRow) this._micRow.unmount();
      this._micRow = new MicRow({
        host: micHost,
        micPitch: window.__musiqMic,
        trackData: this.trackData,
      });
      this._micRow.mount();
    }
```

- [ ] **Step 2: Run the existing sidebar-adjacent tests to make sure no regression.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/*.test.js"
```
Expected: all green. Pay particular attention to `track-picker.test.js`, `tags-row.test.js`, and `xcheck.test.js` (the ones that may exercise nearby sidebar code).

- [ ] **Step 3: Commit.**

```bash
git add webui/static/js/ui/sidebar.js
git commit -m "$(cat <<'EOF'
feat(webui/sidebar): inject MicRow above the six stem rows

Guarded on window.__musiqMic so headless / test renders without a
microphone subsystem stay untouched. main.js wires window.__musiqMic
before mounting the sidebar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Theme — add `--mic-accent` CSS token + row layout styles

**Files:**
- Modify: `webui/static/css/main.css` (or whichever stylesheet currently defines the stem-swatch / side-stem-row classes — find it before editing)

- [ ] **Step 1: Locate the stylesheet that defines the stem-row classes.**

```bash
cd "<PROJECT_PATH>/webui"
grep -rln "stem-swatch\|side-stem-row\|status-dot" static/css 2>/dev/null
```

You will get one or two files. Use whichever defines `.side-stem-row`. Confirm with:

```bash
grep -n "side-stem-row\|stem-swatch\|status-dot" $(grep -rln "side-stem-row" static/css | head -1)
```

- [ ] **Step 2: Append mic-row styles to that stylesheet.**

Append (at the end of the located stylesheet):

```css
/* ---- Live Input row (Task 17 of live-mic-pitch plan) -------------------- */
:root {
  --mic-accent: #a48cff;     /* default neutral / row swatch */
}
.mic-row-host { padding: 4px 8px; }
.mic-row .mic-swatch { background: var(--mic-accent); }
.mic-readout {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--fg-dim, #888);
}
.mic-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 4px 6px 24px;
  font-size: 11px;
  color: var(--fg-dim, #888);
}
.mic-controls select { font-size: 11px; }
.mic-offset { width: 100px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; margin: 0 6px; }
.status-dot.status-off  { background: #555; }
.status-dot.status-live { background: var(--ok, #7fdc20); box-shadow: 0 0 4px var(--ok, #7fdc20); }
```

- [ ] **Step 3: No new test — visual. Commit.**

```bash
git add webui/static/css/
git commit -m "$(cat <<'EOF'
style(webui/mic): --mic-accent token + Live Input row layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: main.js — instantiate MicPitch + MicOverlay; clear ring on track change

**Files:**
- Modify: `webui/static/js/main.js`

- [ ] **Step 1: Add imports at top (next to other render/audio imports).**

```js
import { MicPitch } from "./audio/mic-pitch.js";
import { MicOverlay } from "./render/mic-overlay.js";
```

- [ ] **Step 2: Find `f0Overlay = new F0Overlay(canvasWrap);` (around main.js:319).**

Right after `f0Overlay.setViewState(viewState);` (around main.js:321), add:

```js
  // Live mic layer — one MicPitch + one MicOverlay per page load. We
  // attach the MicPitch to window.__musiqMic before the sidebar mounts
  // so sidebar.js can inject the MicRow guarded on its presence.
  if (!window.__musiqMic) {
    window.__musiqMic = new MicPitch({ engine });
  } else {
    // Hot-reload / track-change: keep the existing mic running but
    // re-point its engine reference (engines are re-created per track).
    window.__musiqMic.engine = engine;
    window.__musiqMic.clearBuffer();
  }
  window.__musiqMic.setTrackData(trackData);
  micOverlay = new MicOverlay(canvasWrap, window.__musiqMic);
  micOverlay.setTrackData(trackData);
  micOverlay.setViewState(viewState);

  // Page-unload cleanup so the OS mic indicator releases promptly. We
  // attach once and idempotently — re-loading a track will re-call this
  // path, but addEventListener with the same handler dedupes by identity
  // and we hold the reference on window so it stays stable.
  if (!window.__musiqMicUnloadAttached) {
    window.__musiqMicUnloadAttached = true;
    window.addEventListener("beforeunload", () => { try { window.__musiqMic?.stop(); } catch { /* */ } });
  }
```

Also declare `let micOverlay;` near the other `let f0Overlay;` / `let pianoRoll;` declarations near the top of the module.

- [ ] **Step 3: No automated test — wiring is verified by Task 19's integration test + Task 21's e2e. Smoke-test manually next.**

- [ ] **Step 4: Run all unit tests, confirm zero regression.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/*.test.js"
```
Expected: all green.

- [ ] **Step 5: Manual smoke (run the webui, sanity-check page loads without console errors).**

```bash
cd "<PROJECT_PATH>/webui"
./webui.ps1 restart
./webui.ps1 status
```
Then open `http://127.0.0.1:8765` in Chrome. Open DevTools. Verify:
- The page loads.
- The Stems section in the sidebar now has a "Live Input" row at the top, with M / status-dot / "—" readout.
- DevTools console has no errors. (Warnings from existing surfaces are OK; new errors are not.)

- [ ] **Step 6: Commit.**

```bash
git add webui/static/js/main.js
git commit -m "$(cat <<'EOF'
feat(webui/mic): wire MicPitch + MicOverlay into main.js

MicPitch is a page-singleton on window.__musiqMic so the sidebar can
guard MicRow on its presence (see ui/sidebar.js). On track change we
keep the mic running but re-point the engine ref + clear the ring
buffer (so the user's stale samples don't bleed into the new track's
timeline).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Integration test — round-trip from synthetic mic stream to ring buffer

**Files:**
- Create: `webui/tests-js/mic-pitch-integration.test.js`

- [ ] **Step 1: Write the integration test.**

Create `webui/tests-js/mic-pitch-integration.test.js`:

```js
// Integration test for the live-mic chain. We wire a real MicPitch to
// fake engine + fake audioContext + fake worklet, then push a sequence
// of synthetic Yin-output messages and assert the ring buffer ends up
// with the right (song-time, midi) pairs.
//
// (Spinning up a real AudioContext + Worklet in node:test is not
// available — that's why this test injects fakes at the seam.)

import { test } from "node:test";
import assert from "node:assert/strict";

import { MicPitch } from "../static/js/audio/mic-pitch.js";

test("MicPitch integration: synthetic melody fills the ring buffer at the right offsets", () => {
  // Engine + ctx walk forward together.
  let song = 10.0, ctx = 5.0;
  const engine = { get currentTime() { return song; }, isPlaying: true, on() {}, off() {} };
  const audioContext = { get currentTime() { return ctx; } };

  const node = { port: { onmessage: null, postMessage() {} } };
  const factory = () => node;
  const mic = new MicPitch({ engine, audioContext, workletFactory: factory });
  mic._attachForTest();

  // Synthetic melody: 5 frames, 50 ms apart, freqs 220, 247, 261, 247, 220
  // (A3, B3, C4, B3, A3).
  const seq = [
    [220.000, 57], [246.942, 59], [261.626, 60], [246.942, 59], [220.000, 57],
  ];
  for (let i = 0; i < seq.length; i++) {
    const [hz, expectedMidi] = seq[i];
    song += 0.05;
    ctx  += 0.05;
    // Worklet processes the block at ctxTime = current ctx (so block age = 0).
    node.port.onmessage({ data: { freq: hz, clarity: 0.95, rms: 0.1, ctxTime: ctx }});
    const samples = mic.getSamplesInRange(-1e6, 1e6);
    assert.equal(samples.midi[samples.midi.length - 1], expectedMidi,
      `frame ${i}: expected MIDI ${expectedMidi} for ${hz} Hz, got ${samples.midi[samples.midi.length - 1]}`);
  }
  // Final state.
  const s = mic.getSamplesInRange(-1e6, 1e6);
  assert.equal(s.time.length, 5);
  // Times should be monotonically increasing.
  for (let i = 1; i < s.time.length; i++) {
    assert.ok(s.time[i] > s.time[i - 1], `times not monotonic at ${i}`);
  }
});
```

- [ ] **Step 2: Run, confirm pass.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/mic-pitch-integration.test.js"
```
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add webui/tests-js/mic-pitch-integration.test.js
git commit -m "$(cat <<'EOF'
test(webui/mic): integration — synthetic melody fills ring buffer correctly

Walks a 5-frame A3-B3-C4-B3-A3 melody through the MicPitch coordinator
with fake engine + ctx + worklet, asserts midi values + monotonic
song-time stamps in the ring buffer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Run the full suite

**Files:** none.

- [ ] **Step 1: Run everything.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/*.test.js" 2>&1 | tee /tmp/test-output.txt
```
Expected: all PASS. If anything fails, fix in-place before continuing — do not move to e2e on a red baseline.

- [ ] **Step 2: Print the summary line.**

```bash
grep -E "^# (pass|fail|tests)" /tmp/test-output.txt
```
Expected: `# fail 0`.

- [ ] **Step 3: No commit.**

---

## Task 21: Playwright e2e — fake mic stream

**Files:**
- Create: `webui/tests-e2e/live-mic.spec.js`

- [ ] **Step 1: Inspect an existing spec to mirror the launch + page-fixture conventions.**

```bash
cd "<PROJECT_PATH>/webui"
cat tests-e2e/viewer.spec.js | head -40
cat tests-e2e/playwright.config.js
```

- [ ] **Step 2: Generate a 5-second 440 Hz WAV fixture for `--use-file-for-fake-audio-capture`.**

```bash
cd "<PROJECT_PATH>/webui"
mkdir -p tests-e2e/fixtures
# Use Python (available on the project venv) to write the WAV — keeps the
# generation reproducible and doesn't depend on ffmpeg in CI.
python -c "
import wave, struct, math
sr = 48000
dur = 5
amp = 0.3
f = 440.0
with wave.open('tests-e2e/fixtures/mic-440hz.wav', 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    for n in range(sr*dur):
        s = int(amp * 32767 * math.sin(2*math.pi*f*n/sr))
        w.writeframes(struct.pack('<h', s))
print('wrote tests-e2e/fixtures/mic-440hz.wav')
"
```

Expected: prints the "wrote" line; file exists at `tests-e2e/fixtures/mic-440hz.wav`.

- [ ] **Step 3: Create the spec.**

Create `webui/tests-e2e/live-mic.spec.js`:

```js
// E2E: enable the Live Input mic with a fake audio stream (a 440 Hz sine),
// open a track in the viewer, click M, assert the row activates + the
// readout updates + the overlay canvas accumulates strokes.
//
// Launches Chromium with --use-fake-device-for-media-stream +
// --use-file-for-fake-audio-capture so the mic input is deterministic.
import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(__dirname, "fixtures/mic-440hz.wav");

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${FIXTURE}`,
    ],
  },
  permissions: ["microphone"],
});

test("Live Input row activates and the readout updates", async ({ page, context }) => {
  await context.grantPermissions(["microphone"], { origin: "http://127.0.0.1:8765" });
  await page.goto("http://127.0.0.1:8765/");

  // Pick the first track from the picker.
  const firstTrack = page.locator(".track-card").first();
  await firstTrack.waitFor({ state: "visible", timeout: 15000 });
  await firstTrack.click();

  // Wait for the viewer + the Live Input row.
  const micRow = page.locator(".mic-row");
  await micRow.waitFor({ state: "visible", timeout: 15000 });

  // Click M to enable.
  const mBtn = micRow.locator(".btn.m");
  await mBtn.click();

  // Status dot should flip to live within 2 s.
  const statusDot = micRow.locator(".status-dot");
  await expect(statusDot).toHaveClass(/status-live/, { timeout: 2000 });

  // Readout should update from "—" to something with a digit (cents) or note name.
  const readout = micRow.locator(".mic-readout");
  await expect(readout).not.toHaveText("—", { timeout: 3000 });

  // Click M again to stop.
  await mBtn.click();
  await expect(statusDot).toHaveClass(/status-off/, { timeout: 2000 });
  await expect(readout).toHaveText("—");
});
```

- [ ] **Step 4: Start the webui server (it must be running for the e2e to hit it).**

```bash
cd "<PROJECT_PATH>/webui"
./webui.ps1 restart
./webui.ps1 status
```
Expected: `running on http://127.0.0.1:8765`.

- [ ] **Step 5: Run the new spec.**

```bash
cd "<PROJECT_PATH>/webui/tests-e2e"
npm test -- live-mic.spec.js
```
Expected: PASS. If "no track found" — the test env may not have a cached track; in that case, the test should be marked `test.skip` with a clear reason and we surface this to the user for a follow-up. Do NOT modify the test to pass under no-data conditions silently.

- [ ] **Step 6: Commit.**

```bash
cd "<PROJECT_PATH>"
git add webui/tests-e2e/live-mic.spec.js webui/tests-e2e/fixtures/mic-440hz.wav
git commit -m "$(cat <<'EOF'
test(webui/mic): playwright e2e — Live Input activates with fake mic stream

Launches Chromium with --use-file-for-fake-audio-capture pointed at a
deterministic 5-second 440 Hz WAV, drives the M button, asserts the
status dot flips live and the readout updates within timeout windows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Manual smoke — run the user-facing checklist on JINN

**Files:** none modified.

- [ ] **Step 1: Make sure the webui is running.**

```bash
cd "<PROJECT_PATH>/webui"
./webui.ps1 status
```
Expected: running. If not: `./webui.ps1 restart`.

- [ ] **Step 2: Open http://127.0.0.1:8765 in Chrome (not the playwright session — a real browser session for the real mic).**

- [ ] **Step 3: Walk through the 7-step checklist from the spec.**

For each step, capture in a scratch note (`/tmp/mic-smoke.md` is fine) whether it PASSED or FAILED, with a one-line reason if failed.

1. Open a track. Sing C4, then C5. Ribbon appears at roughly the right MIDI value.
2. Change the reference dropdown from "vocals" to "piano" (or "bass"); colour bands should shift to match wherever the new reference's notes land.
3. Slide the offset slider left/right; ribbon translates horizontally (later/earlier).
4. Switch the global notation system in settings (Scientific ↔ Solfège); readout label changes (e.g., "F♯4" → "Fa♯4").
5. Switch to a different track. Ribbon clears. Mic stays on (status dot remains green).
6. Click M to disable. The browser's mic-in-use indicator (red dot on the tab) goes away within ~1 s.
7. Deny permission once: click M (when not yet enabled), reject in the OS prompt. Row should show "Mic access denied". Click M again, grant, recover into the live state.

- [ ] **Step 4: If any step fails, file a follow-up issue and STOP — do not declare the feature shipped.**

If all pass:

- [ ] **Step 5: Commit the smoke note as `install-logs/live-mic-smoke-2026-05-22.md` for the project history.**

```bash
cd "<PROJECT_PATH>"
cp /tmp/mic-smoke.md install-logs/live-mic-smoke-$(date +%F).md
git add install-logs/live-mic-smoke-*.md
git commit -m "$(cat <<'EOF'
docs(install-logs): live-mic 7-step smoke pass

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Update CLAUDE.md with a one-line pointer to the new feature

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read the project-instructions section to find the right insertion point.**

Open `<PROJECT_PATH>/CLAUDE.md` and find the block where other webui-side features are mentioned (the WASAPI engine paragraph is a good anchor).

- [ ] **Step 2: Add one paragraph below the WASAPI engine paragraph.**

Insert (verbatim — keep the cross-link format consistent with the rest of the file):

```markdown
   **Live mic-pitch layer (May 2026)** — browser-only "Live Input" pseudo-stem above the existing six rows, showing the user's microphone pitch contour drawn in real time pinned to the song timeline. Cents-off colouring vs a user-selectable reference stem (default vocals). YIN in an AudioWorklet, ring-buffered on the main thread, rendered above the F0 overlay. Per-user offset slider compensates for browser mic input latency (Web Audio doesn't expose it). Spec: [`docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md`](docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md). Lesson: forcing `echoCancellation/noiseSuppression/AGC = false` in `getUserMedia` constraints is mandatory — the browser's default "voice" DSP destroys pitch information.
```

- [ ] **Step 3: Commit.**

```bash
cd "<PROJECT_PATH>"
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude.md): add live mic-pitch layer pointer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 24: Final verification gate

**Files:** none.

- [ ] **Step 1: Re-run the full unit suite.**

```bash
cd "<PROJECT_PATH>/webui"
node --test "tests-js/*.test.js"
```
Expected: all PASS.

- [ ] **Step 2: Re-run the e2e.**

```bash
cd "<PROJECT_PATH>/webui/tests-e2e"
npm test -- live-mic.spec.js
```
Expected: PASS (or skip-with-reason if no cached track).

- [ ] **Step 3: Confirm git log shows ~14 feature commits since the spec.**

```bash
cd "<PROJECT_PATH>"
git log --oneline 9436b38..HEAD
```
Expected: a clean run of `feat(webui/mic): …` / `test(webui/mic): …` / `docs(…): …` commits in order.

- [ ] **Step 4: Done.** Feature is shipped; no PR required (project commits straight to main, per `[[branching_workflow]]`).

---

## Out-of-scope reminders (do NOT do as part of this plan)

- **No** take recording / WAV export / per-track persistence.
- **No** click-track latency calibration wizard.
- **No** alternative estimators (CREPE / FCPE / pYIN) — even though `mic-yin-processor.js` is structured to allow swap-in later.
- **No** ScriptProcessorNode fallback.
- **No** server-side mic capture.
- **No** automatic AEC against song bleed.
- **No** auto-pause on silence.
- **No** sensitivity slider (RMS gate fixed at 0.005).
- **No** spectrogram / FFT visualisation.
- **No** in-row device picker UI. `MicPitch.setDeviceId()` is callable + persisted, but a proper picker needs the post-permission `enumerateDevices()` refresh dance (labels are anonymized before permission is granted). v1 uses the system default device; per-device selection is a v1.5 follow-up. Users can change the default device in Windows Sound settings.

These are listed so an over-eager implementer doesn't drift in.

---

## Executed (2026-05-22 → 2026-05-23)

This plan was executed end-to-end via subagent-driven-development (24 tasks, ~28 commits including bug-fix iterations from per-task code review). Six bugs found-and-fixed during the per-chunk reviews; two more (the staircase quantization + silence-gap bridging) surfaced during user manual smoke and were fixed within the same day, plus one visual polish pass that rebuilt MicRow on the existing `.track-row` grid.

For the authoritative current state of the code, see:

- **Post-ship deltas section** in `docs/superpowers/specs/2026-05-22-live-mic-pitch-layer-design.md` — what changed between this plan's task definitions and what actually shipped.
- **Ship report**: `install-logs/live-mic-results-2026-05-23.md` — outcome summary + bug list + lessons.
- **Memory entry**: `[[live_mic_layer_shipped]]` — concise pointer for future sessions.

The task-by-task code snippets in this plan are preserved as a historical artifact of how the work was decomposed; do NOT use them as a reference for current behaviour. The git log between `3d8258c` and HEAD is the authoritative source.
