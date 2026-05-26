// Shared helpers used by reanalyze.js and analyze-modal.js. Extracted during
// the analyze-from-library work so both modals draw from the same vocabulary
// (stage order, quality presets, NDJSON event handling, stats rendering).

import { el } from "./dom.js";
import { renderCrosscheckRow } from "../analyze-modal/crosscheck-row.js";
import {
  parseKey,
  reformatRootedName,
  respellPitchString,
  formatChordShorthand,
  humanizeKeyString,
} from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";

// Mirrors analyze.pipeline._STAGE_EXECUTION_ORDER. Keep in sync with
// analyze/pipeline.py:83-96 — wrong order or missing stages here means the
// modal shows blank chips while real work is happening server-side.
//
// Why this exact order: `vocal_f0` MUST run before `transcription` so the
// vocals stem can read vocal_f0.npz. `vocal_consensus_contour` MUST run last
// because it consumes vocal_f0 + transcription (+ optional stems_dynamics).
export const STAGE_ORDER = [
  "stems",
  "stems_dynamics",
  "beats",
  "key",
  "chords",
  "vocal_f0",
  "transcription",
  "beats_xcheck",
  "drums",
  "vocal_consensus_contour",
];

// Friendly labels for the chips. Backend protocol still uses the raw names
// in {"type":"stage","name":...} events; we only beautify on display.
export const STAGE_LABELS = {
  "stems": "stems",
  "stems_dynamics": "stem dynamics",
  "beats": "beats",
  "key": "key",
  "chords": "chords",
  "vocal_f0": "vocal F0",
  "transcription": "transcription",
  "beats_xcheck": "beats xcheck",
  "drums": "drums",
  "vocal_consensus_contour": "vocal consensus",
};

// Stem-separation quality presets surfaced in the confirmation modal. Mirrors
// analyze.stages.stems.STEMS_QUALITY_PARAMS — keep in sync. The blurb text is
// the only thing the user sees; numbers are documented in the python module.
export const QUALITY_PRESETS = [
  { value: "fast",   label: "Fast",   blurb: "shifts=2  · ~½ time" },
  { value: "normal", label: "Normal", blurb: "shifts=4  · ~½ time vs best" },
  { value: "best",   label: "Best",   blurb: "shifts=8  · default" },
];

export const STATUS_COLOR = {
  running: "var(--status-info)",
  cached: "var(--text-muted)",
  done: "var(--status-success)",
  error: "var(--status-error)",
};

export function buildQualitySelector(state) {
  const wrap = document.createElement("div");
  wrap.className = "reanalyze-quality";

  const label = document.createElement("div");
  label.className = "reanalyze-quality-label";
  label.textContent = "Stem separation quality";
  wrap.appendChild(label);

  const seg = document.createElement("div");
  seg.className = "reanalyze-quality-seg";
  wrap.appendChild(seg);

  const buttons = QUALITY_PRESETS.map((preset) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reanalyze-quality-btn";
    btn.dataset.value = preset.value;
    btn.setAttribute("aria-pressed", String(preset.value === state.quality));
    if (preset.value === state.quality) btn.classList.add("active");

    const lbl = document.createElement("span");
    lbl.className = "reanalyze-quality-btn-label";
    lbl.textContent = preset.label;
    btn.appendChild(lbl);

    const blurb = document.createElement("span");
    blurb.className = "reanalyze-quality-btn-blurb";
    blurb.textContent = preset.blurb;
    btn.appendChild(blurb);

    seg.appendChild(btn);
    return btn;
  });

  for (const btn of buttons) {
    btn.addEventListener("click", () => {
      state.quality = btn.dataset.value;
      for (const other of buttons) {
        const isActive = other === btn;
        other.classList.toggle("active", isActive);
        other.setAttribute("aria-pressed", String(isActive));
      }
    });
  }

  return wrap;
}

export async function* parseNdjsonStream(byteSource) {
  const decoder = new TextDecoder();
  let buf = "";
  for await (const chunk of byteSource) {
    buf += decoder.decode(chunk, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try { yield JSON.parse(line); }
      catch { yield { type: "log", line: `(unparseable: ${line})` }; }
    }
  }
  const tail = buf.trim();
  if (tail) {
    try { yield JSON.parse(tail); }
    catch { yield { type: "log", line: tail }; }
  }
}

export async function streamAnalyze(url, init, onEvent) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    onEvent({ type: "error", message: `HTTP ${res.status}: ${body || res.statusText}` });
    return;
  }
  async function* readerToBytes() {
    const reader = res.body.getReader();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      yield value;
    }
  }
  for await (const ev of parseNdjsonStream(readerToBytes())) onEvent(ev);
}

