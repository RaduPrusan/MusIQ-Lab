// Per-slug cross-check toggle state for tempo + key.
//
// When essentia_agreement reports a disagreement, the user can choose to view
// the track under either the analyze pipeline's value (default) or Essentia's
// second opinion. The choice is per-slug and per-browser (localStorage), and
// is broadcast via a CustomEvent("musiq:xcheck-changed") so every renderer
// that reads tempo / key (top-bar, sidebar Now-playing, harmony stats,
// chord roman+function overlays) can react.
//
// Storage shape (localStorage key `musiq.xcheck.<slug>`):
//   { "bpm": "analyze" | "essentia", "key": "analyze" | "essentia" }
//
// Missing slot defaults to "analyze". A missing localStorage entry defaults
// to {bpm:"analyze", key:"analyze"} — the unchanged-from-current-behavior path.
// Storing an empty object after a reset is supported but normally we just
// removeItem so the disk doesn't accumulate noise from every browsed track.

const STORAGE_PREFIX = "musiq.xcheck.";
const EVENT_NAME = "musiq:xcheck-changed";
const VALID_VALUES = new Set(["analyze", "essentia"]);

const DEFAULT_STATE = Object.freeze({ bpm: "analyze", key: "analyze" });

function _key(slug) {
  return `${STORAGE_PREFIX}${slug}`;
}

function _readRaw(slug) {
  try {
    const raw = localStorage.getItem(_key(slug));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    // Corrupt JSON (manual edit?) — treat as missing rather than crashing
    // every renderer that consults the toggle.
    return null;
  }
}

export function getXcheck(slug) {
  const raw = _readRaw(slug) || {};
  return {
    bpm: VALID_VALUES.has(raw.bpm) ? raw.bpm : DEFAULT_STATE.bpm,
    key: VALID_VALUES.has(raw.key) ? raw.key : DEFAULT_STATE.key,
  };
}

// Partial update; merges with current state. Pass field=null to reset that
// slot back to the default ("analyze"). Dispatches musiq:xcheck-changed on
// every write so subscribers re-render — *even* when the value didn't change,
// so a UI that wants to force a refresh can re-apply the same state.
export function setXcheck(slug, partial) {
  const current = getXcheck(slug);
  const next = { ...current };
  for (const field of ["bpm", "key"]) {
    if (!(field in partial)) continue;
    const v = partial[field];
    if (v === null || v === undefined) {
      next[field] = DEFAULT_STATE[field];
    } else if (VALID_VALUES.has(v)) {
      next[field] = v;
    }
    // Silently ignore invalid values — defensive against typos in callers.
  }
  // Only persist when the state diverges from defaults — keeps localStorage
  // clean for the common case where the user never touches the toggles.
  if (next.bpm === DEFAULT_STATE.bpm && next.key === DEFAULT_STATE.key) {
    try { localStorage.removeItem(_key(slug)); } catch { /* quota errors etc. */ }
  } else {
    try { localStorage.setItem(_key(slug), JSON.stringify(next)); } catch { /* ignore */ }
  }
  _broadcast(slug, next);
  return next;
}

function _broadcast(slug, state) {
  // The event payload carries the slug + the resolved state so subscribers
  // can ignore notifications for other tracks (the same browser can have
  // multiple tabs open on different slugs in principle, though current usage
  // doesn't lean on that).
  if (typeof document === "undefined" || typeof CustomEvent === "undefined") return;
  document.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { slug, state } }));
}

// Subscribe to cross-check changes. Returns an unsubscriber. Handler receives
// the event detail `{slug, state}`. Use the slug filter inside your handler
// if you only care about the current track.
export function onXcheckChanged(handler) {
  if (typeof document === "undefined") return () => {};
  const wrapped = (ev) => handler(ev.detail);
  document.addEventListener(EVENT_NAME, wrapped);
  return () => document.removeEventListener(EVENT_NAME, wrapped);
}

