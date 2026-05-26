// Unit tests for the median-MIDI smoothing helper used by the F0 overlay.
// We test the helper directly without exercising the SVG rendering — the
// helper is a pure function and the rendering test would require a much
// heavier jsdom setup.

import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// Origin needed so jsdom doesn't reject SVG createElementNS during module init.
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;

const { medianMidiOver, rmsToOpacity } = await import("../static/js/render/f0-overlay.js");

// 440 Hz = MIDI 69 by definition; 220 Hz = 57; 880 Hz = 81; 466.16... ≈ 70.
const HZ_A4 = 440.0;
const HZ_A3 = 220.0;
const HZ_A5 = 880.0;
const HZ_BB4 = 440.0 * Math.pow(2, 1 / 12);  // ≈ 466.16

test("returns NaN for empty range", () => {
  assert.ok(Number.isNaN(medianMidiOver([HZ_A4, HZ_A4], 1, 1)));
});

test("returns NaN when all entries are zero/NaN/negative", () => {
  assert.ok(Number.isNaN(medianMidiOver([0, NaN, -1, 0], 0, 4)));
});

test("ignores zero/NaN frames mixed with valid ones", () => {
  // Mixed: [0, 440, NaN, 440, 0]; valid pair both at MIDI 69
  const arr = [0, HZ_A4, NaN, HZ_A4, 0];
  const m = medianMidiOver(arr, 0, 5);
  assert.equal(m, 69);
});

test("returns the single value when only one is valid", () => {
  const arr = [0, HZ_A4, NaN];
  assert.equal(medianMidiOver(arr, 0, 3), 69);
});

test("median of [A3, A4, A5] is the middle MIDI value (69 = A4)", () => {
  // Span an octave on each side; median in MIDI space is exactly A4
  const arr = [HZ_A3, HZ_A4, HZ_A5];
  assert.equal(medianMidiOver(arr, 0, 3), 69);
});

test("operates in MIDI (log-frequency) space, not Hz", () => {
  // [220, 880] would have linear-Hz mean of 550 (≈ MIDI 71.5). MIDI median
  // picks one of the two endpoints (57 or 81), NOT 71.5.
  const arr = [HZ_A3, HZ_A5];
  const m = medianMidiOver(arr, 0, 2);
  // Either 57 (lower middle) or 81 (upper middle) is acceptable for an
  // even-length input. The important property is "nowhere near 71.5".
  assert.ok(m === 57 || m === 81, `expected 57 or 81, got ${m}`);
});

test("kills a single-frame octave-glitch outlier", () => {
  // 5-frame window, all A4 except one frame doubled (A5). Median is still A4.
  const arr = [HZ_A4, HZ_A4, HZ_A5, HZ_A4, HZ_A4];   // glitch at index 2
  assert.equal(medianMidiOver(arr, 0, 5), 69);
});

test("kills two-octave glitch in 5-frame window", () => {
  const arr = [HZ_A4, HZ_A4, 4 * HZ_A4, HZ_A4, HZ_A4];   // +2 octaves
  assert.equal(medianMidiOver(arr, 0, 5), 69);
});

test("respects lo/hi window bounds", () => {
  // Full array has many distinct values; we only median over [1,4)
  const arr = [HZ_A3, HZ_A4, HZ_A4, HZ_A4, HZ_A5];
  // Window [1,4) = [A4, A4, A4] → median 69, regardless of bookends
  assert.equal(medianMidiOver(arr, 1, 4), 69);
});

test("handles a noisy real-vibrato-like window without distortion", () => {
  // Vibrato-style sweep: 440Hz ± 20¢ over 7 frames. Median should be near 69.
  const cents = [-20, -10, 0, 10, 20, 10, 0];
  const arr = cents.map((c) => HZ_A4 * Math.pow(2, c / 1200));
  const m = medianMidiOver(arr, 0, arr.length);
  // Median of evenly distributed cents around 0¢: should land close to 0¢.
  // Allow a 1-cent slop because median picks an existing sample, not the mean.
  assert.ok(Math.abs(m - 69) < 0.02, `expected near 69, got ${m}`);
});

test("preserves a sustained note's pitch class through smoothing", () => {
  // 7 frames at Bb4 ± small jitter. Median should land on Bb4 (≈70.0)
  const arr = new Array(7).fill(HZ_BB4);
  const m = medianMidiOver(arr, 0, 7);
  assert.ok(Math.abs(m - 70) < 0.01, `expected ≈70 (Bb4), got ${m}`);
});

test("a Float32Array input works the same as a plain Array", () => {
  // The real renderer passes Float32Array (track-data hands them off);
  // the helper must accept both transparently.
  const f32 = new Float32Array([HZ_A4, HZ_A4, HZ_A5, HZ_A4, HZ_A4]);
  assert.equal(medianMidiOver(f32, 0, 5), 69);
});


// ---------- mask param (Phase 0c Step 2: smoothing within bucket) ------

test("mask=null is identical to no mask supplied", () => {
  const arr = [HZ_A4, HZ_A4, HZ_A5, HZ_A4, HZ_A4];
  assert.equal(
    medianMidiOver(arr, 0, 5, null),
    medianMidiOver(arr, 0, 5),
  );
});

