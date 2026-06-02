import { el } from "./dom.js";
import { showReanalyzeModal } from "./reanalyze.js";
import { showToast } from "./toast.js";
import { getNotationSystem, setNotationSystem, NOTATION_SYSTEMS } from "../music/notation-prefs.js";
import {
  getShowDelayMs, setShowDelayMs,
  getEffectsEnabled, setEffectsEnabled,
  TOOLTIP_DELAY_RANGE,
} from "./tooltip-prefs.js";
import {
  getMicLineWidth, setMicLineWidth,
  getVocalsLineWidth, setVocalsLineWidth,
  LINE_WIDTH_RANGE,
} from "./line-width-prefs.js";
import {
  getDrumLaneHeight,
  setDrumLaneHeight,
  DRUM_LAYOUT_RANGE,
} from "./drum-layout-prefs.js";
import {
  getColor, setColor, resetColor,
} from "./color-prefs.js";
import { PRESETS, PRESET_IDS, PRESET_LABELS } from "../theme/presets.js";
import { getTheme, setPreset, setToken, resetTokens, setLock } from "../theme/store.js";
import { deriveAccentOn, deriveAccentEmphasis } from "../theme/derive.js";
import { getStoredEngineChoice } from "../audio/engine-factory.js";
import { WasapiEngine } from "../audio/wasapi-engine.js";
import { buildDevicePicker } from "../audio/device-picker.js";

// Tools-menu side-effect endpoints (open MIDI, reveal cache) return no body
// and are fire-and-forget. Non-2xx responses were previously silent — now
// they raise a toast so the user knows the request failed.
async function postSideEffect(url, label) {
  try {
    const r = await fetch(url, { method: "POST" });
    if (!r.ok) {
      showToast("error", `${label} failed (${r.status})`);
    }
  } catch (err) {
    showToast("error", `${label} failed: ${err?.message || "network error"}`);
  }
}

// Adds a top-right × close affordance to a modal panel. The panel must be
// positioned (relative/absolute/fixed) so the absolutely-positioned button
// anchors inside it. `onClose` is invoked on click; typically removes the
// overlay. Exported so other modal builders (e.g. shortcuts.js) can reuse it.
export function addCloseButton(panel, onClose) {
  const btn = document.createElement("button");
  btn.className = "modal-close";
  btn.setAttribute("aria-label", "Close");
  btn.textContent = "×";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    onClose();
  });
  panel.appendChild(btn);
  return btn;
}

/**
 * Settings → Audio engine radio group + Phase 1 device-picker stub.
 *
 * Returns an array of DOM nodes appended below the "Audio engine" heading.
 * Switching to WASAPI inserts the device picker; switching back to WebAudio
 * removes it. **Phase 1 does NOT swap the currently-running engine
 * instance** — that's Phase 2's job; the radio just persists the choice for
 * the next page load and surfaces a "pending implementation" hint.
 */
function buildEngineRadioGroup() {
  const initial = getStoredEngineChoice();
  const pickerHost = el("div", { style: { marginTop: "6px" } });
  let pickerEngine = null;  // lazily-created WasapiEngine, only while picker is mounted

  function syncPicker(choice) {
    // Tear down any previous picker / WasapiEngine to avoid leaking sockets.
    while (pickerHost.firstChild) pickerHost.removeChild(pickerHost.firstChild);
    if (pickerEngine) {
      try { pickerEngine.dispose(); } catch { /* noop */ }
      pickerEngine = null;
    }
    if (choice !== "wasapi") return;
    pickerEngine = new WasapiEngine();
    pickerHost.appendChild(buildDevicePicker(pickerEngine));
  }

  function persistChoice(choice) {
    try {
      const raw = localStorage.getItem("musiq.audio");
      const prev = raw ? JSON.parse(raw) : {};
      const next = { ...(prev && typeof prev === "object" ? prev : {}), engine: choice };
      localStorage.setItem("musiq.audio", JSON.stringify(next));
    } catch { /* localStorage disabled — ignore */ }
  }

  // Trigger main.js to dispose the current engine + re-mount the page
  // against the newly-chosen engine. The hook is installed on the window
  // by main.js; if it's missing (e.g. running on a page that doesn't
  // boot main.js), we fall back to a hard reload which achieves the
  // same end state.
  function rebuildEngine() {
    if (typeof window.__musiqEngineRebuild === "function") {
      window.__musiqEngineRebuild();
    } else {
      location.reload();
    }
  }

  const webaudioRadio = el("input", {
    type: "radio",
    attrs: { name: "engine", value: "webaudio", ...(initial === "webaudio" ? { checked: "checked" } : {}) },
    onChange: (e) => {
      if (!e.target.checked) return;
      persistChoice("webaudio");
      syncPicker("webaudio");
      rebuildEngine();
    },
  });
  const wasapiRadio = el("input", {
    type: "radio",
    attrs: { name: "engine", value: "wasapi", ...(initial === "wasapi" ? { checked: "checked" } : {}) },
    onChange: (e) => {
      if (!e.target.checked) return;
      persistChoice("wasapi");
      syncPicker("wasapi");
      rebuildEngine();
    },
  });

  const rows = [
    el("label", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [
      webaudioRadio,
      document.createTextNode("WebAudio (default)"),
    ]),
    el("label", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [
      wasapiRadio,
      document.createTextNode("WASAPI Shared (pick a device below)"),
    ]),
    pickerHost,
  ];

  // Mount picker if WASAPI was already the persisted choice.
  syncPicker(initial);

  return rows;
}


