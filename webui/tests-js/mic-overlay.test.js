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

// jsdom does not implement getContext("2d") without the `canvas` npm package
// (it returns null). Stub it at the prototype level so MicOverlay's
// constructor and the spy test both receive a usable mock ctx object.
// Each canvas element gets exactly one ctx instance so monkey-patches
// applied in the spy test hit the same object that render() holds.
{
  const _ctxMap = new WeakMap();
  const _makeCtx = () => ({
    setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {},
    lineTo() {}, bezierCurveTo() {}, quadraticCurveTo() {},
    stroke() {}, strokeStyle: "", globalAlpha: 1,
    lineWidth: 1, lineCap: "butt", lineJoin: "miter",
  });
  dom.window.HTMLCanvasElement.prototype.getContext = function () {
    if (!_ctxMap.has(this)) _ctxMap.set(this, _makeCtx());
    return _ctxMap.get(this);
  };
}

// Also stub requestAnimationFrame (not provided by jsdom for non-window usage).
// Use a no-fire stub so _scheduleDraw() doesn't invoke render() synchronously
// during the spy test; the spy test calls render() directly to control timing.
let _rafCounter = 0;
globalThis.requestAnimationFrame = (_cb) => ++_rafCounter;
globalThis.cancelAnimationFrame = (_id) => {};

// getComputedStyle is on dom.window but not globalThis in Node ESM.
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

import { centsToColourBucket, rmsToAlpha, ALPHA_FLOOR, ALPHA_CEIL, MicOverlay } from "../static/js/render/mic-overlay.js";

test("rmsToAlpha maps dBFS linearly between ALPHA_FLOOR and ALPHA_CEIL", () => {
  // Below the gate (~0.005 linear = -46 dBFS) clamps to floor.
  assert.equal(rmsToAlpha(0),     ALPHA_FLOOR);
  assert.equal(rmsToAlpha(0.001), ALPHA_FLOOR);
  // RMS = 0.01 (-40 dBFS) is the curve's floor — alpha at or just above
  // ALPHA_FLOOR (0.30).
  assert.ok(Math.abs(rmsToAlpha(0.01) - ALPHA_FLOOR) < 1e-6,
    `at -40 dBFS expected ${ALPHA_FLOOR}, got ${rmsToAlpha(0.01)}`);
  // RMS slightly above the ceil (0.3 ≈ -10.5 dBFS, above the -12 ceil)
  // clamps to ALPHA_CEIL. Use a value clearly past the edge to dodge
  // float-precision sensitivity right at the boundary.
  assert.equal(rmsToAlpha(0.3), ALPHA_CEIL);
  // Loud singing well above ceil → still clamped.
  assert.equal(rmsToAlpha(0.5), ALPHA_CEIL);
  assert.equal(rmsToAlpha(1.0), ALPHA_CEIL);
  // Midpoint check: -26 dBFS (linear ≈ 0.0501) is halfway between floor
  // and ceil in dBFS space → alpha ≈ midpoint (0.65).
  const mid = rmsToAlpha(0.0501);
  const expectedMid = (ALPHA_FLOOR + ALPHA_CEIL) / 2;
  assert.ok(Math.abs(mid - expectedMid) < 0.02,
    `at -26 dBFS expected ~${expectedMid}, got ${mid}`);
  // Monotonic: louder always means more opaque.
  assert.ok(rmsToAlpha(0.02) < rmsToAlpha(0.1));
  assert.ok(rmsToAlpha(0.1) < rmsToAlpha(0.2));
});

