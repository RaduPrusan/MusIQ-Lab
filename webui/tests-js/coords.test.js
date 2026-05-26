import { test } from "node:test";
import assert from "node:assert/strict";

import { timeToX, xToTime, midiToY, yToMidi, viewportSec, autoScrollFor } from "../static/js/render/coords.js";

const VS_BASE = { zoomH: 100, zoomV: 14, scrollSec: 0, midiCenter: 60 };

test("timeToX maps 0s to 0px when scrollSec=0", () => {
  assert.equal(timeToX(0, VS_BASE), 0);
  assert.equal(timeToX(1, VS_BASE), 100);
  assert.equal(timeToX(2.5, VS_BASE), 250);
});

test("scrollSec shifts time origin", () => {
  const vs = { ...VS_BASE, scrollSec: 10 };
  assert.equal(timeToX(10, vs), 0);
  assert.equal(timeToX(11, vs), 100);
});

test("zoomH scales pixels per second", () => {
  const vs = { ...VS_BASE, zoomH: 200 };
  assert.equal(timeToX(1, vs), 200);
});

test("xToTime is inverse of timeToX", () => {
  for (const t of [0, 1, 12.345, 200]) {
    const x = timeToX(t, VS_BASE);
    assert.ok(Math.abs(xToTime(x, VS_BASE) - t) < 1e-6);
  }
});

test("midiToY puts midiCenter at viewportHeight/2", () => {
  const vp = 280;
  assert.equal(midiToY(60, VS_BASE, vp), 140);
});

test("higher midi maps to smaller Y (top of canvas)", () => {
  const vp = 280;
  const y67 = midiToY(67, VS_BASE, vp);
  const y53 = midiToY(53, VS_BASE, vp);
  assert.ok(y67 < y53);
});

test("yToMidi is inverse of midiToY", () => {
  const vp = 280;
  for (const m of [60, 67, 50, 72]) {
    const y = midiToY(m, VS_BASE, vp);
    assert.ok(Math.abs(yToMidi(y, VS_BASE, vp) - m) < 1e-6);
  }
});

test("viewportSec returns visible seconds for a given pixel width", () => {
  assert.equal(viewportSec(VS_BASE, 800), 8);
  assert.equal(viewportSec({ ...VS_BASE, zoomH: 200 }, 800), 4);
});

const EDGE_VS = { ...VS_BASE, scrollAnchor: "edge", scrollSec: 0 };

test("edge mode: cursor inside [30%,70%] → no scroll", () => {
  // vp=10s. cursor at 5s = 50% → no scroll
  const out = autoScrollFor(5, EDGE_VS, 1000, 215);
  assert.equal(out, 0);
});

test("edge mode: cursor past 70% → pin at 70%", () => {
  // vp=10s. cursor at 9s = 90% → scroll so cursor at 70% (=> scrollSec = 9-7 = 2)
  const out = autoScrollFor(9, EDGE_VS, 1000, 215);
  assert.ok(Math.abs(out - 2) < 1e-9, `expected ~2, got ${out}`);
});

test("edge mode: cursor below 30% (e.g. backward seek inside vp) → pin at 30%", () => {
  // vp=10s, scrollSec=10 → viewport covers t=10..20. cursor at 12s = 20% from left.
  const vs = { ...EDGE_VS, scrollSec: 10 };
  const out = autoScrollFor(12, vs, 1000, 215);
  // cursor must end up at 30% → scrollSec = 12 - 0.3*10 = 9
  assert.ok(Math.abs(out - 9) < 1e-9, `expected ~9, got ${out}`);
});

test("edge mode: clamps scroll to 0 when cursor near song start", () => {
  // vp=10s. cursor at 0s = 0% → would compute target=-2 → clamped to 0
  const out = autoScrollFor(0, EDGE_VS, 1000, 215);
  assert.equal(out, 0);
});

test("center mode: cursor pinned at viewport midpoint", () => {
  // vp=10s. cursor at 30s → scrollSec = 30 - 5 = 25
  const vs = { ...VS_BASE, scrollAnchor: "center", scrollSec: 0 };
  const out = autoScrollFor(30, vs, 1000, 215);
  assert.ok(Math.abs(out - 25) < 1e-9, `expected ~25, got ${out}`);
});

test("center mode: clamps to 0 near song start", () => {
  const vs = { ...VS_BASE, scrollAnchor: "center", scrollSec: 0 };
  const out = autoScrollFor(2, vs, 1000, 215);
  assert.equal(out, 0);
});
