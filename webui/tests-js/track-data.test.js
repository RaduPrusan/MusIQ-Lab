import { test } from "node:test";
import assert from "node:assert/strict";

import { buildTrackData } from "../static/js/data/track-data.js";

const SUMMARY = {
  track: {
    file: "Some Title-AbCdEfGhIjK.mp3",
    duration_sec: 215.064,
    tempo_bpm: 107.14,
    key: "F minor",
    time_signature: "4/4",
  },
  sections: [],
  downbeats: [0.76, 3.01, 5.25],
  chords: [
    { start: 0.0, end: 2.95, label: "N",     root: null, type: "N",   roman: null,  function: null,    confidence: 1.0 },
    { start: 2.95, end: 5.22, label: "F:min", root: "F",  type: "min", roman: "i",   function: "tonic", confidence: 1.0 },
  ],
  stems: {
    vocals: { notes: [
      { t: 0.29, dur: 0.24, midi: 67, name: "G4", vel: 0.6, scale_deg: "2", in_chord: null, role: null },
      { t: 0.55, dur: 0.30, midi: 65, name: "F4", vel: 0.5, scale_deg: "1", in_chord: true, role: "chord_tone" },
    ] },
    bass:   { notes: [{ t: 0.0, dur: 1.0, midi: 41, name: "F2", vel: 0.7, scale_deg: "1", in_chord: true, role: "chord_tone" }] },
    guitar: { notes: [] },
    piano:  { notes: [] },
    other:  { notes: [] },
    drums:  { transcribed: false, reason: "drums skipped per Stage 6" },
  },
  analysis: {
    scale: "F natural minor",
    modal_interchange_count: 29,
    predominant_chord_loop: ["F:min", "C:min", "C#:maj", "Ab:maj"],
    loop_roman: ["i", "v", "♭VI", "♭III"],
    loop_appearances: [{ start: 2.95, end: 12.1 }],
    vocal_range: { low: "F2", high: "C7" },
  },
  provenance: { models: { "audio-separator": "0.44.1" }, warnings: [] },
};

const F0 = {
  fcpe:  [0.0, 220.0, 0.0, 440.5],
  pesto: [110.1, 220.1, 330.1, 440.1],
  hop_sec: 0.01,
  n_frames: 4,
};

test("buildTrackData populates meta from track block", () => {
  const td = buildTrackData(SUMMARY, F0, "my-slug");
  assert.equal(td.meta.slug, "my-slug");
  assert.equal(td.meta.title, "Some Title");
  assert.equal(td.meta.durationSec, 215.064);
  assert.equal(td.meta.tempoBpm, 107.14);
  assert.equal(td.meta.key, "F minor");
  assert.equal(td.meta.scale, "F natural minor");
  assert.equal(td.meta.timeSig, "4/4");
});

test("downbeats become a Float32Array", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.ok(td.downbeats instanceof Float32Array);
  assert.equal(td.downbeats.length, 3);
  assert.ok(Math.abs(td.downbeats[0] - 0.76) < 1e-5);
});

test("chords array is preserved with the fields the renderer needs", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.equal(td.chords.length, 2);
  assert.deepEqual(td.chords[1], { start: 2.95, end: 5.22, label: "F:min", roman: "i", fn: "tonic" });
});

test("notes are packed into typed arrays per stem", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.ok(td.notes.vocals.t instanceof Float32Array);
  assert.ok(td.notes.vocals.dur instanceof Float32Array);
  assert.ok(td.notes.vocals.midi instanceof Uint8Array);
  assert.ok(td.notes.vocals.vel instanceof Float32Array);
  assert.equal(td.notes.vocals.t.length, 2);
  assert.equal(td.notes.vocals.midi[0], 67);
  assert.equal(td.notes.vocals.midi[1], 65);
});

test("note meta is preserved as plain array for inspector", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.equal(td.notes.vocals.meta.length, 2);
  assert.equal(td.notes.vocals.meta[0].name, "G4");
  assert.equal(td.notes.vocals.meta[0].scale_deg, "2");
});

