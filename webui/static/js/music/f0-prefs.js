// User-facing preference: which F0 contour(s) to overlay on the piano roll.
// Persisted in localStorage; emits a "musiq:f0-prefs-changed" CustomEvent on
// document so the F0 overlay (and any other listeners) can re-render lazily.

const STORAGE_KEY = "musiq.f0Prefs";

// Agreement-strength bucket cuts for the consensus contour renderer.
// Frames with strength >= STRONG_CUT draw on the strong (full-opacity) path;
// MEDIUM_CUT..STRONG_CUT on the medium path; WEAK_CUT..MEDIUM_CUT on the
// weak (dim) path. Frames below WEAK_CUT break the pen.
//
// Defaults are tuned for Phase 0c Step 2's heuristic strength scheme:
//   Strong (>=0.7): both F0 estimators voiced AND agree within threshold
//   Medium (~0.4-0.5): single F0 + anchor, or anchor breaks disagreement tie
//   Weak (~0.25): single F0 alone; weakest evidence renders as a hint
//
// Phase 0c Step 4 (Viterbi) replaces the heuristic strength with continuous
// emission-cost-derived confidence; the cuts may need re-tuning then.
// Surfaced as constants (not yet UI-exposed) so re-tuning is a one-line
// change rather than spelunking through render code.
export const STRENGTH_STRONG_CUT = 0.7;
export const STRENGTH_MEDIUM_CUT = 0.4;
export const STRENGTH_WEAK_CUT = 0.1;

export function getF0StrengthCuts() {
  return {
    strong: STRENGTH_STRONG_CUT,
    medium: STRENGTH_MEDIUM_CUT,
    weak: STRENGTH_WEAK_CUT,
  };
}

// RMS-to-opacity mapping for the consensus contour. The vocals stem RMS
// (linear amplitude, frame-rate-aligned) maps to opacity through a
// dBFS hinge: frames at or below RMS_DB_FLOOR draw at the floor opacity
// (faint trace), frames at or above RMS_DB_CEIL draw at the ceiling
// opacity (full visibility), with linear interpolation in between.
//
// Defaults are tuned for BS-RoFormer-cleaned vocal stems where typical
// soft passages sit around -35 to -25 dBFS and shouts/peaks reach
// -10 to -5 dBFS. Surfaced as constants so a re-tune is a one-line
// change without code surgery.
export const RMS_DB_FLOOR = -45.0;
export const RMS_DB_CEIL = -15.0;
export const RMS_OPACITY_FLOOR = 0.05;  // never quite zero — keeps a faint trace
export const RMS_OPACITY_CEIL = 1.0;

export function getF0RmsOpacityRange() {
  return {
    dbFloor: RMS_DB_FLOOR,
    dbCeil: RMS_DB_CEIL,
    opacityFloor: RMS_OPACITY_FLOOR,
    opacityCeil: RMS_OPACITY_CEIL,
  };
}

// Default: consensus on (the cleanest pitch line, with confidence-driven
// opacity), FCPE off and PESTO off (raw estimators available as comparison
// when the user wants to see disagreement directly). Caches that haven't
// run the consensus stage gracefully fall back to nothing rendered for
// the consensus path; the FCPE/PESTO toggles still work on the raw arrays.
const DEFAULT = Object.freeze({ fcpe: false, pesto: false, consensus: true });

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

export function getF0Prefs() {
  const stored = readStored() || {};
  return {
    fcpe: typeof stored.fcpe === "boolean" ? stored.fcpe : DEFAULT.fcpe,
    pesto: typeof stored.pesto === "boolean" ? stored.pesto : DEFAULT.pesto,
    consensus: typeof stored.consensus === "boolean" ? stored.consensus : DEFAULT.consensus,
  };
}

export function setF0Prefs(patch) {
  if (!patch || typeof patch !== "object") return;
  const current = getF0Prefs();
  const next = { ...current };
  if (typeof patch.fcpe === "boolean") next.fcpe = patch.fcpe;
  if (typeof patch.pesto === "boolean") next.pesto = patch.pesto;
  if (typeof patch.consensus === "boolean") next.consensus = patch.consensus;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch {}
  document.dispatchEvent(new CustomEvent("musiq:f0-prefs-changed", { detail: next }));
}
