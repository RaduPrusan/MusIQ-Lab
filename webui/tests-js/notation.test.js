import { test } from "node:test";
import assert from "node:assert/strict";

import {
  parseKey,
  spellingTableFor,
  formatPitch,
  formatPitchClass,
  reformatRootedName,
  respellPitchString,
  splitPitchOctave,
} from "../static/js/music/notation.js";

// Helpers
const NAMES = (table) => table.map((e) => e.letter + e.accidental);

test("parseKey returns null for empty/garbage input", () => {
  assert.equal(parseKey(""), null);
  assert.equal(parseKey(null), null);
  assert.equal(parseKey("not a key"), null);
});

test("parseKey extracts tonic letter, accidental, isMinor", () => {
  const c = parseKey("C major");
  assert.equal(c.tonicLetter, "C");
  assert.equal(c.tonicAcc, "");
  assert.equal(c.isMinor, false);
  assert.equal(c.parentLetter, "C");

  const fsm = parseKey("F# minor");
  assert.equal(fsm.tonicLetter, "F");
  assert.equal(fsm.tonicAcc, "#");
  assert.equal(fsm.isMinor, true);
  assert.equal(fsm.parentLetter, "A");      // F# minor → A major
  assert.equal(fsm.parentAcc, "");
});

test("parseKey handles Unicode accidentals (♯/♭) like ASCII", () => {
  // The analyze backend now emits canonical key strings with Unicode
  // accidentals ("E♭ natural minor", "F♯ minor", "B♭ major"). parseKey must
  // resolve the same pitch class as the ASCII form — otherwise the gutter
  // tonic + spelling bias land a semitone off (E natural instead of E♭).
  const ebm = parseKey("E♭ natural minor");
  assert.equal(ebm.tonicLetter, "E");
  assert.equal(ebm.tonicAcc, "b");
  assert.equal(ebm.tonicCls, 3);            // E♭ = pc 3, NOT E natural (4)
  assert.equal(ebm.isMinor, true);

  assert.equal(parseKey("F♯ minor").tonicCls, 6);
  assert.equal(parseKey("F♯ minor").tonicAcc, "#");
  assert.equal(parseKey("B♭ major").tonicCls, 10);
  assert.equal(parseKey("B♭ major").isMinor, false);

  // ASCII forms still parse identically (regression guard).
  assert.equal(parseKey("D# minor").tonicCls, 3);
  assert.equal(parseKey("Bb major").tonicCls, 10);
});

test("parentMajor for relative-minor keys lands on the right letter+accidental", () => {
  // Bb minor → relative major Db
  const bbm = parseKey("Bb minor");
  assert.equal(bbm.parentLetter, "D");
  assert.equal(bbm.parentAcc, "b");
  assert.equal(bbm.parentCls, 1);

  // D# minor → relative major F#
  const dsm = parseKey("D# minor");
  assert.equal(dsm.parentLetter, "F");
  assert.equal(dsm.parentAcc, "#");
});

test("spellingTableFor: C major spells the diatonic 7 with no accidentals", () => {
  const t = spellingTableFor(parseKey("C major"));
  // C D E F G A B at PCs 0 2 4 5 7 9 11
  assert.equal(t[0].letter, "C");  assert.equal(t[0].accidental, "");
  assert.equal(t[2].letter, "D");  assert.equal(t[2].accidental, "");
  assert.equal(t[4].letter, "E");  assert.equal(t[4].accidental, "");
  assert.equal(t[5].letter, "F");  assert.equal(t[5].accidental, "");
  assert.equal(t[7].letter, "G");  assert.equal(t[7].accidental, "");
  assert.equal(t[9].letter, "A");  assert.equal(t[9].accidental, "");
  assert.equal(t[11].letter, "B"); assert.equal(t[11].accidental, "");
});

test("spellingTableFor: D major has F# and C# (each letter once)", () => {
  const t = spellingTableFor(parseKey("D major"));
  assert.equal(t[6].letter, "F");  assert.equal(t[6].accidental, "#");
  assert.equal(t[1].letter, "C");  assert.equal(t[1].accidental, "#");
  // No letter should appear twice in the diatonic 7
  const diatonic = [2, 4, 6, 7, 9, 11, 1].map((pc) => t[pc].letter);
  assert.equal(new Set(diatonic).size, 7);
});

test("spellingTableFor: Eb major uses Bb, Eb, Ab (flats, no sharps)", () => {
  const t = spellingTableFor(parseKey("Eb major"));
  assert.equal(t[3].letter, "E");  assert.equal(t[3].accidental, "b");
  assert.equal(t[10].letter, "B"); assert.equal(t[10].accidental, "b");
  assert.equal(t[8].letter, "A");  assert.equal(t[8].accidental, "b");
});

