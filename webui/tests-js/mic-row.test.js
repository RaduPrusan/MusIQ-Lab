// Tests for the Live Input sidebar row.
import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;

import { MicRow } from "../static/js/ui/mic-row.js";

function fakeMic() {
  return new (class extends EventTarget {
    _ref = null; _off = 0; _dev = null; _running = false;
    setReferenceStem(s) { this._ref = s; }
    setOffsetMs(n) { this._off = n; }
    setDeviceId(d) { this._dev = d; }
    getOffsetMs() { return this._off; }
    getReferenceStem() { return this._ref; }
    isRunning() { return this._running; }
    async start() { this._running = true; this.dispatchEvent(new Event("started")); }
    stop() { this._running = false; this.dispatchEvent(new Event("stopped")); }
  })();
}

function fakeTrackData(notesPresent = ["vocals", "piano"]) {
  const td = { notes: {} };
  for (const name of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
    td.notes[name] = notesPresent.includes(name)
      ? { t: new Float32Array([0]), dur: new Float32Array([1]), midi: new Uint8Array([60]), transcribed: true }
      : { t: new Float32Array(), dur: new Float32Array(), midi: new Uint8Array(), transcribed: false };
  }
  return td;
}

test("MicRow renders label 'Live Input' + an M button", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const row = new MicRow({ host, micPitch: fakeMic(), trackData: fakeTrackData() });
  row.mount();
  assert.match(host.textContent, /Live Input/);
  assert.ok(host.querySelector(".btn.m"), "expected .btn.m mute button");
});

test("MicRow reference dropdown lists only stems with notes (plus 'none')", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const row = new MicRow({
    host,
    micPitch: fakeMic(),
    trackData: fakeTrackData(["vocals", "bass"]),
  });
  row.mount();
  const opts = [...host.querySelectorAll("select.mic-ref option")].map((o) => o.value);
  assert.deepEqual(opts.sort(), ["bass", "none", "vocals"]);
});

test("MicRow persists offset slider changes to localStorage", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData() });
  row.mount();
  const slider = host.querySelector(".mic-offset");
  // Stub the slider's rect (jsdom returns zeros by default) so attachDrag's
  // frac-from-clientX math knows where the user clicked. Width 200 maps
  // 1:1 to the slider's value range (-150..+50ms = 200ms wide).
  slider.getBoundingClientRect = () => ({ left: 0, right: 200, top: 0, bottom: 4, width: 200, height: 4, x: 0, y: 0, toJSON: () => ({}) });
  slider.setPointerCapture = () => {};
  slider.releasePointerCapture = () => {};
  // Simulate a pointerdown at clientX=100 → frac=0.5 → value -50ms.
  const evt = new dom.window.Event("pointerdown", { bubbles: true });
  Object.defineProperty(evt, "clientX", { value: 100 });
  Object.defineProperty(evt, "button", { value: 0 });
  Object.defineProperty(evt, "pointerId", { value: 1 });
  slider.dispatchEvent(evt);
  assert.equal(localStorage.getItem("musiq.mic.offsetMs"), "-50");
  assert.equal(mic.getOffsetMs(), -50);
});

test("MicRow M-button toggles mic.start/stop and updates status dot", async () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData() });
  row.mount();
  const btn = host.querySelector(".btn.m");
  const rowEl = host.querySelector(".track-row.mic");
  // Off state: row does NOT carry the .mic-on modifier; M button doesn't
  // carry .mic-live. (CSS uses these to drive the dot colour + button
  // accent — the test exercises the JS toggle that flips them.)
  assert.ok(!rowEl.classList.contains("mic-on"), "row should not be .mic-on initially");
  assert.ok(!btn.classList.contains("mic-live"), "M btn should not be .mic-live initially");
  btn.click();
  // start() is async; wait a microtask.
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(rowEl.classList.contains("mic-on"), "row should flip to .mic-on after start");
  assert.ok(btn.classList.contains("mic-live"), "M btn should flip to .mic-live after start");
  btn.click();
  assert.ok(!rowEl.classList.contains("mic-on"), "row should clear .mic-on after stop");
});

test("MicRow reference falls back to first present stem if persisted ref is missing", () => {
  localStorage.clear();
  localStorage.setItem("musiq.mic.referenceStem", "guitar");  // not present
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData(["vocals", "bass"]) });
  row.mount();
  // Fell back to "vocals" (first present).
  assert.equal(mic.getReferenceStem(), "vocals");
});

test("MicRow readout reformats on musiq:notation-changed", () => {
  localStorage.clear();
  // Default notation = scientific.
  localStorage.setItem("musiq.notation", "scientific");
  const host = document.createElement("div");
  const mic = fakeMic();
  const td = fakeTrackData();
  td.meta = { key: "C major" };
  const row = new MicRow({ host, micPitch: mic, trackData: td });
  row.mount();
  // Push a sample with MIDI 69 (A4).
  mic.dispatchEvent(new CustomEvent("sample", { detail: { midi: 69, cents: 0, freq: 440, clarity: 1, rms: 0.1 }}));
  const readout = host.querySelector(".mic-readout");
  // Scientific: should contain "A4".
  assert.match(readout.textContent, /A4/);
  // Switch to solfège.
  // notation-prefs.js dispatches on document (not window).
  localStorage.setItem("musiq.notation", "solfege");
  document.dispatchEvent(new dom.window.Event("musiq:notation-changed"));
  assert.match(readout.textContent, /La4|La/);
});

test("MicRow does not leak document listeners across setTrackData() calls", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const td1 = fakeTrackData(["vocals"]);
  const td2 = fakeTrackData(["bass"]);
  td1.meta = { key: "C major" };
  td2.meta = { key: "C major" };

  const row = new MicRow({ host, micPitch: mic, trackData: td1 });
  row.mount();

  // Switch tracks several times. Each setTrackData calls mount().
  row.setTrackData(td2);
  row.setTrackData(td1);
  row.setTrackData(td2);

  // Push a sample so _lastReadoutDetail is set.
  mic.dispatchEvent(new CustomEvent("sample", {
    detail: { midi: 69, cents: 0, freq: 440, clarity: 1, rms: 0.1 },
  }));

  // Count how many times _updateReadout fires from one notation-changed event.
  let fires = 0;
  const origUpdate = row._updateReadout.bind(row);
  row._updateReadout = (d) => { fires++; origUpdate(d); };

  document.dispatchEvent(new dom.window.Event("musiq:notation-changed"));
  // With the leak fix, exactly one listener is attached at any time.
  assert.equal(fires, 1, `expected exactly 1 readout update, got ${fires} (listener leak)`);
});