// Convenience: which BPM should be displayed right now, given a trackData?
// Returns null when there's no essentia_agreement.bpm (no toggle available).
export function activeBpm(trackData) {
  const xc = trackData?.meta?.slug ? getXcheck(trackData.meta.slug) : DEFAULT_STATE;
  const agreement = trackData?.essentiaAgreement?.bpm;
  if (!agreement) {
    // No cross-check available — fall back to pipeline value.
    return typeof trackData?.meta?.tempoBpm === "number" ? trackData.meta.tempoBpm : null;
  }
  return xc.bpm === "essentia" ? agreement.essentia : agreement.analyze;
}

// Convenience: which key string should be displayed right now, given a
// trackData? Returns the string in the form each side natively emits —
// pipeline gives "F Major", Essentia consensus gives "Bb:major". Callers
// that render the key should run it through the project's notation
// helpers (reformatRootedName) regardless of source.
export function activeKey(trackData) {
  const xc = trackData?.meta?.slug ? getXcheck(trackData.meta.slug) : DEFAULT_STATE;
  const agreement = trackData?.essentiaAgreement?.key;
  if (!agreement) {
    return trackData?.meta?.key ?? null;
  }
  return xc.key === "essentia" ? agreement.essentia_consensus : agreement.analyze;
}

// Convenience: which chord annotations (roman + function) should be applied
// right now? Returns null when the user picked "analyze" (use the canonical
// chord.roman / chord.function fields directly). Returns the parallel
// annotations array from summary.chords_alt_key when "essentia" is active
// and the alt-key block exists. Length matches trackData.chords.
export function activeChordAnnotations(trackData) {
  const xc = trackData?.meta?.slug ? getXcheck(trackData.meta.slug) : DEFAULT_STATE;
  if (xc.key !== "essentia") return null;
  const altKey = trackData?.chordsAltKey;
  if (!altKey || !Array.isArray(altKey.annotations)) return null;
  return altKey.annotations;
}

// Return a *view* of the trackData with key-dependent fields overridden when
// the user has toggled the Key cross-check to Essentia AND a chords_alt_key
// block is available. Otherwise returns the input unchanged. The view is a
// plain object (not frozen) so consumers can store/replace it without
// fighting the original Object.freeze() in track-data.js.
//
// Fields overridden when active:
//   - meta.key, meta.scale (top-bar Key + scale tracking goes server-side
//     via alt_key.key / .scale)
//   - chords[i].roman, chords[i].fn (from chordsAltKey.annotations[i])
//   - loopRoman (from chordsAltKey.loop_roman)
//   - modalInterchange (from chordsAltKey.modal_interchange_count)
//
// Note: BPM is intentionally NOT swapped here — beat positions, drum-grid
// tightness, and downbeats are key-independent AND were computed at the
// original pipeline BPM. The top-bar BPM display reads activeBpm() directly,
// no view rebuild needed.
export function effectiveTrackData(trackData) {
  if (!trackData || !trackData.meta?.slug) return trackData;
  const xc = getXcheck(trackData.meta.slug);
  if (xc.key !== "essentia") return trackData;
  const alt = trackData.chordsAltKey;
  if (!alt || !Array.isArray(alt.annotations)) return trackData;

  const annotations = alt.annotations;
  // Splice per-chord roman + fn. Out-of-bounds annotations fall back to the
  // original chord (defensive — server emits parallel arrays so length match
  // is expected, but a corrupt summary shouldn't crash the renderer).
  const chords = trackData.chords.map((c, i) => {
    const a = annotations[i];
    if (!a) return c;
    return { ...c, roman: a.roman, fn: a.function };
  });

  return {
    ...trackData,
    meta: { ...trackData.meta, key: alt.key, scale: alt.scale },
    chords,
    loopRoman: Array.isArray(alt.loop_roman) ? alt.loop_roman : trackData.loopRoman,
    modalInterchange: typeof alt.modal_interchange_count === "number"
      ? alt.modal_interchange_count
      : trackData.modalInterchange,
  };
}

// Test seam — internal-only. Tests use this to clear localStorage between
// cases without poking the storage API directly.
export function _resetForTesting(slug) {
  if (slug) {
    try { localStorage.removeItem(_key(slug)); } catch { /* no-op */ }
  }
}

export const _internals = { STORAGE_PREFIX, EVENT_NAME, DEFAULT_STATE };
