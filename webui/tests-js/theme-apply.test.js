import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;

const { applyTheme } = await import("../static/js/theme/apply.js");
const root = dom.window.document.documentElement;

beforeEach(() => {
  root.removeAttribute("style");
});

test("applyTheme sets every token as a CSS custom property on documentElement", () => {
  applyTheme({ "accent": "#ff00ff", "alpha-scrim": "0.42" });
  assert.equal(root.style.getPropertyValue("--accent").trim(), "#ff00ff");
  assert.equal(root.style.getPropertyValue("--alpha-scrim").trim(), "0.42");
});

test("applyTheme overwrites prior values cleanly", () => {
  applyTheme({ "accent": "#aaaaaa" });
  applyTheme({ "accent": "#bbbbbb" });
  assert.equal(root.style.getPropertyValue("--accent").trim(), "#bbbbbb");
});
