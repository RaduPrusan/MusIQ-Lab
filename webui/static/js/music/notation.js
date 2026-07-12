// Music-notation utilities — proper enharmonic spelling per key, plus
// pitch-name formatting in different notation systems (scientific, solfège).
//
// Spelling algorithm: the seven-letter rule applied to the parent major
// scale. Each diatonic pitch in a key uses one and only one of the seven
// letter names (A-G), with whatever accidental is needed to land on the
// right pitch class. Chromatic pitches outside the scale follow the bias
// of the parent major's accidentals (sharp keys → sharp spellings,
// flat keys → flat spellings) so a chromatic G# in D major reads as G#,
// while the same pitch class in Eb major reads as Ab.
//
// Modes are mapped to their parent major (currently only major/minor are
// distinguished by the analyzer; minor → relative major at +3 semitones).
// Adding richer mode handling later is a one-line change in modeToParentOffset.

const LETTER_NATURAL_PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const LETTERS_DIATONIC  = ["C", "D", "E", "F", "G", "A", "B"];   // walk in scale order
const MAJOR_INTERVALS   = [0, 2, 4, 5, 7, 9, 11];                // W W H W W W H

// Solfège letter→syllable table (Italian/Romance system; chromatic notes
// take the syllable for the spelled letter plus the accidental literal).
const SOLFEGE = { C: "Do", D: "Re", E: "Mi", F: "Fa", G: "Sol", A: "La", B: "Si" };

// Naturals' pitch classes used as fallback when no key is available.
const SHARP_FALLBACK = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

