// Live-mic canvas overlay. Self-installs into the same .canvas-wrap host
// as F0Overlay (see f0-overlay.js:88-105 for the pattern we mirror).
// Drawn ABOVE F0Overlay in the layer stack.
//
// The renderer is pulled (not pushed): it owns no timer of its own — main.js
// calls `render()` whenever it needs a refresh (currently: when MicPitch
// emits 'sample', plus on viewState changes). For tear-free updates on
// fast scrolls, we also kick a one-shot rAF inside render() if dirty.

import { timeToX, midiToY } from "./coords.js";
import { CHORD_H, drumLaneHeight } from "./layout.js";
import { getMicLineWidth } from "../ui/line-width-prefs.js";

// NOTE: EMA smoothing now happens at WRITE time inside MicPitch (see
// EMA_ALPHA + EMA_GAP_S in mic-pitch.js). The ring carries pre-smoothed
// values, so this overlay reads s.midi / s.cents directly. Render-time
// EMA was abandoned because it re-seeded from the visible window's
// leftmost sample on every frame — as the viewport panned, the EMA
// chain shifted and produced a ~1 px shimmer on near-horizontal line
// sections. Vocals (F0Overlay) doesn't have this problem because its
// median smoother is non-recursive.

// Binary cents bucket: in tune (within one semitone of the reference note)
// or off. A semitone window (±100¢) is loose on purpose — a vocalist holding
// a note breathes ±30-50¢ around the target and a tighter window would make
// the ribbon strobe between buckets on every frame. The `neutral` case fires
// when cents is null/NaN (no reference active, or the reference stem has no
// note at this song time — e.g. between vocal phrases).
const SEMITONE_CENTS = 100;

// Maximum |time gap| between two ring-buffer samples before we treat them
// as belonging to separate utterances and stop drawing a connecting
// segment. At ~43 ms per worklet block this corresponds to ~3 consecutive
// unvoiced/gated frames — voiced glissandos easily clear the threshold;
// silences cleanly break the ribbon instead of being bridged by a long
// diagonal that misrepresents pitch and timing.
//
// Compared with Math.abs so that BACKWARD jumps trip the guard too — the
// ring stores samples in insertion order, not time order, so a backward
// seek (playhead moved back, then user sang) yields adjacent entries with
// t1 < t0. A one-sided `t1 - t0 > THRESHOLD` check would silently bridge
// that, producing a long horizontal line across the seek boundary.
const MAX_SEGMENT_GAP_S = 0.15;

// Bucket the per-frame cents value into a colour key.
//
//   in        — voiced, |cents| ≤ 100¢ (matched within a semitone)
//   off       — voiced, |cents| > 100¢ (more than a semitone off target)
//   neutral   — matched to a stem but the stem has no note at this song
//               time (between vocal phrases — there is a reference, just
//               not here)
//   no-match  — user picked "match: none" so there is no reference at all
//
// The split between `neutral` and `no-match` lets the user distinguish
// "the stem is silent here, I'm still being graded against it" from
// "I deliberately turned off matching" via two independent theme tokens.
// hasReference defaults to true so existing call sites that don't pass
// the flag keep the pre-split behaviour ("any NaN → neutral").
export function centsToColourBucket(c, hasReference = true) {
  if (c === null || c === undefined || Number.isNaN(c)) {
    return hasReference ? "neutral" : "no-match";
  }
  return Math.abs(c) <= SEMITONE_CENTS ? "in" : "off";
}

