// User-facing preferences for pitch-contour stroke widths (Live Input + Vocals).
//
// Two knobs, both in CSS pixels:
//   - mic:    MicOverlay's live-mic ribbon width. Default 1.
//   - vocals: F0Overlay's consensus contour width. Default 1, but
//             applied as a SCALE relative to the per-bucket base widths
//             (strong=1.8, medium=1.5, weak=1.2 in f0-overlay.js). At
//             vocals=1 the bucket gradient collapses to ~0.8/1.0/1.2 —
//             still visibly different, but slim enough to feel precise.
//             At vocals=2 it doubles to ~1.6/2.0/2.4. Etc.
//
// Persistence + event shape mirror tooltip-prefs.js / notation-prefs.js:
// localStorage is the single source of truth; a `musiq:line-width-changed`
// CustomEvent on document lets every overlay subscribe and re-render
// without a reload. Unrecognised storage values are ignored, so a
// hand-edited blob can never crash the boot path.

const STORAGE_KEY = "musiq.lineWidth";
const MIC_DEFAULT    = 1;
const VOCALS_DEFAULT = 1;
const MIN_WIDTH = 0.5;
const MAX_WIDTH = 4;

// Used by F0Overlay to convert the user's "vocals width" pref (in CSS px)
// into a scale factor against the per-bucket STRENGTH_STROKE_WIDTH table.
// 1.5 is the bucket gradient's midpoint (strong=1.8, medium=1.5, weak=1.2).
export const VOCALS_BUCKET_BASE = 1.5;

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    return obj && typeof obj === "object" ? obj : null;
  } catch {
    return null;
  }
}

function writeStored(obj) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(obj)); } catch {}
}

function clamp(v, fallback) {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, n));
}

function emit() {
  document.dispatchEvent(new CustomEvent("musiq:line-width-changed", {
    detail: { mic: getMicLineWidth(), vocals: getVocalsLineWidth() },
  }));
}

export function getMicLineWidth() {
  return clamp(readStored()?.mic, MIC_DEFAULT);
}

export function setMicLineWidth(value) {
  const s = readStored() || {};
  s.mic = clamp(value, MIC_DEFAULT);
  writeStored(s);
  emit();
}

export function getVocalsLineWidth() {
  return clamp(readStored()?.vocals, VOCALS_DEFAULT);
}

export function setVocalsLineWidth(value) {
  const s = readStored() || {};
  s.vocals = clamp(value, VOCALS_DEFAULT);
  writeStored(s);
  emit();
}

export const LINE_WIDTH_RANGE = { min: MIN_WIDTH, max: MAX_WIDTH, step: 0.25 };
