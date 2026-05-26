import { el, attachDrag } from "./dom.js";

export class Transport {
  constructor(host) {
    this.host = host;
    this.engine = null;
    this.viewState = null;
    this.duration = 0;
  }

  mount(viewState, engine, durationSec) {
    this.viewState = viewState;
    this.engine = engine;
    this.duration = durationSec;

    this.playBtn = el("div", { class: "play-btn", text: "▶", onClick: () => this._togglePlay() });
    this.autoBadge = el("button", {
      class: "auto-badge",
      text: "▶ AUTO",
      onClick: () => this._reengageAutoScroll(),
    });
    this._refreshAutoBadge();
    this.modeToggle = this._buildModeToggle();
    this.anchorToggle = this._buildAnchorToggle();
    this._refreshAnchorToggle();
    this.timeLabel = el("div", { class: "time", text: "0:00.0 / " + formatTime(durationSec) });
    this.scrubFill = el("div", { class: "fill", style: { width: "0%" } });
    this.scrub = el("div", { class: "scrub" }, [this.scrubFill]);
    this._dragging = false;
    attachDrag(this.scrub,
      (frac) => {
        // Live visual feedback only — actual audio seek is deferred to onEnd
        // because seek() does pause+reschedule and would glitch at 60Hz.
        this._dragging = true;
        this.scrubFill.style.width = `${(frac * 100).toFixed(2)}%`;
        if (this.timeLabel) {
          this.timeLabel.textContent = `${formatTime(frac * this.duration)} / ${formatTime(this.duration)}`;
        }
      },
      { onEnd: (frac) => { this._dragging = false; this._scrubToFrac(frac); } },
    );

    // H zoom: log scale 20..2000. V zoom: linear 4..40. Both sliders are
    // now click-and-drag-able (in addition to ctrl+wheel / ⇧wheel on the
    // piano-roll). Dragging H also disables autoScroll — same as the
    // wheel handler in main.js, since the user is taking manual control.
    this.zoomH = this._zoomGroup("H", "ctrl+wheel",
      () => Math.min(1, Math.max(0, Math.log10(viewState.zoomH / 20) / 2)),
      (frac) => {
        viewState.zoomH = 20 * Math.pow(10, 2 * frac);
        viewState.autoScroll = false;
      },
    );
    this.zoomV = this._zoomGroup("V", "⇧wheel",
      () => (viewState.zoomV - 4) / 36,
      (frac) => { viewState.zoomV = 4 + frac * 36; },
    );

    this.host.appendChild(this.playBtn);
    this.host.appendChild(this.autoBadge);
    this.host.appendChild(this.anchorToggle.group);
    this.host.appendChild(this.modeToggle.group);
    this.host.appendChild(this.timeLabel);
    this.host.appendChild(this.scrub);
    this.loopChip = el("button", {
      class: "loop-chip",
      attrs: { type: "button", title: "Click to clear loop" },
      onClick: () => this.viewState.clearLoop(),
    });
    this.loopChip.style.display = "none";
    this.host.appendChild(this.loopChip);
    this.host.appendChild(this.zoomH.group);
    this.host.appendChild(this.zoomV.group);

    // Refresh slider fills + badge state whenever viewState changes.
    viewState.on("change", () => {
      this._refreshZoom();
      this._refreshAutoBadge();
      this._refreshLoopChip();
      this._refreshAnchorToggle();
    });

    // Initial mode-toggle state + subscribe to engine for live updates.
    this._refreshModeToggle();
    this.engine.on("modeChanged", () => this._refreshModeToggle());
    this.engine.on("modeAvailability", () => this._refreshModeToggle());
    this._refreshLoopChip();
  }

  _buildModeToggle() {
    const stems = el("button", {
      class: "mode-btn mode-stems",
      attrs: { title: "Play the per-stem mix (vocals/piano/other/guitar/bass/drums)" },
      text: "MIX",
      onClick: () => this.engine?.setMode("stems"),
    });
    const source = el("button", {
      class: "mode-btn mode-source",
      attrs: { title: "Play the original source MP3 (compare against the stem mix)" },
      text: "SRC",
      onClick: () => this.engine?.setMode("source"),
    });
    const group = el("div", { class: "mode-toggle", attrs: { role: "group", "aria-label": "Playback source" } }, [stems, source]);
    return { group, stems, source };
  }

  _refreshModeToggle() {
    if (!this.modeToggle || !this.engine) return;
    const active = this.engine.getMode();
    const avail = this.engine.getModeAvailability();
    this.modeToggle.stems.classList.toggle("active", active === "stems");
    this.modeToggle.source.classList.toggle("active", active === "source");
    // Disable the button whose buffers haven't loaded yet so users can't
    // click into a dead state.
    this.modeToggle.stems.disabled = !avail.stems;
    this.modeToggle.source.disabled = !avail.source;
  }

  // Auto-scroll anchor pill (CENTER | EDGE). Drives viewState.scrollAnchor
  // and persists to localStorage so the choice survives reloads. Triggers
  // a glide on toggle so the next "time" event's autoScrollFor result is
  // reached smoothly instead of snapping.
  _buildAnchorToggle() {
    const center = el("button", {
      class: "anchor-btn anchor-center",
      attrs: { title: "Center: playhead stays glued to the middle of the canvas" },
      text: "CENTER",
      onClick: () => this._setAnchor("center"),
    });
    const edge = el("button", {
      class: "anchor-btn anchor-edge",
      attrs: { title: "Edge: playhead drifts inside a 30–70% band; canvas jumps when it crosses" },
      text: "EDGE",
      onClick: () => this._setAnchor("edge"),
    });
    const group = el("div", { class: "anchor-toggle", attrs: { role: "group", "aria-label": "Auto-scroll anchor" } }, [center, edge]);
    return { group, center, edge };
  }

