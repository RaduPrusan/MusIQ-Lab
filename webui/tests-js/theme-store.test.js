import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;
globalThis.CustomEvent = dom.window.CustomEvent;

const { PRESETS, DEFAULT_PRESET_ID } = await import("../static/js/theme/presets.js");
const { getTheme, setPreset, setToken, resetTokens, subscribe, setLock, _resetForTests } =
  await import("../static/js/theme/store.js");

beforeEach(() => {
  localStorage.clear();
  _resetForTests();
});

test("getTheme returns the default preset on first read", () => {
  const t = getTheme();
  assert.equal(t.preset, DEFAULT_PRESET_ID);
  assert.deepEqual(t.tokens, PRESETS[DEFAULT_PRESET_ID]);
  assert.deepEqual(t.locks, []);
});

test("setPreset persists and switches the active preset", () => {
  setPreset("midnight");
  const t = getTheme();
  assert.equal(t.preset, "midnight");
  assert.equal(t.tokens["surface-base"], PRESETS["midnight"]["surface-base"]);
  // Survives reload by re-reading from localStorage:
  _resetForTests();
  assert.equal(getTheme().preset, "midnight");
});

test("setToken changes a single token and flips preset to 'custom'", () => {
  setPreset("classic-dark");
  setToken("accent", "#ff00ff");
  const t = getTheme();
  assert.equal(t.preset, "custom");
  assert.equal(t.tokens["accent"], "#ff00ff");
});

test("setToken rejects invalid color values", () => {
  setToken("accent", "not-a-color");
  assert.equal(getTheme().tokens["accent"], PRESETS[DEFAULT_PRESET_ID]["accent"]);
});

test("setToken rejects out-of-range alpha values", () => {
  setToken("alpha-scrim", "1.5");
  assert.equal(getTheme().tokens["alpha-scrim"], PRESETS[DEFAULT_PRESET_ID]["alpha-scrim"]);
});

test("resetTokens reapplies the current preset's values", () => {
  setPreset("midnight");
  setToken("accent", "#ff00ff");
  resetTokens();
  const t = getTheme();
  assert.equal(t.preset, "midnight");
  assert.equal(t.tokens["accent"], PRESETS["midnight"]["accent"]);
});

test("subscribe fires on every change and unsubscribes cleanly", () => {
  let calls = 0;
  const off = subscribe(() => calls++);
  setPreset("midnight");
  setToken("accent", "#ff00ff");
  off();
  setToken("accent", "#000000");
  assert.equal(calls, 2);
});

test("corrupt localStorage payload falls back to default preset", () => {
  localStorage.setItem("musiq.theme", "{not json");
  _resetForTests();
  assert.equal(getTheme().preset, DEFAULT_PRESET_ID);
});

test("schema-version mismatch falls back to default preset", () => {
  localStorage.setItem("musiq.theme", JSON.stringify({ v: 999, preset: "midnight", tokens: {} }));
  _resetForTests();
  assert.equal(getTheme().preset, DEFAULT_PRESET_ID);
});

test("setToken('accent', X) re-derives accent-emphasis + accent-on", () => {
  setToken("accent", "#000000");
  const t = getTheme();
  assert.equal(t.tokens["accent-on"], "#ffffff", "dark accent → white accent-on");
  assert.match(t.tokens["accent-emphasis"], /color-mix\(in srgb, #000000 92%, #ffffff 8%\)/);
});

test("locks block re-derivation of accent-on", () => {
  setLock("accent-on", true);
  setToken("accent-on", "#abcdef");
  setToken("accent", "#000000");
  assert.equal(getTheme().tokens["accent-on"], "#abcdef");
});
