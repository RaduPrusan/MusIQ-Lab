import { timeToX, midiToY } from "./coords.js";
import { CHORD_H, drumLaneHeight } from "./layout.js";
import {
  getF0Prefs,
  getF0StrengthCuts,
  getF0RmsOpacityRange,
} from "../music/f0-prefs.js";
import { readToken, subscribe as subscribeTheme } from "../theme/css-tokens.js";
import { getVocalsLineWidth, VOCALS_BUCKET_BASE } from "../ui/line-width-prefs.js";

// PESTO + consensus stroke colors are now token-driven (2026-05-09-iter-5):
// the original off-white consensus stroke (#f0f0f0) and teal PESTO (#7eddff)
// were tuned for dark backgrounds and read as washed-out greys on Studio
// Light's cream canvas. Resolved via `--f0-consensus-stroke`,
// `--f0-fcpe-stroke`, and `--f0-pesto-stroke`, refreshed on every
// `musiq:theme-changed`.

// Base opacity per agreement-strength bucket — used as a multiplicative
// modulator on top of the per-frame RMS-derived opacity (Phase 0c Step 4
// follow-up). When `vocals_rms` is unavailable on this track (dynamics
// stage hasn't run), these become the *only* source of opacity, matching
// the previous Step 2 behavior.
const STRENGTH_BASE_OPACITY = { strong: 1.0, medium: 0.7, weak: 0.4 };

// Stroke-width modulation by strength: a secondary visual cue alongside
// opacity. Strong frames are slightly thicker; weak frames are slimmer
// breadcrumbs. Even when RMS modulation drives opacity uniformly, the
// width difference still distinguishes confidence levels.
const STRENGTH_STROKE_WIDTH = { strong: 1.8, medium: 1.5, weak: 1.2 };

// Convert an F0 in Hz to MIDI. Returns NaN for f<=0 / NaN (unvoiced).
function hzToMidi(hz) {
  if (!hz || hz <= 0 || Number.isNaN(hz)) return NaN;
  return 69 + 12 * Math.log2(hz / 440);
}

// Median MIDI value of consensusF0[lo..hi) in MIDI space (log-frequency,
// not Hz — equal-cents distance == equal-MIDI distance, which is what
// "musical median" should mean). NaN/non-positive entries are skipped.
//
// Used by the consensus path renderer for stride-aware anti-aliasing
// (window grows with zoom-out) and outlier rejection (single-frame
// octave-glitch residuals get squeezed out by the median).
//
// `mask` is an optional same-length typed array; when supplied, only
// frames with truthy mask values contribute to the median. The renderer
// uses this to keep the smoother from crossing agreement-strength bucket
// boundaries — a high-strength center frame's smoothed Hz is computed
// only from other high-strength frames in the window, so the strong-bucket
// path can't pick up Hz values that belong to the medium or weak path.
//
// Performance note: we sort a small window per output sample, but the
// window is at most ~stride+5 elements so the O(n log n) cost is
// dominated by hzToMidi. At 1080p with stride=1, that's ~1080 medians
// per frame, each over ~5 elements — negligible compared to the
// piano-roll canvas redraw.
export function medianMidiOver(consensusF0, lo, hi, mask = null) {
  const ms = [];
  for (let k = lo; k < hi; k++) {
    if (mask && !mask[k]) continue;
    const v = consensusF0[k];
    if (v && v > 0 && Number.isFinite(v)) {
      ms.push(69 + 12 * Math.log2(v / 440));
    }
  }
  if (ms.length === 0) return NaN;
  ms.sort((a, b) => a - b);
  return ms[ms.length >> 1];
}

