import { el, clear } from "../ui/dom.js";
import { timeToX, midiToY } from "./coords.js";
import { CHORD_H, DRUM_SUBSTEMS, drumLaneHeight } from "./layout.js";
import { parseKey, formatPitch, formatPitchClass, formatChordShorthand, reformatRootedName } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";
import { pitchChildren } from "../ui/pitch-label.js";
import { readToken, readAlpha, subscribe as subscribeTheme } from "../theme/css-tokens.js";

// Same canonical order as audio/engine.js STEM_NAMES, with drums dropped
// (drums paints in its own lane below the piano roll). Iteration order
// becomes the z-order for dimmed (non-highlighted) stems — the highlighted
// stem is always re-sorted to the end, so it sits on top of all others.
const STEM_ORDER = ["vocals", "piano", "other", "guitar", "bass"];
const PITCH_CLASS = {
  C: 0, "C#": 1, Db: 1, D: 2, "D#": 3, Eb: 3, E: 4, F: 5, "F#": 6,
  Gb: 6, G: 7, "G#": 8, Ab: 8, A: 9, "A#": 10, Bb: 10, B: 11,
};

// Major and natural-minor scale intervals from the tonic (in semitones).
const SCALE_MAJOR = [0, 2, 4, 5, 7, 9, 11];
const SCALE_MINOR = [0, 2, 3, 5, 7, 8, 10];

// Format a MIDI number as a pitch label for hover tooltips and other
// context-aware UI. Routes through the notation module so the user's
// notation-system preference (scientific vs solfège) and the key's proper
// enharmonic spelling are both applied. Accepts the *full* key text
// ("F# minor", "Eb major") rather than just the tonic letter, since
// mode-aware spelling needs both. The second arg can also be a parseKey()
// result (object) for callers that already have one.
export function midiToContextualName(midi, keyTextOrParse) {
  const parse = (keyTextOrParse && typeof keyTextOrParse === "object")
    ? keyTextOrParse
    : parseKey(keyTextOrParse);
  return formatPitch(midi, parse, getNotationSystem());
}