function buildAppearanceSection() {
  const root = el("div");
  const heading = el("h3", {
    style: {
      fontSize: "11px", textTransform: "uppercase",
      color: "var(--text-muted)", margin: "16px 0 8px",
      letterSpacing: "var(--ls-caps)",
    },
    text: "Appearance",
  });
  root.appendChild(heading);

  const presetRow = el("div", {
    style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "8px", marginBottom: "12px" },
  });
  for (const id of PRESET_IDS) {
    const card = el("div", {
      style: {
        border: "1px solid var(--border-strong)", borderRadius: "var(--radius-3)",
        padding: "8px 10px", cursor: "pointer", display: "flex", flexDirection: "column", gap: "6px",
        background: "var(--surface-2)", transition: "border-color var(--motion-fast)",
      },
      onClick: () => {
        setPreset(id);
        rebuild();
      },
    });
    if (getTheme().preset === id) {
      card.style.borderColor = "var(--accent)";
    }
    const label = el("div", { text: PRESET_LABELS[id], style: { fontSize: "12px", color: "var(--text-primary)" } });
    const swatchRow = el("div", { style: { display: "flex", gap: "3px" } });
    for (const t of ["surface-base","surface-2","accent","stem-vocals","stem-bass","status-error"]) {
      swatchRow.appendChild(el("div", {
        style: {
          width: "16px", height: "12px", borderRadius: "2px",
          background: PRESETS[id][t],
          border: "1px solid var(--border-soft)",
        },
      }));
    }
    card.appendChild(label);
    card.appendChild(swatchRow);
    presetRow.appendChild(card);
  }
  root.appendChild(presetRow);

  // Tooltip subsection — show-delay slider + hover-effects toggle. Lives
  // here (between presets and the Customize tokens panel) because the two
  // prefs are user-experience knobs rather than theme tokens, and surfacing
  // them at the top of Appearance keeps them discoverable.
  root.appendChild(buildTooltipSubsection());

  // Customize panel — surfaced expanded by default so the densest section
  // of Appearance reads at a glance instead of hiding behind a toggle.
  // The toggle itself is preserved so users can collapse it.
  const customizeBtn = el("button", {
    style: {
      background: "transparent", border: "1px solid var(--border-strong)",
      color: "var(--text-secondary)", fontSize: "11px", borderRadius: "var(--radius-2)",
      padding: "4px 10px", cursor: "pointer",
    },
    text: "▾ Customize",
  });
  const customizePanel = el("div", { style: { display: "block", marginTop: "8px" } });
  buildCustomizePanel(customizePanel, rebuild);
  customizePanel.dataset.built = "1";
  let isOpen = true;
  customizeBtn.addEventListener("click", () => {
    isOpen = !isOpen;
    customizeBtn.textContent = isOpen ? "▾ Customize" : "▸ Customize";
    customizePanel.style.display = isOpen ? "block" : "none";
  });
  root.appendChild(customizeBtn);
  root.appendChild(customizePanel);

  function rebuild() {
    const next = buildAppearanceSection();
    root.replaceWith(next);
  }

  return root;
}

