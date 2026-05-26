// Integration test for the live-mic chain. We wire a real MicPitch to
// fake engine + fake audioContext + fake worklet, then push a sequence
// of synthetic Yin-output messages and assert the ring buffer ends up
// with the right (song-time, midi) pairs.
//
// (Spinning up a real AudioContext + Worklet in node:test is not
// available — that's why this test injects fakes at the seam.)

import { test } from "node:test";
import assert from "node:assert/strict";

import { MicPitch } from "../static/js/audio/mic-pitch.js";

test("MicPitch integration: synthetic melody fills the ring buffer at the right offsets", () => {
  // Engine + ctx walk forward together.
  let song = 10.0, ctx = 5.0;
  const engine = { get currentTime() { return song; }, isPlaying: true, on() {}, off() {} };
  const audioContext = { get currentTime() { return ctx; } };

  const node = { port: { onmessage: null, postMessage() {} } };
  const factory = () => node;
  const mic = new MicPitch({ engine, audioContext, workletFactory: factory });
  mic._attachForTest();

  // Synthetic melody: 5 frames, 200 ms apart, freqs 220, 247, 261, 247, 220
  // (A3, B3, C4, B3, A3). Spacing chosen > EMA_GAP_S (150 ms) so each
  // frame trips the write-time EMA reset in MicPitch and lands in the
  // ring as its raw value — keeps the assertion checking the worklet →
  // coordinator data flow, not the smoother's internal coefficients.
  const seq = [
    [220.000, 57], [246.942, 59], [261.626, 60], [246.942, 59], [220.000, 57],
  ];
  for (let i = 0; i < seq.length; i++) {
    const [hz, expectedMidi] = seq[i];
    song += 0.2;
    ctx  += 0.2;
    // Worklet processes the block at ctxTime = current ctx (so block age = 0).
    node.port.onmessage({ data: { freq: hz, clarity: 0.95, rms: 0.1, ctxTime: ctx }});
    const samples = mic.getSamplesInRange(-1e6, 1e6);
    // Ring stores continuous (float) MIDI since dcd5c56 — assert nearest
    // semitone matches expected. The seq freqs are exact tempered tones
    // so the float MIDI is integer-equal in principle, but Float32
    // round-trip can drift by ~1e-5 cents; round to nearest for a
    // tolerant assertion.
    const got = samples.midi[samples.midi.length - 1];
    assert.equal(Math.round(got), expectedMidi,
      `frame ${i}: expected MIDI ${expectedMidi} for ${hz} Hz, got ${got}`);
  }
  // Final state.
  const s = mic.getSamplesInRange(-1e6, 1e6);
  assert.equal(s.time.length, 5);
  // Times should be monotonically increasing.
  for (let i = 1; i < s.time.length; i++) {
    assert.ok(s.time[i] > s.time[i - 1], `times not monotonic at ${i}`);
  }
});