test("stems without notes (drums) yield empty packed arrays", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.ok(td.notes.drums.t instanceof Float32Array);
  assert.equal(td.notes.drums.t.length, 0);
  assert.equal(td.notes.drums.transcribed, false);
});

test("drums v2 events shape packs onsets per substem with velocity + total", () => {
  const summary = {
    ...SUMMARY,
    stems: {
      ...SUMMARY.stems,
      drums: {
        transcribed: true,
        model: "larsnet",
        kick:    [{t: 0.05, vel: 0.9}, {t: 0.53, vel: 0.7}, {t: 1.06, vel: 1.0}, {t: 1.54, vel: 0.4}],
        snare:   [{t: 0.55, vel: 0.85}, {t: 1.54, vel: 0.95}, {t: 2.55, vel: 0.6}],
        toms:    [],
        hihat:   [{t: 0.06, vel: 0.5}, {t: 0.56, vel: 0.5}, {t: 1.06, vel: 0.5}, {t: 1.56, vel: 0.5}, {t: 2.06, vel: 0.5}],
        cymbals: [{t: 35.64, vel: 1.0}],
      },
    },
  };
  const td = buildTrackData(summary, F0, "x");
  const drums = td.notes.drums;
  assert.equal(drums.transcribed, true);
  assert.equal(drums.model, "larsnet");
  assert.equal(drums.onsetTotal, 4 + 3 + 0 + 5 + 1);
  assert.ok(drums.drums.kick.t instanceof Float32Array);
  assert.ok(drums.drums.kick.vel instanceof Float32Array);
  assert.equal(drums.drums.kick.t.length, 4);
  assert.equal(drums.drums.snare.t.length, 3);
  assert.equal(drums.drums.toms.t.length, 0);
  assert.equal(drums.drums.hihat.t.length, 5);
  assert.equal(drums.drums.cymbals.t.length, 1);
  // Per-substem arrays preserve onset times + velocities.
  assert.ok(Math.abs(drums.drums.kick.t[2] - 1.06) < 1e-5);
  assert.ok(Math.abs(drums.drums.kick.vel[2] - 1.0) < 1e-5);
  assert.ok(Math.abs(drums.drums.snare.vel[1] - 0.95) < 1e-5);
});

test("drums v1 legacy shape (bare timestamps) still packs with vel=1.0", () => {
  // Old caches written before SCHEMA_VERSION 2 emitted plain numbers. The
  // packer accepts both during the transition window.
  const summary = {
    ...SUMMARY,
    stems: {
      ...SUMMARY.stems,
      drums: {
        transcribed: true,
        model: "larsnet",
        kick: [0.05, 0.53],
        snare: [],
        toms: [],
        hihat: [],
        cymbals: [],
      },
    },
  };
  const td = buildTrackData(summary, F0, "x");
  assert.equal(td.notes.drums.onsetTotal, 2);
  assert.ok(Math.abs(td.notes.drums.drums.kick.t[1] - 0.53) < 1e-5);
  assert.equal(td.notes.drums.drums.kick.vel[1], 1.0);
});

test("drums gated by RMS check exposes ratio_db on the packed entry", () => {
  const summary = {
    ...SUMMARY,
    stems: {
      ...SUMMARY.stems,
      drums: {
        transcribed: false,
        reason: "drum content below gate (-64.8 dB ...)",
        ratio_db: -64.8,
      },
    },
  };
  const td = buildTrackData(summary, F0, "x");
  assert.equal(td.notes.drums.transcribed, false);
  assert.equal(td.notes.drums.reason, "drum content below gate (-64.8 dB ...)");
  assert.equal(td.notes.drums.ratioDb, -64.8);
});

test("F0 arrays become Float32Arrays", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.ok(td.f0.fcpe instanceof Float32Array);
  assert.ok(td.f0.pesto instanceof Float32Array);
  assert.equal(td.f0.hopSec, 0.01);
  assert.equal(td.f0.fcpe.length, 4);
});

