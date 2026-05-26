/**
 * Factory that chooses the right AudioEngine implementation based on the
 * user's persisted preference in localStorage["musiq.audio"].
 *
 * Phase 2 contract: WebAudio is the default; WASAPI is selected via the
 * Settings → Audio engine radio. The radio handler in menus.js calls
 * `window.__musiqEngineRebuild()` (installed by main.js) to swap the
 * active engine mid-track without a page reload. We keep this factory
 * pure (no engine cache) and let main.js own the lifecycle — the
 * rebuild hook is the cleanest seam for a one-time mid-session swap
 * without dragging a subscription registry into the factory.
 */
import { WebAudioEngine } from "./web-audio-engine.js";
import { WasapiEngine } from "./wasapi-engine.js";

const STORAGE_KEY = "musiq.audio";

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    return (obj && typeof obj === "object") ? obj : null;
  } catch {
    return null;
  }
}

export function getStoredEngineChoice() {
  const stored = readStored();
  return stored?.engine === "wasapi" ? "wasapi" : "webaudio";
}

export function createAudioEngine() {
  // Default: WebAudio. If the user has explicitly flipped the radio to
  // WASAPI, return WasapiEngine — but note that in Phase 1 every playback
  // method on WasapiEngine throws, so callers that try to load() / play()
  // will surface the "Phase 1 stub" error. The Settings UI is responsible
  // for warning the user when they make this selection.
  const choice = getStoredEngineChoice();
  if (choice === "wasapi") return new WasapiEngine();
  return new WebAudioEngine();
}
