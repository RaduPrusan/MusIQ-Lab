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

test("Yin produces identical output on the same buffer across repeated process() calls (no stale state)", () => {
  const sampleRate = 48000;
  const windowSize = 2048;
  const yin = new Yin({ sampleRate, windowSize });
  const buf = sine(440, sampleRate, windowSize);
  const a = yin.process(buf);
  // Run a different buffer in between so any stale-state bug would surface.
  yin.process(sine(110, sampleRate, windowSize));
  yin.process(sine(880, sampleRate, windowSize));
  const b = yin.process(buf);
  // Both should report the same freq within float tolerance.
  assert.ok(Math.abs(a.freq - b.freq) < 1e-6,
    `same input must produce same output across calls: a=${a.freq}, b=${b.freq}, diff=${a.freq - b.freq}`);
  assert.ok(Math.abs(a.clarity - b.clarity) < 1e-6,
    `same input must produce same clarity across calls: a=${a.clarity}, b=${b.clarity}`);
});
