// Analyze-from-library modal. Two entry variants — file picker or YouTube
// URL — flow through the same state machine: input → (collision step) →
// streaming → done | error. Built from analyze-shared.js primitives so
// reanalyze and "analyze new" agree on UX vocabulary.

import { el } from "./dom.js";
import {
  buildQualitySelector,
  streamAnalyze,
  renderStats,
  STATUS_COLOR,
  buttonStyle,
  createStageBar,
  createOverallTimer,
} from "./analyze-shared.js";
import { api } from "../api.js";

const DEFAULT_QUALITY = "best";

export function showAnalyzeModal({ mode }) {
  const overlay = el("div", {
    style: {
      position: "fixed", inset: 0, background: `rgb(0 0 0 / var(--alpha-scrim))`, zIndex: 200,
      display: "flex", alignItems: "center", justifyContent: "center",
    },
  });
  const panel = el("div", {
    style: {
      background: "var(--surface-1)", border: "1px solid var(--surface-3)", borderRadius: "8px",
      padding: "20px 24px", display: "flex", flexDirection: "column", gap: "12px",
      fontSize: "12px", color: "var(--text-secondary)",
    },
    onClick: (e) => e.stopPropagation(),
  });
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  const state = {
    mode,
    quality: DEFAULT_QUALITY,
    file: null,
    url: "",
    slug: null,
    suggestedNew: null,
    exists: false,
    extError: null,
  };

  renderInputStep(panel, overlay, state);
  return overlay;
}

function renderInputStep(panel, overlay, state) {
  panel.replaceChildren();
  panel.style.width = "min(560px, 92vw)";
  panel.style.height = "auto";

  const heading = document.createElement("h2");
  heading.style.margin = "0";
  heading.style.fontSize = "15px";
  heading.style.color = "white";
  heading.textContent = state.mode === "file"
    ? "Analyze new audio file"
    : "Analyze YouTube URL";
  panel.appendChild(heading);

  if (state.mode === "file") {
    panel.appendChild(buildFileInputBlock(state, refresh));
  } else {
    panel.appendChild(buildUrlInputBlock(state, refresh));
  }

  panel.appendChild(buildQualitySelector(state));

  const actions = document.createElement("div");
  actions.className = "reanalyze-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => overlay.remove());

  const analyzeBtn = document.createElement("button");
  analyzeBtn.className = "btn-confirm";
  analyzeBtn.textContent = "Analyze";
  analyzeBtn.addEventListener("click", () => onAnalyzeClick(panel, overlay, state));

  actions.appendChild(cancelBtn);
  actions.appendChild(analyzeBtn);
  panel.appendChild(actions);

  function refresh() {
    const ready = state.mode === "file"
      ? !!state.file && !state.extError && !!state.slug
      : !!state.url.trim();
    analyzeBtn.disabled = !ready;
  }
  refresh();
}

function buildFileInputBlock(state, onRefresh) {
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });

  const input = document.createElement("input");
  input.type = "file";
  input.setAttribute("accept", ".mp3,.wav,.flac");

  const nameEl = el("div", { style: { fontSize: "11px", color: "var(--text-muted)" }, text: "" });
  const errorEl = el("div", { style: { fontSize: "11px", color: "var(--status-error)" }, text: "" });

  input.addEventListener("change", async () => {
    const file = input.files?.[0] ?? null;
    state.file = file;
    state.slug = null;
    state.extError = null;
    state.exists = false;
    nameEl.textContent = file ? file.name : "";
    errorEl.textContent = "";
    onRefresh();
    if (!file) return;
    try {
      const res = await api.slugForFilename(file.name);
      // Stale-fetch guard: user may have picked a different file (or cleared
      // the picker) while this request was in flight. If `state.file` no
      // longer points at the same File object, drop the result silently.
      if (state.file !== file) return;
      if (res.error === "unsupported_type") {
        state.extError = `Unsupported file type: ${res.extension || "(none)"}`;
        errorEl.textContent = state.extError;
        onRefresh();
        return;
      }
      state.slug = res.slug;
      state.exists = res.exists;
      state.suggestedNew = res.suggested_new_slug;
      onRefresh();
    } catch (e) {
      if (state.file !== file) return;
      state.extError = `Pre-check failed: ${e.message || e}`;
      errorEl.textContent = state.extError;
      onRefresh();
    }
  });

  wrap.appendChild(input);
  wrap.appendChild(nameEl);
  wrap.appendChild(errorEl);
  return wrap;
}

