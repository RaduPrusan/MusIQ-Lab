import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { JSDOM } from "jsdom";
const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.document ??= dom.window.document;
globalThis.window ??= dom.window;

import {
  QUALITY_PRESETS,
  STAGE_ORDER,
  STAGE_LABELS,
  STATUS_COLOR,
  parseNdjsonStream,
  formatElapsed,
  createStageBar,
  createOverallTimer,
  pitchNameToMidi,
  renderStats,
} from "../static/js/ui/analyze-shared.js";

test("QUALITY_PRESETS exposes fast/normal/best with stable ordering", () => {
  const ids = QUALITY_PRESETS.map((p) => p.value);
  assert.deepEqual(ids, ["fast", "normal", "best"]);
});

test("STAGE_ORDER includes all known stages", () => {
  for (const name of ["stems", "beats", "key", "chords", "transcription", "beats_xcheck", "vocal_f0", "drums"]) {
    assert.ok(STAGE_ORDER.includes(name), `missing ${name}`);
  }
});

test("STAGE_ORDER mirrors analyze.pipeline._STAGE_EXECUTION_ORDER (10 stages, vocal_f0 before transcription)", () => {
  // Exact order: must match analyze/pipeline.py:83-96. vocal_f0 < transcription
  // because transcription_vocals reads vocal_f0.npz; vocal_consensus_contour
  // last because it consumes vocal_f0 + transcription.
  assert.deepEqual(STAGE_ORDER, [
    "stems",
    "stems_dynamics",
    "beats",
    "key",
    "chords",
    "vocal_f0",
    "transcription",
    "beats_xcheck",
    "drums",
    "vocal_consensus_contour",
  ]);
});

test("STATUS_COLOR has running/cached/done/error", () => {
  assert.ok(STATUS_COLOR.running);
  assert.ok(STATUS_COLOR.cached);
  assert.ok(STATUS_COLOR.done);
  assert.ok(STATUS_COLOR.error);
});

test("reanalyze.js DEFAULT_QUALITY is 'best'", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(resolve(here, "../static/js/ui/reanalyze.js"), "utf-8");
  assert.match(src, /const DEFAULT_QUALITY = "best";/);
});

test("formatElapsed renders M:SS with zero-padded seconds; '—' for null/negative", () => {
  assert.equal(formatElapsed(0), "0:00");
  assert.equal(formatElapsed(1500), "0:01");
  assert.equal(formatElapsed(65 * 1000), "1:05");
  assert.equal(formatElapsed(125 * 1000), "2:05");
  assert.equal(formatElapsed(null), "—");
  assert.equal(formatElapsed(-1), "—");
});

test("createStageBar renders one chip per STAGE_ORDER entry with friendly labels", () => {
  const c = createStageBar();
  assert.equal(c.root.children.length, STAGE_ORDER.length);
  // Spot-check that the friendly label, not the raw backend name, is rendered
  // (the chip's first child is the label span).
  const consensusChip = c.root.children[STAGE_ORDER.indexOf("vocal_consensus_contour")];
  assert.match(consensusChip.textContent, /vocal consensus/);
  const dynamicsChip = c.root.children[STAGE_ORDER.indexOf("stems_dynamics")];
  assert.match(dynamicsChip.textContent, /stem dynamics/);
});

test("createStageBar.setStage toggles chip presentation per status", () => {
  const c = createStageBar();
  const i = STAGE_ORDER.indexOf("stems");
  c.setStage("stems", "running");
  assert.match(c.root.children[i].textContent, /^▶ /, "running chip is prefixed with ▶");
  c.setStage("stems", "done");
  assert.match(c.root.children[i].textContent, /^✓ /, "done chip is prefixed with ✓");
  c.setStage("beats", "cached");
  const beatsChip = c.root.children[STAGE_ORDER.indexOf("beats")];
  assert.match(beatsChip.textContent, /\(cached\)/);
  c.stop();
});

