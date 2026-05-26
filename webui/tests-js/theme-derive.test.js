import { test } from "node:test";
import assert from "node:assert/strict";

const { deriveAccentEmphasis, deriveAccentOn, hexToRgb, relativeLuminance } =
  await import("../static/js/theme/derive.js");

test("hexToRgb accepts 3- and 6-digit hex", () => {
  assert.deepEqual(hexToRgb("#fff"),    { r: 255, g: 255, b: 255 });
  assert.deepEqual(hexToRgb("#000000"), { r: 0,   g: 0,   b: 0 });
  assert.deepEqual(hexToRgb("#ffb86b"), { r: 255, g: 184, b: 107 });
});

test("relativeLuminance matches WCAG examples within rounding", () => {
  assert.ok(Math.abs(relativeLuminance({ r: 255, g: 255, b: 255 }) - 1.0) < 1e-6);
  assert.ok(relativeLuminance({ r: 0, g: 0, b: 0 }) === 0);
});

test("deriveAccentOn picks dark for light accents", () => {
  assert.equal(deriveAccentOn("#ffb86b"), "#1a1a25");
  assert.equal(deriveAccentOn("#ffd166"), "#1a1a25");
});

test("deriveAccentOn picks white for dark accents", () => {
  assert.equal(deriveAccentOn("#3a2a4a"), "#ffffff");
  assert.equal(deriveAccentOn("#1a1a25"), "#ffffff");
});

test("deriveAccentEmphasis returns a color-mix string", () => {
  const e = deriveAccentEmphasis("#ffb86b");
  assert.match(e, /^color-mix\(in srgb, #ffb86b 92%, #ffffff 8%\)$/);
});
