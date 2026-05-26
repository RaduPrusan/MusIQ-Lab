import { el } from "./dom.js";
import { addCloseButton } from "./menus.js";

export const KEYMAP = [
  { keys: ["Space"],                act: "togglePlay",   help: "play / pause" },
  { keys: ["ArrowLeft"],            act: "nudgeBack",    help: "nudge by beat (Shift = bar)" },
  { keys: ["ArrowRight"],           act: "nudgeFwd",     help: "nudge by beat (Shift = bar)" },
  { keys: ["Home"],                 act: "seekStart",    help: "seek to 0" },
  { keys: ["End"],                  act: "seekEnd",      help: "seek to end" },
  { keys: ["Equal", "NumpadAdd"],   act: "zoomHIn",      help: "zoom-H step" },
  { keys: ["Minus", "NumpadSubtract"], act: "zoomHOut",  help: "zoom-H step" },
  { keys: ["Digit0", "Numpad0"],    act: "resetView",    help: "reset zoom and scroll" },
  { keys: ["KeyM"],                 act: "muteHi",       help: "mute the highlighted stem" },
  { keys: ["KeyS"],                 act: "soloHi",       help: "solo the highlighted stem" },
  { keys: ["Digit1"],               act: "hi:vocals",    help: "highlight Vocals" },
  { keys: ["Digit2"],               act: "hi:bass",      help: "highlight Bass" },
  { keys: ["Digit3"],               act: "hi:guitar",    help: "highlight Guitar" },
  { keys: ["Digit4"],               act: "hi:piano",     help: "highlight Piano" },
  { keys: ["Digit5"],               act: "hi:other",     help: "highlight Other" },
  { keys: ["Digit6"],               act: "hi:drums",     help: "highlight Drums" },
  { keys: ["KeyL"],                 act: "openPicker",   help: "open track picker" },
  { keys: ["Slash"],                act: "openHelp",     shift: true, help: "shortcuts modal (?)" },
  { keys: ["Escape"],               act: "closeAny",     help: "close any open dropdown / modal" },
];

export function dispatchKey(e, handlers) {
  for (const entry of KEYMAP) {
    if (!entry.keys.includes(e.code)) continue;
    if (entry.shift && !e.shiftKey) continue;
    const fn = handlers[entry.act];
    if (typeof fn === "function") {
      e.preventDefault();
      fn(e);
      return entry.act;
    }
  }
  return null;
}

export function showShortcutsModal() {
  const overlay = el("div", {
    style: { position: "fixed", inset: 0, background: `rgb(0 0 0 / var(--alpha-scrim))`, zIndex: 100,
             display: "flex", alignItems: "center", justifyContent: "center" },
    onClick: () => overlay.remove(),
  });
  const panel = el("div", {
    style: { background: "var(--surface-1)", border: "1px solid var(--surface-3)", borderRadius: "8px",
             padding: "20px 24px", maxWidth: "520px", width: "92%", maxHeight: "80vh", overflowY: "auto",
             position: "relative" },
    onClick: (e) => e.stopPropagation(),
  });
  panel.appendChild(el("h2", { style: { margin: "0 0 16px 0", fontSize: "16px", color: "white" }, text: "Keyboard shortcuts" }));
  const table = el("div", { style: { display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px", fontSize: "12px", color: "var(--text-secondary)" } });
  for (const entry of KEYMAP) {
    const label = (entry.shift ? "Shift+" : "") + entry.keys.map(humanizeCode).join(" / ");
    table.appendChild(el("div", { style: { color: "white", fontFamily: "ui-monospace, monospace" }, text: label }));
    table.appendChild(el("div", { text: entry.help }));
  }
  panel.appendChild(table);
  addCloseButton(panel, () => overlay.remove());
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  return overlay;
}

function humanizeCode(code) {
  return code
    .replace(/^Key/, "")
    .replace(/^Digit/, "")
    .replace(/^Numpad/, "Num")
    .replace("ArrowLeft", "←").replace("ArrowRight", "→")
    .replace("Equal", "+").replace("Minus", "−")
    .replace("Slash", "/");
}
