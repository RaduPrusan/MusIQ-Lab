// Reanalyze modal: wipes cache for a track and re-runs the analyze pipeline,
// streaming progress (NDJSON over POST) into a scrolling log + stage badge,
// and rendering a stats panel on completion. Pipeline runs in WSL via the
// /api/tools/reanalyze/{slug} endpoint.
//
// Lifecycle:
//   1. user clicks "Reanalyze" in Tools → modal opens in confirmation state
//   2. user clicks "Reanalyze" inside modal → modal swaps to streaming UI,
//      fetch starts, lock taken on backend
//   3. each NDJSON event mutates the modal (stage badge / log / stats)
//   4. on done: stats render, "Reload" button re-fetches the page
//   5. on error: error banner stays, "Close" button dismisses (pipeline may
//      keep running on backend; lock prevents re-kicking until done)

import { el } from "./dom.js";
import {
  QUALITY_PRESETS,
  STATUS_COLOR,
  buildQualitySelector,
  streamAnalyze,
  renderStats,
  buttonStyle,
  createStageBar,
  createOverallTimer,
} from "./analyze-shared.js";

const DEFAULT_QUALITY = "best";

export function showReanalyzeModal(slug, title, opts = {}) {
  const mode = opts.mode === "stale" ? "stale" : "full";
  // Optional filter: when provided, the analyze-stale endpoint will only
  // iterate these stage names. Library row's small ⟳ button passes the
  // stale_stages array here so we skip the cache-hit walk over fresh stages
  // and dodge CUDA warmup on every cold rerun.
  const stages = Array.isArray(opts.stages) ? opts.stages : null;
  const overlay = el("div", {
    style: {
      position: "fixed", inset: 0, background: `rgb(0 0 0 / var(--alpha-scrim))`, zIndex: 200,
      display: "flex", alignItems: "center", justifyContent: "center",
    },
  });
  const panel = el("div", {
    style: {
      background: "var(--surface-1)", border: "1px solid var(--surface-3)", borderRadius: "8px",
      padding: "20px 24px",
      display: "flex", flexDirection: "column", gap: "12px",
      fontSize: "12px", color: "var(--text-secondary)",
    },
    onClick: (e) => e.stopPropagation(),
  });

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  // Closure holds the currently-selected quality preset; the segmented control
  // mutates it, and the confirm handler reads it at click time.
  const state = { quality: DEFAULT_QUALITY };

  renderConfirmationState(panel, slug, title, state, () => {
    startReanalyzePipeline(panel, overlay, slug, title, state.quality, mode, stages);
  }, () => overlay.remove(), mode, stages);

  return overlay;
}

// Confirmation pre-state: warning copy + quality selector + Cancel / Reanalyze
// buttons. Built with createElement + textContent (no innerHTML) per the
// security/XSS posture of the rest of the webui codebase.
function renderConfirmationState(panel, slug, title, state, onConfirm, onCancel, mode = "full", stages = null) {
  panel.replaceChildren();
  // Compact width for the confirmation step; the streaming state expands.
  panel.style.width = "min(560px, 92vw)";
  panel.style.height = "auto";

  const heading = document.createElement("h2");
  heading.style.margin = "0";
  heading.style.fontSize = "15px";
  heading.style.color = "white";
  heading.textContent = mode === "stale"
    ? `Analyze (rerun stale stages) — ${title}`
    : `Reanalyze — ${title}`;
  panel.appendChild(heading);

  panel.appendChild(buildQualitySelector(state));

  const warn = document.createElement("p");
  warn.className = "reanalyze-warn";
  if (mode === "stale") {
    if (stages && stages.length) {
      warn.appendChild(document.createTextNode(
        `This will re-run only the ${stages.length} stale stage${stages.length === 1 ? "" : "s"} detected: `
      ));
      const code = document.createElement("code");
      code.textContent = stages.join(", ");
      warn.appendChild(code);
      warn.appendChild(document.createTextNode(
        ". Fresh stages aren't touched. The cache and source MP3 are preserved."
      ));
    } else {
      warn.appendChild(document.createTextNode(
        "This re-runs only stages whose cache is stale (schema bump, params drift). " +
        "Cached stages are skipped. Typical case: a few seconds to ~30 s for a "
      ));
      const beatsCode = document.createElement("code");
      beatsCode.textContent = "beats";
      warn.appendChild(beatsCode);
      warn.appendChild(document.createTextNode(
        " re-run when the schema has bumped, or instant if everything is fresh. " +
        "The cache and source MP3 are preserved."
      ));
    }
  } else {
    warn.appendChild(document.createTextNode("This will wipe "));
    const slugCode = document.createElement("code");
    slugCode.textContent = `cache/${slug}/`;
    warn.appendChild(slugCode);
    warn.appendChild(document.createTextNode(
      " and re-run the full analysis pipeline (typically 5–15 minutes, runs in WSL). " +
      "The original source MP3 is staged outside the cache, so the in-cache copy is safe to lose."
    ));
  }
  panel.appendChild(warn);

  const actions = document.createElement("div");
  actions.className = "reanalyze-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", onCancel);

  const confirmBtn = document.createElement("button");
  confirmBtn.className = "btn-confirm";
  confirmBtn.textContent = mode === "stale" ? "Analyze stale" : "Reanalyze";
  confirmBtn.addEventListener("click", onConfirm);

  actions.appendChild(cancelBtn);
  actions.appendChild(confirmBtn);
  panel.appendChild(actions);
}