export function renderStats(target, s) {
  while (target.firstChild) target.removeChild(target.firstChild);
  target.style.display = "";
  target.appendChild(el("h3", {
    style: { margin: "8px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--text-muted)" },
    text: "Analysis result",
  }));

  const grid = el("div", {
    style: {
      display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
      gap: "4px 16px", fontSize: "12px",
    },
  });
  // M:SS rounded — matches track-picker.js:formatDuration (the canonical
  // duration formatter used in the library list). The previous M:SS.S format
  // ("3:42.8") looked unfamiliar next to the same track shown as "3:43" in
  // every player and the picker.
  const fmtDuration = (sec) => {
    if (sec == null) return "—";
    const m = Math.floor(sec / 60);
    const s = Math.round(sec - m * 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  };
  const row = (label, value) => {
    grid.appendChild(el("span", { style: { color: "var(--text-muted)" }, text: label }));
    grid.appendChild(el("span", { style: { color: "var(--text-secondary)" }, text: String(value ?? "—") }));
  };
  // Resolve the user's pitch-notation preference once per render so every
  // pitch-bearing field (Key / Scale / chord-loop / Vocal range) reads in the
  // same system as the rest of the UI. The modal does not re-render on
  // notation-changed (it closes after a run completes), so this snapshot at
  // mount time is sufficient.
  const notationSystem = getNotationSystem();
  const keyParse = parseKey(s.key ?? "");
  const keyDisplay = reformatRootedName(humanizeKeyString(s.key ?? ""), notationSystem);
  row("Duration", fmtDuration(s.duration_sec));
  row("Tempo", s.tempo_bpm != null ? `${s.tempo_bpm.toFixed(1)} BPM` : "—");
  row("Key", s.key_confidence != null
    ? `${keyDisplay} (conf ${(s.key_confidence * 100).toFixed(0)}%)`
    : (keyDisplay || "—"));
  row("Scale", s.scale ? reformatRootedName(s.scale, notationSystem) : "—");
  row("Downbeats", s.downbeat_count);
  row("Chords", s.chord_count);
  // Provenance: surface the stems-quality preset the user actually got. Not
  // visible in the run UI without scraping the log; visible here gives the
  // user a quick "did the right preset run?" sanity check.
  if (s.stems_quality) row("Stems quality", s.stems_quality);
  // Client-side run elapsed (set by the modal before calling renderStats —
  // not present in the server payload). Distinct from `Duration` (the song
  // length).
  if (s.run_elapsed_ms != null) row("Run time", formatElapsed(s.run_elapsed_ms));
  if (Array.isArray(s.predominant_chord_loop) && s.predominant_chord_loop.length) {
    const loopText = s.predominant_chord_loop
      .map((c) => reformatRootedName(formatChordShorthand(c), notationSystem))
      .join(" | ");
    const roman = Array.isArray(s.loop_roman) && s.loop_roman.length
      ? `  (${s.loop_roman.join(" | ")})` : "";
    row("Loop", `${loopText}${roman} × ${s.loop_appearances}`);
  } else {
    row("Loop", "none");
  }
  row("Modal interchange", s.modal_interchange_count ?? 0);
  // Backend produces {low, high} as pitch-name strings — see
  // analyze/derived/vocal_range.py:36-39. The span is not computed
  // server-side, so we derive it client-side from the parsed pitch names.
  // Note that the pitch names use Unicode ♯/♭ (U+266F / U+266D), not ASCII
  // # / b — pitchNameToMidi handles both.
  const vr = s.vocal_range;
  if (vr && typeof vr.low === "string" && typeof vr.high === "string") {
    const loMidi = pitchNameToMidi(vr.low);
    const hiMidi = pitchNameToMidi(vr.high);
    const span = (loMidi != null && hiMidi != null) ? `${hiMidi - loMidi} st` : "?";
    // Re-spell against the active key so the modal's range matches the
    // sidebar's "VOCAL RANGE" line (which uses the same helper). Both
    // accidental glyphs (♯/♭) and solfège transposition are applied.
    const loDisplay = respellPitchString(vr.low, keyParse, notationSystem);
    const hiDisplay = respellPitchString(vr.high, keyParse, notationSystem);
    row("Vocal range", `${loDisplay}–${hiDisplay} (${span})`);
  } else {
    row("Vocal range", "—");
  }
  target.appendChild(grid);

  // Stem note counts
  if (s.note_counts && Object.keys(s.note_counts).length) {
    target.appendChild(el("h3", {
      style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--text-muted)" },
      text: "Notes per stem",
    }));
    const stemGrid = el("div", {
      style: {
        display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: "2px 12px", fontSize: "12px",
      },
    });
    for (const [stem, n] of Object.entries(s.note_counts)) {
      stemGrid.appendChild(el("span", {
        style: { color: "var(--text-secondary)" },
        text: `${stem}: ${n}`,
      }));
    }
    target.appendChild(stemGrid);
  }

  // Drums
  target.appendChild(el("h3", {
    style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--text-muted)" },
    text: "Drums",
  }));
  if (s.drums?.transcribed) {
    const drumLine = Object.entries(s.drums.pieces || {})
      .map(([k, n]) => `${k}: ${n}`).join("  ·  ");
    target.appendChild(el("div", {
      style: { color: "var(--text-secondary)" },
      text: `${drumLine}  (total ${s.drums.total} hits)`,
    }));
  } else {
    target.appendChild(el("div", {
      style: { color: "var(--text-muted)" },
      text: s.drums?.reason ? `not transcribed — ${s.drums.reason}` : "not transcribed",
    }));
  }

  // Warnings
  if (Array.isArray(s.warnings) && s.warnings.length) {
    target.appendChild(el("h3", {
      style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--status-warning)" },
      text: `Warnings (${s.warnings.length})`,
    }));
    const ul = el("ul", { style: { margin: 0, paddingLeft: "18px", color: "var(--text-secondary)" } });
    for (const w of s.warnings) ul.appendChild(el("li", { text: w }));
    target.appendChild(ul);
  }

  // Plan C Task 8: Essentia cross-check (tempo + key second opinion). The
  // backend (analyze/derived/essentia_agreement.py) populates
  // summary.essentia_agreement with {bpm, key} per-field comparison vs the
  // pipeline's own estimates; appendCrosscheckRow is a no-op when the block
  // is empty (Essentia not installed / extraction failed).
  appendCrosscheckRow(target, s.essentia_agreement, notationSystem);
}

