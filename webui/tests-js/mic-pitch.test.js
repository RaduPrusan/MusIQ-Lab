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
  // 440 Hz → MIDI 69.0 exact in tempered tuning. Ring stores Float32, so we
  // compare with a tolerance — the staircase-quantization bug fix in
  // dcd5c56 made this a float not a Uint8.
  assert.ok(Math.abs(samples.midi[0] - 69) < 1e-3, `got ${samples.midi[0]}`);
});

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

test("MicPitch ring stores NaN cents when no reference is active (not 0)", () => {
  const engine = fakeEngine(0.5);
  const ctx = fakeCtx(0.5);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();
  // No setReferenceStem call — reference is null.
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.5 });
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 1);
  // The downstream MicOverlay relies on NaN to mean "no reference" so it can
  // render the neutral colour instead of in-tune green. 0 would be wrong.
  assert.ok(Number.isNaN(s.cents[0]), `expected NaN, got ${s.cents[0]}`);
});

test("MicPitch ring stores NaN cents when reference is set but tSong is in a note gap", () => {
  const engine = fakeEngine(1.5);   // gap: notes at [0..1] and [2..3]
  const ctx = fakeCtx(1.5);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();
  mic.setTrackData({ notes: { vocals: {
    t: new Float32Array([0, 2]),
    dur: new Float32Array([1, 1]),
    midi: new Uint8Array([60, 62]),
  }}});
  mic.setReferenceStem("vocals");
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 1.5 });
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 1);
  assert.ok(Number.isNaN(s.cents[0]), `expected NaN in gap, got ${s.cents[0]}`);
});

test("MicPitch.start emits 'error' with code=permission when getUserMedia denies", async () => {
  const orig = globalThis.AudioWorkletNode;
  globalThis.AudioWorkletNode = class {};
  try {
    const errors = [];
    const fakeGetUserMedia = () => {
      const e = new Error("denied");
      e.name = "NotAllowedError";
      return Promise.reject(e);
    };
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
  } finally {
    if (orig === undefined) delete globalThis.AudioWorkletNode;
    else globalThis.AudioWorkletNode = orig;
  }
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
    if (orig === undefined) delete globalThis.AudioWorkletNode;
    else globalThis.AudioWorkletNode = orig;
  }
});

test("MicPitch.start is reentrancy-safe: concurrent calls do not acquire two streams", async () => {
  const orig = globalThis.AudioWorkletNode;
  globalThis.AudioWorkletNode = class { constructor() {} get port() { return { onmessage: null, postMessage: () => {} }; } };
  try {
    let getUmCalls = 0;
    const fakeStream = { getTracks: () => [{ stop: () => {} }], oninactive: null };
    const fakeGetUserMedia = () => {
      getUmCalls++;
      // Delay so the second start() call gets in while we're still awaiting.
      return new Promise((res) => setTimeout(() => res(fakeStream), 30));
    };
    const ctx = {
      state: "running",
      audioWorklet: { addModule: async () => {} },
      createMediaStreamSource: () => ({ connect: () => {}, disconnect: () => {} }),
    };
    const mic = new MicPitch({
      engine: fakeEngine(0),
      audioContext: ctx,
      getUserMedia: fakeGetUserMedia,
    });
    // Fire two start() calls back-to-back without awaiting the first.
    const p1 = mic.start();
    const p2 = mic.start();
    await Promise.all([p1, p2]);
    assert.equal(getUmCalls, 1, "expected getUserMedia to be called exactly once across concurrent start() calls");
  } finally {
    if (orig === undefined) delete globalThis.AudioWorkletNode;
    else globalThis.AudioWorkletNode = orig;
  }
});

test("MicPitch.start emits 'error' code=device-busy when getUserMedia throws NotReadableError", async () => {
  const orig = globalThis.AudioWorkletNode;
  globalThis.AudioWorkletNode = class {};
  try {
    const errors = [];
    const fakeGetUserMedia = () => {
      const e = new Error("hardware busy");
      e.name = "NotReadableError";
      return Promise.reject(e);
    };
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
    assert.equal(errors[0].code, "device-busy");
  } finally {
    if (orig === undefined) delete globalThis.AudioWorkletNode;
    else globalThis.AudioWorkletNode = orig;
  }
});

test("MicPitch transpose shifts detected pitch before cents, 'sample' event, and ring write", () => {
  const engine = fakeEngine(0.5);   // inside the reference note (t=0..1, midi=60)
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
  mic.setTranspose(3);
  assert.equal(mic.getTranspose(), 3);

  let lastSample = null;
  mic.addEventListener("sample", (e) => { lastSample = e.detail; });
  // 440 Hz = MIDI 69; transposed +3 → 72. Cents vs C4 = 100*(72-60) = +1200,
  // NOT the un-transposed +900 — the shift must land BEFORE the cents math
  // so line position and colour bucketing agree.
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.5 });
  assert.ok(Math.abs(lastSample.midi - 72) < 1e-3, `event midi: got ${lastSample.midi}`);
  assert.ok(Math.abs(lastSample.cents - 1200) < 1e-3, `event cents: got ${lastSample.cents}`);
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 1);
  assert.ok(Math.abs(s.midi[0] - 72) < 1e-3, `ring midi: got ${s.midi[0]}`);
  assert.ok(Math.abs(s.cents[0] - 1200) < 1e-3, `ring cents: got ${s.cents[0]}`);
});