// Streaming state: stage chips + scrolling log + stats area + footer buttons.
// Replaces the confirmation UI inside the same panel/overlay so the modal
// transitions in place when the user confirms.
function startReanalyzePipeline(panel, overlay, slug, title, quality, mode = "full", stages = null) {
  panel.replaceChildren();
  // Switch to the wide/tall streaming layout.
  panel.style.width = "min(1080px, 96vw)";
  panel.style.height = "min(1400px, 96vh)";

  // Heading row: title + overall elapsed (right-aligned). Frozen elapsed
  // value is the user's signal that the pipeline terminated.
  const headingRow = el("div", {
    style: { display: "flex", alignItems: "baseline", gap: "12px", justifyContent: "space-between" },
  });
  headingRow.appendChild(el("h2", {
    style: { margin: 0, fontSize: "15px", color: "white", flex: "1 1 auto", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
    text: mode === "stale" ? `Analyzing (stale stages) — ${title}` : `Reanalyzing — ${title}`,
  }));
  const overallTimer = createOverallTimer();
  headingRow.appendChild(overallTimer.el);
  panel.appendChild(headingRow);
  overallTimer.start();

  const stageController = createStageBar();
  panel.appendChild(stageController.root);

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

  const footer = el("div", {
    style: { display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "4px" },
  });
  const closeBtn = el("button", {
    style: buttonStyle(), text: "Close", attrs: { disabled: "true" },
    onClick: () => overlay.remove(),
  });
  closeBtn.disabled = true;
  closeBtn.style.opacity = 0.5;
  const reloadBtn = el("button", {
    style: { ...buttonStyle(), display: "none" },
    text: "Reload track",
    onClick: () => location.reload(),
  });
  footer.appendChild(reloadBtn);
  footer.appendChild(closeBtn);
  panel.appendChild(footer);

  // --- streaming wire-up ----------------------------------------------------
  const pushLog = (line) => {
    const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 4;
    logBox.appendChild(document.createTextNode(line + "\n"));
    if (atBottom) logBox.scrollTop = logBox.scrollHeight;
  };
  const setStage = (name, status) => stageController.setStage(name, status);
  const finish = ({ ok }) => {
    // Stop both timers; freezes the displayed elapsed values. Then mark any
    // still-running chip as done so the final view is clean (handles stages
    // that crashed mid-run without a terminal "done" marker).
    stageController.stop();
    overallTimer.stop();
    stageController.finalizeRunningStages();
    closeBtn.disabled = false;
    closeBtn.style.opacity = 1;
    if (ok) reloadBtn.style.display = "";
  };
  const showError = (msg) => {
    errorBanner.textContent = msg;
    errorBanner.style.display = "";
    finish({ ok: false });
  };
  const showStats = (stats) => {
    finish({ ok: true });
    // Augment with client-side run elapsed so the report shows "Run time".
    const augmented = { ...stats, run_elapsed_ms: overallTimer.elapsedMs() };
    renderStats(statsArea, augmented);
    statsArea.style.display = "";
  };

  const endpoint = mode === "stale"
    ? `/api/tools/analyze-stale/${encodeURIComponent(slug)}`
    : `/api/tools/reanalyze/${encodeURIComponent(slug)}`;
  const reqBody = { quality };
  // Selective rerun: pass only when stages are explicitly provided. Empty
  // array would also be valid per _parse_reanalyze_body, but we treat null
  // as "no filter" so the user can still see a generic stale rerun fall
  // back to walking every stage when invoked without a filter.
  if (stages && stages.length) reqBody.stages = stages;
  streamAnalyze(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(reqBody),
  }, (event) => {
    if (event.type === "log") pushLog(event.line);
    else if (event.type === "stage") setStage(event.name, event.status);
    else if (event.type === "done") showStats(event.stats);
    else if (event.type === "error") showError(event.message);
  }).catch((err) => showError(`request failed: ${err.message || err}`));
}