test("F# major includes E# (theoretical letter, correct enharmonic)", () => {
  const t = spellingTableFor(parseKey("F# major"));
  // F# major scale: F# G# A# B C# D# E#
  assert.equal(t[5].letter, "E");  assert.equal(t[5].accidental, "#");
  assert.equal(t[6].letter, "F");  assert.equal(t[6].accidental, "#");
});

test("Chromatic notes follow the scale's accidental bias", () => {
  // D major (sharp side) → chromatic G# spelled as G#, not Ab
  const dMaj = spellingTableFor(parseKey("D major"));
  assert.equal(dMaj[8].letter, "G"); assert.equal(dMaj[8].accidental, "#");

  // Eb major (flat side) → same chromatic PC=8 spelled as Ab
  // (PC 8 is in the Eb major scale → Ab; that's diatonic, not chromatic.
  // Use PC 1, which is chromatic in both: D major → C#, Eb major → Db.)
  const ebMaj = spellingTableFor(parseKey("Eb major"));
  assert.equal(ebMaj[1].letter, "D"); assert.equal(ebMaj[1].accidental, "b");
  assert.equal(dMaj[1].letter, "C");  assert.equal(dMaj[1].accidental, "#");
});

test("Minor keys spell from their relative-major parent", () => {
  // A minor → C major: same diatonic spellings (no accidentals)
  const am = NAMES(spellingTableFor(parseKey("A minor")));
  const cM = NAMES(spellingTableFor(parseKey("C major")));
  assert.deepEqual(am, cM);

  // F# minor → A major: F#, C#, G# are diatonic
  const fsm = spellingTableFor(parseKey("F# minor"));
  assert.equal(fsm[6].accidental, "#");   // F#
  assert.equal(fsm[1].accidental, "#");   // C#
  assert.equal(fsm[8].accidental, "#");   // G#
});

test("formatPitch: scientific notation matches expected octave/letter", () => {
  // MIDI 60 = C4 (middle C); accidentals emitted as unicode ♯/♭
  assert.equal(formatPitch(60, parseKey("C major"), "scientific"), "C4");
  assert.equal(formatPitch(61, parseKey("D major"), "scientific"), "C♯4");
  assert.equal(formatPitch(61, parseKey("Eb major"), "scientific"), "D♭4");
  assert.equal(formatPitch(69, parseKey("F# major"), "scientific"), "A4");
});

test("formatPitch: solfège uses Italian Do/Re/Mi/Fa/Sol/La/Si plus ♯/♭", () => {
  assert.equal(formatPitch(60, parseKey("C major"), "solfege"), "Do4");
  assert.equal(formatPitch(64, parseKey("C major"), "solfege"), "Mi4");
  assert.equal(formatPitch(67, parseKey("C major"), "solfege"), "Sol4");
  assert.equal(formatPitch(71, parseKey("C major"), "solfege"), "Si4");
  assert.equal(formatPitch(66, parseKey("D major"), "solfege"), "Fa♯4");
  assert.equal(formatPitch(63, parseKey("Eb major"), "solfege"), "Mi♭4");
});

test("formatPitchClass omits the octave number", () => {
  assert.equal(formatPitchClass(0, parseKey("C major"), "scientific"), "C");
  assert.equal(formatPitchClass(6, parseKey("D major"), "scientific"), "F♯");
  assert.equal(formatPitchClass(6, parseKey("D major"), "solfege"), "Fa♯");
  assert.equal(formatPitchClass(10, parseKey("Eb major"), "solfege"), "Si♭");
});

test("Null/empty key falls back to plain-sharp scientific spelling", () => {
  assert.equal(formatPitch(61, null, "scientific"), "C♯4");
  assert.equal(formatPitch(66, parseKey(""), "scientific"), "F♯4");
});

test("reformatRootedName: scientific pretty-prints accidentals to unicode", () => {
  assert.equal(reformatRootedName("F#m7", "scientific"), "F♯m7");
  assert.equal(reformatRootedName("E natural minor", "scientific"), "E natural minor");
  assert.equal(reformatRootedName("Bb major", "scientific"), "B♭ major");
});

test("reformatRootedName: solfège transforms chord labels (with unicode)", () => {
  assert.equal(reformatRootedName("F", "solfege"), "Fa");
  assert.equal(reformatRootedName("Fm", "solfege"), "Fam");
  assert.equal(reformatRootedName("F#m7", "solfege"), "Fa♯m7");
  assert.equal(reformatRootedName("Bbmaj7", "solfege"), "Si♭maj7");
  assert.equal(reformatRootedName("C7", "solfege"), "Do7");
  assert.equal(reformatRootedName("G°", "solfege"), "Sol°");
});