// "Tooltip" subsection in Appearance — show-delay slider + hover-effects
// toggle. Section header matches the Customize sections (uppercase 10px
// label + "?" help button) so the visual rhythm is consistent. Mutating
// the prefs here updates --tooltip-show-delay (via setShowDelayMs) and
// fires musiq:tooltip-prefs-changed; the canvas reads getEffectsEnabled
// at picking time, so changes take effect on the next mousemove.
function buildTooltipSubsection() {
  const wrap = el("div", {
    class: "tooltip-prefs",
    style: {
      margin: "12px 0 0 0",
      paddingTop: "10px",
      borderTop: "1px solid var(--border-soft)",
    },
  });
  const header = el("div", {
    style: { display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" },
  });
  header.appendChild(el("div", {
    text: "Tooltip",
    style: {
      fontSize: "10px", color: "var(--text-muted)",
      letterSpacing: "var(--ls-caps)", textTransform: "uppercase",
    },
  }));
  header.appendChild(el("button", {
    type: "button",
    text: "?",
    attrs: {
      title: "Hover-tooltip behaviour: how long it waits before fading in, and whether the hovered note enlarges to 120% with full opacity.",
      "aria-label": "Tooltip help",
    },
    style: {
      background: "transparent", border: "1px solid var(--border-soft)",
      color: "var(--text-muted)", borderRadius: "9999px",
      width: "14px", height: "14px", padding: "0",
      fontSize: "10px", lineHeight: "1", cursor: "help",
      display: "inline-flex", alignItems: "center", justifyContent: "center",
    },
  }));
  wrap.appendChild(header);

  // Row 1: show-delay slider.
  const delayRow = el("label", {
    style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-secondary)", marginBottom: "6px" },
  });
  delayRow.appendChild(document.createTextNode("Show delay"));
  const slider = el("input", {
    class: "tooltip-delay",
    type: "range",
    attrs: {
      min: String(TOOLTIP_DELAY_RANGE.min),
      max: String(TOOLTIP_DELAY_RANGE.max),
      step: String(TOOLTIP_DELAY_RANGE.step),
    },
    style: { flex: "1", maxWidth: "180px" },
  });
  slider.value = String(getShowDelayMs());
  const valueLabel = el("span", {
    style: { fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)", minWidth: "44px", textAlign: "right" },
    text: `${slider.value}ms`,
  });
  slider.addEventListener("input", () => {
    setShowDelayMs(slider.value);
    valueLabel.textContent = `${slider.value}ms`;
  });
  delayRow.appendChild(slider);
  delayRow.appendChild(valueLabel);
  wrap.appendChild(delayRow);

  // Row 2: effects checkbox.
  const effectsRow = el("label", {
    style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-secondary)" },
  });
  const cb = el("input", {
    class: "tooltip-effects",
    type: "checkbox",
    style: { margin: "0" },
  });
  cb.checked = getEffectsEnabled();
  cb.addEventListener("change", () => setEffectsEnabled(cb.checked));
  effectsRow.appendChild(cb);
  effectsRow.appendChild(document.createTextNode("Hover effects (enlarge note to 120%, pop-in)"));
  wrap.appendChild(effectsRow);

  return wrap;
}

