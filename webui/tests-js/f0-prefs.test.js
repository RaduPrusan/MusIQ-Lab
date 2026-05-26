import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// Origin is required for localStorage — opaque origins (the default when no
// url is given) make jsdom throw SecurityError on storage access.
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;
globalThis.CustomEvent = dom.window.CustomEvent;

const { getF0Prefs, setF0Prefs } = await import("../static/js/music/f0-prefs.js");

const DEFAULT = { fcpe: false, pesto: false, consensus: true };

beforeEach(() => { localStorage.clear(); });

test("getF0Prefs returns the consensus-on default for empty storage", () => {
  assert.deepEqual(getF0Prefs(), DEFAULT);
});

test("setF0Prefs round-trips through localStorage", () => {
  setF0Prefs({ fcpe: true, pesto: true, consensus: false });
  assert.deepEqual(getF0Prefs(), { fcpe: true, pesto: true, consensus: false });
});

test("setF0Prefs merges partial updates instead of clobbering", () => {
  setF0Prefs({ fcpe: true });
  assert.deepEqual(getF0Prefs(), { ...DEFAULT, fcpe: true });
  setF0Prefs({ pesto: true });
  assert.deepEqual(getF0Prefs(), { ...DEFAULT, fcpe: true, pesto: true });
  setF0Prefs({ consensus: false });
  assert.deepEqual(getF0Prefs(), { fcpe: true, pesto: true, consensus: false });
});

test("setF0Prefs ignores non-boolean values", () => {
  setF0Prefs({ fcpe: "yes", pesto: 1, consensus: "no" });
  assert.deepEqual(getF0Prefs(), DEFAULT);
});

test("setF0Prefs ignores unknown keys without throwing", () => {
  setF0Prefs({ random: true });
  assert.deepEqual(getF0Prefs(), DEFAULT);
});

test("setF0Prefs tolerates null/undefined patch", () => {
  assert.doesNotThrow(() => setF0Prefs(null));
  assert.doesNotThrow(() => setF0Prefs(undefined));
  assert.deepEqual(getF0Prefs(), DEFAULT);
});

test("setF0Prefs emits musiq:f0-prefs-changed with the new state", () => {
  let detail = null;
  const handler = (ev) => { detail = ev.detail; };
  document.addEventListener("musiq:f0-prefs-changed", handler);
  try {
    setF0Prefs({ fcpe: true });
    assert.deepEqual(detail, { ...DEFAULT, fcpe: true });
  } finally {
    document.removeEventListener("musiq:f0-prefs-changed", handler);
  }
});

test("setF0Prefs emits when consensus toggle flips", () => {
  let detail = null;
  document.addEventListener("musiq:f0-prefs-changed", (ev) => { detail = ev.detail; });
  setF0Prefs({ consensus: false });
  assert.equal(detail.consensus, false);
});

test("getF0Prefs falls back to defaults if localStorage is corrupt", () => {
  localStorage.setItem("musiq.f0Prefs", "not json");
  assert.deepEqual(getF0Prefs(), DEFAULT);
});

test("partial stored state fills missing keys from defaults", () => {
  // Simulate older stored prefs that don't include the consensus key
  localStorage.setItem("musiq.f0Prefs", JSON.stringify({ fcpe: true, pesto: true }));
  const prefs = getF0Prefs();
  assert.equal(prefs.fcpe, true);
  assert.equal(prefs.pesto, true);
  assert.equal(prefs.consensus, true);  // back-filled from default
});
