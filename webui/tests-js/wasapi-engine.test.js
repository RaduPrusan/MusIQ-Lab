// Tests for WasapiEngine's UI-surface contract.
//
// Two real Phase 2 bugs surfaced by manual smoke-test motivated these:
//   1. Transport.mount() calls engine.getMode() / getModeAvailability() /
//      setMode(...). The abstract AudioEngine class in engine.js doesn't
//      declare these methods — only WebAudioEngine defines them. Earlier
//      WasapiEngine was missing them, so switching the engine radio to
//      WASAPI immediately threw "getMode is not a function" at mount.
//   2. WasapiEngine.load() used to throw when no WASAPI device was chosen
//      yet. main.js's loadTrack() bubbled this up and bricked the page on
//      initial mount. Now load() emits a clear `sourceFailed` event and
//      returns cleanly; the device-picker fires __musiqEngineRebuild()
//      after a successful setDevice to retry the load.
//
// These tests pin both behaviours so future Phase 3+ refactors don't
// quietly regress the UI-surface compatibility with WebAudioEngine.

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.location = dom.window.location;
// Note: don't reassign globalThis.performance — Node's built-in works
// and jsdom's Performance.now reaches back into globalThis.performance,
// which would cause infinite recursion when re-aliased.

// In-memory localStorage shim — readable/writable, scoped to one test run.
const _lsStore = new Map();
globalThis.localStorage = {
  getItem: (k) => (_lsStore.has(k) ? _lsStore.get(k) : null),
  setItem: (k, v) => _lsStore.set(k, String(v)),
  removeItem: (k) => _lsStore.delete(k),
  clear: () => _lsStore.clear(),
};

// WasapiEngine opens a WebSocket in its constructor. Replace the global
// with a stub that never actually opens — the methods under test
// (getMode/setMode/setDuration/getModeAvailability/setLoop/clearLoop)
// are synchronous and don't await _ready, so the ws not opening is fine
// as long as the constructor doesn't throw. load() DOES await _ready;
// we don't test load() against a real ws here, only the no-device early
// return path.
class FakeWebSocket {
  constructor() {
    this.readyState = 0;
    this._listeners = new Map();
  }
  addEventListener(ev, fn) {
    if (!this._listeners.has(ev)) this._listeners.set(ev, []);
    this._listeners.get(ev).push(fn);
  }
  send() { /* swallow */ }
  close() { this.readyState = 3; }
}
globalThis.WebSocket = FakeWebSocket;

const { WasapiEngine } = await import("../static/js/audio/wasapi-engine.js");

beforeEach(() => {
  _lsStore.clear();
});

test("Bug 1: WasapiEngine has the full UI-surface method contract", () => {
  const engine = new WasapiEngine();
  // These are the methods Transport / sidebar / main.js call on the
  // engine that the abstract AudioEngine class doesn't declare. The
  // bug was that WasapiEngine inherited the abstract contract and
  // didn't redefine these, so Transport's mount() threw.
  for (const name of [
    "getMode", "getPreferredMode", "getModeAvailability",
    "setMode", "setDuration", "setLoop", "clearLoop",
  ]) {
    assert.equal(typeof engine[name], "function", `missing method: ${name}`);
  }
  engine.dispose();
});

test("Bug 1: getMode returns 'source' (Phase 2)", () => {
  const engine = new WasapiEngine();
  assert.equal(engine.getMode(), "source");
  engine.dispose();
});

test("Bug 1: setMode('source' | 'stems' | null) does not throw; invalid values do", () => {
  const engine = new WasapiEngine();
  // Phase 2 accepts all three without throwing — the user clicks SRC/MIX
  // and a thrown error would surface as a console error mid-interaction.
  assert.doesNotThrow(() => engine.setMode("source"));
  assert.doesNotThrow(() => engine.setMode("stems"));
  assert.doesNotThrow(() => engine.setMode(null));
  // Programming bug (typo) is loud.
  assert.throws(() => engine.setMode("bogus"), /setMode: invalid mode bogus/);
  engine.dispose();
});