function buildCustomizePanel(host, rebuild) {
  // Sectioned layout. Each section: header bar (title + "?" help button)
  // + a 2-column grid of pickers/sliders. Sections are separated by a
  // 12px top margin and a thin top border so they read as distinct groups.
  // Token taxonomy mirrors presets.js — keep this in sync if presets grow.
  const SECTIONS = [
    {
      title: "Surfaces",
      help: "Background panels in elevation order. Base is the page; surface-1 is sidebar; surface-2 is cards; surface-3 is hovered chrome. Selected/hover variants apply to picker rows.",
      kind: "color",
      tokens: ["surface-base","surface-1","surface-2","surface-3","surface-selected","surface-hover","surface-hover-2","surface-pill-hover","picker-divider"],
    },
    {
      title: "Borders",
      help: "Container outlines: soft for surface-1 dividers, strong for elevated chrome and buttons.",
      kind: "color",
      tokens: ["border-soft","border-strong"],
    },
    {
      title: "Text",
      help: "Foreground text in tier order: primary headings → secondary body → muted labels → disabled placeholders. Each tier should clear 4.5:1 contrast against its surface.",
      kind: "color",
      tokens: ["text-primary","text-secondary","text-muted","text-disabled"],
    },
    {
      title: "Accent",
      help: "Brand accent for active controls and the play-band marker. Emphasis is the hover state; accent-on is text painted on accent fills (auto-derived per preset). Focus-ring is the keyboard-nav outline.",
      kind: "color",
      tokens: ["accent","accent-emphasis","accent-on","focus-ring"],
    },
    {
      title: "Status",
      help: "Semantic colors for errors, warnings, success, info. Error-emphasis is the destructive-button fill; status dots indicate per-stem load state in the track row.",
      kind: "color",
      tokens: ["status-error","status-error-bg","status-warning","status-success","status-info","status-dot-loaded","status-dot-missing","error-emphasis-bg","error-emphasis-bd"],
    },
    {
      title: "Stems (full)",
      help: "Per-stem note colors on the piano roll. Drums shows aggregate hits; pick distinct hues so stems read clearly when overlapping.",
      kind: "color",
      tokens: ["stem-vocals","stem-piano","stem-other","stem-guitar","stem-bass","stem-drums"],
    },
    {
      title: "Drum pieces",
      help: "Per-piece colors painted on the drum lane. These dots are small; favor saturated, high-contrast hues.",
      kind: "color",
      tokens: ["drum-kick","drum-snare","drum-toms","drum-hihat","drum-cymbals"],
    },
    {
      title: "Piano roll",
      help: "Canvas backgrounds: chord strip when no harmonic function is detected, no-chord cells, and the drum lane backdrop.",
      kind: "color",
      tokens: ["chord-default-bg","chord-no-bg","drum-lane-bg"],
    },
    {
      title: "Grid lines",
      help: "The piano-roll grid, configurable as one unit. Grid-line is the color of the bar, beat, and octave lines (distinct from text color; defaults to it). The three opacities set how prominent each line type is: bar = downbeats, beat = sub-beats, line = horizontal octave rows.",
      kind: "color",
      tokens: ["grid-line", { name: "alpha-grid-bar", kind: "alpha" }, { name: "alpha-grid-beat", kind: "alpha" }, { name: "alpha-grid-line", kind: "alpha" }],
    },
    {
      title: "Function colors",
      help: "Color-coded chord-strip cells by harmonic function: tonic / predominant / dominant / modal-interchange. Each pair is a soft fill plus a saturated label color. Fn-on is text painted on the fn-bar segments.",
      kind: "color",
      tokens: ["fn-tonic-bg","fn-tonic-fg","fn-dominant-bg","fn-dominant-fg","fn-modal-bg","fn-modal-fg","fn-predominant-bg","fn-predominant-fg","fn-on"],
    },
    {
      title: "Keyboard gutter",
      help: "The piano-key column on the left of the roll. Black keys (sharps/flats) get a darker tone. White-key and black-key label colors are tunable on their own; the C row (absolute Do) and the song's detected tonic override both with tinted accents (neon green / hot pink by default) so they're easy to find at a glance.",
      kind: "color",
      tokens: ["gutter-bg","gutter-row-bg","gutter-row-black-bg","gutter-row-fg","gutter-row-black-fg","gutter-row-octave-fg","gutter-row-tonic-fg"],
    },
    {
      title: "F0 overlay",
      help: "Vocal pitch contour strokes painted on the canvas. Consensus is the smoothed Viterbi line; FCPE and PESTO are the raw per-frame estimators (each shown when its bucket is enabled). FCPE defaults to magenta so it's easy to tell apart from the cool-toned PESTO line.",
      kind: "color",
      tokens: ["f0-consensus-stroke","f0-fcpe-stroke","f0-pesto-stroke"],
    },
    {
      title: "Soft tags",
      help: "Pale tinted bg/fg pairs for chips, badges, and tags. Each pair must clear 4.5:1 contrast (WCAG AA).",
      kind: "color",
      tokens: ["accent-soft-bg","accent-soft-fg","success-soft-bg","success-soft-fg","info-soft-bg","info-soft-fg","warn-soft-bg","warn-soft-fg","modal-soft-bg","modal-soft-fg"],
    },
    {
      title: "Transparencies",
      help: "Per-element opacity 0–1. Lower values are subtler, higher are more visible. Bar-number is text opacity above the canvas grid. (Grid-line opacities live in the Grid lines group.)",
      kind: "alpha",
      tokens: ["alpha-scrim","alpha-overlay-soft","alpha-overlay-med","alpha-overlay-strong","alpha-glow-soft","alpha-glow-strong","alpha-stem-fill","alpha-loop-band-fill","alpha-loop-band-stroke","alpha-play-band-fill","alpha-play-band-stroke","alpha-bar-number"],
    },
    {
      title: "Sizing",
      help: "Corner radii for buttons, chips, and panels in tier order. Pill is fully rounded (used for badges).",
      kind: "size",
      tokens: ["radius-1","radius-2","radius-3","radius-4","radius-pill"],
      sizeOpts: { min: 0, max: 20, step: 1 },
    },
    {
      title: "Motion",
      help: "Animation durations. Fast is for hovers, medium for state changes, slow for modal transitions. Set all to 0s for reduced motion.",
      kind: "motion",
      tokens: ["motion-fast","motion-medium","motion-slow"],
    },
    {
      title: "Typography",
      help: "Text-size tiers used by most UI elements: micro (small labels), body (default UI), prose (long-form text), display (chord and key readouts).",
      kind: "size",
      tokens: ["t-micro","t-body","t-prose","t-display"],
      sizeOpts: { min: 8, max: 28, step: 1 },
    },
  ];

  let isFirstSection = true;
  for (const sec of SECTIONS) {
    const wrap = el("div", {
      style: {
        margin: isFirstSection ? "4px 0 0 0" : "12px 0 0 0",
        paddingTop: isFirstSection ? "0" : "10px",
        borderTop: isFirstSection ? "none" : "1px solid var(--border-soft)",
      },
    });
    isFirstSection = false;

    // Section header bar: title + "?" help button.
    const header = el("div", {
      style: { display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" },
    });
    header.appendChild(el("div", {
      text: sec.title,
      style: {
        fontSize: "10px", color: "var(--text-muted)",
        letterSpacing: "var(--ls-caps)", textTransform: "uppercase",
      },
    }));
    const helpBtn = el("button", {
      type: "button",
      text: "?",
      attrs: { title: sec.help, "aria-label": `${sec.title}: ${sec.help}` },
      style: {
        background: "transparent", border: "1px solid var(--border-soft)",
        color: "var(--text-muted)", borderRadius: "9999px",
        width: "14px", height: "14px", padding: "0",
        fontSize: "10px", lineHeight: "1", cursor: "help",
        display: "inline-flex", alignItems: "center", justifyContent: "center",
      },
    });
    header.appendChild(helpBtn);
    wrap.appendChild(header);

    const grid = el("div", {
      style: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: "6px 16px" },
    });
    for (const t of sec.tokens) {
      // A token entry is either a bare name (uses the section's kind) or an
      // {name, kind} object so a single section can mix kinds (e.g. the Grid
      // lines group pairs a color with its opacity sliders).
      const name = typeof t === "string" ? t : t.name;
      const kind = typeof t === "string" ? sec.kind : (t.kind || sec.kind);
      let row;
      if (kind === "color")       row = buildColorRow(name);
      else if (kind === "alpha")  row = buildAlphaRow(name);
      else if (kind === "size")   row = buildSizeRow(name, sec.sizeOpts || {});
      else if (kind === "motion") row = buildMotionRow(name);
      if (row) grid.appendChild(row);
    }
    wrap.appendChild(grid);
    host.appendChild(wrap);
  }

  // Footer
  const footer = el("div", { style: { display: "flex", gap: "8px", marginTop: "12px" } });
  const presetForResetLabel = getTheme().preset === "custom"
    ? PRESET_LABELS["classic-dark"]
    : PRESET_LABELS[getTheme().preset];
  const resetBtn = el("button", {
    text: `Reset to ${presetForResetLabel}`,
    style: {
      background: "var(--surface-2)", border: "1px solid var(--border-strong)",
      color: "var(--text-primary)", borderRadius: "var(--radius-2)", padding: "5px 10px",
      fontSize: "11px", cursor: "pointer",
    },
    onClick: () => { resetTokens(); rebuild(); },
  });
  const copyBtn = el("button", {
    text: "Copy theme JSON",
    style: {
      background: "transparent", border: "1px solid var(--border-strong)",
      color: "var(--text-secondary)", borderRadius: "var(--radius-2)", padding: "5px 10px",
      fontSize: "11px", cursor: "pointer",
    },
    onClick: async () => {
      try {
        await navigator.clipboard.writeText(JSON.stringify(getTheme(), null, 2));
        copyBtn.textContent = "Copied!";
        setTimeout(() => { copyBtn.textContent = "Copy theme JSON"; }, 1200);
      } catch (e) {
        showToast("error", "Clipboard write failed");
      }
    },
  });
  footer.appendChild(resetBtn);
  footer.appendChild(copyBtn);
  host.appendChild(footer);
}

