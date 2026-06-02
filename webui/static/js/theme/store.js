// webui/static/js/theme/store.js
// localStorage-backed theme store. Mirrors the f0-prefs/notation-prefs
// pattern: STORAGE_KEY + JSON + try/catch + musiq:theme-changed event.

import { PRESETS, DEFAULT_PRESET_ID } from "./presets.js";
import { deriveAccentEmphasis, deriveAccentOn } from "./derive.js";

const STORAGE_KEY = "musiq.theme";
const SCHEMA_VERSION = 1;

const COLOR_KEYS_PREFIX = ["surface-","text-","accent","focus-","status-","stem-","fn-","border-","drum-","chord-","f0-","mic-","picker-","gutter-","vol-","grid-"];
const ALPHA_KEYS_PREFIX = ["alpha-"];
const RADIUS_KEYS_PREFIX = ["radius-", "t-"];   // "t-*" are type-size tokens (px / rem / em); same syntax as radii
const MOTION_KEYS_PREFIX = ["motion-"];

let cache = null;
const subscribers = new Set();

function defaultTheme() {
  return { preset: DEFAULT_PRESET_ID, tokens: { ...PRESETS[DEFAULT_PRESET_ID] }, locks: [] };
}

function isValidColor(v) {
  return typeof v === "string" && /^#[0-9a-fA-F]{3,8}$/.test(v.trim());
}
function isValidAlpha(v) {
  if (typeof v !== "string") return false;
  const n = parseFloat(v);
  return Number.isFinite(n) && n >= 0 && n <= 1;
}
function isValidRadius(v) {
  return typeof v === "string" && /^\d+(?:\.\d+)?(?:px|rem|em)$/.test(v.trim());
}
function isValidMotion(v) {
  return typeof v === "string" && /^\d+(?:\.\d+)?m?s$/.test(v.trim());
}

function categoryOf(name) {
  if (ALPHA_KEYS_PREFIX.some((p) => name.startsWith(p))) return "alpha";
  if (RADIUS_KEYS_PREFIX.some((p) => name.startsWith(p))) return "radius";
  if (MOTION_KEYS_PREFIX.some((p) => name.startsWith(p))) return "motion";
  if (COLOR_KEYS_PREFIX.some((p) => name.startsWith(p))) return "color";
  return null;
}

function validate(name, value) {
  switch (categoryOf(name)) {
    case "color":  return isValidColor(value);
    case "alpha":  return isValidAlpha(value);
    case "radius": return isValidRadius(value);
    case "motion": return isValidMotion(value);
    default:       return false;
  }
}

function readStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultTheme();
    const obj = JSON.parse(raw);
    if (!obj || obj.v !== SCHEMA_VERSION) return defaultTheme();
    if (!obj.tokens || typeof obj.tokens !== "object") return defaultTheme();
    const presetId = (obj.preset === "custom" || PRESETS[obj.preset]) ? obj.preset : DEFAULT_PRESET_ID;
    const baseline = presetId === "custom"
      ? { ...PRESETS[DEFAULT_PRESET_ID] }
      : { ...PRESETS[presetId] };
    const tokens = { ...baseline };
    for (const [k, v] of Object.entries(obj.tokens)) {
      if (validate(k, v)) tokens[k] = v;
    }
    const locks = Array.isArray(obj.locks) ? obj.locks.filter((s) => typeof s === "string") : [];
    const _basePreset = (obj._basePreset && PRESETS[obj._basePreset]) ? obj._basePreset : undefined;
    return { preset: presetId, _basePreset, tokens, locks };
  } catch {
    return defaultTheme();
  }
}

function writeStorage(theme) {
  try {
    const payload = JSON.stringify({
      v: SCHEMA_VERSION,
      preset: theme.preset,
      _basePreset: theme._basePreset,
      tokens: theme.tokens,
      locks: theme.locks,
    });
    localStorage.setItem(STORAGE_KEY, payload);
  } catch (e) {
    console.warn("theme: localStorage write failed", e);
  }
}

function ensureCache() {
  if (cache === null) cache = readStorage();
  return cache;
}

function broadcast() {
  for (const fn of subscribers) {
    try { fn(cache); } catch (e) { console.warn("theme subscriber threw", e); }
  }
  document.dispatchEvent(new CustomEvent("musiq:theme-changed", { detail: cache }));
}

export function getTheme() {
  return ensureCache();
}

export function setPreset(id) {
  if (!PRESETS[id]) return;
  cache = { preset: id, tokens: { ...PRESETS[id] }, locks: [] };
  writeStorage(cache);
  broadcast();
}

export function setToken(name, value) {
  if (!validate(name, value)) return;
  ensureCache();
  // When first going custom, remember which named preset we branched from
  // so resetTokens() can restore it rather than falling to DEFAULT_PRESET_ID.
  const basePreset = cache.preset === "custom" ? cache._basePreset ?? DEFAULT_PRESET_ID : cache.preset;
  const tokens = { ...cache.tokens, [name]: value };
  if (name === "accent") {
    if (!cache.locks.includes("accent-emphasis")) {
      tokens["accent-emphasis"] = deriveAccentEmphasis(value);
    }
    if (!cache.locks.includes("accent-on")) {
      tokens["accent-on"] = deriveAccentOn(value);
    }
  }
  cache = {
    preset: "custom",
    _basePreset: basePreset,
    tokens,
    locks: cache.locks,
  };
  writeStorage(cache);
  broadcast();
}

export function resetTokens() {
  ensureCache();
  const presetId = cache.preset === "custom"
    ? (cache._basePreset ?? DEFAULT_PRESET_ID)
    : cache.preset;
  cache = { preset: presetId, tokens: { ...PRESETS[presetId] }, locks: [] };
  writeStorage(cache);
  broadcast();
}

export function setLock(name, locked) {
  ensureCache();
  const set = new Set(cache.locks);
  if (locked) set.add(name); else set.delete(name);
  cache = { ...cache, locks: [...set] };
  writeStorage(cache);
  broadcast();
}

export function subscribe(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// Test hook only — drops the in-memory cache so tests can simulate a reload.
export function _resetForTests() {
  cache = null;
  subscribers.clear();
}