// DOM-side mounting helper for renderCrosscheckRow. Keeps the renderer pure
// (string-returning, easy to unit test) while routing materialization through
// a <template> element — the dynamic values inside the HTML string are
// already escaped at the source (see crosscheck-row.js:escapeHtml).
function appendCrosscheckRow(target, agreement, notationSystem) {
  const html = renderCrosscheckRow(agreement, notationSystem);
  if (!html) return;
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const node = tpl.content.firstElementChild;
  if (node) target.appendChild(node);
}

// rAF / cAF with a setTimeout fallback. The fallback exists so unit tests
// (jsdom without rAF on globalThis) can construct the streaming UI without
// crashing — production browsers always have rAF.
const _raf = (cb) => (globalThis.requestAnimationFrame || ((fn) => setTimeout(fn, 16)))(cb);
const _caf = (id) => (globalThis.cancelAnimationFrame || globalThis.clearTimeout)(id);

// Parse a pitch name like "F♯2", "C4", "Eb3" into a MIDI number (60 = C4),
// or null if unparseable. Handles both Unicode ♯/♭ (U+266F / U+266D — what
// analyze/derived/vocal_range.py emits) and ASCII #/b for safety. Exported
// so unit tests can pin the contract.
export function pitchNameToMidi(name) {
  if (typeof name !== "string") return null;
  const m = name.trim().match(/^([A-G])([#♯b♭]?)(-?\d+)$/);
  if (!m) return null;
  const STEP = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  let pc = STEP[m[1]];
  if (m[2] === "#" || m[2] === "♯") pc += 1;
  else if (m[2] === "b" || m[2] === "♭") pc -= 1;
  const octave = parseInt(m[3], 10);
  return (octave + 1) * 12 + pc;
}

// "M:SS" elapsed formatter. Returns "—" for null/negative input so callers
// don't have to special-case the pre-start state.
export function formatElapsed(ms) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// Stage bar with built-in per-stage timer. One source of truth for both
// modals. Returns the root DOM node + a controller:
//
//   setStage(name, status)  — "running" | "cached" | "done" | "error"
//   finalizeRunningStages() — mark any still-running chip as done (terminal)
//   stop()                  — cancel the rAF loop (call on terminal event)
//   getRunElapsed()         — ms between first running and last running/done
//
// rAF (not setInterval) so tabs in the background pause the ticker — saves
// CPU during long stems separation when the user has switched away.
export function createStageBar() {
  const root = el("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" } });
  const chipState = new Map();

  for (const name of STAGE_ORDER) {
    const wrap = document.createElement("span");
    Object.assign(wrap.style, {
      padding: "3px 8px", borderRadius: "10px",
      border: "1px solid var(--surface-3)", color: "var(--text-muted)",
      fontSize: "10px", fontFamily: "var(--font-mono, monospace)",
      display: "inline-flex", alignItems: "baseline", gap: "6px",
      background: "transparent", whiteSpace: "nowrap",
    });
    const label = document.createElement("span");
    label.textContent = STAGE_LABELS[name] || name;
    const time = document.createElement("span");
    Object.assign(time.style, { color: "currentColor", opacity: "0.65", fontSize: "9px" });
    time.textContent = "";
    wrap.appendChild(label);
    wrap.appendChild(time);
    root.appendChild(wrap);
    chipState.set(name, {
      wrap, label, time, status: "pending",
      startedAt: null, endedAt: null,
    });
  }

  let firstStartedAt = null;
  let lastEventAt = null;
  let rafId = null;

  const setLabel = (chip, name, prefix) => {
    chip.label.textContent = `${prefix}${STAGE_LABELS[name] || name}`;
  };

  const ensureTicker = () => {
    if (rafId != null) return;
    const tick = () => {
      const now = performance.now();
      let anyRunning = false;
      for (const chip of chipState.values()) {
        if (chip.status === "running") {
          chip.time.textContent = formatElapsed(now - chip.startedAt);
          anyRunning = true;
        }
      }
      // Keep ticking while any stage is running. Stops naturally on stop().
      rafId = anyRunning ? _raf(tick) : null;
    };
    rafId = _raf(tick);
  };

  function setStage(name, status) {
    const chip = chipState.get(name);
    if (!chip) return;
    const now = performance.now();
    lastEventAt = now;
    if (status === "running") {
      chip.status = "running";
      chip.startedAt = now;
      chip.endedAt = null;
      if (firstStartedAt == null) firstStartedAt = now;
      chip.wrap.style.color = STATUS_COLOR.running;
      chip.wrap.style.borderColor = STATUS_COLOR.running;
      chip.wrap.style.background = `rgb(126 221 255 / var(--alpha-overlay-soft))`;
      setLabel(chip, name, "▶ ");
      chip.time.textContent = "0:00";
      ensureTicker();
    } else if (status === "cached") {
      chip.status = "cached";
      chip.wrap.style.color = STATUS_COLOR.cached;
      chip.wrap.style.borderColor = STATUS_COLOR.cached;
      chip.wrap.style.background = "transparent";
      setLabel(chip, name, "");
      chip.time.textContent = "(cached)";
    } else if (status === "done") {
      chip.status = "done";
      chip.endedAt = now;
      chip.wrap.style.color = STATUS_COLOR.done;
      chip.wrap.style.borderColor = STATUS_COLOR.done;
      chip.wrap.style.background = "transparent";
      setLabel(chip, name, "✓ ");
      chip.time.textContent = chip.startedAt != null
        ? formatElapsed(now - chip.startedAt)
        : "";
    } else if (status === "error") {
      chip.status = "error";
      chip.endedAt = now;
      chip.wrap.style.color = STATUS_COLOR.error;
      chip.wrap.style.borderColor = STATUS_COLOR.error;
      setLabel(chip, name, "✗ ");
    }
  }

  function finalizeRunningStages() {
    for (const [name, chip] of chipState) {
      if (chip.status === "running") setStage(name, "done");
    }
  }

  function stop() {
    if (rafId != null) _caf(rafId);
    rafId = null;
  }

  function getRunElapsed() {
    if (firstStartedAt == null) return 0;
    return (lastEventAt ?? performance.now()) - firstStartedAt;
  }

  return { root, setStage, finalizeRunningStages, stop, getRunElapsed };
}

// Small "Elapsed M:SS" line; auto-refreshes via rAF until stop() is called.
// Decoupled from createStageBar so each modal can place it wherever it likes
// (heading row vs. above the log) and the same instance survives the modal's
// own re-renders.
export function createOverallTimer() {
  const node = el("div", {
    style: {
      fontSize: "11px", color: "var(--text-muted)",
      fontFamily: "var(--font-mono, monospace)",
    },
    text: "Elapsed —",
  });
  let startedAt = null;
  let stoppedAt = null;
  let rafId = null;

  const render = () => {
    const now = stoppedAt ?? performance.now();
    node.textContent = `Elapsed ${formatElapsed(startedAt != null ? now - startedAt : 0)}`;
  };

  return {
    el: node,
    start() {
      if (startedAt != null) return;
      startedAt = performance.now();
      const tick = () => {
        render();
        if (stoppedAt == null) rafId = _raf(tick);
      };
      rafId = _raf(tick);
    },
    stop() {
      if (stoppedAt != null) return;
      stoppedAt = performance.now();
      if (rafId != null) _caf(rafId);
      rafId = null;
      render();
    },
    elapsedMs() {
      if (startedAt == null) return 0;
      return (stoppedAt ?? performance.now()) - startedAt;
    },
  };
}

export function buttonStyle() {
  return {
    padding: "6px 14px", background: "var(--surface-2)", color: "var(--text-secondary)",
    border: "1px solid var(--surface-3)", borderRadius: "4px", cursor: "pointer",
    fontSize: "12px",
  };
}