test("Bug 1: setMode stores the preference (getPreferredMode reflects it) but getMode is still 'source'", () => {
  const engine = new WasapiEngine();
  engine.setMode("stems");
  assert.equal(engine.getPreferredMode(), "stems");
  // Phase 2 never physically plays stems — getMode is the *active* mode,
  // which stays "source" no matter the preference.
  assert.equal(engine.getMode(), "source");
  engine.setMode(null);
  assert.equal(engine.getPreferredMode(), null);
  engine.dispose();
});

test("Bug 1: getModeAvailability reflects whether the source has loaded", () => {
  const engine = new WasapiEngine();
  // Pre-load: source not yet available.
  let avail = engine.getModeAvailability();
  assert.equal(avail.source, false);
  assert.equal(avail.stems, false);
  // After setDuration (which load() does once the server's `loaded`
  // message arrives), source becomes available.
  engine.setDuration(120.5);
  avail = engine.getModeAvailability();
  assert.equal(avail.source, true);
  assert.equal(avail.stems, false, "stems are Phase 3");
  engine.dispose();
});

test("Bug 1: setDuration(0) / setDuration(-1) collapse to null (mirrors WebAudioEngine)", () => {
  const engine = new WasapiEngine();
  engine.setDuration(0);
  assert.equal(engine.getModeAvailability().source, false);
  engine.setDuration(-1);
  assert.equal(engine.getModeAvailability().source, false);
  engine.setDuration(60);
  assert.equal(engine.getModeAvailability().source, true);
  engine.dispose();
});

test("Bug 1: setMode sends set_mode; modeChanged emits only when the server's StateMsg confirms", () => {
  // The Phase-2 synchronous emit was replaced by the server-confirm design:
  // setMode fire-and-forgets {op:"set_mode"} and modeChanged is emitted from
  // _onMessage when a StateMsg actually flips the mode mirror (wasapi-engine.js
  // setMode + _onMessage "state" branch).
  const engine = new WasapiEngine();
  const sent = [];
  engine._ws.send = (raw) => sent.push(JSON.parse(raw));
  const events = [];
  engine.on("modeChanged", (payload) => events.push(payload));
  engine.setMode("stems");
  // No synchronous emit — confirmation comes from the server.
  assert.equal(events.length, 0, "modeChanged must not fire before StateMsg confirms");
  assert.ok(
    sent.some((m) => m.op === "set_mode" && m.mode === "stems"),
    `expected a set_mode fire-and-forget, sent: ${JSON.stringify(sent)}`,
  );
  // Simulate the server's StateMsg confirmation.
  engine._onMessage({ data: JSON.stringify({ type: "state", playing: false, mode: "stems" }) });
  assert.equal(events.length, 1);
  assert.equal(events[0].mode, "stems");
  engine.dispose();
});

test("Bug 1: setLoop / clearLoop record locally without throwing", () => {
  const engine = new WasapiEngine();
  assert.doesNotThrow(() => engine.setLoop(1.0, 5.0));
  assert.doesNotThrow(() => engine.clearLoop());
  // Invalid loop: end <= start collapses to null end.
  engine.setLoop(5.0, 1.0);
  assert.doesNotThrow(() => engine.clearLoop());
  engine.dispose();
});

test("Bug 2: load() with no device in localStorage emits sourceFailed and returns cleanly (no throw)", async () => {
  const engine = new WasapiEngine();
  const failures = [];
  const availability = [];
  engine.on("sourceFailed", (payload) => failures.push(payload));
  engine.on("modeAvailability", (payload) => availability.push(payload));
  // localStorage has no `musiq.audio` entry → no device chosen yet.
  // Earlier this would throw and main.js would brick the page.
  // _ready resolves immediately because FakeWebSocket emits no open
  // event but our `_send` is never reached on this path — the no-device
  // early return fires first, before any await of _ready.
  await engine.load({ sourceUrl: "/api/tracks/demo_slug/audio/source" });
  assert.equal(failures.length, 1, "sourceFailed should fire exactly once");
  assert.match(failures[0].error, /no device chosen/i);
  // modeAvailability also fires with source=false so Transport disables
  // the SRC button instead of showing it as ready.
  assert.ok(availability.length >= 1);
  const last = availability[availability.length - 1];
  assert.equal(last.source, false);
  assert.equal(last.stems, false);
  engine.dispose();
});