function buildColorRow(name) {
  const row = el("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-secondary)" } });
  const input = el("input", {
    type: "color",
    style: { width: "28px", height: "20px", padding: "0", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-1)", background: "transparent" },
  });
  input.value = getTheme().tokens[name] || "#000000";
  input.addEventListener("input", () => {
    setToken(name, input.value);
  });
  row.appendChild(input);
  row.appendChild(document.createTextNode(name));
  return row;
}

// Shared slider-row layout: token name on its own single-line top row
// (ellipsis on overflow), then the slider + readout on the next row with
// the readout pulled close to the slider (no flex: 1 spacer between them).
// More compact vertically than the previous 3-column flex (label wrapped
// to 2–3 lines when token names were long, e.g. "alpha-loop-band-fill").
function buildSliderRow({ name, min, max, step, initial, format, commit }) {
  const row = el("label", {
    style: {
      display: "flex", flexDirection: "column", gap: "2px",
      fontSize: "11px", color: "var(--text-secondary)", marginBottom: "6px",
    },
  });
  row.appendChild(el("div", {
    text: name,
    style: {
      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      lineHeight: "1.2",
    },
  }));
  const sliderRow = el("div", {
    style: { display: "flex", alignItems: "center", gap: "6px" },
  });
  const slider = el("input", {
    type: "range",
    attrs: { min: String(min), max: String(max), step: String(step) },
    style: { flex: "1 1 auto", minWidth: "0" },
  });
  slider.value = String(initial);
  const valueLabel = el("span", {
    style: {
      fontFamily: "var(--font-mono)", fontSize: "10px",
      color: "var(--text-muted)", textAlign: "right",
      flex: "0 0 auto",
    },
    text: format(initial),
  });
  slider.addEventListener("input", () => {
    const v = slider.value;
    commit(v);
    valueLabel.textContent = format(v);
  });
  sliderRow.appendChild(slider);
  sliderRow.appendChild(valueLabel);
  row.appendChild(sliderRow);
  return row;
}

