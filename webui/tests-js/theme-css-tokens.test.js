import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.CustomEvent = dom.window.CustomEvent;
globalThis.getComputedStyle = dom.window.getComputedStyle;

const root = dom.window.document.documentElement;
root.style.setProperty("--surface-base", "#0e0e10");
root.style.setProperty("--alpha-stem-fill", "0.85");
root.style.setProperty("--accent", "#ffb86b");

const { readToken, readAlpha, subscribe } = await import("../static/js/theme/css-tokens.js");

beforeEach(() => {
  root.style.setProperty("--surface-base", "#0e0e10");
  root.style.setProperty("--alpha-stem-fill", "0.85");
  root.style.setProperty("--accent", "#ffb86b");
});

test("readToken returns the resolved CSS variable value", () => {
  assert.equal(readToken("surface-base"), "#0e0e10");
});

test("readAlpha parses a numeric alpha token", () => {
  assert.equal(readAlpha("alpha-stem-fill"), 0.85);
});

test("readAlpha clamps to [0,1] and returns the default on parse failure", () => {
  root.style.setProperty("--alpha-stem-fill", "broken");
  assert.equal(readAlpha("alpha-stem-fill", 0.5), 0.5);
  root.style.setProperty("--alpha-stem-fill", "1.5");
  assert.equal(readAlpha("alpha-stem-fill"), 1);
  root.style.setProperty("--alpha-stem-fill", "-0.2");
  assert.equal(readAlpha("alpha-stem-fill"), 0);
});

test("subscribe fires the callback when musiq:theme-changed dispatches", () => {
  let calls = 0;
  const off = subscribe(() => calls++);
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: {} }));
  assert.equal(calls, 1);
  off();
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: {} }));
  assert.equal(calls, 1);
});
