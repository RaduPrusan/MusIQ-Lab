import { test } from "node:test";
import assert from "node:assert/strict";

import { filterTracks } from "../static/js/ui/track-picker.js";

const TRACKS = [
  { slug: "a", title: "Apple",  key: "C major", tempo_bpm: 120, duration_sec: 180, has_vocals: true,  summary_mtime_ns: 100 },
  { slug: "b", title: "Banana", key: "G major", tempo_bpm:  90, duration_sec: 200, has_vocals: false, summary_mtime_ns: 200 },
  { slug: "c", title: "Cherry", key: "D minor", tempo_bpm: 140, duration_sec: 150, has_vocals: true,  summary_mtime_ns: 150 },
];

test("default sort is by recent (mtime desc)", () => {
  const r = filterTracks(TRACKS, {});
  assert.deepEqual(r.map((t) => t.slug), ["b", "c", "a"]);
});

test("query filters by title (case-insensitive)", () => {
  const r = filterTracks(TRACKS, { query: "ban" });
  assert.deepEqual(r.map((t) => t.slug), ["b"]);
});

test("hasVocals=instr keeps only instrumental", () => {
  const r = filterTracks(TRACKS, { hasVocals: "instr" });
  assert.deepEqual(r.map((t) => t.slug), ["b"]);
});

test("hasVocals=vocal keeps only vocal", () => {
  const r = filterTracks(TRACKS, { hasVocals: "vocal" });
  assert.deepEqual(r.map((t) => t.slug).sort(), ["a", "c"]);
});

test("sort=tempo ascending", () => {
  const r = filterTracks(TRACKS, { sort: "tempo" });
  assert.deepEqual(r.map((t) => t.slug), ["b", "a", "c"]);
});

test("sort=title alphabetical", () => {
  const r = filterTracks(TRACKS, { sort: "title" });
  assert.deepEqual(r.map((t) => t.slug), ["a", "b", "c"]);
});

test("track-picker header includes + File and + YT buttons", async () => {
  const { JSDOM } = await import("jsdom");
  const dom = new JSDOM("<!doctype html><html><body><div id='picker'></div></body></html>");
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  globalThis.HTMLElement = dom.window.HTMLElement;
  const { mountTrackPicker } = await import("../static/js/ui/track-picker.js");
  const picker = dom.window.document.getElementById("picker");
  mountTrackPicker(picker, [], { currentSlug: null, onPick: () => {} });
  picker.toggle();
  const headerText = picker.querySelector(".tp-header")?.textContent ?? "";
  assert.match(headerText, /\+ File/);
  assert.match(headerText, /\+ YT/);
});