// Map a per-frame linear RMS amplitude to an opacity in [opacityFloor, 1].
// Below `dbFloor` dBFS: opacityFloor (faint trace). Above `dbCeil`: full.
// Linear interpolation in between, in dBFS space (matches perception).
//
// Exported for unit testing the mapping curve itself; the renderer calls
// it inline on the hot path. RMS = 0 (pure silence) maps to opacityFloor
// — no division-by-zero from log10(0).
export function rmsToOpacity(rms, range) {
  const { dbFloor, dbCeil, opacityFloor, opacityCeil } = range;
  if (!(rms > 0)) return opacityFloor;
  const db = 20 * Math.log10(rms);
  if (db <= dbFloor) return opacityFloor;
  if (db >= dbCeil) return opacityCeil;
  const t = (db - dbFloor) / (dbCeil - dbFloor);
  return opacityFloor + t * (opacityCeil - opacityFloor);
}

export class F0Overlay {
  constructor(host) {
    // Switch from SVG to canvas: SVG paths can't carry per-segment alpha
    // (path-level opacity only), and the user-visible feature here is
    // opacity proportional to per-frame vocal volume. Canvas's globalAlpha
    // reset between segments handles this naturally.
    this.canvas = document.createElement("canvas");
    this.canvas.classList.add("f0");
    // Match the SVG positioning the overlay had previously — absolutely
    // positioned, fills the canvasWrap, doesn't intercept clicks.
    Object.assign(this.canvas.style, {
      position: "absolute",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      pointerEvents: "none",
    });
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.dpr = window.devicePixelRatio || 1;
    this.dirty = true;
    this.trackData = null;
    this.viewState = null;
    this.canvasWrap = host;

    // Theme cache — populated before first paint, refreshed on theme change.
    // F0Overlay is a singleton per page load, so the subscriber leak is
    // bounded to one entry; a dispose() is provided for completeness.
    this._theme = {};
    this._readThemeCache();
    this._unsubTheme = subscribeTheme(() => {
      this._readThemeCache();
      this.dirty = true;
    });

    new ResizeObserver(() => { this.dirty = true; this._render(); }).observe(host);
    document.addEventListener("musiq:f0-prefs-changed",   () => { this.dirty = true; });
    document.addEventListener("musiq:line-width-changed", () => { this.dirty = true; });
    // Colour overrides from Settings → Pitch lines → Colours now ride on
    // musiq:theme-changed (writes go through the theme store), so the
    // existing subscribeTheme handler set up earlier in the constructor
    // already refreshes _theme + marks dirty. No extra listener needed.
    this._loop();
  }

  // Read CSS token values used by this renderer.
  _readThemeCache() {
    // Fall back to the historical literals if the token is missing — keeps
    // the renderer working under an old localStorage payload that pre-dates
    // the iter-5 token additions. fcpe-stroke previously rode along with
    // --stem-vocals; it now has its own token so users can pick a contour
    // hue independent of the vocals fill.
    this._theme.consensusStroke = readToken("f0-consensus-stroke") || "#f0f0f0";
    this._theme.fcpeStroke      = readToken("f0-fcpe-stroke")      || "#ff00ff";
    this._theme.pestoStroke     = readToken("f0-pesto-stroke")     || "#7eddff";
  }

  dispose() {
    if (this._unsubTheme) { this._unsubTheme(); this._unsubTheme = null; }
  }

  setTrackData(td) { this.trackData = td; this.dirty = true; }
  setViewState(vs) {
    if (this.viewState) this.viewState.off("change", this._onChange);
    this.viewState = vs;
    this._onChange = () => { this.dirty = true; };
    vs.on("change", this._onChange);
    this.dirty = true;
  }

  _loop() {
    requestAnimationFrame(() => this._loop());
    if (!this.dirty) return;
    this.dirty = false;
    this._render();
  }