function keyInfo(keyText) {
  if (!keyText) return null;
  const m = keyText.trim().match(/^([A-G][#b]?)\s*(.*)$/);
  if (!m) return null;
  const tonic = PITCH_CLASS[m[1]];
  if (tonic == null) return null;
  const tail = (m[2] || "").toLowerCase();
  // Treat anything that says "min", a trailing/standalone "m", or a minor-mode
  // modal name as minor; everything else (incl. bare "C") falls back to major.
  const isMinor = /\bmin|^m$|^m\s|aeolian|phrygian|locrian|dorian/.test(tail);
  const intervals = isMinor ? SCALE_MINOR : SCALE_MAJOR;
  const scale = new Set(intervals.map((i) => (tonic + i) % 12));
  return { tonic, scale, isMinor };
}

// Convert a "#rrggbb" CSS token value into an "rgba(r,g,b,a)" canvas color.
// Tolerates 3-char shorthand (#abc) and surrounding whitespace; on parse
// failure it returns the input unchanged so canvas paths fall back to the
// browser's color parser. Used by the theme cache to compose accent +
// alpha pairs at theme-apply time (canvas-side analogue to color-mix).
function hexToRgba(hex, alpha) {
  let v = (hex || "").trim();
  if (v.startsWith("#")) v = v.slice(1);
  if (v.length === 3) v = v.split("").map((c) => c + c).join("");
  if (v.length !== 6) return hex;
  const r = parseInt(v.slice(0, 2), 16);
  const g = parseInt(v.slice(2, 4), 16);
  const b = parseInt(v.slice(4, 6), 16);
  if (![r, g, b].every(Number.isFinite)) return hex;
  return `rgba(${r},${g},${b},${alpha})`;
}

export class PianoRoll {
  constructor(root) {
    this.root = root;
    this.gutter = el("div", { class: "gutter" }, [el("div", { class: "gutter-head", text: "PITCH" })]);
    this.canvasWrap = el("div", { class: "canvas-wrap" });
    this.canvas = el("canvas", { class: "notes" });
    this.canvasWrap.appendChild(this.canvas);
    this.playhead = el("div", { class: "playhead" });
    this.canvasWrap.appendChild(this.playhead);
    root.appendChild(this.gutter);
    root.appendChild(this.canvasWrap);

    this.ctx = this.canvas.getContext("2d");
    this.dpr = window.devicePixelRatio || 1;
    this.trackData = null;
    this.viewState = null;
    this.currentTime = 0;
    this.dirty = true;
    this._lastSize = { w: 0, h: 0 };

    // Theme cache — populated before first paint, refreshed on theme change.
    this._theme = {};
    this._readThemeCache();
    this._unsubTheme = subscribeTheme(() => {
      this._readThemeCache();
      this.dirty = true;
    });

    new ResizeObserver(() => { this.dirty = true; this._resizeCanvas(); }).observe(this.canvasWrap);
    // Re-render whenever the user toggles their notation preference — the
    // gutter labels and any next-frame tooltips will pick up the new system.
    document.addEventListener("musiq:notation-changed", () => { this.dirty = true; });
    // Drum-lane height slider (Settings → Layout) — drumLaneHeight() is
    // re-read on every draw, so the next dirty pass picks up the change.
    document.addEventListener("musiq:drum-layout-changed", () => { this.dirty = true; });
    this._frameLoop();
  }

  // Read all CSS token values into a plain cache object. Called once in
  // the constructor (before any paint) and again on musiq:theme-changed.
  // 2026-05-09 iter-2: every paint color is now derived from the live token
  // map. Previously the accent rgbas were frozen #ffb86b literals, which
  // made the loop band / play band / chord borders all paint warm amber
  // even after a Studio Light or Midnight preset switch. The theme cache
  // is rebuilt on every musiq:theme-changed event so canvas paint paths
  // pick up the new --accent / --fn-*-bg / --chord-*-bg / --drum-lane-bg
  // values without a reload.
  _readThemeCache() {
    const t = this._theme;
    // Stem colors — resolved from CSS custom properties.
    t.stems = {
      vocals: readToken("stem-vocals"),
      bass:   readToken("stem-bass"),
      guitar: readToken("stem-guitar"),
      piano:  readToken("stem-piano"),
      other:  readToken("stem-other"),
      drums:  readToken("stem-drums"),
    };
    // Drum sub-stem colors — read live from CSS tokens so the lane repaints
    // on theme switch (tokenized 2026-05-10).
    t.drums = {
      kick:    readToken("drum-kick"),
      snare:   readToken("drum-snare"),
      toms:    readToken("drum-toms"),
      hihat:   readToken("drum-hihat"),
      cymbals: readToken("drum-cymbals"),
    };
    // Accent — resolved fresh, then composed with the alpha values that
    // the original 2026-05-02 implementation captured as literal rgbas.
    t.accent = readToken("accent");
    t.accentLoopFill     = hexToRgba(t.accent, readAlpha("alpha-loop-band-fill", 0.05));
    t.accentLoopStroke   = hexToRgba(t.accent, readAlpha("alpha-loop-band-stroke", 0.225));
    t.accentPlayFill     = hexToRgba(t.accent, readAlpha("alpha-play-band-fill", 0.10));
    t.accentPlayStroke   = hexToRgba(t.accent, readAlpha("alpha-play-band-stroke", 0.55));
    t.accentOctave       = hexToRgba(t.accent, 0.32);
    t.accentChordNow     = hexToRgba(t.accent, 0.10);
    t.accentChordBorder  = hexToRgba(t.accent, 0.85);
    t.accentEOT          = hexToRgba(t.accent, 0.75);
    t.accentEOTLabel     = hexToRgba(t.accent, 0.95);
    // Chord strip surface.
    t.chordStripBg       = readToken("surface-1");
    // Function-band fill colors (per chord category).
    t.fnBg = {
      tonic:             readToken("fn-tonic-bg"),
      dominant:          readToken("fn-dominant-bg"),
      predominant:       readToken("fn-predominant-bg"),
      modal_interchange: readToken("fn-modal-bg"),
    };
    t.chordDefaultBg     = readToken("chord-default-bg");
    t.chordNoBg          = readToken("chord-no-bg");
    t.drumLaneBg         = readToken("drum-lane-bg");
    // Reusable text-on-surface alphas (replaces the previous
    // rgba(255,255,255,...) and rgba(0,0,0,...) literals so the chord
    // labels, beat counters, and end-of-track scrim follow the active
    // text-primary color instead of pinning to white). Read --text-primary
    // once and pre-compose three alpha buckets matching the legacy values.
    const textPrimary = readToken("text-primary");
    t.textPrimary        = textPrimary;
    t.chordLabel         = hexToRgba(textPrimary, 0.78);
    // Bar-number alpha is theme-tunable: dark text @ 0.60 on cream reads
    // perceptually lighter than light text @ 0.60 on near-black, so
    // Studio Light bumps this multiplier in presets.js. Iter-4 verdict
    // flagged numerals as "slightly recessed" on the cream canvas.
    t.beatNumberFg       = hexToRgba(textPrimary, readAlpha("alpha-bar-number", 0.60));
    // Grid lines: a distinct --grid-line color (defaults to --text-primary per
    // preset) composed with per-element alphas. Bar lines read stronger than
    // beat lines; the diatonic/octave rows reuse --alpha-grid-line.
    const gridLine       = readToken("grid-line");
    t.barLine            = hexToRgba(gridLine, readAlpha("alpha-grid-bar", 0.13));
    t.beatLine           = hexToRgba(gridLine, readAlpha("alpha-grid-beat", 0.06));
    t.diatonicLine       = hexToRgba(gridLine, readAlpha("alpha-grid-line", 0.10));
    t.chordSep           = hexToRgba(textPrimary, 0.08);
    t.chordStripDivider  = hexToRgba(textPrimary, 0.12);
    t.songTimeAnchor     = hexToRgba(textPrimary, 0.18);
    t.drumLaneDivider    = hexToRgba(textPrimary, 0.12);
    t.drumSubDivider     = hexToRgba(textPrimary, 0.04);
    t.eotShade           = "rgba(0,0,0,0.45)";   // dark scrim works on every theme
    // Note border for highlighted-stem on top of stem fills — needs to be
    // dark on light themes too. accent-on flips with the theme so re-use it.
    t.noteBorder         = hexToRgba(readToken("accent-on"), 0.55);
  }

  dispose() {
    if (this._unsubTheme) { this._unsubTheme(); this._unsubTheme = null; }
  }

  setTrackData(td) {
    this.trackData = td;
    this.keyInfo = keyInfo(td?.meta?.key ?? "");
    this.keyTonicCls = this.keyInfo?.tonic ?? null;
    this.keyParse = parseKey(td?.meta?.key ?? "");
    this.dirty = true;
  }
  setViewState(vs) {
    if (this.viewState) this.viewState.off("change", this._onChange);
    this.viewState = vs;
    this._onChange = () => { this.dirty = true; this._positionPlayhead(); };
    vs.on("change", this._onChange);
    this.dirty = true;
  }
  setCurrentTime(t) { this.currentTime = t; this.dirty = true; this._positionPlayhead(); }

  // Fit the piano-roll's vertical range so [lowMidi, highMidi] sits inside
  // the inner pitch area (the slice between the chord strip and the drum
  // lane), with one semitone of breathing room on each side so the boundary
  // pitches' note rectangles render fully (not clipped at the edge).
  // Updates viewState.midiCenter and viewState.zoomV. Returns true if
  // applied, false if the canvas isn't sized yet.
  fitMidiRange(lowMidi, highMidi) {
    if (!this.viewState || !this._lastSize.h) return false;
    const drumH = drumLaneHeight(this.trackData);
    const innerH = this._lastSize.h - CHORD_H - drumH;
    if (innerH <= 0) return false;
    const pad = 1;                                   // semitones of margin
    const semis = Math.max(1, (highMidi - lowMidi) + 2 * pad);
    const zoomV = innerH / semis;
    const midiCenter = (lowMidi + highMidi) / 2;
    this.viewState.update({ midiCenter, zoomV });
    return true;
  }

  _positionPlayhead() {
    if (!this.viewState || !this._lastSize.w) return;
    const x = timeToX(this.currentTime, this.viewState);
    const clamped = Math.max(0, Math.min(this._lastSize.w, x));
    this.playhead.style.left = `${clamped}px`;
    this.playhead.style.opacity = (x < -2 || x > this._lastSize.w + 2) ? "0" : "1";
  }

  _resizeCanvas() {
    const rect = this.canvasWrap.getBoundingClientRect();
    this.canvas.width  = Math.floor(rect.width * this.dpr);
    this.canvas.height = Math.floor(rect.height * this.dpr);
    this.canvas.style.width  = rect.width + "px";
    this.canvas.style.height = rect.height + "px";
    this._lastSize = { w: rect.width, h: rect.height };
  }

  _frameLoop() {
    requestAnimationFrame(() => this._frameLoop());
    if (!this.dirty || !this.trackData || !this.viewState) return;
    this.dirty = false;
    this._draw();
  }

  _draw() {
    const td = this.trackData, vs = this.viewState;
    const { w, h } = this._lastSize;
    if (w === 0 || h === 0) return;
    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Layout: chord strip [0, top], piano roll [top, bottom], drum lane
    // [bottom, h]. Drum lane only present when drums stage transcribed.
    const top = CHORD_H;
    const drumH = drumLaneHeight(td);
    const bottom = h - drumH;
    this._drawLoopBands(ctx, td, vs, w, top, bottom);
    this._drawGrid(ctx, td, vs, w, top, bottom);
    this._drawDiatonicLines(ctx, vs, w, top, bottom);
    this._drawOctaveLines(ctx, vs, w, top, bottom);
    this._drawDiatonicTriangles(ctx, vs, top, bottom);
    this._drawChordStrip(ctx, td, vs, w, top);
    this._drawDrumLane(ctx, td, vs, w, bottom, drumH);
    this._drawSongTimeAnchor(ctx, vs, w, h);
    this._drawNotes(ctx, td, vs, w, top, bottom);
    this._drawPlaybackLoop(ctx, vs, w, top, bottom);
    this._drawEndOfTrack(ctx, td, vs, w, h);
    this._drawGutter(td, vs, top, bottom);
  }

  _drawEndOfTrack(ctx, td, vs, w, h) {
    const dur = td.meta.durationSec;
    if (!dur) return;
    const x = timeToX(dur, vs);
    if (x > w + 2) return;             // end is far off-screen to the right
    // Shade the region after the track ends, so the user sees there's no
    // more music. Uses a slight checker-like darkening to be obvious without
    // being noisy.
    if (x < w) {
      ctx.fillStyle = this._theme.eotShade;
      ctx.fillRect(Math.max(0, x), 0, w - Math.max(0, x), h);
    }
    if (x < -1) return;                // end already scrolled off-screen left
    // Vertical end-of-track marker.
    ctx.strokeStyle = this._theme.accentEOT;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, h);
    ctx.stroke();
    // "END" badge above the chord strip baseline. Place to the left of the
    // line so it stays inside the visible song area.
    ctx.fillStyle = this._theme.accentEOTLabel;
    ctx.font = "700 10px ui-monospace, monospace";
    ctx.textBaseline = "middle";
    ctx.fillText("END", Math.max(2, x - 28), 12);
  }

  _drawDrumLane(ctx, td, vs, w, top, drumH) {
    if (!drumH) return;
    const drums = td.notes.drums;
    ctx.fillStyle = this._theme.drumLaneBg;
    ctx.fillRect(0, top, w, drumH);

    // Top border separating drum lane from piano roll above
    ctx.strokeStyle = this._theme.drumLaneDivider;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, top + 0.5);
    ctx.lineTo(w, top + 0.5);
    ctx.stroke();

    // Drums live in their own lane below the piano roll, so they never
    // overlap with melodic notes. No reason to dim them when another stem
    // is selected — keep them at full alpha unconditionally.
    const baseAlpha = 1;

    const rowH = drumH / DRUM_SUBSTEMS.length;
    // Hover-enlarge for drum hits — same mechanism as melodic notes, but
    // ticks are 3px-wide rectangles so the scale runs through both width
    // and height around the tick's centre. See _drawNotes for the analogue.
    const HOVER_SCALE = 1.2;
    const hover = (vs.hoveredEvent && vs.hoveredEvent.kind === "drum") ? vs.hoveredEvent : null;
    for (let r = 0; r < DRUM_SUBSTEMS.length; r++) {
      const name = DRUM_SUBSTEMS[r];
      const sub = drums.drums[name];
      const yTop = top + r * rowH;
      const yMid = yTop + rowH / 2;
      // Faint sub-lane separator
      if (r > 0) {
        ctx.strokeStyle = this._theme.drumSubDivider;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, yTop + 0.5); ctx.lineTo(w, yTop + 0.5); ctx.stroke();
      }
      if (!sub || sub.t.length === 0) continue;
      const color = this._theme.drums[name];
      const n = sub.t.length;
      ctx.fillStyle = color;
      for (let i = 0; i < n; i++) {
        const x = timeToX(sub.t[i], vs);
        if (x < -2 || x > w + 2) continue;
        const v = sub.vel[i];
        // Tick height runs from 60% (quiet) to 100% (peak) of sub-lane,
        // alpha 0.55–1.0. Even quiet hits remain clearly visible.
        let tickH = (0.6 + 0.4 * v) * (rowH - 1);
        let tickW = 3;
        const isHovered = !!(hover && hover.stem === name && hover.idx === i);
        if (isHovered) { tickH *= HOVER_SCALE; tickW *= HOVER_SCALE; }
        const tickY = yMid - tickH / 2;
        ctx.globalAlpha = isHovered ? 1 : baseAlpha * (0.55 + 0.45 * v);
        ctx.fillRect(Math.round(x) - tickW / 2, tickY, tickW, tickH);
      }
    }
    ctx.globalAlpha = 1;
  }

  _drawLoopBands(ctx, td, vs, w, top, bottom) {
    ctx.fillStyle = this._theme.accentLoopFill;
    ctx.strokeStyle = this._theme.accentLoopStroke;
    ctx.lineWidth = 1;
    for (const band of td.loopBands) {
      const x0 = timeToX(band.start, vs);
      const x1 = timeToX(band.end, vs);
      if (x1 < 0 || x0 > w) continue;
      const fx0 = Math.max(0, x0);
      const fx1 = Math.min(w, x1);
      ctx.fillRect(fx0, top, fx1 - fx0, bottom - top);
      if (x0 >= 0 && x0 <= w) { ctx.beginPath(); ctx.moveTo(x0 + 0.5, top); ctx.lineTo(x0 + 0.5, bottom); ctx.stroke(); }
      if (x1 >= 0 && x1 <= w) { ctx.beginPath(); ctx.moveTo(x1 + 0.5, top); ctx.lineTo(x1 + 0.5, bottom); ctx.stroke(); }
    }
  }

  _drawPlaybackLoop(ctx, vs, w, top, bottom) {
    if (vs.loopStart == null || vs.loopEnd == null) return;
    const x0 = timeToX(vs.loopStart, vs);
    const x1 = timeToX(vs.loopEnd, vs);
    if (x1 < 0 || x0 > w) return;
    const fx0 = Math.max(0, x0);
    const fx1 = Math.min(w, x1);
    // Brighter than analyzed loopBands (which use 0.05 fill / 0.225 stroke)
    // so the user's playback loop reads as a distinct, deliberate selection.
    ctx.fillStyle = this._theme.accentPlayFill;
    ctx.fillRect(fx0, top, fx1 - fx0, bottom - top);
    ctx.strokeStyle = this._theme.accentPlayStroke;
    ctx.lineWidth = 1;
    if (x0 >= 0 && x0 <= w) { ctx.beginPath(); ctx.moveTo(x0 + 0.5, top); ctx.lineTo(x0 + 0.5, bottom); ctx.stroke(); }
    if (x1 >= 0 && x1 <= w) { ctx.beginPath(); ctx.moveTo(x1 + 0.5, top); ctx.lineTo(x1 + 0.5, bottom); ctx.stroke(); }
  }

  _drawOctaveLines(ctx, vs, w, top, bottom) {
    if (this.keyTonicCls == null) return;
    const innerH = bottom - top;
    const topMidi = Math.ceil(vs.midiCenter + (innerH / 2) / vs.zoomV);
    const botMidi = Math.floor(vs.midiCenter - (innerH / 2) / vs.zoomV);
    // Smallest MIDI >= botMidi whose pitch-class equals the tonic. The
    // previous `ceil(botMidi/12)*12 + tonicCls` formula assumed the start
    // of a C-aligned octave block, which silently dropped the in-octave
    // tonic when botMidi sat between the prior C and the tonic (e.g. with
    // Bb tonic and botMidi=27 it jumped to MIDI 46 / Bb2 and missed
    // MIDI 34 / Bb1 entirely).
    const startMidi = botMidi + (((this.keyTonicCls - botMidi) % 12) + 12) % 12;
    ctx.save();
    ctx.strokeStyle = this._theme.accentOctave;
    ctx.lineWidth = 1;
    for (let m = startMidi; m <= topMidi; m += 12) {
      if (m < botMidi) continue;
      const y = Math.round(midiToY(m, vs, innerH) + top) + 0.5;
      if (y < top || y > bottom) continue;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  // Small right-pointing triangles at the canvas left edge, with the apex
  // touching each diatonic pitch line. Anchored at the same midiToY position
  // as the lines themselves, so they remain perfectly aligned at any zoom.
  // Tonic gets full accent intensity; other diatonic degrees are dimmed for
  // a strong-vs-weak hierarchy.
  _drawDiatonicTriangles(ctx, vs, top, bottom) {
    if (!this.keyInfo) return;
    const innerH = bottom - top;
    const topMidi = Math.ceil(vs.midiCenter + (innerH / 2) / vs.zoomV);
    const botMidi = Math.floor(vs.midiCenter - (innerH / 2) / vs.zoomV);
    const tonic = this.keyInfo.tonic;
    const scale = this.keyInfo.scale;
    const W = 11;           // triangle width (apex distance from left edge)
    const H = 11;           // triangle base height
    ctx.save();
    ctx.fillStyle = this._theme.accent;
    for (let m = botMidi; m <= topMidi; m++) {
      const cls = ((m % 12) + 12) % 12;
      if (!scale.has(cls)) continue;
      const isTonic = cls === tonic;
      const y = midiToY(m, vs, innerH) + top;
      if (y < top - H || y > bottom + H) continue;
      ctx.globalAlpha = isTonic ? 1.0 : 0.55;
      ctx.beginPath();
      ctx.moveTo(0, y - H / 2);
      ctx.lineTo(W, y);
      ctx.lineTo(0, y + H / 2);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }

  _drawDiatonicLines(ctx, vs, w, top, bottom) {
    if (!this.keyInfo) return;
    const innerH = bottom - top;
    const topMidi = Math.ceil(vs.midiCenter + (innerH / 2) / vs.zoomV);
    const botMidi = Math.floor(vs.midiCenter - (innerH / 2) / vs.zoomV);
    const tonic = this.keyInfo.tonic;
    const scale = this.keyInfo.scale;
    ctx.save();
    ctx.strokeStyle = this._theme.diatonicLine;
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 4]);
    for (let m = botMidi; m <= topMidi; m++) {
      const cls = ((m % 12) + 12) % 12;
      // Skip the tonic — it gets its own solid octave line on top.
      if (cls === tonic || !scale.has(cls)) continue;
      const y = Math.round(midiToY(m, vs, innerH) + top) + 0.5;
      if (y < top || y > bottom) continue;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawGrid(ctx, td, vs, w, top, bottom) {
    const beatsPerBar = 4;     // assumes 4/4 — covered by td.meta.timeSig in M5
    ctx.lineWidth = 1;
    for (let i = 0; i < td.downbeats.length; i++) {
      const x = Math.round(timeToX(td.downbeats[i], vs)) + 0.5;
      if (x < -1 || x > w + 1) continue;
      ctx.strokeStyle = this._theme.barLine;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
      ctx.font = "600 10px ui-monospace, monospace";
      ctx.fillStyle = this._theme.beatNumberFg;
      ctx.fillText(String(i + 1), x + 4, top + 12);
      const next = td.downbeats[i + 1] ?? td.meta.durationSec;
      const beatLen = (next - td.downbeats[i]) / beatsPerBar;
      ctx.strokeStyle = this._theme.beatLine;
      for (let b = 1; b < beatsPerBar; b++) {
        const bx = Math.round(timeToX(td.downbeats[i] + b * beatLen, vs)) + 0.5;
        if (bx < 0 || bx > w) continue;
        ctx.beginPath(); ctx.moveTo(bx, top); ctx.lineTo(bx, bottom); ctx.stroke();
      }
    }
  }

  _drawChordStrip(ctx, td, vs, w, chordH) {
    ctx.fillStyle = this._theme.chordStripBg;
    ctx.fillRect(0, 0, w, chordH);
    // Route every chord label through the same shorthand→reformat pipeline
    // the sidebar's now-card uses, so the canvas strip and the sidebar agree
    // on accidentals (♯/♭) and on solfège vs scientific root letters.
    const notationSystem = getNotationSystem();
    for (const c of td.chords) {
      const x0 = timeToX(c.start, vs);
      const x1 = timeToX(c.end, vs);
      if (x1 < 0 || x0 > w) continue;
      const fx0 = Math.max(0, x0);
      const fx1 = Math.min(w, x1);
      const isNo = !c.label || c.label === "N";
      ctx.fillStyle = isNo ? this._theme.chordNoBg : (this._theme.fnBg[c.fn] ?? this._theme.chordDefaultBg);
      ctx.fillRect(fx0, 0, fx1 - fx0, chordH);
      // Highlight current chord
      const isNow = this.currentTime >= c.start && this.currentTime < c.end;
      if (isNow) {
        ctx.fillStyle = this._theme.accentChordNow;
        ctx.fillRect(fx0, 0, fx1 - fx0, chordH);
        ctx.strokeStyle = this._theme.accentChordBorder;
        ctx.lineWidth = 2;
        ctx.strokeRect(fx0 + 1, 1, (fx1 - fx0) - 2, chordH - 2);
      }
      const cellW = fx1 - fx0;
      if (c.roman && cellW >= 16) {
        ctx.fillStyle = this._theme.accent;
        ctx.font = "700 14px ui-serif, Georgia, serif";
        ctx.textBaseline = "middle";
        ctx.fillText(c.roman, fx0 + 6, chordH * 0.36);
      }
      if (c.label && c.label !== "N" && cellW >= 24) {
        ctx.fillStyle = this._theme.chordLabel;
        ctx.font = "11px ui-sans-serif, system-ui";
        ctx.textBaseline = "middle";
        const labelText = reformatRootedName(formatChordShorthand(c.label), notationSystem, this.keyParse);
        ctx.fillText(labelText, fx0 + 6, chordH * 0.74);
      }
      if (x1 >= 0 && x1 <= w) {
        ctx.strokeStyle = this._theme.chordSep;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x1 + 0.5, 0); ctx.lineTo(x1 + 0.5, chordH); ctx.stroke();
      }
    }
    ctx.strokeStyle = this._theme.chordStripDivider;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, chordH - 0.5); ctx.lineTo(w, chordH - 0.5); ctx.stroke();
  }

  _drawSongTimeAnchor(ctx, vs, w, h) {
    const x = Math.round(timeToX(this.currentTime, vs)) + 0.5;
    if (x < 0 || x > w) return;
    ctx.strokeStyle = this._theme.songTimeAnchor;
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }

  _drawNotes(ctx, td, vs, w, top, bottom) {
    // Each note's rectangle height *and* alpha scale linearly with its
    // velocity (no floor). Loud notes read as fat capsules; silent notes
    // disappear entirely — turning the row into a dynamics silhouette
    // without changing pitch ID.
    const baseH = Math.max(3, Math.min(18, vs.zoomV * 0.8));
    const dimAlpha = 0.16;
    // Highlighted-stem fill alpha — driven by --alpha-stem-fill so the
    // High Contrast preset (0.95) reads more saturated than Classic Dark
    // (0.85), as designed in the spec. Falls back to 0.85 if the token
    // isn't set yet (e.g. first paint before hydration completes).
    const stemFillAlpha = readAlpha("alpha-stem-fill", 0.85);
    const order = STEM_ORDER.slice();
    // dim first, highlighted last (so it sits on top)
    order.sort((a, b) => (a === vs.highlightedStem ? 1 : 0) - (b === vs.highlightedStem ? 1 : 0));
    const tNow = this.currentTime;
    // Hover-enlarge: when the user's cursor is on a detected note, the
    // matching {stem, idx} renders at 120% scale and full opacity (it's
    // also the last note painted on top, so it can't be hidden by a
    // neighbour). Inspector publishes this signal via vs.hoveredEvent.
    const HOVER_SCALE = 1.2;
    const hover = (vs.hoveredEvent && vs.hoveredEvent.kind === "note") ? vs.hoveredEvent : null;
    for (const stem of order) {
      const pack = td.notes[stem];
      if (!pack || pack.t.length === 0) continue;
      const isHi = stem === vs.highlightedStem;
      const baseAlpha = isHi ? stemFillAlpha : dimAlpha;
      const stemFill = this._theme.stems[stem];
      const n = pack.t.length;
      for (let i = 0; i < n; i++) {
        const t0 = pack.t[i];
        const t1 = t0 + pack.dur[i];
        const x0 = timeToX(t0, vs);
        const x1 = timeToX(t1, vs);
        if (x1 < 0 || x0 > w) continue;
        const dyn = pack.vel[i] ?? 0.5;  // 0% floor → 100% at full velocity
        let noteH = baseH * dyn;
        const isHovered = !!(hover && hover.stem === stem && hover.idx === i);
        // Hover-enlarge is vertical-only: the rectangle gets taller around
        // its centre, never wider. Stretching the width too would make
        // adjacent notes on the same row visually overlap and shift the
        // perceived onset, which is the opposite of what an inspector
        // affordance should do.
        if (isHovered) noteH *= HOVER_SCALE;
        const y = midiToY(pack.midi[i], vs, bottom - top) + top - noteH / 2;
        if (y + noteH < top || y > bottom) continue;
        const fx = Math.max(0, x0);
        const fw = Math.max(2, Math.min(w, x1) - fx);
        ctx.globalAlpha = isHovered ? 1 : baseAlpha * dyn;
        const isPlaying = isHi && tNow >= t0 && tNow < t1;
        if (isPlaying) {
          // text-primary flips white→dark on Studio Light, so the playing
          // note "pop" stays visible on every theme.
          ctx.fillStyle = this._theme.textPrimary;
          ctx.fillRect(fx, y, fw, noteH);
          ctx.strokeStyle = stemFill;
          ctx.lineWidth = 1.5;
          ctx.strokeRect(fx + 0.75, y + 0.75, Math.max(0, fw - 1.5), Math.max(0, noteH - 1.5));
        } else {
          ctx.fillStyle = stemFill;
          ctx.fillRect(fx, y, fw, noteH);
          if (isHi && fw >= 4 && noteH >= 4) {
            ctx.strokeStyle = this._theme.noteBorder;
            ctx.lineWidth = 1;
            ctx.strokeRect(fx + 0.5, y + 0.5, fw - 1, noteH - 1);
          }
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  _drawGutter(td, vs, top, bottom) {
    clear(this.gutter);
    this.gutter.appendChild(el("div", { class: "gutter-head", text: "PITCH" }));
    const innerH = bottom - top;
    const topMidi = Math.ceil(vs.midiCenter + (innerH / 2) / vs.zoomV);
    const botMidi = Math.floor(vs.midiCenter - (innerH / 2) / vs.zoomV);
    const labels = el("div", { class: "gutter-labels", style: { top: top + "px", height: innerH + "px" } });
    const rowH = vs.zoomV;
    const tonicCls = this.keyTonicCls;   // pitch class of current key tonic, set by setTrackData
    const notationSystem = getNotationSystem();
    // Label font scales with row height so the gutter text grows when the
    // user zooms in vertically (Shift+wheel) and shrinks back at low zoom.
    const fontPx = Math.max(8, Math.min(18, Math.round(rowH * 0.55)));
    for (let m = botMidi; m <= topMidi; m++) {
      const y = midiToY(m, vs, innerH);
      // Skip rows that fall outside the gutter's visible band.
      if (y + rowH / 2 < 0 || y - rowH / 2 > innerH) continue;
      const cls = (m % 12);
      const isBlack = [1, 3, 6, 8, 10].includes(cls);
      const isC = cls === 0;
      const isTonic = (tonicCls != null) && (cls === tonicCls);
      const isDiatonic = !!this.keyInfo?.scale.has(cls);
      const showLabel = rowH >= 14 || isC || isTonic || cls === 7;
      // Only label *in-key* pitches plus the tonic. When no key is known
      // (keyInfo null), fall back to the showLabel gate so the gutter
      // doesn't go blank — orientation labels (C, dominant) still appear.
      const inKey = this.keyInfo ? (isDiatonic || isTonic) : true;
      const labelText = (showLabel && inKey)
        ? formatPitch(m, this.keyParse, notationSystem)
        : "";
      // Octave digits render as <sub> via pitchChildren; empty input → empty
      // children array, leaving the row visually blank as before.
      const row = el("div", {
        class: `gutter-row${isBlack ? " black" : ""}${isC ? " octave" : ""}${isTonic ? " tonic" : ""}${isDiatonic ? " diatonic" : ""}`,
        // data-midi is the source of truth for which row corresponds to which
        // MIDI number — the inspector's hover-highlight reads this, instead
        // of trying to reconstruct the label, so the highlight stays correct
        // in solfège and in flat keys where the label spelling differs.
        data: { midi: String(m) },
        style: { top: (y - rowH / 2) + "px", height: rowH + "px", fontSize: fontPx + "px" },
      }, pitchChildren(labelText));
      labels.appendChild(row);
    }
    this.gutter.appendChild(labels);
  }

  viewportWidth() { return this._lastSize.w; }
}