function buildAlphaRow(name) {
  const initial = getTheme().tokens[name] || "0";
  return buildSliderRow({
    name, min: 0, max: 1, step: 0.01, initial,
    format: (v) => String(v),
    commit: (v) => setToken(name, v),
  });
}

// Numeric "px" slider for radius-* and t-* tokens. Both validators in
// store.js accept strings of the form `Npx | Nrem | Nem`, so we strip the
// "px" suffix off the current value, clamp to range, and write back with
// "px" appended on every input event.
function buildSizeRow(name, opts = {}) {
  const min  = opts.min  != null ? opts.min  : 0;
  const max  = opts.max  != null ? opts.max  : 32;
  const step = opts.step != null ? opts.step : 1;
  const raw = getTheme().tokens[name] || `${min}px`;
  const parsed = parseFloat(String(raw).replace(/(px|rem|em)$/i, ""));
  const initial = Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : min;
  return buildSliderRow({
    name, min, max, step, initial,
    format: (v) => `${v}px`,
    commit: (v) => setToken(name, `${v}px`),
  });
}

// Motion duration slider: 0..0.6s, written back as "Ns". The motion
// validator in store.js accepts plain `Ns` or `Nms`; we always emit "s".
function buildMotionRow(name) {
  const raw = getTheme().tokens[name] || "0s";
  let parsed = 0;
  const m = String(raw).match(/^([\d.]+)(ms|s)$/i);
  if (m) parsed = m[2].toLowerCase() === "ms" ? parseFloat(m[1]) / 1000 : parseFloat(m[1]);
  const initial = Math.min(0.6, Math.max(0, Number.isFinite(parsed) ? parsed : 0));
  return buildSliderRow({
    name, min: 0, max: 0.6, step: 0.02, initial,
    format: (v) => `${v}s`,
    commit: (v) => setToken(name, `${v}s`),
  });
}

// "Pitch lines" section — width sliders for the Live Input (mic) ribbon
// and the Vocals (Consensus F0) contour. Values land in localStorage via
// the prefs module and fire `musiq:line-width-changed`, which both
// overlays subscribe to so the change is visible without a reload.
function buildPitchLinesSection() {
  const root = el("div");
  root.appendChild(el("h3", {
    style: {
      fontSize: "11px", textTransform: "uppercase",
      color: "var(--text-muted)", margin: "16px 0 6px",
      letterSpacing: "var(--ls-caps)",
    },
    text: "Pitch lines",
  }));
  root.appendChild(el("div", {
    style: { fontSize: "11px", color: "var(--text-muted)", marginBottom: "8px" },
    text: "Stroke width in pixels. Default 1.",
  }));

  function buildRow(label, getter, setter) {
    const valLabel = el("span", {
      style: { fontSize: "11px", color: "var(--text-muted)", fontVariantNumeric: "tabular-nums", minWidth: "36px", textAlign: "right" },
      text: `${getter()} px`,
    });
    const input = el("input", {
      type: "range",
      attrs: {
        min:   String(LINE_WIDTH_RANGE.min),
        max:   String(LINE_WIDTH_RANGE.max),
        step:  String(LINE_WIDTH_RANGE.step),
        value: String(getter()),
      },
      style: { flex: "1", accentColor: "var(--text-primary)" },
      onInput: (e) => {
        const v = Number(e.target.value);
        setter(v);
        valLabel.textContent = `${v} px`;
      },
    });
    return el("label", {
      style: { display: "flex", gap: "10px", alignItems: "center", margin: "4px 0" },
    }, [
      el("span", { style: { fontSize: "12px", minWidth: "92px", color: "var(--text-secondary)" }, text: label }),
      input,
      valLabel,
    ]);
  }

  root.appendChild(buildRow("Live Input", getMicLineWidth, setMicLineWidth));
  root.appendChild(buildRow("Vocals",     getVocalsLineWidth, setVocalsLineWidth));

  root.appendChild(buildPitchColoursSubsection());
  return root;
}