test("centsToColourBucket: 4-bucket (in/off/neutral/no-match) with hasReference flag", () => {
  // Within one semitone of the target → 'in' (--mic-in, green default). The
  // window is loose on purpose; vocal breath wobble of ±30-50¢ must not
  // flip buckets.
  assert.equal(centsToColourBucket(0),    "in");
  assert.equal(centsToColourBucket(50),   "in");
  assert.equal(centsToColourBucket(-50),  "in");
  assert.equal(centsToColourBucket(100),  "in");
  assert.equal(centsToColourBucket(-100), "in");
  // Beyond one semitone → 'off' (--mic-off, red default). The user is
  // closer to a different note than the target one.
  assert.equal(centsToColourBucket(101),  "off");
  assert.equal(centsToColourBucket(-150), "off");
  assert.equal(centsToColourBucket(400),  "off");
  // NaN cents + reference stem set → 'neutral' (--mic-neutral, blue default):
  // we're matched to a stem but the stem has no note at this song time
  // (between vocal phrases). hasReference defaults to true.
  assert.equal(centsToColourBucket(null), "neutral");
  assert.equal(centsToColourBucket(NaN),  "neutral");
  assert.equal(centsToColourBucket(NaN, true),  "neutral");
  // NaN cents + no reference stem → 'no-match' (--mic-no-match, purple
  // default): match dropdown is set to none. Distinct semantic — gets
  // its own theme token so the user can recolour the two independently.
  assert.equal(centsToColourBucket(NaN,  false), "no-match");
  assert.equal(centsToColourBucket(null, false), "no-match");
});

test("MicOverlay.render strokes one segment per consecutive sample pair with finite, in-bounds Y coordinates", () => {
  // Fake host with getBoundingClientRect.
  const host = document.createElement("div");
  const HOST_H = 600;
  Object.defineProperty(host, "getBoundingClientRect", {
    value: () => ({ width: 800, height: HOST_H, left: 0, top: 0, right: 800, bottom: HOST_H }),
  });
  document.body.appendChild(host);

  // Stub MicPitch.
  const fakeSamples = {
    time:    new Float32Array([1.0, 1.1, 1.2]),
    midi:    new Uint8Array([60, 62, 60]),
    cents:   new Float32Array([0, 30, -3]),
    clarity: new Uint8Array([255, 200, 100]),
    rms:     new Float32Array([0.1, 0.05, 0.02]),
  };
  const fakeMic = new (class extends EventTarget {
    getSamplesInRange() { return fakeSamples; }
  })();

  const overlay = new MicOverlay(host, fakeMic);

  // Spy on ctx. The renderer draws each Catmull-Rom segment as a polyline
  // of SUB_STEPS=6 short straight lineTo calls (subdivided for pixel-dense
  // AA stability under pan). Per ring segment: 1 beginPath + 1 moveTo +
  // 6 lineTo + 1 stroke.
  let beginCount = 0, strokeCount = 0;
  const moves = [];   // [[x, y], ...]
  const lines = [];   // [[x, y], ...]
  const ctx = overlay.canvas.getContext("2d");
  const origBegin = ctx.beginPath.bind(ctx);
  const origStroke = ctx.stroke.bind(ctx);
  const origMove = ctx.moveTo.bind(ctx);
  const origLine = ctx.lineTo.bind(ctx);
  ctx.beginPath = () => { beginCount++; origBegin(); };
  ctx.stroke = () => { strokeCount++; origStroke(); };
  ctx.moveTo = (x, y) => { moves.push([x, y]); origMove(x, y); };
  ctx.lineTo = (x, y) => { lines.push([x, y]); origLine(x, y); };

  // NB: midiCenter (not scrollMidi). midiToY in coords.js reads midiCenter;
  // using the wrong field name would make every Y NaN — exactly the bug
  // this test now catches.
  overlay.setViewState({ scrollSec: 0, zoomH: 100, zoomV: 8, midiCenter: 60 });
  overlay.render();

  // 3 samples → 2 ring segments → 2 beginPath / 2 stroke / 2 moveTo / 12 lineTo
  // (6 subdivisions per segment).
  assert.equal(beginCount, 2, "beginPath called once per ring segment");
  assert.equal(strokeCount, 2, "stroke called once per ring segment");
  assert.equal(moves.length, 2, "moveTo called once per ring segment");
  assert.equal(lines.length, 12, "lineTo called SUB_STEPS times per ring segment (6 × 2)");

  // Every recorded coordinate must be a finite number inside the host bounds.
  // NaN-checks pin the "wrong viewState field" / missing-CHORD_H bug class.
  for (const [x, y] of [...moves, ...lines]) {
    assert.ok(Number.isFinite(x), `x must be finite, got ${x}`);
    assert.ok(Number.isFinite(y), `y must be finite, got ${y}`);
    assert.ok(y >= 0 && y <= HOST_H,
      `y must fall inside [0, ${HOST_H}], got ${y} — this catches missing CHORD_H offset bugs`);
  }
});

