import { test } from "node:test";
import assert from "node:assert/strict";

const { PRESETS, PRESET_IDS, DEFAULT_PRESET_ID } = await import("../static/js/theme/presets.js");

const REQUIRED_TOKENS = [
  "surface-base","surface-1","surface-2","surface-3",
  "text-primary","text-secondary","text-muted","text-disabled",
  "accent","accent-emphasis","accent-on",
  "focus-ring",
  "status-error","status-error-bg","status-warning","status-success","status-info",
  "stem-vocals","stem-bass","stem-guitar","stem-piano","stem-other","stem-drums",
  "fn-tonic-bg","fn-tonic-fg","fn-dominant-bg","fn-dominant-fg","fn-modal-bg","fn-modal-fg","fn-predominant-fg",
  "border-soft","border-strong",
  "alpha-scrim","alpha-overlay-soft","alpha-overlay-med","alpha-overlay-strong",
  "alpha-glow-soft","alpha-glow-strong","alpha-grid-line","alpha-stem-fill",
  "alpha-loop-band-fill","alpha-loop-band-stroke",
  "alpha-play-band-fill","alpha-play-band-stroke",
  "radius-1","radius-2","radius-3","radius-4","radius-pill",
  "motion-fast","motion-medium","motion-slow",
];

test("PRESET_IDS contains the five named presets", () => {
  assert.deepEqual(PRESET_IDS.sort(), ["classic-dark","high-contrast","jinn","midnight","studio-light"]);
});

test("DEFAULT_PRESET_ID is jinn", () => {
  assert.equal(DEFAULT_PRESET_ID, "jinn");
});

for (const id of ["classic-dark","midnight","studio-light","high-contrast","jinn"]) {
  test(`preset '${id}' defines every required token`, () => {
    const p = PRESETS[id];
    assert.ok(p, `preset ${id} missing`);
    for (const name of REQUIRED_TOKENS) {
      assert.ok(name in p, `preset ${id} missing token ${name}`);
    }
  });
}