// "Layout" section — vertical sizing knobs. Today it surfaces the drum-hit
// lane height (the kick/snare/toms/hihat/cymbals strip at the bottom of
// every track's piano-roll canvas). Set to 0 to hide the lane entirely
// (same visual effect as a track without transcribed drums). Persists to
// localStorage and fires `musiq:drum-layout-changed`, which pianoroll +
// inspector + f0-overlay + mic-overlay subscribe to.
function buildLayoutSection() {
  const root = el("div");
  root.appendChild(el("h3", {
    style: {
      fontSize: "11px", textTransform: "uppercase",
      color: "var(--text-muted)", margin: "16px 0 6px",
      letterSpacing: "var(--ls-caps)",
    },
    text: "Layout",
  }));
  root.appendChild(el("div", {
    style: { fontSize: "11px", color: "var(--text-muted)", marginBottom: "8px" },
    text: `Drum-hit lane height (px) at the bottom of the piano roll. Default ${DRUM_LAYOUT_RANGE.default}. Set to 0 to hide the lane.`,
  }));

  const valLabel = el("span", {
    style: {
      fontSize: "11px", color: "var(--text-muted)",
      fontVariantNumeric: "tabular-nums", minWidth: "36px", textAlign: "right",
    },
    text: `${getDrumLaneHeight()} px`,
  });
  const input = el("input", {
    type: "range",
    attrs: {
      min:   String(DRUM_LAYOUT_RANGE.min),
      max:   String(DRUM_LAYOUT_RANGE.max),
      step:  String(DRUM_LAYOUT_RANGE.step),
      value: String(getDrumLaneHeight()),
    },
    style: { flex: "1", accentColor: "var(--text-primary)" },
    onInput: (e) => {
      const v = Number(e.target.value);
      setDrumLaneHeight(v);
      valLabel.textContent = `${v} px`;
    },
  });
  root.appendChild(el("label", {
    style: { display: "flex", gap: "10px", alignItems: "center", margin: "4px 0" },
  }, [
    el("span", {
      style: { fontSize: "12px", minWidth: "92px", color: "var(--text-secondary)" },
      text: "Drum lane",
    }),
    input,
    valLabel,
  ]));
  return root;
}

// "Colours" subsection inside Pitch lines. Six native colour inputs, two
// groups (Live Input × 3 buckets, Vocals × 3 estimators). The picker
// writes directly to documentElement.style via color-prefs.setColor, so
// the overlays — subscribed to musiq:theme-changed — repaint immediately.
function buildPitchColoursSubsection() {
  const root = el("div");
  root.appendChild(el("h4", {
    style: {
      fontSize: "11px", textTransform: "uppercase",
      color: "var(--text-muted)", margin: "14px 0 4px",
      letterSpacing: "var(--ls-caps)",
    },
    text: "Colours",
  }));

  function buildSwatchRow(groupLabel, items) {
    const row = el("div", {
      style: { display: "flex", gap: "10px", alignItems: "center", margin: "4px 0", flexWrap: "wrap" },
    });
    row.appendChild(el("span", {
      style: { fontSize: "12px", minWidth: "92px", color: "var(--text-secondary)" },
      text: groupLabel,
    }));
    for (const { key, label } of items) {
      const swatch = el("input", {
        type: "color",
        attrs: { value: getColor(key), title: label },
        style: { width: "26px", height: "20px", padding: "0", border: "1px solid var(--border-strong)", borderRadius: "var(--radius-2)", background: "transparent", cursor: "pointer" },
        onInput: (e) => setColor(key, e.target.value),
      });
      row.appendChild(el("label", {
        style: { display: "inline-flex", gap: "5px", alignItems: "center", fontSize: "11px", color: "var(--text-muted)" },
      }, [swatch, document.createTextNode(label)]));
    }
    // Reset link — clears overrides for THIS group's keys and rebuilds the
    // row so the swatches snap back to the theme defaults.
    const resetBtn = el("button", {
      style: {
        background: "transparent", border: "1px solid var(--border-soft)",
        color: "var(--text-muted)", fontSize: "10px", borderRadius: "var(--radius-2)",
        padding: "2px 6px", cursor: "pointer", marginLeft: "auto",
      },
      text: "Reset",
      onClick: () => {
        for (const { key } of items) resetColor(key);
        const next = buildPitchColoursSubsection();
        root.replaceWith(next);
      },
    });
    row.appendChild(resetBtn);
    return row;
  }

  root.appendChild(buildSwatchRow("Live Input", [
    { key: "mic_in",       label: "Matched" },
    { key: "mic_off",      label: "Unmatched" },
    { key: "mic_neutral",  label: "Stem silent" },
    { key: "mic_no_match", label: "No match" },
  ]));
  root.appendChild(buildSwatchRow("Vocals", [
    { key: "vocals_consensus", label: "Consensus" },
    { key: "vocals_fcpe",      label: "FCPE" },
    { key: "vocals_pesto",     label: "PESTO" },
  ]));
  return root;
}