test("reformatRootedName: solfège transforms slash bass", () => {
  assert.equal(reformatRootedName("C/E", "solfege"), "Do/Mi");
  assert.equal(reformatRootedName("G/B", "solfege"), "Sol/Si");
  assert.equal(reformatRootedName("F#m7/A", "solfege"), "Fa♯m7/La");
});

test("reformatRootedName: solfège transforms key/scale strings", () => {
  assert.equal(reformatRootedName("E minor", "solfege"), "Mi minor");
  assert.equal(reformatRootedName("E natural minor", "solfege"), "Mi natural minor");
  assert.equal(reformatRootedName("Eb major", "solfege"), "Mi♭ major");
  assert.equal(reformatRootedName("F# Dorian", "solfege"), "Fa♯ Dorian");
});

test("reformatRootedName: solfège transforms pitch strings with octaves", () => {
  assert.equal(reformatRootedName("B2", "solfege"), "Si2");
  assert.equal(reformatRootedName("G#7", "solfege"), "Sol♯7");
  assert.equal(reformatRootedName("Eb4", "solfege"), "Mi♭4");
});

test("reformatRootedName: handles unicode sharp/flat input (♯ ♭)", () => {
  assert.equal(reformatRootedName("G♯7", "solfege"), "Sol♯7");
  assert.equal(reformatRootedName("E♭ major", "solfege"), "Mi♭ major");
});

test("reformatRootedName: leaves Roman numerals untouched", () => {
  // Lowercase i/v don't match [A-G] uppercase
  assert.equal(reformatRootedName("vi", "solfege"), "vi");
  assert.equal(reformatRootedName("ii7", "solfege"), "ii7");
  // Uppercase V isn't A-G either
  assert.equal(reformatRootedName("V7", "solfege"), "V7");
});

test("reformatRootedName: null/empty input returns as-is", () => {
  assert.equal(reformatRootedName("", "solfege"), "");
  assert.equal(reformatRootedName(null, "solfege"), null);
  assert.equal(reformatRootedName(undefined, "solfege"), undefined);
});

test("respellPitchString: re-spells to match the key (F minor: E2 → F♭2)", () => {
  // F minor's parent is Ab major (flat side). PC 4 (E natural) is chromatic
  // and should spell as Fb under flat-bias chromatic rules. Output uses ♭.
  const fm = parseKey("F minor");
  assert.equal(respellPitchString("E2", fm, "scientific"), "F♭2");
  assert.equal(respellPitchString("E2", fm, "solfege"), "Fa♭2");
});

test("respellPitchString: handles unicode sharp glyph (♯ → ♯)", () => {
  // E minor parent is G major (sharp side). G♯ raw = PC 8 = G♯ in this key.
  const em = parseKey("E minor");
  assert.equal(respellPitchString("G♯7", em, "scientific"), "G♯7");
  assert.equal(respellPitchString("G♯7", em, "solfege"), "Sol♯7");
});

test("respellPitchString: agrees with formatPitch for any MIDI in any key", () => {
  // The vocal-range and gutter labels should always match: "respell what the
  // analyzer wrote at MIDI X in key K" must equal "format MIDI X in key K".
  const ebMaj = parseKey("Eb major");
  // Analyzer might write "G#3" (PC 8, octave 3, MIDI 56). In Eb major PC 8
  // is diatonic Ab, so the respelled form must be "A♭3".
  assert.equal(respellPitchString("G#3", ebMaj, "scientific"), "A♭3");
  assert.equal(formatPitch(56, ebMaj, "scientific"), "A♭3");
});

test("respellPitchString: returns input unchanged for unparseable strings", () => {
  assert.equal(respellPitchString("?", parseKey("C major"), "scientific"), "?");
  assert.equal(respellPitchString("", null, "scientific"), "");
});

test("splitPitchOctave: splits scientific names (ASCII or unicode)", () => {
  assert.deepEqual(splitPitchOctave("C4"), { head: "C", octave: "4" });
  assert.deepEqual(splitPitchOctave("F♯5"), { head: "F♯", octave: "5" });
  assert.deepEqual(splitPitchOctave("B♭-1"), { head: "B♭", octave: "-1" });
});

test("splitPitchOctave: splits solfège names (ASCII or unicode)", () => {
  assert.deepEqual(splitPitchOctave("Do4"), { head: "Do", octave: "4" });
  assert.deepEqual(splitPitchOctave("Fa♯5"), { head: "Fa♯", octave: "5" });
  assert.deepEqual(splitPitchOctave("Si♭7"), { head: "Si♭", octave: "7" });
});

test("splitPitchOctave: empty/unparseable input is safe", () => {
  assert.deepEqual(splitPitchOctave(""), { head: "", octave: "" });
  assert.deepEqual(splitPitchOctave(null), { head: "", octave: "" });
  assert.deepEqual(splitPitchOctave("C"), { head: "C", octave: "" });
});