test("MicOverlay.destroy() removes the 'sample' listener so dead instances don't redraw", () => {
  const host = document.createElement("div");
  Object.defineProperty(host, "getBoundingClientRect", {
    value: () => ({ width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600 }),
  });
  document.body.appendChild(host);

  const fakeSamples = {
    time:    new Float32Array([1.0, 1.1]),
    midi:    new Uint8Array([60, 62]),
    cents:   new Float32Array([0, 10]),
    clarity: new Uint8Array([255, 255]),
    rms:     new Float32Array([0.1, 0.1]),
  };
  let drawCalls = 0;
  const fakeMic = new (class extends EventTarget {
    getSamplesInRange() { drawCalls++; return fakeSamples; }
  })();

  const overlay = new MicOverlay(host, fakeMic);
  overlay.setViewState({ scrollSec: 0, zoomH: 100, zoomV: 8, midiCenter: 60 });

  // Trigger an initial render via the sample event — render is rAF-scheduled
  // but our test stub for requestAnimationFrame is no-op, so we render
  // synchronously to count the draw deterministically.
  overlay.render();
  const beforeDestroy = drawCalls;

  overlay.destroy();
  // After destroy, a new sample event must NOT cause a draw.
  fakeMic.dispatchEvent(new CustomEvent("sample", { detail: {} }));
  // Force any pending work (there shouldn't be any).
  overlay.render?.();
  // overlay.render() still works (we just kept it callable), but the listener
  // detachment means dispatchEvent("sample") above produced zero new schedules.
  // The deterministic check is "render only runs when we explicitly call it,
  // not via a dead listener". Since our rAF stub never fires the callback,
  // we instead verify the listener was actually removed:
  assert.equal(overlay._onSample, null, "destroy should null out _onSample");
  assert.equal(overlay.micPitch, null, "destroy should drop the micPitch reference");
});

test("MicOverlay does not draw a connecting segment across a >0.15s silence gap", () => {
  const host = document.createElement("div");
  Object.defineProperty(host, "getBoundingClientRect", {
    value: () => ({ width: 800, height: 600, left: 0, top: 0, right: 800, bottom: 600 }),
  });
  document.body.appendChild(host);

  // 4 samples: two voiced "phrases" separated by a 0.25s silence (above
  // MAX_SEGMENT_GAP_S = 0.15s). The middle pair should NOT be connected.
  //   phrase A: t=[1.00, 1.05]  → 1 segment
  //   gap:      t=[1.05 → 1.30] = 0.25s → no segment
  //   phrase B: t=[1.30, 1.35]  → 1 segment
  //   total: 2 segments expected, not 3
  const samples = {
    time:    new Float32Array([1.00, 1.05, 1.30, 1.35]),
    midi:    new Uint8Array([60, 62, 67, 65]),
    cents:   new Float32Array([0, 10, -5, 0]),
    clarity: new Uint8Array([255, 255, 255, 255]),
    rms:     new Float32Array([0.1, 0.1, 0.1, 0.1]),
  };
  const fakeMic = new (class extends EventTarget {
    getSamplesInRange() { return samples; }
  })();

  const overlay = new MicOverlay(host, fakeMic);
  let strokeCount = 0;
  const ctx = overlay.canvas.getContext("2d");
  const origStroke = ctx.stroke.bind(ctx);
  ctx.stroke = () => { strokeCount++; origStroke(); };

  overlay.setViewState({ scrollSec: 0, zoomH: 100, zoomV: 8, midiCenter: 60 });
  overlay.render();

  assert.equal(strokeCount, 2,
    "expected 2 segments (one per voiced phrase); a 3rd segment means " +
    "the silence gap was incorrectly bridged");
});
