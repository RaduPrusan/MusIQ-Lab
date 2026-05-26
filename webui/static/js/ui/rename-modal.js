import { el } from "./dom.js";
import { api } from "../api.js";

// Lazy-imported on first ✎ click in the topbar. Single text input + Save/Cancel,
// PATCHes /api/tracks/{slug} with {display_name}. Server splits on " - " and
// updates lyrics meta as a side effect; the onSaved callback receives the
// parsed shape so the caller can update topbar + browser title + lyrics tab
// without an additional GET.
export function showRenameModal({ slug, currentName, onSaved }) {
  const overlay = el("div", { class: "rename-modal-overlay" });
  const panel = el("div", { class: "rename-modal-panel" });

  panel.appendChild(el("h2", { class: "rename-modal-title", text: "Rename track" }));

  const input = el("input", {
    class: "rename-modal-input",
    attrs: { type: "text", value: currentName ?? "", spellcheck: "false", autocomplete: "off" },
  });
  panel.appendChild(input);

  panel.appendChild(el("p", {
    class: "rename-modal-hint",
    text: 'Use "Artist - Title" to populate both fields. Otherwise the whole text becomes the title.',
  }));

  const errorBanner = el("div", { class: "rename-modal-error", style: { display: "none" } });
  panel.appendChild(errorBanner);

  const row = el("div", { class: "rename-modal-actions" });
  const cancelBtn = el("button", {
    class: "btn", attrs: { type: "button" }, text: "Cancel",
    onClick: () => overlay.remove(),
  });
  const saveBtn = el("button", {
    class: "btn primary", attrs: { type: "button" }, text: "Save",
    onClick: () => save(),
  });
  row.appendChild(cancelBtn);
  row.appendChild(saveBtn);
  panel.appendChild(row);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  // Autofocus and select-all so the common case (paste-and-replace) is one motion.
  input.focus();
  input.select();

  const updateSaveEnabled = () => {
    const v = input.value.trim();
    saveBtn.disabled = !v || v === (currentName ?? "").trim();
  };
  updateSaveEnabled();
  input.addEventListener("input", updateSaveEnabled);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); if (!saveBtn.disabled) save(); }
    else if (e.key === "Escape") { e.preventDefault(); overlay.remove(); }
  });

  // Click on the dimmed backdrop closes; clicks on the panel don't bubble.
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  panel.addEventListener("click", (e) => e.stopPropagation());

  async function save() {
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    errorBanner.style.display = "none";
    try {
      const resp = await api.renameTrack(slug, input.value.trim());
      // Close the modal before calling onSaved so a throw in the consumer's
      // callback (e.g. lyrics-tab refresh hook side effects) can't trap the
      // user inside a stuck dialog after a successful save.
      overlay.remove();
      try { onSaved?.(resp); } catch (cbErr) { console.error("rename onSaved failed:", cbErr); }
      return;
    } catch (e) {
      // api.js wraps all 4xx/5xx into Error with .body holding the parsed JSON.
      // Prefer the server's `detail` (validation message) over the raw
      // `<path> -> <status>` string we'd otherwise show.
      errorBanner.textContent = e.body?.detail || e.message || String(e);
      errorBanner.style.display = "block";
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  }
}
