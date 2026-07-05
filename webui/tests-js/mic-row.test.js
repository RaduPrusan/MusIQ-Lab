// Tests for the Live Input sidebar row.
import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.localStorage = dom.window.localStorage;
// App code constructs bare `new CustomEvent(...)` for its document-level
// broadcasts (stem-mute, mic-transpose). jsdom's dispatchEvent brand-checks
// the event and rejects Node's built-in Event classes, so align the Event
// globals (and EventTarget, which fakeMic extends) with the jsdom window.
globalThis.Event = dom.window.Event;
globalThis.CustomEvent = dom.window.CustomEvent;
globalThis.EventTarget = dom.window.EventTarget;

import { MicRow } from "../static/js/ui/mic-row.js";

function fakeMic() {
  return new (class extends EventTarget {
    _ref = null; _off = 0; _dev = null; _running = false; _transpose = 0;
    setReferenceStem(s) { this._ref = s; }
    setOffsetMs(n) { this._off = n; }
    setDeviceId(d) { this._dev = d; }
    setTranspose(n) { this._transpose = Math.max(-24, Math.min(24, Math.round(n))); }
    getOffsetMs() { return this._off; }
    getReferenceStem() { return this._ref; }
    getTranspose() { return this._transpose; }
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

test("MicRow renders the transpose spinner on both full and compact variants with signed value", () => {
  localStorage.clear();
  localStorage.setItem("musiq.mic.transpose", "3");

  // Full row: spinner lives in the .mic-meta sub-row.
  const fullHost = document.createElement("div");
  new MicRow({ host: fullHost, micPitch: fakeMic(), trackData: fakeTrackData() }).mount();
  const fullSpinner = fullHost.querySelector(".mic-meta .mic-transpose");
  assert.ok(fullSpinner, "full row: expected .mic-transpose inside .mic-meta");
  assert.ok(fullSpinner.querySelector(".mic-transpose-btn.up"), "full row: up stepper");
  assert.ok(fullSpinner.querySelector(".mic-transpose-btn.down"), "full row: down stepper");
  // Positive values render with an explicit sign.
  assert.equal(fullSpinner.querySelector(".mic-transpose-value").textContent, "+3");

  // Compact row: no sub-meta, spinner sits inline in the .ms button cell.
  const compactHost = document.createElement("div");
  new MicRow({ host: compactHost, micPitch: fakeMic(), trackData: fakeTrackData(), compact: true }).mount();
  assert.ok(!compactHost.querySelector(".mic-meta"), "compact row must not attach a sub-meta");
  const compactSpinner = compactHost.querySelector(".ms .mic-transpose");
  assert.ok(compactSpinner, "compact row: expected .mic-transpose inside .ms");
  assert.equal(compactSpinner.querySelector(".mic-transpose-value").textContent, "+3");
});

test("MicRow transpose steppers apply via mic.setTranspose and persist to localStorage", () => {
  localStorage.clear();
  const host = document.createElement("div");
  const mic = fakeMic();
  const row = new MicRow({ host, micPitch: mic, trackData: fakeTrackData() });
  row.mount();
  // Persisted default (0) is applied on mount like offset/ref/device.
  assert.equal(mic.getTranspose(), 0);
  const value = host.querySelector(".mic-transpose-value");
  assert.equal(value.textContent, "0");

  host.querySelector(".mic-transpose-btn.up").click();
  assert.equal(mic.getTranspose(), 1);
  assert.equal(localStorage.getItem("musiq.mic.transpose"), "1");
  assert.equal(value.textContent, "+1");

  host.querySelector(".mic-transpose-btn.down").click();
  host.querySelector(".mic-transpose-btn.down").click();
  assert.equal(mic.getTranspose(), -1);
  assert.equal(localStorage.getItem("musiq.mic.transpose"), "-1");
  assert.equal(value.textContent, "-1", "negative values must render");
});

test("MicRow transpose spinners sync across rows via musiq:mic-transpose-changed", () => {
  localStorage.clear();
  // Same MicPitch instance behind both surfaces, as in the app
  // (window.__musiqMic is shared by sidebar.js and lyrics-tab.js).
  const mic = fakeMic();
  const hostA = document.createElement("div");
  const hostB = document.createElement("div");
  const rowA = new MicRow({ host: hostA, micPitch: mic, trackData: fakeTrackData() });
  const rowB = new MicRow({ host: hostB, micPitch: mic, trackData: fakeTrackData(), compact: true });
  rowA.mount();
  rowB.mount();

  // Stepping on the full row updates the compact row's display.
  hostA.querySelector(".mic-transpose-btn.up").click();
  assert.equal(hostB.querySelector(".mic-transpose-value").textContent, "+1");
  // …and stepping on the compact row updates the full row.
  hostB.querySelector(".mic-transpose-btn.down").click();
  hostB.querySelector(".mic-transpose-btn.down").click();
  assert.equal(hostA.querySelector(".mic-transpose-value").textContent, "-1");
  assert.equal(mic.getTranspose(), -1);

  // Remount hygiene: setTrackData() remounts; the stale document listener
  // must be removed, so one step still means one increment (not N).
  rowA.setTrackData(fakeTrackData(["vocals"]));
  hostA.querySelector(".mic-transpose-btn.up").click();
  assert.equal(mic.getTranspose(), 0);
  assert.equal(hostB.querySelector(".mic-transpose-value").textContent, "0");
  rowB.unmount();
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
