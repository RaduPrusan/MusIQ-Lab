// User-facing preference for the drum-hit lane height (DRUM_LANE_H).
//
// One knob, in CSS pixels: how much vertical space the kick/snare/toms/
// hihat/cymbals strip at the bottom of every track's piano-roll canvas
// occupies. Default 60 (the legacy hard-coded value).
//
// 0 collapses the lane entirely — same effect as a track without
// transcribed drums. Useful for users who don't care about the drum-hit
// visualization and want the extra vertical space for the piano roll.
//
// Persistence + event shape mirror line-width-prefs.js: localStorage is
// the single source of truth; a `musiq:drum-layout-changed` CustomEvent
// on document lets the renderer + overlays subscribe and redraw without
// a reload. Unrecognised storage values fall back to the default, so a
// hand-edited blob can never crash the boot path.

const STORAGE_KEY = "musiq.drumLayout";
const DEFAULT_HEIGHT = 60;
const MIN_HEIGHT = 0;
const MAX_HEIGHT = 160;

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
  return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, Math.round(n)));
}

function emit() {
  document.dispatchEvent(new CustomEvent("musiq:drum-layout-changed", {
    detail: { height: getDrumLaneHeight() },
  }));
}

export function getDrumLaneHeight() {
  return clamp(readStored()?.height, DEFAULT_HEIGHT);
}

export function setDrumLaneHeight(value) {
  const s = readStored() || {};
  s.height = clamp(value, DEFAULT_HEIGHT);
  writeStored(s);
  emit();
}

export const DRUM_LAYOUT_RANGE = {
  min: MIN_HEIGHT,
  max: MAX_HEIGHT,
  step: 2,
  default: DEFAULT_HEIGHT,
};