function buildUrlInputBlock(state, onRefresh) {
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "https://www.youtube.com/watch?v=...";
  input.style.width = "100%";
  input.style.padding = "6px 8px";
  input.addEventListener("input", () => {
    state.url = input.value;
    onRefresh();
  });
  wrap.appendChild(input);
  return wrap;
}

async function onAnalyzeClick(panel, overlay, state) {
  if (state.mode === "file") {
    if (!state.exists) {
      startStreaming(panel, overlay, state, { mode: "new", slug: state.slug });
      return;
    }
    _renderCollisionStep(panel, overlay, state);
    return;
  }
  // YouTube: dry-run for the slug + collision check.
  // Disable the Analyze button before the await to prevent double-fire.
  // Success paths re-render the panel (button is gone); error paths that
  // stay on the input step must restore it.
  const analyzeBtn = panel.querySelector(".btn-confirm");
  if (analyzeBtn) analyzeBtn.disabled = true;
  try {
    const dry = await api.youtubeDryRun(state.url, { update_ytdlp: false });
    state.slug = dry.predicted_slug;
    state.exists = dry.exists;
    state.suggestedNew = dry.suggested_new_slug;
    if (!state.exists) {
      startStreaming(panel, overlay, state, { mode: "new", slug: state.slug });
      return;
    }
    _renderCollisionStep(panel, overlay, state);
  } catch (e) {
    if (e.kind === "ytdlp_stale") {
      _renderInlineYtdlpStale(panel, overlay, state);
      return;
    }
    _renderError(panel, overlay, `Metadata fetch failed: ${e.message || e}`);
  }
}

export function _renderCollisionStep(panel, overlay, state) {
  panel.replaceChildren();
  panel.style.width = "min(560px, 92vw)";

  panel.appendChild(el("h2", {
    style: { margin: 0, fontSize: "15px", color: "white" },
    text: state.mode === "file" ? "Analyze new audio file" : "Analyze YouTube URL",
  }));
  panel.appendChild(el("div", {
    style: { color: "var(--text-secondary)" },
    text: `Already in library: ${state.slug}`,
  }));

  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  const cancelBtn = el("button", {
    style: buttonStyle(), text: "Cancel",
    onClick: () => overlay.remove(),
  });
  const reanalyzeBtn = el("button", {
    style: buttonStyle(), text: "Reanalyze",
    onClick: () => startStreaming(panel, overlay, state, { mode: "reanalyze", slug: state.slug }),
  });
  const addNewBtn = el("button", {
    style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
    text: `Add New ${state.suggestedNew}`,
    onClick: () => startStreaming(panel, overlay, state, { mode: "new", slug: state.suggestedNew }),
  });
  row.appendChild(cancelBtn);
  row.appendChild(reanalyzeBtn);
  row.appendChild(addNewBtn);
  panel.appendChild(row);
}

function _renderInlineYtdlpStale(panel, overlay, state) {
  panel.replaceChildren();
  panel.appendChild(el("h2", { style: { margin: 0, fontSize: "15px", color: "white" }, text: "yt-dlp is stale" }));
  panel.appendChild(el("p", {
    style: { color: "var(--status-error)" },
    text: "yt-dlp failed with a stale-version pattern. Update and retry?",
  }));
  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  row.appendChild(el("button", { style: buttonStyle(), text: "Cancel", onClick: () => overlay.remove() }));
  const retryBtn = el("button", {
    style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
    text: "Update yt-dlp & retry",
    onClick: async () => {
      // Disable to prevent double-fire; every continuation path replaces
      // the panel, so no restore is needed.
      retryBtn.disabled = true;
      try {
        const dry = await api.youtubeDryRun(state.url, { update_ytdlp: true });
        state.slug = dry.predicted_slug;
        state.exists = dry.exists;
        state.suggestedNew = dry.suggested_new_slug;
        if (!state.exists) startStreaming(panel, overlay, state, { mode: "new", slug: state.slug, update_ytdlp: true });
        else _renderCollisionStep(panel, overlay, state);
      } catch (e) {
        _renderError(panel, overlay, `Retry failed: ${e.message || e}`);
      }
    },
  });
  row.appendChild(retryBtn);
  panel.appendChild(row);
}

function _renderError(panel, overlay, message) {
  panel.replaceChildren();
  panel.appendChild(el("h2", { style: { margin: 0, fontSize: "15px", color: "var(--status-error)" }, text: "Error" }));
  panel.appendChild(el("p", { style: { color: "var(--status-error)", whiteSpace: "pre-wrap" }, text: message }));
  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  row.appendChild(el("button", { style: buttonStyle(), text: "Close", onClick: () => overlay.remove() }));
  panel.appendChild(row);
}

