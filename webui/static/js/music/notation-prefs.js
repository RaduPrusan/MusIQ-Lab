// User-facing preference: which notation system to display pitch names in.
// Persisted in localStorage; emits a "musiq:notation-changed" CustomEvent on
// document so the canvas (and any other listeners) can re-render lazily.

const STORAGE_KEY = "musiq.notation";
const VALID = new Set(["scientific", "solfege"]);
const DEFAULT = "scientific";

export function getNotationSystem() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return VALID.has(v) ? v : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

export function setNotationSystem(value) {
  if (!VALID.has(value)) return;
  try { localStorage.setItem(STORAGE_KEY, value); } catch {}
  document.dispatchEvent(new CustomEvent("musiq:notation-changed", { detail: { value } }));
}

export const NOTATION_SYSTEMS = [
  { id: "scientific", label: "Scientific (C, C#, D, …)" },
  { id: "solfege",    label: "Solfège (Do, Do#, Re, …)" },
];
