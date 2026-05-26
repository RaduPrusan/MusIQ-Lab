import { test } from "node:test";
import assert from "node:assert/strict";

import { createViewState } from "../static/js/view/view-state.js";

test("createViewState returns defaults", () => {
  const vs = createViewState();
  assert.equal(typeof vs.zoomH, "number");
  assert.equal(typeof vs.zoomV, "number");
  assert.equal(vs.scrollSec, 0);
  assert.equal(vs.highlightedStem, "vocals");
  assert.equal(vs.autoScroll, true);
});

test("setting a property triggers change subscribers", () => {
  const vs = createViewState();
  let calls = 0;
  let lastChanged = null;
  vs.on("change", (ev) => { calls++; lastChanged = ev.changed; });
  vs.zoomH = 200;
  assert.equal(calls, 1);
  assert.deepEqual(lastChanged, ["zoomH"]);
  vs.scrollSec = 5;
  assert.equal(calls, 2);
  assert.deepEqual(lastChanged, ["scrollSec"]);
});

test("setting same value does not trigger event", () => {
  const vs = createViewState();
  let calls = 0;
  vs.on("change", () => calls++);
  vs.zoomH = vs.zoomH;
  assert.equal(calls, 0);
});

test("off() unsubscribes and prevents further calls", () => {
  const vs = createViewState();
  let calls = 0;
  const handler = () => calls++;
  vs.on("change", handler);
  vs.zoomH = 200;
  vs.off("change", handler);
  vs.zoomH = 300;
  assert.equal(calls, 1);
});

test("update() applies multiple fields atomically (one event)", () => {
  const vs = createViewState();
  let calls = 0;
  let changed = null;
  vs.on("change", (ev) => { calls++; changed = ev.changed; });
  vs.update({ zoomH: 250, scrollSec: 10, highlightedStem: "bass" });
  assert.equal(calls, 1);
  assert.deepEqual(changed.sort(), ["highlightedStem", "scrollSec", "zoomH"]);
});