test("mask excludes frames where mask[k] is falsy", () => {
  // 5 frames at A4, with one A5 outlier — but the outlier is masked out.
  // Median should land on A4 (69) regardless of the outlier.
  const arr = [HZ_A4, HZ_A4, HZ_A5, HZ_A4, HZ_A4];
  const mask = new Uint8Array([1, 1, 0, 1, 1]);
  assert.equal(medianMidiOver(arr, 0, 5, mask), 69);
});

test("mask of all-zero in window yields NaN", () => {
  const arr = [HZ_A4, HZ_A4, HZ_A4];
  const mask = new Uint8Array([0, 0, 0]);
  assert.ok(Number.isNaN(medianMidiOver(arr, 0, 3, mask)));
});

test("smoothing-within-bucket: strong center frame doesn't pick up medium neighbors", () => {
  // This is the failure mode the spec called out: a strong-bucket center
  // frame whose window contains medium-bucket frames at very different Hz.
  // Without bucket masking, the median would be pulled toward the medium
  // values (orphaning a bright dot far from its strong neighbors). With
  // masking, only same-bucket frames contribute, and the strong center's
  // smoothed Hz reflects only strong context.

  // 5-frame window: positions 0,4 are strong @ A4; positions 1,2,3 are
  // medium @ A5 (higher pitch). Center frame is index 0 (strong).
  const arr = [HZ_A4, HZ_A5, HZ_A5, HZ_A5, HZ_A4];
  const strongMask = new Uint8Array([1, 0, 0, 0, 1]);

  // With mask: only positions 0 and 4 contribute → median = A4 (MIDI 69)
  assert.equal(medianMidiOver(arr, 0, 5, strongMask), 69);

  // Without mask: medium frames dominate (3 of 5) → median = A5 (MIDI 81)
  assert.equal(medianMidiOver(arr, 0, 5), 81);
});

// ---------- rmsToOpacity (Phase 0c Step 4 follow-up) -------------------

const RANGE = {
  dbFloor: -45.0,
  dbCeil: -15.0,
  opacityFloor: 0.05,
  opacityCeil: 1.0,
};

test("rmsToOpacity: zero RMS returns floor opacity", () => {
  assert.equal(rmsToOpacity(0, RANGE), 0.05);
});

test("rmsToOpacity: negative or NaN RMS returns floor", () => {
  assert.equal(rmsToOpacity(-0.1, RANGE), 0.05);
  assert.equal(rmsToOpacity(NaN, RANGE), 0.05);
});

test("rmsToOpacity: RMS at dbFloor returns floor opacity", () => {
  // -45 dBFS = 10^(-45/20) ≈ 0.005623
  const rms = Math.pow(10, -45 / 20);
  assert.ok(Math.abs(rmsToOpacity(rms, RANGE) - 0.05) < 1e-6);
});

test("rmsToOpacity: RMS at or above dbCeil returns ceiling opacity", () => {
  const rmsAtCeil = Math.pow(10, -15 / 20);
  assert.equal(rmsToOpacity(rmsAtCeil, RANGE), 1.0);
  assert.equal(rmsToOpacity(rmsAtCeil * 2, RANGE), 1.0); // even louder → still clamped
});

test("rmsToOpacity: midpoint dB lands at midpoint opacity", () => {
  // dBFS midpoint between -45 and -15 is -30. RMS = 10^(-30/20) ≈ 0.0316.
  // Opacity midpoint between 0.05 and 1.0 is 0.525.
  const rmsMid = Math.pow(10, -30 / 20);
  const op = rmsToOpacity(rmsMid, RANGE);
  assert.ok(Math.abs(op - 0.525) < 1e-6, `expected ~0.525, got ${op}`);
});

test("rmsToOpacity: monotonically non-decreasing in RMS", () => {
  let prev = -Infinity;
  for (const rms of [0, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]) {
    const op = rmsToOpacity(rms, RANGE);
    assert.ok(op >= prev, `expected non-decreasing; prev=${prev}, op=${op}, rms=${rms}`);
    prev = op;
  }
});


test("strong/medium/weak masks each isolate their bucket frames", () => {
  // 7 frames; cents-equivalent: each bucket pinned to a distinct MIDI value.
  //   strong frames at A4 (MIDI 69)
  //   medium frames at A5 (MIDI 81)
  //   weak frames at A6 (MIDI 93)
  const HZ_A6 = 1760.0;
  const arr = [HZ_A4, HZ_A4, HZ_A5, HZ_A5, HZ_A6, HZ_A6, HZ_A4];
  const strongMask = new Uint8Array([1, 1, 0, 0, 0, 0, 1]);
  const mediumMask = new Uint8Array([0, 0, 1, 1, 0, 0, 0]);
  const weakMask = new Uint8Array([0, 0, 0, 0, 1, 1, 0]);

  assert.equal(medianMidiOver(arr, 0, 7, strongMask), 69);
  assert.equal(medianMidiOver(arr, 0, 7, mediumMask), 81);
  assert.equal(medianMidiOver(arr, 0, 7, weakMask), 93);
});