test("MicPitch setTranspose back-shifts buffered ring samples, clamps midi, keeps NaN cents NaN", () => {
  const engine = fakeEngine(0.5);
  const ctx = fakeCtx(0.5);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  mic.setTrackData({
    notes: { vocals: {
      t: new Float32Array([0]),
      dur: new Float32Array([1]),
      midi: new Uint8Array([60]),
    }},
  });
  mic.setReferenceStem("vocals");
  // Buffer one sample with a reference (finite cents = +900) …
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.5 });
  // … and one without (NaN cents), in a note gap.
  mic.setReferenceStem(null);
  engine._t = 2.5; ctx._t = 2.5;
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 2.5 });

  mic.setTranspose(5);
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 2);
  // Both midi values shifted by +5 (69 → 74).
  assert.ok(Math.abs(s.midi[0] - 74) < 1e-3, `ring[0] midi: got ${s.midi[0]}`);
  assert.ok(Math.abs(s.midi[1] - 74) < 1e-3, `ring[1] midi: got ${s.midi[1]}`);
  // Finite cents shifted by 100*d; NaN stays NaN (the "no reference"
  // sentinel must survive the back-shift).
  assert.ok(Math.abs(s.cents[0] - 1400) < 1e-3, `ring[0] cents: got ${s.cents[0]}`);
  assert.ok(Number.isNaN(s.cents[1]), `ring[1] cents should stay NaN, got ${s.cents[1]}`);

  // Clamp: buffer a very high pitch (10 kHz ≈ MIDI 123 + current +5 → 127,
  // write-clamped), then transpose further up — the back-shift must pin the
  // buffered value at 127 instead of writing 146 into the ring.
  engine._t = 4.0; ctx._t = 4.0;
  factory.push({ freq: 10000, clarity: 1, rms: 0.1, ctxTime: 4.0 });
  mic.setTranspose(24);   // delta +19 over every buffered sample
  const s2 = mic.getSamplesInRange(-1, 100);
  assert.equal(s2.time.length, 3);
  assert.equal(s2.midi[2], 127, `high sample should clamp at 127, got ${s2.midi[2]}`);
  for (let i = 0; i < s2.midi.length; i++) {
    assert.ok(s2.midi[i] >= 0 && s2.midi[i] <= 127, `ring midi out of [0,127]: ${s2.midi[i]}`);
  }
});

test("MicPitch setTranspose clamps to [-24,+24], resets the EMA chain, and dispatches transpose-changed", () => {
  const engine = fakeEngine(0.5);
  const ctx = fakeCtx(0.5);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  // Clamp + integer coercion.
  mic.setTranspose(100);
  assert.equal(mic.getTranspose(), 24);
  mic.setTranspose(-100);
  assert.equal(mic.getTranspose(), -24);
  mic.setTranspose(2.6);
  assert.equal(mic.getTranspose(), 3);

  // transpose-changed fires on change, not on a no-op set.
  let events = 0;
  mic.addEventListener("transpose-changed", () => events++);
  mic.setTranspose(0);
  assert.equal(events, 1);
  mic.setTranspose(0);
  assert.equal(events, 1, "no-op setTranspose must not re-dispatch");

  // EMA reset: seed the smoother, change transpose, then push a sample
  // 20 ms later (inside EMA_GAP_S). Without the reset the new sample would
  // blend with the stale un-transposed EMA (0.4*71 + 0.6*69 = 69.8) and
  // glide; with the reset it re-seeds at exactly the shifted pitch.
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.5 });   // midi 69
  mic.setTranspose(2);
  engine._t = 0.52; ctx._t = 0.52;
  factory.push({ freq: 440, clarity: 1, rms: 0.1, ctxTime: 0.52 });  // midi 69+2=71
  const s = mic.getSamplesInRange(-1, 100);
  const last = s.midi[s.midi.length - 1];
  assert.ok(Math.abs(last - 71) < 1e-3,
    `expected clean jump to 71 (EMA re-seeded), got ${last} — smoother glide?`);
});

test("MicPitch ring stores continuous (float) MIDI — no semitone quantization", () => {
  const engine = fakeEngine(0);
  const ctx = fakeCtx(0);
  const factory = fakeWorkletFactory();
  const mic = new MicPitch({ engine, audioContext: ctx, workletFactory: factory });
  mic._attachForTest();

  // 452 Hz is ~47 cents sharp of A4 (440). The float MIDI should be ~69.47,
  // NOT rounded to 69. A Uint8 ring would silently drop the fractional part.
  factory.push({ freq: 452, clarity: 1, rms: 0.1, ctxTime: 0 });
  const s = mic.getSamplesInRange(-1, 100);
  assert.equal(s.time.length, 1);
  const m = s.midi[0];
  // Expected: 69 + 12 * log2(452/440) ≈ 69.4651
  assert.ok(m > 69.3 && m < 69.6,
    `expected ~69.47 (452 Hz is ~47¢ sharp of A4), got ${m} — ring is quantizing`);
  // Also assert it's NOT an exact integer (the bug-was-here check).
  assert.ok(Math.abs(m - Math.round(m)) > 0.01,
    `MIDI ${m} suspiciously close to an integer — Uint8 quantization regression?`);
});