test("consensus block is null when not provided by server", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.equal(td.f0.consensus, null);
});

test("consensus block populates Float32Array + Int8Arrays when present", () => {
  const f0WithConsensus = {
    ...F0,
    consensus: {
      n_frames: 4,
      consensus_f0: [null, 220.0, null, 440.0],   // server emits NaN as JSON null
      agreement_strength: [0.0, 0.85, 0.0, 1.0],
      vote_count: [0, 3, 2, 3],
      octave_corrections_fcpe: [0, 0, 0, -1],
      octave_corrections_pesto: [0, 0, 0, 0],
    },
  };
  const td = buildTrackData(SUMMARY, f0WithConsensus, "x");
  assert.ok(td.f0.consensus.consensusF0 instanceof Float32Array);
  assert.ok(td.f0.consensus.agreementStrength instanceof Float32Array);
  assert.ok(td.f0.consensus.voteCount instanceof Int8Array);
  assert.ok(td.f0.consensus.octaveCorrectionsFcpe instanceof Int8Array);
  assert.equal(td.f0.consensus.nFrames, 4);
  // Server-side null → client-side NaN so the renderer can use isNaN()
  assert.ok(Number.isNaN(td.f0.consensus.consensusF0[0]));
  assert.equal(td.f0.consensus.consensusF0[1], 220.0);
  assert.ok(Number.isNaN(td.f0.consensus.consensusF0[2]));
  assert.equal(td.f0.consensus.consensusF0[3], 440.0);
  assert.equal(td.f0.consensus.voteCount[3], 3);
  assert.equal(td.f0.consensus.octaveCorrectionsFcpe[3], -1);
  // Agreement strength loaded as-is (not synthesized from vote_count).
  assert.equal(td.f0.consensus.agreementStrength.length, 4);
  assert.equal(td.f0.consensus.agreementStrength[1], Math.fround(0.85));
});

test("consensus block synthesizes agreement_strength when server omits it", () => {
  // Pre-Phase-0c-Step-2 servers ship a consensus block without the new
  // agreement_strength field. track-data must synthesize it from vote_count
  // (3 → 1.0, 2 → 0.5, else 0.0) so the renderer always has the array.
  const f0Old = {
    ...F0,
    consensus: {
      n_frames: 4,
      consensus_f0: [null, 220.0, null, 440.0],
      vote_count: [0, 3, 2, 3],
      octave_corrections_fcpe: [0, 0, 0, 0],
      octave_corrections_pesto: [0, 0, 0, 0],
    },
  };
  const td = buildTrackData(SUMMARY, f0Old, "x");
  assert.ok(td.f0.consensus.agreementStrength instanceof Float32Array);
  assert.deepEqual(
    Array.from(td.f0.consensus.agreementStrength),
    [0.0, 1.0, 0.5, 1.0],
  );
});

test("vocalsRms is null when server omits it", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.equal(td.f0.vocalsRms, null);
});

test("vocalsRms becomes Float32Array when server provides it", () => {
  const f0WithRms = {
    ...F0,
    vocals_rms: [0.0, 0.05, 0.1, 0.02],
  };
  const td = buildTrackData(SUMMARY, f0WithRms, "x");
  assert.ok(td.f0.vocalsRms instanceof Float32Array);
  assert.equal(td.f0.vocalsRms.length, 4);
  assert.equal(td.f0.vocalsRms[2], Math.fround(0.1));
});

test("loop appearances + roman labels passed through", () => {
  const td = buildTrackData(SUMMARY, F0, "x");
  assert.deepEqual(td.loopBands, [{ start: 2.95, end: 12.1 }]);
  assert.deepEqual(td.loopRoman, ["i", "v", "♭VI", "♭III"]);
});

test("buildTrackData with null F0 (instrumental track) yields empty F0", () => {
  const td = buildTrackData(SUMMARY, null, "x");
  assert.equal(td.f0, null);
});