test("createOverallTimer.elapsedMs is 0 before start and frozen after stop", () => {
  const t = createOverallTimer();
  assert.equal(t.elapsedMs(), 0);
  t.start();
  t.stop();
  const a = t.elapsedMs();
  // Frozen — sampling again returns the same value.
  assert.equal(t.elapsedMs(), a);
});

test("pitchNameToMidi: ASCII and Unicode accidentals + middle-C anchor", () => {
  assert.equal(pitchNameToMidi("C4"), 60, "middle C");
  assert.equal(pitchNameToMidi("A4"), 69, "A 440");
  // Unicode ♯/♭ — what the backend emits (U+266F / U+266D).
  assert.equal(pitchNameToMidi("F♯2"), 42);
  assert.equal(pitchNameToMidi("E♭5"), 75);
  // ASCII variants for safety.
  assert.equal(pitchNameToMidi("F#2"), 42);
  assert.equal(pitchNameToMidi("Eb5"), 75);
  // Negative octaves (rare, but valid for sub-bass).
  assert.equal(pitchNameToMidi("C-1"), 0);
  // Span sanity: B6 (MIDI 95) - F♯2 (MIDI 42) = 53 semitones (the actual
  // Lou Reed Perfect Day values from the failing screenshot — pins the bug
  // fix forever).
  assert.equal(pitchNameToMidi("B6"), 95);
  assert.equal(pitchNameToMidi("F♯2"), 42);
  assert.equal(pitchNameToMidi("B6") - pitchNameToMidi("F♯2"), 53);
  // Unparseable input.
  assert.equal(pitchNameToMidi("nope"), null);
  assert.equal(pitchNameToMidi(null), null);
  assert.equal(pitchNameToMidi(""), null);
});

test("renderStats: vocal_range reads {low, high}, computes span, no 'undefined'", () => {
  const target = document.createElement("div");
  renderStats(target, {
    duration_sec: 222.79,
    vocal_range: { low: "F♯2", high: "B6" },
  });
  const txt = target.textContent;
  // Must NOT contain "undefined" — the regression we're guarding against.
  assert.ok(!/undefined/.test(txt), `regression: rendered text contains "undefined":\n${txt}`);
  // Must contain the actual pitch names + computed span.
  assert.match(txt, /F♯2/);
  assert.match(txt, /B6/);
  assert.match(txt, /53 st/);
});

test("renderStats: vocal_range falls back to '—' when null or shape-broken", () => {
  for (const vr of [null, undefined, {}, { low: "C4" }, { high: "C5" }]) {
    const target = document.createElement("div");
    renderStats(target, { duration_sec: 60, vocal_range: vr });
    assert.ok(!/undefined/.test(target.textContent), `'undefined' leaked for ${JSON.stringify(vr)}`);
  }
});

test("renderStats: Duration shows M:SS rounded, no decimal", () => {
  const target = document.createElement("div");
  renderStats(target, { duration_sec: 222.79 });
  // 222.79s = 3:42.79 rounds to 3:43; old format produced "3:42.8".
  assert.match(target.textContent, /3:43/);
  assert.ok(!/3:42\.8/.test(target.textContent), "must not show fractional-second format");
});

test("STAGE_LABELS covers every entry in STAGE_ORDER", () => {
  for (const name of STAGE_ORDER) {
    assert.ok(STAGE_LABELS[name], `missing label for ${name}`);
  }
});

test("parseNdjsonStream splits lines including those crossing chunk boundaries", async () => {
  async function* gen() {
    yield new TextEncoder().encode('{"type":"log","line":"a"}\n{"type":"sta');
    yield new TextEncoder().encode('ge","name":"stems","status":"running"}\n');
  }
  const events = [];
  for await (const ev of parseNdjsonStream(gen())) events.push(ev);
  assert.equal(events.length, 2);
  assert.equal(events[0].line, "a");
  assert.equal(events[1].name, "stems");
});
