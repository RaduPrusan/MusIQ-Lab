// Thin wrapper that exposes the seven pitch-line stroke colours as theme
// tokens, so Settings → Pitch lines → Colours can read/write them through
// the central theme store (webui/static/js/theme/store.js).
//
// Why route through the theme store instead of a standalone localStorage
// blob: the user asked for "all pitch lines colors part of the theme."
// That means a preset switch should rewrite these (the per-preset values
// live in theme/presets.js), and a custom override should ride along on
// the same musiq:theme-changed event the rest of the app already
// listens to. No new init step, no parallel persistence.
//
// Keys are kebab-case prefs IDs that map to the underlying CSS custom
// property names (without the leading `--`):
//
//   mic_in            → mic-in            (matched, ≤100¢)
//   mic_off           → mic-off           (unmatched, >100¢)
//   mic_neutral       → mic-neutral       (matched to stem, stem silent here)
//   mic_no_match      → mic-no-match      (match dropdown = none) + sidebar swatch
//   vocals_consensus  → f0-consensus-stroke
//   vocals_fcpe       → f0-fcpe-stroke
//   vocals_pesto      → f0-pesto-stroke

import { getTheme, setToken } from "../theme/store.js";
import { PRESETS, DEFAULT_PRESET_ID } from "../theme/presets.js";

export const COLOR_TOKEN_MAP = Object.freeze({
  mic_in:           "mic-in",
  mic_off:          "mic-off",
  mic_neutral:      "mic-neutral",
  mic_no_match:     "mic-no-match",
  vocals_consensus: "f0-consensus-stroke",
  vocals_fcpe:      "f0-fcpe-stroke",
  vocals_pesto:     "f0-pesto-stroke",
});

// Hard-coded fallbacks for the picker UI on first paint, before the theme
// has finished applying (or for tokens missing from a hand-edited preset).
const FALLBACK = Object.freeze({
  mic_in:           "#7fdc20",
  mic_off:          "#e7574a",
  mic_neutral:      "#5ab4ff",
  mic_no_match:     "#a48cff",
  vocals_consensus: "#f0f0f0",
  vocals_fcpe:      "#ff00ff",
  vocals_pesto:     "#7eddff",
});

function activePresetId(theme) {
  // When the user has customised tokens, theme.preset becomes "custom" and
  // _basePreset records the preset they branched from. Reset uses that
  // baseline rather than DEFAULT_PRESET_ID so "Reset" feels like "go back
  // to what this theme looked like" instead of "snap to Classic Dark".
  if (theme.preset === "custom") return theme._basePreset || DEFAULT_PRESET_ID;
  return theme.preset;
}

// Effective colour for a key. Read order:
//   1. theme store cache (covers both preset defaults and user overrides)
//   2. computed style (catches tokens defined only in track.css :root)
//   3. hard-coded fallback
export function getColor(key) {
  const tokenName = COLOR_TOKEN_MAP[key];
  if (!tokenName) return FALLBACK[key] || "#000000";
  const theme = getTheme();
  const fromTheme = theme.tokens?.[tokenName];
  if (fromTheme) return fromTheme;
  if (typeof document !== "undefined") {
    const v = getComputedStyle(document.documentElement)
      .getPropertyValue("--" + tokenName)
      .trim();
    if (v) return v;
  }
  return FALLBACK[key];
}

export function setColor(key, hex) {
  const tokenName = COLOR_TOKEN_MAP[key];
  if (!tokenName) return;
  setToken(tokenName, hex);
  // The theme store dispatches musiq:theme-changed + runs applyTheme via
  // main.js's subscriber; overlays subscribed to that event repaint.
}

// Per-key reset: writes the active preset's value for this token. Theme
// store has no per-token reset (resetTokens() wipes ALL custom tokens),
// so this is the closest reasonable behaviour — the swatch snaps back to
// whatever the preset says, without disturbing other custom edits.
export function resetColor(key) {
  const tokenName = COLOR_TOKEN_MAP[key];
  if (!tokenName) return;
  const theme = getTheme();
  const presetId = activePresetId(theme);
  const presetDefault = PRESETS[presetId]?.[tokenName];
  setToken(tokenName, presetDefault || FALLBACK[key]);
}

// No-op kept so main.js's existing boot call sequence doesn't need to
// change. The theme store handles persistence + DOM application on boot
// via the applyTheme(getTheme().tokens) call in main.js.
export function initColorPrefs() { /* no-op — theme store handles boot */ }