export function showSettings() {
  const overlay = modalOverlay();
  const panel = modalPanel("Settings");
  // Settings is the densest modal — widen it and let its content scroll
  // inside a wrapper. The wrapper carries overflow rather than the panel
  // itself so the absolute-positioned ".modal-close" stays anchored to
  // the panel's top-right (not to a moving content edge during scroll).
  panel.style.width    = "min(95vw, 960px)";
  panel.style.maxWidth = "min(95vw, 960px)";

  const scrollWrap = el("div", {
    style: {
      maxHeight:    "calc(85vh - 64px)",   // 64px ≈ panel padding + h2 title + footer breathing room
      overflowY:    "auto",
      overflowX:    "hidden",
      paddingRight: "8px",                  // make room for the scrollbar so it doesn't overlap content
      marginRight:  "-8px",
    },
  });

  const currentNotation = getNotationSystem();
  const notationRows = NOTATION_SYSTEMS.map((opt) => {
    const input = el("input", {
      type: "radio",
      attrs: {
        name: "notation",
        value: opt.id,
        ...(opt.id === currentNotation ? { checked: "checked" } : {}),
      },
      onChange: (e) => { if (e.target.checked) setNotationSystem(opt.id); },
    });
    return el("label", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [
      input,
      document.createTextNode(opt.label),
    ]);
  });
  scrollWrap.appendChild(el("div", { style: { fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.7 } }, [
    el("h3", { style: { fontSize: "11px", textTransform: "uppercase", color: "var(--text-muted)", margin: "12px 0 4px" }, text: "Pitch notation" }),
    ...notationRows,
    el("h3", { style: { fontSize: "11px", textTransform: "uppercase", color: "var(--text-muted)", margin: "16px 0 4px" }, text: "Audio engine" }),
    ...buildEngineRadioGroup(),
  ]));
  scrollWrap.appendChild(buildPitchLinesSection());
  scrollWrap.appendChild(buildLayoutSection());
  scrollWrap.appendChild(buildAppearanceSection());
  panel.appendChild(scrollWrap);
  addCloseButton(panel, () => overlay.remove());
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  return overlay;
}

export function showTools(slug, title) {
  const overlay = modalOverlay();
  const panel = modalPanel("Tools");
  for (const stem of ["vocals", "piano", "other", "guitar", "bass"]) {
    panel.appendChild(el("div", {
      style: { padding: "6px 0", cursor: "pointer", color: "var(--text-secondary)", fontSize: "12px" },
      onClick: async () => {
        overlay.remove();
        await postSideEffect(
          `/api/tools/open-midi/${encodeURIComponent(slug)}/${stem}`,
          `Open ${stem}.mid`,
        );
      },
      text: `Open ${stem}.mid in default Windows handler`,
    }));
  }
  panel.appendChild(el("div", {
    style: { padding: "6px 0", cursor: "pointer", color: "var(--text-secondary)", fontSize: "12px", borderTop: "1px solid var(--surface-3)", marginTop: "8px" },
    onClick: async () => {
      overlay.remove();
      await postSideEffect(
        `/api/tools/reveal-cache/${encodeURIComponent(slug)}`,
        "Reveal cache",
      );
    },
    text: `Reveal cache/${slug}/ in Explorer`,
  }));
  // Non-destructive — same neutral styling as the open-MIDI entries. Re-runs
  // only stages whose cache is stale (schema bump, params drift); cached
  // stages are skipped. Typical case: a few seconds to ~30 s for a `beats`
  // re-run after a schema bump, or instant when everything is already fresh.
  panel.appendChild(el("div", {
    style: { padding: "6px 0", cursor: "pointer", color: "var(--text-secondary)", fontSize: "12px" },
    onClick: () => {
      overlay.remove();
      showReanalyzeModal(slug, title || slug, { mode: "stale" });
    },
    text: `Analyze (rerun stale stages only)`,
  }));
  // Destructive — separated by a divider and color-shifted so it doesn't sit
  // in the middle of innocent "open MIDI" entries. The reanalyze modal opens
  // in a confirmation pre-state (see reanalyze.js) so we don't fire a native
  // confirm() that would break the dark UI.
  panel.appendChild(el("div", {
    style: {
      padding: "6px 0", cursor: "pointer", color: "var(--status-error)", fontSize: "12px",
      borderTop: "1px solid var(--surface-3)", marginTop: "8px",
    },
    onClick: () => {
      overlay.remove();
      showReanalyzeModal(slug, title || slug);
    },
    text: `Reanalyze (clear cache + re-run pipeline)`,
  }));
  addCloseButton(panel, () => overlay.remove());
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  return overlay;
}

function modalOverlay() {
  return el("div", {
    style: { position: "fixed", inset: 0, background: `rgb(0 0 0 / var(--alpha-scrim))`, zIndex: 100,
             display: "flex", alignItems: "center", justifyContent: "center" },
    onClick: function () { this.remove(); },
  });
}

function modalPanel(title) {
  const panel = el("div", {
    style: { background: "var(--surface-1)", border: "1px solid var(--surface-3)", borderRadius: "8px",
             padding: "20px 24px", minWidth: "360px", maxWidth: "520px",
             position: "relative" },
    onClick: (e) => e.stopPropagation(),
  });
  panel.appendChild(el("h2", { style: { margin: "0 0 16px 0", fontSize: "16px", color: "var(--text-primary)" }, text: title }));
  return panel;
}