  // Draw a single contour (FCPE or PESTO raw estimator) with constant
  // opacity. These are comparison lines, not the primary user-facing
  // contour, so we keep them simple — no per-frame opacity modulation.
  _drawRaw(arr, hop, rect, vs, innerH, stroke, opacity) {
    if (!arr) return;
    const ctx = this.ctx;
    const t0 = vs.scrollSec;
    const t1 = t0 + rect.width / vs.zoomH;
    const i0 = Math.max(0, Math.floor(t0 / hop));
    const i1 = Math.min(arr.length, Math.ceil(t1 / hop));
    const stride = Math.max(1, Math.floor((i1 - i0) / Math.max(1, rect.width)));
    ctx.save();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.6;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.globalAlpha = opacity;
    ctx.beginPath();
    let pen = false;
    for (let i = i0; i < i1; i += stride) {
      const m = hzToMidi(arr[i]);
      if (Number.isNaN(m)) { pen = false; continue; }
      const x = timeToX(i * hop, vs);
      const y = midiToY(m, vs, innerH) + CHORD_H;
      if (pen) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      pen = true;
    }
    ctx.stroke();
    ctx.restore();
  }

  // Draw the consensus contour with per-frame variable opacity.
  //
  // Opacity per frame = STRENGTH_BASE_OPACITY[bucket] * rmsOpacity(rms[i])
  // where `rmsOpacity` maps frame RMS through a dBFS hinge (see
  // `rmsToOpacity`). When `vocalsRms` is null (dynamics stage hasn't run
  // on this track), per-frame opacity = STRENGTH_BASE_OPACITY[bucket]
  // alone — matching the pre-RMS-modulation rendering.
  //
  // Stroke width also varies by strength bucket as a secondary cue
  // (strong=1.8, medium=1.5, weak=1.2). Color is constant off-white so
  // strength distinction reads as a width/opacity gradient, not a color
  // change — easier on the eye and more accessible to colorblind users.
  //
  // Implementation: each frame transition (adjacent rendered samples)
  // becomes its own canvas line segment with its own globalAlpha, set
  // to the average of the two endpoints' opacities. Stroke width
  // changes between buckets, so we accumulate same-bucket runs and
  // flush at the boundary.
  _drawConsensus(consensusF0, agreementStrength, vocalsRms, hop, rect, vs, innerH, dimMul) {
    const ctx = this.ctx;
    const t0 = vs.scrollSec;
    const t1 = t0 + rect.width / vs.zoomH;
    const i0 = Math.max(0, Math.floor(t0 / hop));
    const i1 = Math.min(consensusF0.length, Math.ceil(t1 / hop));
    const stride = Math.max(1, Math.floor((i1 - i0) / Math.max(1, rect.width)));
    const halfWindow = Math.max(2, Math.ceil(stride / 2));

    const cuts = getF0StrengthCuts();
    const rmsRange = getF0RmsOpacityRange();
    // Per-bucket boolean masks for the median smoother (so a strong-bucket
    // center frame's smoothed Hz is computed only from other strong-bucket
    // frames — see medianMidiOver's mask param).
    const strongMask = new Uint8Array(consensusF0.length);
    const mediumMask = new Uint8Array(consensusF0.length);
    const weakMask = new Uint8Array(consensusF0.length);
    for (let k = i0; k < i1; k++) {
      const s = agreementStrength[k];
      if (s >= cuts.strong) strongMask[k] = 1;
      else if (s >= cuts.medium) mediumMask[k] = 1;
      else if (s >= cuts.weak) weakMask[k] = 1;
    }

    ctx.save();
    ctx.strokeStyle = this._theme.consensusStroke;
    ctx.lineJoin = "round";
    // `butt` (not `round`) caps — each segment ends exactly at the
    // geometric endpoint, so adjacent segments touch without overlap.
    // Round caps stack alpha at every shared vertex (two semicircular
    // caps overlay each other with potentially different per-segment
    // globalAlpha values, doubling the contribution and producing
    // visible bright beads along the line). Becomes especially obvious
    // at thinner widths after the line-width pref landed.
    ctx.lineCap = "butt";
    // User pref (Settings → Pitch lines → Vocals) scales the per-bucket
    // base widths. At vocals=1 (default) the bucket gradient compresses
    // to ~0.8 / 1.0 / 1.2; at vocals=2 it doubles. Bucket-relative gradient
    // is preserved so strength still reads visually.
    const widthScale = getVocalsLineWidth() / VOCALS_BUCKET_BASE;

    let prevX = null, prevY = null, prevAlpha = null, prevBucket = null;
    for (let i = i0; i < i1; i += stride) {
      const ci = consensusF0[i];
      if (!ci || ci <= 0 || Number.isNaN(ci)) {
        prevX = null; prevY = null; prevAlpha = null; prevBucket = null;
        continue;
      }
      let bucket, mask;
      if (strongMask[i]) { bucket = "strong"; mask = strongMask; }
      else if (mediumMask[i]) { bucket = "medium"; mask = mediumMask; }
      else if (weakMask[i]) { bucket = "weak"; mask = weakMask; }
      else {
        prevX = null; prevY = null; prevAlpha = null; prevBucket = null;
        continue;
      }
      const winLo = Math.max(i0, i - halfWindow);
      const winHi = Math.min(i1, i + halfWindow + 1);
      const m = medianMidiOver(consensusF0, winLo, winHi, mask);
      if (Number.isNaN(m)) {
        prevX = null; prevY = null; prevAlpha = null; prevBucket = null;
        continue;
      }
      const x = timeToX(i * hop, vs);
      const y = midiToY(m, vs, innerH) + CHORD_H;
      const baseOp = STRENGTH_BASE_OPACITY[bucket];
      const rmsOp = vocalsRms ? rmsToOpacity(vocalsRms[i], rmsRange) : 1.0;
      const alpha = baseOp * rmsOp * dimMul;

      if (prevX !== null) {
        // Segment from previous point to this one. Stroke width comes
        // from the current frame's bucket; opacity averages the two
        // endpoints (smooth visual transitions between adjacent frames).
        ctx.lineWidth = STRENGTH_STROKE_WIDTH[bucket] * widthScale;
        ctx.globalAlpha = (prevAlpha + alpha) * 0.5;
        ctx.beginPath();
        ctx.moveTo(prevX, prevY);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      prevX = x; prevY = y; prevAlpha = alpha; prevBucket = bucket;
    }
    ctx.restore();
  }

  _render() {
    const ctx = this.ctx;
    if (!this.trackData?.f0 || !this.viewState) {
      // Clear and bail.
      const w = this.canvas.width;
      const h = this.canvas.height;
      if (w && h) ctx.clearRect(0, 0, w, h);
      return;
    }
    const rect = this.canvasWrap.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;

    // Resize for HiDPI: device-pixel-sized backing buffer, CSS-pixel-sized
    // logical viewport. Otherwise lines look chunky on retina displays.
    const targetW = Math.max(1, Math.round(cssW * this.dpr));
    const targetH = Math.max(1, Math.round(cssH * this.dpr));
    if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
      this.canvas.width = targetW;
      this.canvas.height = targetH;
    }
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const drumH = drumLaneHeight(this.trackData);
    const innerH = cssH - CHORD_H - drumH;
    const vs = this.viewState;
    const f0 = this.trackData.f0;
    const hop = f0.hopSec;
    const prefs = getF0Prefs();

    // Stem-highlight dim/bright (vocals stem highlighted = full opacity).
    const dimMul = vs.highlightedStem === "vocals" ? 1.0 : 0.45;

    // Raw FCPE/PESTO comparison lines — drawn underneath, constant opacity.
    if (prefs.pesto && f0.pesto) {
      this._drawRaw(f0.pesto, hop, rect, vs, innerH, this._theme.pestoStroke, 0.9 * dimMul);
    }
    if (prefs.fcpe && f0.fcpe) {
      this._drawRaw(f0.fcpe, hop, rect, vs, innerH, this._theme.fcpeStroke, 0.9 * dimMul);
    }

    // Consensus — primary line, per-frame RMS-modulated opacity.
    if (prefs.consensus && f0.consensus) {
      this._drawConsensus(
        f0.consensus.consensusF0,
        f0.consensus.agreementStrength,
        f0.vocalsRms,
        hop, rect, vs, innerH, dimMul,
      );
    }
  }
}