function startStreaming(panel, overlay, state, params) {
  _renderStreamingStep(panel, overlay, state, params);
}

export function _renderStreamingStep(panel, overlay, state, params) {
  panel.replaceChildren();
  panel.style.width = "min(1080px, 96vw)";
  panel.style.height = "min(1400px, 96vh)";

  // Heading row: title + overall elapsed (right-aligned). The timer instance
  // outlives the inline ticking so its `stop()` fires once on terminal events.
  const headingRow = el("div", {
    style: { display: "flex", alignItems: "baseline", gap: "12px", justifyContent: "space-between" },
  });
  headingRow.appendChild(el("h2", {
    style: { margin: 0, fontSize: "15px", color: "white", flex: "1 1 auto", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
    text: state.mode === "file" ? `Analyzing — ${state.file?.name ?? params.slug}` : `Analyzing — ${state.url}`,
  }));
  const overallTimer = createOverallTimer();
  headingRow.appendChild(overallTimer.el);
  panel.appendChild(headingRow);
  overallTimer.start();

  // Phase strip
  const phasesForFile = ["upload", state.file?.name?.toLowerCase().endsWith(".mp3") ? null : "transcode", "analyze"].filter(Boolean);
  const phasesForYoutube = ["download", "analyze"];
  const phases = state.mode === "file" ? phasesForFile : phasesForYoutube;

  const phaseStrip = el("div", { style: { display: "flex", gap: "6px" } });
  const phaseChips = new Map();
  for (const name of phases) {
    const chip = el("span", {
      class: "analyze-phase-chip",
      style: {
        padding: "3px 10px", borderRadius: "12px", border: "1px solid var(--surface-3)",
        color: "var(--text-muted)", fontSize: "11px", textTransform: "capitalize",
      },
      text: name,
    });
    phaseChips.set(name, chip);
    phaseStrip.appendChild(chip);
  }
  panel.appendChild(phaseStrip);

  // Optional download progress bar (YouTube only)
  let progressBar = null, progressFill = null, progressText = null;
  if (state.mode === "youtube") {
    progressBar = el("div", { style: { width: "100%", height: "6px", background: "var(--surface-3)", borderRadius: "3px", overflow: "hidden" } });
    progressFill = el("div", { style: { width: "0%", height: "100%", background: "var(--accent, #4a90e2)", transition: "width .15s linear" } });
    progressBar.appendChild(progressFill);
    progressText = el("div", { style: { fontSize: "10px", color: "var(--text-muted)" }, text: "" });
    panel.appendChild(progressBar);
    panel.appendChild(progressText);
  }

  // Stage chips with built-in per-stage timer (createStageBar manages its
  // own rAF loop and stops itself when no chip is "running" anymore).
  const stageController = createStageBar();
  panel.appendChild(stageController.root);

  // Log
  const logBox = el("pre", {
    style: {
      flex: "1 1 auto", minHeight: "300px", overflow: "auto",
      margin: 0, padding: "10px 12px", background: "var(--surface-base, #000)",
      border: "1px solid var(--surface-3)", borderRadius: "4px",
      fontFamily: "var(--font-mono, monospace)", fontSize: "11px",
      whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--text-secondary)",
    },
  });
  panel.appendChild(logBox);

  const statsArea = el("div", { style: { display: "none" } });
  panel.appendChild(statsArea);

  const errorBanner = el("div", {
    style: {
      display: "none", padding: "8px 12px", background: `rgb(255 107 107 / var(--alpha-overlay-soft))`,
      border: "1px solid var(--status-error)", borderRadius: "4px", color: "var(--status-error)",
      whiteSpace: "pre-wrap",
    },
  });
  panel.appendChild(errorBanner);

  const footer = el("div", { style: { display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "4px" } });
  // Close stays enabled even mid-stream: dismissing the modal does NOT abort
  // the backend pipeline (the analyze lock prevents collisions, and the user
  // can find the finished track in the library afterward). This mirrors the
  // reanalyze-modal precedent and avoids deadlocking the modal if the stream
  // hangs (server crash, network drop) before any final event arrives.
  const closeBtn = el("button", { style: buttonStyle(), text: "Close", onClick: () => overlay.remove() });
  const openBtn = el("button", {
    style: { ...buttonStyle(), display: "none", background: "var(--accent, #4a90e2)", color: "white" },
    text: "Open new track",
    onClick: () => { /* set in onDone */ },
  });
  footer.appendChild(openBtn);
  footer.appendChild(closeBtn);
  panel.appendChild(footer);

  // Helpers
  const pushLog = (line) => {
    const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 4;
    logBox.appendChild(document.createTextNode(line + "\n"));
    if (atBottom) logBox.scrollTop = logBox.scrollHeight;
  };
  const setPhase = (name, status) => {
    const chip = phaseChips.get(name);
    if (!chip) return;
    if (status === "start") {
      chip.style.color = STATUS_COLOR.running;
      chip.style.borderColor = STATUS_COLOR.running;
    } else if (status === "end") {
      chip.style.color = STATUS_COLOR.done;
      chip.style.borderColor = STATUS_COLOR.done;
    }
  };
  const setStage = (name, status) => stageController.setStage(name, status);
  const setProgress = (pct, eta_sec, speed) => {
    if (!progressFill) return;
    progressFill.style.width = `${pct.toFixed(1)}%`;
    progressText.textContent = `${pct.toFixed(1)}%  ·  ${speed}  ·  ETA ${eta_sec}s`;
  };
  const finalize = ({ ok, slug, stats, errorMessage, errorKind }) => {
    // Stop both timers regardless of outcome — a frozen "Elapsed" line is the
    // user's signal that the pipeline has terminated. Then mark any chip
    // still in `running` state as `done` so the user sees a clean final view
    // (covers stages that finished without an explicit "done" marker, or
    // crashes mid-stage).
    stageController.stop();
    overallTimer.stop();
    stageController.finalizeRunningStages();
    if (ok) {
      // Augment server stats with our client-side run timing before rendering
      // so the report includes "Run time: M:SS".
      const augmented = { ...stats, run_elapsed_ms: overallTimer.elapsedMs() };
      renderStats(statsArea, augmented);
      statsArea.style.display = "";
      openBtn.style.display = "";
      openBtn.onclick = () => {
        location.search = `?slug=${encodeURIComponent(slug)}`;
      };
    } else {
      errorBanner.textContent = errorMessage || "(unknown error)";
      errorBanner.style.display = "";
      // Stale-yt-dlp recovery affordance
      if (errorKind === "ytdlp_stale") {
        const retryBtn = el("button", {
          style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
          text: "Update yt-dlp & retry",
          onClick: () => _renderInlineYtdlpStale(panel, overlay, state),
        });
        footer.insertBefore(retryBtn, openBtn);
      }
    }
  };

  // Wire up the network call.
  let finalSlug = params.slug;
  let finalStats = null;
  const onEvent = (event) => {
    if (event.type === "log") pushLog(event.line);
    else if (event.type === "phase") setPhase(event.name, event.status);
    else if (event.type === "progress") setProgress(event.pct, event.eta_sec, event.speed);
    else if (event.type === "stage") setStage(event.name, event.status);
    else if (event.type === "slug") finalSlug = event.slug;
    else if (event.type === "done") {
      finalStats = event.stats;
      // Defensive: server should always emit `slug` (either as a top-level
      // event mid-stream or in the done payload). If neither arrived, fall
      // back to the predicted slug from the dry-run/upload pre-check and
      // log it so the user knows the navigate-target is the predicted one,
      // not the server-confirmed one.
      if (event.slug != null) {
        finalSlug = event.slug;
      } else if (finalSlug === params.slug) {
        pushLog(`(warning: done event missing slug; using predicted ${finalSlug})`);
      }
      finalize({ ok: true, slug: finalSlug, stats: finalStats });
    }
    else if (event.type === "error") finalize({ ok: false, errorMessage: event.message, errorKind: event.kind });
  };

  if (state.mode === "file") {
    const fd = new FormData();
    fd.append("file", state.file);
    fd.append("quality", state.quality);
    fd.append("mode", params.mode);
    fd.append("slug", params.slug);
    streamAnalyze("/api/tools/analyze/upload", { method: "POST", body: fd }, onEvent)
      .catch((e) => onEvent({ type: "error", message: `request failed: ${e.message || e}` }));
  } else {
    streamAnalyze("/api/tools/analyze/youtube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: state.url, quality: state.quality,
        mode: params.mode, slug: params.slug,
        update_ytdlp: !!params.update_ytdlp,
      }),
    }, onEvent).catch((e) => onEvent({ type: "error", message: `request failed: ${e.message || e}` }));
  }
}