  _refreshAnchorToggle() {
    if (!this.anchorToggle || !this.viewState) return;
    const active = this.viewState.scrollAnchor;
    this.anchorToggle.center.classList.toggle("active", active === "center");
    this.anchorToggle.edge.classList.toggle("active", active === "edge");
  }

  _setAnchor(mode) {
    if (!this.viewState || this.viewState.scrollAnchor === mode) return;
    this.viewState.scrollAnchor = mode;
    try { localStorage.setItem("musiq.scrollAnchor", mode); } catch { /* ignore */ }
    // Re-engage auto-scroll if it was off — picking an anchor implies the
    // user wants the playhead followed again. Without this, the toggle is a
    // silent preference change and the user has to also click AUTO.
    if (!this.viewState.autoScroll) this.viewState.autoScroll = true;
    // Tell the main-loop glide handler to lerp toward the new target instead
    // of snap-jumping. The next "time" event will compute the delta and ride
    // the LERP path until the playhead lands at its anchor position.
    this.viewState.triggerGlide?.();
  }

  _refreshLoopChip() {
    if (!this.loopChip) return;
    const vs = this.viewState;
    if (vs.loopStart == null || vs.loopEnd == null) {
      this.loopChip.style.display = "none";
      return;
    }
    this.loopChip.textContent = `Loop ${formatTime(vs.loopStart)}–${formatTime(vs.loopEnd)} ✕`;
    this.loopChip.style.display = "";
  }

  _refreshAutoBadge() {
    if (!this.autoBadge || !this.viewState) return;
    const on = this.viewState.autoScroll;
    this.autoBadge.textContent = on ? "▶ AUTO" : "○ MANUAL";
    this.autoBadge.classList.toggle("off", !on);
  }

  _reengageAutoScroll() {
    if (!this.viewState) return;
    // Toggle: clicking re-engages when off; when already on, lets the user
    // turn it back off (matches the previous canvas-badge behaviour).
    this.viewState.autoScroll = !this.viewState.autoScroll;
  }

  _refreshZoom() {
    if (!this.zoomH || !this.zoomV) return;
    this.zoomH.fill.style.width = `${(this.zoomH.fracFn() * 100).toFixed(0)}%`;
    this.zoomV.fill.style.width = `${(this.zoomV.fracFn() * 100).toFixed(0)}%`;
  }

  _togglePlay() {
    if (!this.engine) return;
    if (this.engine.isPlaying) { this.engine.pause(); this.playBtn.textContent = "▶"; }
    else { this.engine.play(); this.playBtn.textContent = "⏸"; }
  }

  _scrubToFrac(frac) {
    if (!this.engine || !this.viewState) return;
    const t = frac * this.duration;
    // Engage auto-scroll + glide BEFORE seek. engine.seek() emits "time"
    // synchronously, and the main.js handler decides whether to scroll
    // based on viewState.autoScroll at that exact moment. Setting these
    // afterwards would arrive too late — the handler would skip the
    // scroll branch entirely. Anchor (CENTER/EDGE) stays the user's
    // pick via the transport pill; we don't override it here.
    this.viewState.update({ autoScroll: true });
    this.viewState.triggerGlide?.();
    this.engine.seek(t);
  }

  setCurrentTime(t) {
    if (!this.timeLabel) return;
    // Don't fight the user's drag — they own the visuals while dragging.
    if (this._dragging) return;
    this.timeLabel.textContent = `${formatTime(t)} / ${formatTime(this.duration)}`;
    this.scrubFill.style.width = `${(t / this.duration * 100).toFixed(2)}%`;
  }

  _zoomGroup(label, hint, fracFn, onDrag) {
    // Click-and-drag the slider to set zoom, OR ctrl+wheel / ⇧wheel on
    // the piano-roll (see installInteractions in main.js). Both paths
    // mutate viewState.zoom*, which fires "change" and triggers
    // _refreshZoom via the viewState.on("change", ...) subscription.
    const lbl = el("span", { class: "zlbl", text: label });
    const fill = el("div", { style: { position: "absolute", left: 0, top: 0, bottom: 0, background: "color-mix(in srgb, var(--text-primary) 50%, transparent)", borderRadius: "3px", width: `${(fracFn() * 100).toFixed(0)}%`, pointerEvents: "none" } });
    const slider = el("div", { style: { width: "60px", height: "6px", background: "color-mix(in srgb, var(--text-primary) 20%, transparent)", border: "1px solid color-mix(in srgb, var(--text-primary) 80%, transparent)", borderRadius: "3px", position: "relative", cursor: "pointer" } }, [fill]);
    if (onDrag) attachDrag(slider, (frac) => onDrag(frac));
    const hintSpan = el("span", { style: { fontSize: "8px", color: "var(--text-disabled)", marginLeft: "3px" }, text: hint });
    const group = el("div", { class: "zoomgrp" }, [lbl, slider, hintSpan]);
    return { group, fill, fracFn };
  }
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}