// Parse a free-form key string (e.g. "F# minor", "Eb major", "C") into a
// structured form. Returns null when the string is empty/unrecognised so
// callers fall back to a plain-sharp default.
export function parseKey(keyText) {
  if (!keyText || typeof keyText !== "string") return null;
  // Backend key strings use Unicode accidentals (e.g. "E♭ natural minor",
  // "F♯ minor"). Normalize to ASCII so the [#b] matcher resolves the right
  // pitch class — otherwise the ♭/♯ is dropped and the tonic (and the whole
  // spelling bias) lands a semitone off.
  const m = keyText.replace(/♯/g, "#").replace(/♭/g, "b").trim().match(/^([A-G])([#b]?)\s*(.*)$/);
  if (!m) return null;
  const tonicLetter = m[1];
  const tonicAcc = m[2] || "";
  const tail = (m[3] || "").toLowerCase();
  // Same minor-detection regex as render/pianoroll.js:keyInfo so all
  // key-aware code agrees on what counts as minor.
  const isMinor = /\bmin|^m$|^m\s|aeolian|phrygian|locrian|dorian/.test(tail);
  let tonicCls = LETTER_NATURAL_PC[tonicLetter];
  if (tonicAcc === "#") tonicCls = (tonicCls + 1) % 12;
  else if (tonicAcc === "b") tonicCls = (tonicCls + 11) % 12;

  // Parent major: for major mode, it's the tonic itself. For minor (or
  // any minor-ish mode the analyzer might emit), it's the relative major
  // at +3 semitones, with the letter advanced by 2 steps in the diatonic
  // ladder so the spelling stays consistent with the tonic's spelling.
  let parentLetter = tonicLetter;
  let parentAcc = tonicAcc;
  let parentCls = tonicCls;
  if (isMinor) {
    const li = LETTERS_DIATONIC.indexOf(tonicLetter);
    parentLetter = LETTERS_DIATONIC[(li + 2) % 7];
    parentCls = (tonicCls + 3) % 12;
    // Compute the parent's accidental so its letter+accidental land on parentCls.
    parentAcc = accidentalForLetterToHitPc(parentLetter, parentCls);
  }

  // Sharp-side bias: the parent major key's tonic accidental decides the
  // direction for chromatic spellings. Naturals are mostly sharp-side
  // (C/G/D/A/E/B major), with the lone exception of F major which is flat-side.
  let sharpSide;
  if (parentAcc === "#") sharpSide = true;
  else if (parentAcc === "b") sharpSide = false;
  else sharpSide = parentLetter !== "F";        // C/G/D/A/E/B → sharps; F → flats

  return { tonicLetter, tonicAcc, tonicCls, isMinor, parentLetter, parentAcc, parentCls, sharpSide };
}

// Compute the accidental (one of "", "#", "b", "##", "bb") needed so that
// `letter + accidental` spells the given pitch class. Used both for the
// parent-major derivation and for in-scale degree spellings.
function accidentalForLetterToHitPc(letter, targetPc) {
  const naturalPc = LETTER_NATURAL_PC[letter];
  const diff = ((targetPc - naturalPc) % 12 + 12) % 12;
  // diff is 0..11; map the small ones to single accidentals, handle ±2 for
  // theoretical double-sharps/flats (Cb major → Fb, F# major → E#, etc.).
  if (diff === 0)  return "";
  if (diff === 1)  return "#";
  if (diff === 2)  return "##";
  if (diff === 11) return "b";
  if (diff === 10) return "bb";
  // Anything bigger means the letter is the wrong choice — caller bug.
  return "?";
}

// Build a 12-entry table mapping every pitch class to its preferred
// {letter, accidental} spelling for the given key. In-scale degrees use
// the seven-letter rule; chromatic degrees use the scale's sharp/flat
// bias. Memoized per key for cheap repeated calls during rendering.
const SPELLING_CACHE = new Map();
export function spellingTableFor(keyParse) {
  if (!keyParse) {
    return SHARP_FALLBACK.map((s) => ({ letter: s[0], accidental: s.slice(1) }));
  }
  const cacheKey = `${keyParse.parentLetter}${keyParse.parentAcc}|${keyParse.sharpSide ? "s" : "f"}`;
  const cached = SPELLING_CACHE.get(cacheKey);
  if (cached) return cached;

  const table = new Array(12).fill(null);
  // Pass 1: spell the seven diatonic degrees of the parent major. Walk the
  // letters starting at parentLetter, stepping through MAJOR_INTERVALS.
  const startIdx = LETTERS_DIATONIC.indexOf(keyParse.parentLetter);
  for (let i = 0; i < 7; i++) {
    const letter = LETTERS_DIATONIC[(startIdx + i) % 7];
    const pc = (keyParse.parentCls + MAJOR_INTERVALS[i]) % 12;
    const accidental = accidentalForLetterToHitPc(letter, pc);
    table[pc] = { letter, accidental };
  }
  // Pass 2: fill in the five chromatic pitch classes. Prefer the parent's
  // accidental bias, but fall back to a natural-letter spelling when the
  // bias direction has no neighbour-letter (e.g. PC 9 in F# major: there's
  // no letter at PC 8 to carry a sharp, so chromatic PC 9 → "A" natural).
  // This is the conventional piano-roll-readable spelling — strict theory
  // would sometimes use double-sharps/flats here, but those are unhelpful
  // in a UI and rare even in scores.
  for (let pc = 0; pc < 12; pc++) {
    if (table[pc]) continue;
    table[pc] = chromaticSpelling(pc, keyParse.sharpSide);
  }
  SPELLING_CACHE.set(cacheKey, table);
  return table;
}

function chromaticSpelling(pc, sharpSide) {
  // Step 1: bias accidental — find a natural letter that, when sharped
  // (or flatted), lands on `pc`. Works for PCs 1, 3, 6, 8, 10.
  const primary = sharpSide ? "#" : "b";
  const primaryOffset = sharpSide ? -1 : +1;
  const primaryNeed = ((pc + primaryOffset) % 12 + 12) % 12;
  for (const L of LETTERS_DIATONIC) {
    if (LETTER_NATURAL_PC[L] === primaryNeed) return { letter: L, accidental: primary };
  }
  // Step 2: natural letter at this PC (handles theoretical keys like
  // F# major where the bias side has no available letter).
  for (const L of LETTERS_DIATONIC) {
    if (LETTER_NATURAL_PC[L] === pc) return { letter: L, accidental: "" };
  }
  // Step 3: opposite accidental — final safety net (shouldn't fire in practice).
  const opp = sharpSide ? "b" : "#";
  const oppOffset = sharpSide ? +1 : -1;
  const oppNeed = ((pc + oppOffset) % 12 + 12) % 12;
  for (const L of LETTERS_DIATONIC) {
    if (LETTER_NATURAL_PC[L] === oppNeed) return { letter: L, accidental: opp };
  }
  return { letter: "C", accidental: "" };
}

// Final-stage glyph polish: convert ASCII "#" → "♯" everywhere, and ASCII
// "b" → "♭" only when it's the accidental on a pitch head (capital A-G,
// or one of the seven solfège syllables). The conditional rule keeps the
// "b" in chord-suffix alterations (e.g. "C7b9") and inside words like
// "minor"/"sub" untouched. Internals of the module continue to use ASCII
// so regex matching, parsing, and equality checks stay simple.
const PITCH_HEAD_FLAT_RE = /((?:[A-G]|Do|Re|Mi|Fa|Sol|La|Si))b/g;
function prettifyAccidentals(s) {
  if (!s || typeof s !== "string") return s;
  return s.replace(/#/g, "♯").replace(PITCH_HEAD_FLAT_RE, "$1♭");
}

// Format a single MIDI number as a pitch label in the requested system.
// `system` is one of "scientific" | "solfege". Octave-numbering uses
// scientific pitch notation (C4 = MIDI 60) regardless of system.
// Output uses unicode ♯/♭ glyphs.
export function formatPitch(midi, keyParse, system) {
  const table = spellingTableFor(keyParse);
  const pc = ((midi % 12) + 12) % 12;
  const { letter, accidental } = table[pc];
  // Derive the octave from the SPELLED letter, not raw MIDI: an accidental that
  // crosses the C boundary (Cb, B#) sits in a different octave than its raw
  // pitch-class implies. Undo the accidental's semitone shift so the octave
  // matches the letter. Provably identical to Math.floor(midi/12)-1 whenever the
  // spelling doesn't cross the boundary (accShift is absorbed within the octave).
  const accShift = (accidental.match(/#/g)?.length || 0) - (accidental.match(/b/g)?.length || 0);
  const oct = Math.floor((midi - accShift) / 12) - 1;
  const head = system === "solfege" ? SOLFEGE[letter] : letter;
  return prettifyAccidentals(`${head}${accidental}${oct}`);
}

// Pitch-class-only formatter (no octave) for gutter labels and the like.
// Output uses unicode ♯/♭ glyphs.
export function formatPitchClass(pc, keyParse, system) {
  const table = spellingTableFor(keyParse);
  const { letter, accidental } = table[((pc % 12) + 12) % 12];
  const head = system === "solfege" ? SOLFEGE[letter] : letter;
  return prettifyAccidentals(`${head}${accidental}`);
}

// Convert a MIDI number to its frequency in Hz (12-TET, A4 = 440 Hz).
// Used by the hover tooltip's physics line; pure math, no key context.
export function midiToHz(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

// Format a Hz value for compact display: 2 decimals under 1 kHz, 1 decimal
// at and above. Returns a plain string; the caller adds the " Hz" suffix.
export function formatHz(hz) {
  if (!Number.isFinite(hz)) return "—";
  return hz < 1000 ? hz.toFixed(2) : hz.toFixed(1);
}

// Split a formatted pitch label ("C4", "Fa#5", "Ab-1") into its
// letter/syllable+accidental head and its trailing octave digits. Returns
// {head, octave} as strings; either may be empty for unparseable input.
// The octave-suffix detection accepts an optional leading minus so very
// low MIDI pitches (octave -1) still split correctly.
export function splitPitchOctave(s) {
  const m = String(s ?? "").match(/^(.*?)(-?\d+)$/);
  if (!m) return { head: String(s ?? ""), octave: "" };
  return { head: m[1], octave: m[2] };
}

// Re-spell a scientific-pitch-notation string ("B2", "G♯7", "Eb4") so its
// letter+accidental matches the proper enharmonic spelling for the given
// key, in the requested notation system. Takes the raw analyzer output
// (which may use unicode ♯/♭ and no key context) and routes it through
// the same spelling table the gutter labels use, so the vocal-range tag
// always agrees with what's drawn on the canvas.
//
// Returns the input unchanged when it can't be parsed (octave missing,
// non-pitch glyphs, etc.) so degenerate values like "?" don't crash.
export function respellPitchString(s, keyParse, system) {
  if (!s || typeof s !== "string") return s;
  const norm = s.replace(/♯/g, "#").replace(/♭/g, "b").trim();
  const m = norm.match(/^([A-G])([#b]?)(-?\d+)$/);
  if (!m) return prettifyAccidentals(s);   // unparseable: at least pretty-print glyphs
  const letter = m[1];
  const acc = m[2];
  const octave = parseInt(m[3], 10);
  let pc = LETTER_NATURAL_PC[letter];
  if (acc === "#") pc = (pc + 1) % 12;
  else if (acc === "b") pc = (pc + 11) % 12;
  // Scientific pitch notation: C4 = MIDI 60, so MIDI = (octave + 1) * 12 + pc.
  const midi = (octave + 1) * 12 + pc;
  return formatPitch(midi, keyParse, system);
}

// Collapse mir_eval-style chord labels ("F:min", "C:maj7", "Bb:7") to
// standard shorthand ("Fm", "Cmaj7", "Bb7"). Bass-slash suffixes ("/E")
// pass through untouched. Pure string transform — does not touch the root
// letter or its accidental, so `reformatRootedName` can be composed on top
// to apply notation-system changes.
export function formatChordShorthand(name) {
  if (!name) return "";
  return name
    .replace(":maj7", "maj7")
    .replace(":min7", "m7")
    .replace(":7", "7")
    .replace(":maj", "")
    .replace(":min", "m")
    .replace(":dim", "°")
    .replace(":aug", "+")
    .replace(":sus2", "sus2")
    .replace(":sus4", "sus4");
}

// Collapse "Bb:major" / "F#:minor" forms (Essentia consensus output) to
// "Bb major" / "F# minor" so `reformatRootedName` can pretty-print the
// accidental and (in solfège mode) transpose the root letter. Strings that
// already match the analyze-pipeline form ("F Major") pass through unchanged.
export function humanizeKeyString(s) {
  if (!s || typeof s !== "string") return s || "";
  return s.replace(/^\s*([A-G][#b♯♭]?)\s*:\s*([a-zA-Z]+)\s*$/, "$1 $2");
}

// Re-format a string that may contain a leading pitch-letter prefix —
// chord labels ("F#m7", "Bb", "C/E"), scale strings ("E natural minor"),
// pitch strings with octaves ("G#4", "B2"), or key strings ("Eb major").
// In scientific mode, returns the input unchanged. In solfège mode,
// substitutes the [A-G] letter (with optional sharp/flat) at the start
// of the string (and after "/" for slash-bass chords) with the matching
// syllable + accidental, leaving the rest ("m7", "maj", " minor")
// otherwise intact.
//
// Optional 3rd arg `keyParse` (from parseKey()): when supplied, pitch
// heads are re-spelled to the key's preferred enharmonic *before* any
// solfège substitution. Chord labels arrive from the analyzer with a
// fixed sharp/flat choice that ignores key context — e.g. "Db" in a
// piece clearly in F♯ minor — so callers that want chord labels to
// agree with the gutter's spelling pass keyParse. Callers that render
// the key/scale string itself (which IS the source of truth for the
// spelling) must NOT pass keyParse, since re-spelling a key string
// against its own spelling table could rewrite its root letter.
//
// Caller convention: pass strings whose pitch is at the start. Don't pass
// a sentence with a pitch embedded mid-string (e.g. "vocal range C4–F5") —
// transform the pitch token first, then compose the sentence. This keeps
// the algorithm simple and avoids false positives like the "D" in "Dorian"
// being mistaken for a pitch root.
//
// Notes:
//  - Sharp glyphs accepted: ASCII "#" or unicode "♯". Flat: "b" or "♭".
//  - Output uses ASCII "#"/"b" so the result is composable with regex code
//    elsewhere in the UI.
//  - Lowercase letters are never matched, so chord-suffix characters
//    (m, maj, dim, sus, aug, min) and lowercase Roman numerals (i, vi)
//    pass through untouched.
export function reformatRootedName(s, system, keyParse) {
  if (!s || typeof s !== "string") return s;
  let result = s;
  // Pre-pass: key-aware re-spelling. The matcher walks the *original*
  // string positions, so each letter is considered a pitch head only when
  // it's at offset 0 or immediately after a "/" (slash bass). Quality
  // suffixes ("m", "maj", "°") and modal-name letters ("D" in "Dorian")
  // never match — the regex requires uppercase [A-G] and the guard rejects
  // mid-word matches.
  if (keyParse) {
    const table = spellingTableFor(keyParse);
    result = result.replace(/([A-G])([#b♯♭]?)/g, (match, letter, acc, offset, full) => {
      if (offset > 0 && full[offset - 1] !== "/") return match;
      let pc = LETTER_NATURAL_PC[letter];
      if (acc === "#" || acc === "♯") pc = (pc + 1) % 12;
      else if (acc === "b" || acc === "♭") pc = (pc + 11) % 12;
      const sp = table[pc];
      return sp.letter + sp.accidental;
    });
  }
  if (system === "solfege") {
    result = result.replace(/([A-G])([#b♯♭]?)/g, (match, letter, acc, offset, full) => {
      if (offset > 0 && full[offset - 1] !== "/") return match;
      let normAcc = "";
      if (acc === "#" || acc === "♯") normAcc = "#";
      else if (acc === "b" || acc === "♭") normAcc = "b";
      return SOLFEGE[letter] + normAcc;
    });
  }
  // Always pretty-print accidentals to unicode, even when the system is
  // scientific (so key strings like "F# minor" become "F♯ minor"). Inputs
  // that already contained unicode glyphs pass through untouched.
  return prettifyAccidentals(result);
}
