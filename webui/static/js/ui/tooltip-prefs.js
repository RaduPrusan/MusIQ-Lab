// User-facing preferences for the canvas hover tooltip.
//
// Two knobs:
//   - showDelayMs: how long the tooltip waits before fading in after the
//     cursor first lands on the canvas (0..500ms). Applied via a CSS custom
//     property `--tooltip-show-delay` so the transition rule in track.css
//     reads it without JS rerunning per frame.
//   - effectsEnabled: whether the hovered note/drum hit reciprocally
//     enlarges to 120% with full opacity. When false, the tooltip still
//     shows but the canvas itself doesn't react — useful for users who find
//     the bobbing motion distracting.
//
// Persistence and event shape mirror notation-prefs.js: localStorage as the
// single source of truth, a `musiq:tooltip-prefs-changed` CustomEvent on
// document so listeners (Inspector, PianoRoll, the Settings panel) update
// without a reload. Unrecognised storage values are ignored, so a
// hand-edited blob can never crash the boot path.

const STORAGE_KEY = "musiq.tooltip";
const DEFAULT_DELAY_MS = 80;
const DEFAULT_EFFECTS  = true;
const MIN_DELAY = 0;
const MAX_DELAY = 500;

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

function emit() {
  document.dispatchEvent(new CustomEvent("musiq:tooltip-prefs-changed", {
    detail: { showDelayMs: getShowDelayMs(), effectsEnabled: getEffectsEnabled() },
  }));
}

export function getShowDelayMs() {
  const s = readStored();
  const v = s?.showDelayMs;
  if (typeof v !== "number" || !Number.isFinite(v)) return DEFAULT_DELAY_MS;
  return Math.min(MAX_DELAY, Math.max(MIN_DELAY, Math.round(v)));
}

export function setShowDelayMs(value) {
  const v = Math.min(MAX_DELAY, Math.max(MIN_DELAY, Math.round(Number(value) || 0)));
  const s = readStored() || {};
  s.showDelayMs = v;
  writeStored(s);
  applyDelayCssVar(v);
  emit();
}

export function getEffectsEnabled() {
  const s = readStored();
  const v = s?.effectsEnabled;
  return typeof v === "boolean" ? v : DEFAULT_EFFECTS;
}

export function setEffectsEnabled(value) {
  const s = readStored() || {};
  s.effectsEnabled = !!value;
  writeStored(s);
  emit();
}

// Push the current delay into the document root as `--tooltip-show-delay`.
// CSS reads it via a `var(--tooltip-show-delay, 0ms)` fallback, so calling
// this on boot makes the very first tooltip honour the persisted delay.
export function applyDelayCssVar(ms) {
  const v = ms != null ? ms : getShowDelayMs();
  document.documentElement.style.setProperty("--tooltip-show-delay", `${v}ms`);
}

// One-call init for main.js: applies the CSS var for the persisted delay.
export function initTooltipPrefs() {
  applyDelayCssVar();
}

export const TOOLTIP_DELAY_RANGE = { min: MIN_DELAY, max: MAX_DELAY, step: 10 };
