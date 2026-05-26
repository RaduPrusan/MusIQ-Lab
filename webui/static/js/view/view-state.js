const DEFAULTS = {
  zoomH: 100,             // pixels per second
  zoomV: 14,              // pixels per midi semitone
  scrollSec: 0,           // left-edge time in viewport
  highlightedStem: "vocals",
  autoScroll: true,
  scrollAnchor: "edge",   // "edge" | "center"  — auto-scroll anchor mode
  midiCenter: 58,         // Bb3 — midpoint of the default E1..E6 range
  loopStart: null,        // seconds — null when loop disabled
  loopEnd: null,
  // Cursor-driven hover signal — written by Inspector on every mousemove,
  // read by PianoRoll to render the matched note/drum hit at 120% / opacity 1.
  // null when no detected event is under the cursor (or the cursor is over
  // empty grid). Shape: { kind: "note"|"drum", stem: string, idx: number }.
  hoveredEvent: null,
};

export function createViewState(overrides = {}) {
  const state = { ...DEFAULTS, ...overrides };
  const subs = new Map();   // event → Set<handler>

  function emit(event, payload) {
    const set = subs.get(event);
    if (!set) return;
    for (const h of set) h(payload);
  }

  return new Proxy(state, {
    set(target, key, value) {
      if (key === "_internal") { target[key] = value; return true; }
      if (target[key] === value) return true;
      target[key] = value;
      emit("change", { changed: [key], state: { ...target } });
      return true;
    },
    get(target, key) {
      if (key === "on") return (event, fn) => {
        if (!subs.has(event)) subs.set(event, new Set());
        subs.get(event).add(fn);
      };
      if (key === "off") return (event, fn) => subs.get(event)?.delete(fn);
      if (key === "update") return (patch) => {
        const changed = [];
        for (const [k, v] of Object.entries(patch)) {
          if (target[k] !== v) { target[k] = v; changed.push(k); }
        }
        if (changed.length) emit("change", { changed, state: { ...target } });
      };
      if (key === "snapshot") return () => ({ ...target });
      if (key === "setLoop") return (start, end) => {
        // Atomic: don't fire two "change" events for what is conceptually one update.
        const changed = [];
        if (target.loopStart !== start) { target.loopStart = start; changed.push("loopStart"); }
        if (target.loopEnd !== end) { target.loopEnd = end; changed.push("loopEnd"); }
        if (changed.length) emit("change", { changed, state: { ...target } });
      };
      if (key === "clearLoop") return () => {
        const changed = [];
        if (target.loopStart !== null) { target.loopStart = null; changed.push("loopStart"); }
        if (target.loopEnd !== null) { target.loopEnd = null; changed.push("loopEnd"); }
        if (changed.length) emit("change", { changed, state: { ...target } });
      };
      // Fire a one-shot "glide" event so the auto-scroll handler in main.js
      // switches from snap-tracking to smooth lerp until the playhead lands
      // back at its anchor position. Used after anchor toggles + scrub-bar
      // releases where we know the next frame will have a large delta.
      if (key === "triggerGlide") return () => emit("glide", {});
      return target[key];
    },
  });
}