// Resolve a bucket to an rgba string. Reads CSS tokens for theme parity
// (--mic-in / --mic-off / --mic-neutral); falls back to hex defaults that
// match the defaults declared in track.css :root. These tokens are
// decoupled from --ok / --err so the user can recolour the mic ribbon
// via Settings → Pitch lines → Colours without affecting success/error
// badges elsewhere in the app.
function readToken(name, fallback) {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

// Per-frame opacity from RMS, mapped through dBFS so it matches how the
// ear perceives loudness — a moderate hum reads as roughly 70% opacity,
// a full belt as 100%, a near-whisper near the worklet gate as ~35%.
// Range chosen for typical vocal RMS:
//   DB_FLOOR = -40 dBFS  ≈ linear 0.01 (a bit above the 0.005 worklet gate)
//   DB_CEIL  = -12 dBFS  ≈ linear 0.25 (moderately loud singing)
// Anything quieter or louder clamps to ALPHA_FLOOR / ALPHA_CEIL.
export const ALPHA_FLOOR = 0.00;
export const ALPHA_CEIL  = 1.00;
const DB_FLOOR = -40;
const DB_CEIL  = -12;

export function rmsToAlpha(rms) {
  if (!(rms > 0)) return ALPHA_FLOOR;
  const db = 20 * Math.log10(rms);
  if (db <= DB_FLOOR) return ALPHA_FLOOR;
  if (db >= DB_CEIL)  return ALPHA_CEIL;
  const t = (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR);
  return ALPHA_FLOOR + t * (ALPHA_CEIL - ALPHA_FLOOR);
}

function strokeFor(bucket, rms) {
  const colour = ({
    in:        readToken("--mic-in",       "#7fdc20"),
    off:       readToken("--mic-off",      "#e7574a"),
    neutral:   readToken("--mic-neutral",  "#5ab4ff"),
    "no-match": readToken("--mic-no-match", "#a48cff"),
  })[bucket];
  return { colour, alpha: rmsToAlpha(rms) };
}

export class MicOverlay {
  constructor(host, micPitch) {
    this.canvas = document.createElement("canvas");
    this.canvas.classList.add("mic");
    Object.assign(this.canvas.style, {
      position: "absolute",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      pointerEvents: "none",
      // Layer above F0Overlay (which has no explicit z-index, so any
      // positive value here wins in DOM order, but be explicit).
      zIndex: "3",
    });
    host.appendChild(this.canvas);
    this.ctx = this.canvas.getContext("2d");
    this.dpr = window.devicePixelRatio || 1;
    this.canvasWrap = host;

    this.micPitch = micPitch;
    this.viewState = null;
    this.trackData = null;
    this._raf = 0;

    if (micPitch) {
      this._onSample = () => this._scheduleDraw();
      this._onRefChanged = () => this._scheduleDraw();
      // setTranspose back-shifts the whole ring in place; redraw right away
      // so the visible trail jumps with the spinner, not on the next sample.
      this._onTransposeChanged = () => this._scheduleDraw();
      micPitch.addEventListener("sample", this._onSample);
      micPitch.addEventListener("reference-changed", this._onRefChanged);
      micPitch.addEventListener("transpose-changed", this._onTransposeChanged);
    }
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => this._scheduleDraw()).observe(host);
    }
    // Repaint immediately when the user drags the Live Input width slider
    // or picks a new mic colour in Settings → Pitch lines → Colours
    // (colour picks land as theme-token writes, dispatching theme-changed).
    if (typeof document !== "undefined") {
      this._onWidthChanged = () => this._scheduleDraw();
      this._onThemeChanged = () => this._scheduleDraw();
      this._onDrumLayoutChanged = () => this._scheduleDraw();
      document.addEventListener("musiq:line-width-changed", this._onWidthChanged);
      document.addEventListener("musiq:theme-changed",      this._onThemeChanged);
      document.addEventListener("musiq:drum-layout-changed", this._onDrumLayoutChanged);
    }
  }

  setViewState(vs) {
    // Subscribe to viewState "change" so the overlay repaints on every
    // scrollSec update (60 Hz during autoScroll), not just on mic sample
    // events (~23 Hz). Without this the line stays at its prior X
    // position for 2-3 frames between sample ticks while the rest of
    // the canvas (vocals, playhead) slides forward — the next sample
    // arrives and the line snaps forward to catch up, reading as a
    // 1-2 px "lag and catch up" judder. F0Overlay subscribes the same
    // way (f0-overlay.js).
    if (this.viewState && this._onViewChange && this.viewState.off) {
      this.viewState.off("change", this._onViewChange);
    }
    this.viewState = vs;
    this._onViewChange = () => this._scheduleDraw();
    // Optional chaining tolerates minimal test fakes (plain {scrollSec,…}
    // objects without the createViewState proxy).
    vs.on?.("change", this._onViewChange);
    this._scheduleDraw();
  }
  setTrackData(td) { this.trackData = td; this._scheduleDraw(); }

  // Removes the "sample" listener and cancels any pending rAF. Call this
  // before discarding a MicOverlay instance (e.g. on track change in
  // main.js) so the long-lived MicPitch singleton doesn't accumulate
  // dead subscribers — each leftover handler would keep this whole
  // MicOverlay (and its captured closure) alive and schedule rAF redraws
  // on every sample tick.
  destroy() {
    if (this.micPitch && this._onSample) {
      this.micPitch.removeEventListener("sample", this._onSample);
      this._onSample = null;
    }
    if (this.micPitch && this._onRefChanged) {
      this.micPitch.removeEventListener("reference-changed", this._onRefChanged);
      this._onRefChanged = null;
    }
    if (this.micPitch && this._onTransposeChanged) {
      this.micPitch.removeEventListener("transpose-changed", this._onTransposeChanged);
      this._onTransposeChanged = null;
    }
    if (this._onWidthChanged && typeof document !== "undefined") {
      document.removeEventListener("musiq:line-width-changed", this._onWidthChanged);
      this._onWidthChanged = null;
    }
    if (this._onThemeChanged && typeof document !== "undefined") {
      document.removeEventListener("musiq:theme-changed", this._onThemeChanged);
      this._onThemeChanged = null;
    }
    if (this._onDrumLayoutChanged && typeof document !== "undefined") {
      document.removeEventListener("musiq:drum-layout-changed", this._onDrumLayoutChanged);
      this._onDrumLayoutChanged = null;
    }
    if (this.viewState && this._onViewChange) {
      this.viewState.off?.("change", this._onViewChange);
      this._onViewChange = null;
    }
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
    this.micPitch = null;
  }

  _scheduleDraw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this.render();
    });
  }

  render() {
    const ctx = this.ctx;
    if (!this.micPitch || !this.viewState) return;

    const rect = this.canvasWrap.getBoundingClientRect();
    const cssW = rect.width;
    const cssH = rect.height;
    const targetW = Math.max(1, Math.round(cssW * this.dpr));
    const targetH = Math.max(1, Math.round(cssH * this.dpr));
    if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
      this.canvas.width = targetW;
      this.canvas.height = targetH;
    }
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const vs = this.viewState;
    const drumH = drumLaneHeight(this.trackData);
    const innerH = cssH - CHORD_H - drumH;

    // Visible song-time window.
    const tStart = vs.scrollSec - 1;
    const tEnd = vs.scrollSec + cssW / vs.zoomH + 1;
    const s = this.micPitch.getSamplesInRange(tStart, tEnd);
    if (s.time.length < 2) return;

    // Ring values are already EMA-smoothed at write time by MicPitch, so
    // we just read s.midi / s.cents directly. No per-frame transformation
    // on the data — only the geometric mapping to canvas coordinates.
    // This is what keeps the line position stable as the viewport pans.
    const N = s.time.length;

    // Pre-compute canvas coords once. midiToY+CHORD_H matches F0Overlay
    // (f0-overlay.js:183, 262) — midiToY returns coordinates relative
    // to the inner piano-roll area, which sits CHORD_H below the canvas
    // top because of the chord strip.
    const xs = new Float32Array(N);
    const ys = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      xs[i] = timeToX(s.time[i], vs);
      ys[i] = midiToY(s.midi[i], vs, innerH) + CHORD_H;
    }

    // Width from the user pref (Settings → Pitch lines → Live Input).
    // Round-cap + round-join keep curve joins visually continuous when
    // adjacent segments are drawn with different colours.
    ctx.lineWidth = getMicLineWidth();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    // Whether the user has a reference stem selected RIGHT NOW. Read
    // once per render — flipping the match dropdown re-renders. NaN
    // cents in the buffer split into "neutral" (matched-to-stem-but-
    // silent) vs "no-match" (match=none) based on this flag.
    // Optional chaining tolerates minimal test fakes that don't define
    // getReferenceStem; default-true preserves the pre-split bucket.
    const hasReference = !!this.micPitch.getReferenceStem?.();

    // Catmull-Rom curves subdivided into short straight sub-segments,
    // then stroked as one polyline per ring segment.
    //
    // Background: ~43 ms YIN blocks give ~4.3 px between samples at
    // default zoom. A pure Bezier between sparse samples is geometrically
    // smooth but each long curve still has only a few path commands; the
    // canvas renderer still rasterises it as one shape, and sub-pixel
    // pan redistributes AA brightness along the curve in concentrated
    // patches that read as horizontal jitter. Vocals (F0) doesn't have
    // this because consensus samples are ~1 px apart — vertex density
    // matches pixel density, so AA settles into a per-pixel pattern that
    // pans smoothly.
    //
    // The fix: keep Catmull-Rom for shape (smooth tangents at every
    // sample, no overshoot at sharp turns), then SUBDIVIDE each segment
    // into SUB_STEPS short line pieces drawn as a polyline. Pixel-dense
    // line, smooth AA, stable under pan. lineCap "butt" avoids the
    // alpha-stacking junction artifact between adjacent polylines.
    //
    // Uniform Catmull-Rom → cubic Bezier:
    //   C1 = P1 + (P2 − P0) / 6     C2 = P2 − (P3 − P1) / 6
    // then evaluate the Bernstein form at t = 1/SUB_STEPS, 2/SUB_STEPS,…
    //
    // Silence/seek gaps (|Δt| > MAX_SEGMENT_GAP_S) break the curve
    // into separate "runs"; each run uses clamped tangent neighbours at
    // its boundaries so endpoint segments don't borrow control points
    // from across a silence.
    ctx.lineCap = "butt";
    const SUB_STEPS = 6;            // 4.3 px / 6 ≈ 0.7 px per sub-segment
    let runStart = 0;
    for (let i = 1; i <= N; i++) {
      const endOfRun = i === N ||
        Math.abs(s.time[i] - s.time[i - 1]) > MAX_SEGMENT_GAP_S;
      if (!endOfRun) continue;
      const runEnd = i;
      const lo = runStart, hi = runEnd - 1;
      for (let j = lo; j < hi; j++) {
        const j0 = j === lo     ? j     : j - 1;
        const j3 = j + 1 === hi ? j + 1 : j + 2;
        const p1x = xs[j],     p1y = ys[j];
        const p2x = xs[j + 1], p2y = ys[j + 1];
        const c1x = p1x + (p2x - xs[j0]) / 6;
        const c1y = p1y + (p2y - ys[j0]) / 6;
        const c2x = p2x - (xs[j3] - p1x) / 6;
        const c2y = p2y - (ys[j3] - p1y) / 6;
        const bucket = centsToColourBucket(s.cents[j], hasReference);
        const { colour, alpha } = strokeFor(bucket, s.rms[j]);
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = colour;
        ctx.beginPath();
        ctx.moveTo(p1x, p1y);
        for (let k = 1; k <= SUB_STEPS; k++) {
          const t = k / SUB_STEPS;
          const u = 1 - t;
          const uu = u * u, tt = t * t;
          const w0 = uu * u, w1 = 3 * uu * t, w2 = 3 * u * tt, w3 = tt * t;
          const x = w0 * p1x + w1 * c1x + w2 * c2x + w3 * p2x;
          const y = w0 * p1y + w1 * c1y + w2 * c2y + w3 * p2y;
          ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      runStart = runEnd;
    }
    ctx.globalAlpha = 1;
  }
}
