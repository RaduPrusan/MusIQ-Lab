// yt-dlp's output template appends "-<11-char id>.mp3". The 11-char body
// is from the base64-url-safe alphabet; we classify it as a YT ID when it
// has high-entropy markers — a digit, underscore, internal dash, OR mixed
// case. Plain English words (single case, all letters, no specials) fall
// through and are preserved as titles. Mirrors the Python heuristic in
// webui/webui/lyrics.py and webui/webui/tracks.py.
const YT_ID_RE = /-[A-Za-z0-9_-]{11}\.mp3$/;
function _looksLikeYtIdTail(tail) {
  const body = tail.slice(1, -4);  // strip leading "-" and trailing ".mp3"
  if (/[\d_-]/.test(body)) return true;
  return /[A-Z]/.test(body) && /[a-z]/.test(body);
}

function deriveTitle(file) {
  const m = file.match(YT_ID_RE);
  const base = (m && _looksLikeYtIdTail(m[0])) ? file.slice(0, m.index) : file.replace(/\.mp3$/, "");
  if (base.includes(" ")) return base;
  // Slug-derived form: "-" between word chars is the artist/title boundary
  // and renders as " - "; "_" is a word-internal separator and renders as " ".
  return base
    .replace(/(\w)-(\w)/g, "$1 - $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Sub-stems emitted by analyze/stages/drums.py. The drums entry in summary
// has these as parallel event arrays instead of a `notes` array.
const DRUM_SUBSTEMS = ["kick", "snare", "toms", "hihat", "cymbals"];

function packStem(stem) {
  if (stem?.transcribed === false) {
    return {
      t: new Float32Array(0),
      dur: new Float32Array(0),
      midi: new Uint8Array(0),
      vel: new Float32Array(0),
      meta: [],
      transcribed: false,
      reason: stem.reason ?? null,
      ratioDb: stem.ratio_db ?? null,    // drums-only legacy field
      presence: stem.presence ?? null,   // full signal block for melodic stems
    };
  }
  // Drums (Stage 9) ships as 5 event arrays, not pitched notes. Each event is
  // {t, vel} (vel in [0,1] relative to the substem's peak). Older v1 caches
  // emitted plain numbers; we accept both shapes so a stale cache renders
  // sanely until it gets re-analyzed.
  if (stem && Array.isArray(stem.kick)) {
    const drums = {};
    let onsetTotal = 0;
    for (const s of DRUM_SUBSTEMS) {
      const events = Array.isArray(stem[s]) ? stem[s] : [];
      const t = new Float32Array(events.length);
      const vel = new Float32Array(events.length);
      for (let i = 0; i < events.length; i++) {
        const e = events[i];
        if (typeof e === "number") {       // legacy v1 shape: bare timestamp
          t[i] = e;
          vel[i] = 1.0;
        } else {                            // v2: {t, vel}
          t[i] = e.t;
          vel[i] = e.vel ?? 1.0;
        }
      }
      drums[s] = { t, vel };
      onsetTotal += events.length;
    }
    return {
      t: new Float32Array(0),
      dur: new Float32Array(0),
      midi: new Uint8Array(0),
      vel: new Float32Array(0),
      meta: [],
      transcribed: true,
      drums,
      onsetTotal,
      model: stem.model ?? null,
    };
  }
  const notes = stem?.notes ?? [];
  const n = notes.length;
  const t = new Float32Array(n);
  const dur = new Float32Array(n);
  const midi = new Uint8Array(n);
  const vel = new Float32Array(n);
  const meta = new Array(n);
  for (let i = 0; i < n; i++) {
    const note = notes[i];
    t[i] = note.t;
    dur[i] = note.dur;
    midi[i] = note.midi;
    vel[i] = note.vel ?? 0.5;
    meta[i] = {
      name: note.name,
      scale_deg: note.scale_deg ?? null,
      in_chord: note.in_chord ?? null,
      role: note.role ?? null,
    };
  }
  return { t, dur, midi, vel, meta, presence: stem?.presence ?? null };
}

export function buildTrackData(summary, f0, slug, lastfm = null) {
  const meta = {
    slug,
    title: deriveTitle(summary.track.file),
    // The rename's canonical name (cache/<slug>/user_meta.json display_name,
    // merged into summary.track by the server). Distinct from `title` because
    // `title` is a filename-derived display fallback, not the source of truth.
    // Consumers like lyrics-tab use this to seed the header before fetch.
    displayName: summary.track.display_name || "",
    durationSec: summary.track.duration_sec,
    tempoBpm: summary.track.tempo_bpm,
    key: summary.track.key,
    scale: summary.analysis?.scale ?? "",
    timeSig: summary.track.time_signature ?? "4/4",
  };
  const downbeats = Float32Array.from(summary.downbeats ?? []);
  const chords = (summary.chords ?? []).map((c) => ({
    start: c.start, end: c.end,
    label: c.label, roman: c.roman, fn: c.function,
  }));
  const notes = {};
  for (const stem of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
    notes[stem] = packStem(summary.stems?.[stem]);
  }
  const loopBands = summary.analysis?.loop_appearances ?? [];
  const loopRoman = summary.analysis?.loop_roman ?? [];
  const vocalRange = summary.analysis?.vocal_range ?? null;
  const modalInterchange = summary.analysis?.modal_interchange_count ?? 0;
  // Optional MusicBrainz identification block from summary.identify (Plan A
  // Task 7). Passed through verbatim — renderMetadataCard handles the
  // identified=true/false split and missing-field cases.
  const identify = summary.identify ?? null;
  // Optional Essentia acoustic-profile block from summary.essentia (Plan C
  // Task 7). Passed through verbatim — renderAcousticProfile handles the
  // extracted=true/false split and the gaia2-unavailable high_level path.
  const essentia = summary.essentia ?? null;
  // Plan C Task 5: tempo/key agreement between the analyze pipeline and
  // Essentia's second opinion. The reanalyze modal has always rendered this
  // in its stats panel; the sidebar Cross-check card surfaces the same data
  // persistently so the disagreement signal (especially half/double-tempo)
  // is visible without re-running. Empty/missing → card renders nothing.
  const essentiaAgreement = summary.essentia_agreement ?? null;
  // Optional parallel chord annotations under Essentia's consensus key.
  // Written by analyze/writers/summary_writer.py when essentia_agreement.key.ok
  // is false. Same length as summary.chords; each entry is {roman, function}.
  // The cross-check toggle (state/xcheck.js) flips renderers between the
  // canonical chord fields and these annotations without re-running analysis.
  const chordsAltKey = summary.chords_alt_key ?? null;

  let f0Out = null;
  if (f0 && f0.fcpe) {
    f0Out = {
      fcpe: Float32Array.from(f0.fcpe),
      pesto: Float32Array.from(f0.pesto),
      hopSec: f0.hop_sec ?? 0.01,
      nFrames: f0.n_frames ?? f0.fcpe.length,
      consensus: null,
      // Per-frame vocals-stem RMS amplitude (linear, frame-rate-aligned
      // with fcpe/pesto). Null when the dynamics stage hasn't run on
      // this track. Used by the F0 overlay renderer to modulate contour
      // opacity proportionally to vocal volume.
      vocalsRms: Array.isArray(f0.vocals_rms)
        ? Float32Array.from(f0.vocals_rms)
        : null,
    };
    // Optional consensus block — present when the vocal_consensus_contour
    // stage has run. Server serializes NaN as JSON null; we map back to
    // NaN in the Float32Array so the renderer can use Number.isNaN() as
    // the "no consensus at this frame" sentinel.
    if (f0.consensus) {
      const c = f0.consensus;
      const cf0 = new Float32Array(c.consensus_f0.length);
      for (let i = 0; i < c.consensus_f0.length; i++) {
        cf0[i] = c.consensus_f0[i] === null ? NaN : c.consensus_f0[i];
      }
      // Pre-Phase-0c-Step-2 servers won't ship agreement_strength; synthesize
      // from vote_count (3 → 1.0, 2 → 0.5, else 0.0) so the renderer always
      // sees the array shape and can bin by strength uniformly.
      let agreementStrength;
      if (Array.isArray(c.agreement_strength)) {
        agreementStrength = Float32Array.from(c.agreement_strength);
      } else {
        agreementStrength = new Float32Array(c.vote_count.length);
        for (let i = 0; i < c.vote_count.length; i++) {
          const v = c.vote_count[i];
          agreementStrength[i] = v === 3 ? 1.0 : v === 2 ? 0.5 : 0.0;
        }
      }
      f0Out.consensus = {
        consensusF0: cf0,
        agreementStrength,
        voteCount: Int8Array.from(c.vote_count),
        octaveCorrectionsFcpe: Int8Array.from(c.octave_corrections_fcpe),
        octaveCorrectionsPesto: Int8Array.from(c.octave_corrections_pesto),
        nFrames: c.n_frames,
      };
    }
  }

  return Object.freeze({
    meta, downbeats, chords, notes,
    loopBands, loopRoman, vocalRange, modalInterchange,
    identify,
    essentia,
    essentiaAgreement,
    chordsAltKey,
    f0: f0Out,
    // Plan B Task 4: Last.fm tags + similar artists from
    // /api/track/<slug>/lastfm. Always {available: bool, tags?,
    // similar_artists?, reason?} or null when the caller didn't fetch.
    // renderTagsSection() returns "" when unavailable, so a null/missing
    // lastfm is a no-op at render time.
    lastfm,
  });
}
