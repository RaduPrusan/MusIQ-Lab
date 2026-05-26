import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Minimal DOM bootstrap; jsdom is a transitive dev-dep already used by playwright.
const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.HTMLElement = dom.window.HTMLElement;

test("showAnalyzeModal({mode:'file'}) renders the file-input step", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /Analyze new audio file/i);
  const fileInput = overlay.querySelector('input[type="file"]');
  assert.ok(fileInput);
  assert.equal(fileInput.getAttribute("accept"), ".mp3,.wav,.flac");
  const buttons = overlay.querySelectorAll("button");
  const analyzeBtn = [...buttons].find((b) => /Analyze/i.test(b.textContent));
  assert.ok(analyzeBtn);
  assert.equal(analyzeBtn.disabled, true);
  overlay.remove();
});

// Stale-fetch race guard: when the user picks file A, then quickly picks file
// B before A's slugForFilename resolves, A's stale result must not overwrite
// B's state. Verified structurally via source pin (functional simulation
// would require exposing the closure-local `state` object).
test("file-picker handler guards against stale slugForFilename result", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(resolve(here, "../static/js/ui/analyze-modal.js"), "utf-8");
  // Both await call sites (success + catch) must check `state.file !== file`.
  const guards = src.match(/if \(state\.file !== file\) return;/g) || [];
  assert.ok(guards.length >= 2, `expected ≥2 stale-fetch guards, found ${guards.length}`);
});

test("showAnalyzeModal({mode:'youtube'}) renders the URL-input step", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "youtube" });
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /Analyze YouTube URL/i);
  const urlInput = overlay.querySelector('input[type="text"]');
  assert.ok(urlInput);
  const buttons = overlay.querySelectorAll("button");
  const analyzeBtn = [...buttons].find((b) => /Analyze/i.test(b.textContent));
  assert.equal(analyzeBtn.disabled, true);
  overlay.remove();
});

test("collision step renders three buttons with the suggested slug", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  // Force the modal into the collision state directly via the exported helper.
  mod._renderCollisionStep(overlay.querySelector("div > div"), overlay, {
    mode: "file",
    quality: "best",
    slug: "bohemian_rhapsody",
    suggestedNew: "bohemian_rhapsody-2",
    exists: true,
  });
  const buttonText = [...overlay.querySelectorAll("button")].map((b) => b.textContent);
  assert.ok(buttonText.some((t) => /Add New bohemian_rhapsody-2/.test(t)));
  assert.ok(buttonText.some((t) => /^Reanalyze$/.test(t)));
  assert.ok(buttonText.some((t) => /^Cancel$/.test(t)));
  overlay.remove();
});

test("streaming step renders phase strip with file-flow phases", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  mod._renderStreamingStep(overlay.querySelector("div > div"), overlay, {
    mode: "file",
    quality: "best",
    slug: "brand_new",
    file: new dom.window.File([new Uint8Array(0)], "brand_new.mp3"),
  }, { mode: "new", slug: "brand_new" });

  const phaseChips = overlay.querySelectorAll(".analyze-phase-chip");
  const labels = [...phaseChips].map((c) => c.textContent);
  // file flow: upload → transcode (hidden for mp3 source) → analyze
  assert.ok(labels.some((l) => /Upload/i.test(l)));
  assert.ok(labels.some((l) => /Analyze/i.test(l)));
  overlay.remove();
});

test("streaming step renders phase strip with YouTube-flow phases", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "youtube" });
  mod._renderStreamingStep(overlay.querySelector("div > div"), overlay, {
    mode: "youtube",
    quality: "best",
    slug: "fresh-slug",
    url: "https://x",
  }, { mode: "new", slug: "fresh-slug" });

  const phaseChips = overlay.querySelectorAll(".analyze-phase-chip");
  const labels = [...phaseChips].map((c) => c.textContent);
  assert.ok(labels.some((l) => /Download/i.test(l)));
  assert.ok(labels.some((l) => /Analyze/i.test(l)));
  overlay.remove();
});
