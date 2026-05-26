import { el } from "./dom.js";

export class Minimap {
  constructor(host) { this.host = host; this.trackData = null; this.viewState = null; }

  mount(trackData, viewState) {
    this.trackData = trackData;
    this.viewState = viewState;
    this.track = el("div", { class: "track" });
    this.host.appendChild(this.track);
    for (const band of trackData.loopBands) {
      const left = (band.start / trackData.meta.durationSec * 100).toFixed(2) + "%";
      const width = ((band.end - band.start) / trackData.meta.durationSec * 100).toFixed(2) + "%";
      this.track.appendChild(el("div", { class: "seg", style: { left, width } }));
    }
    this.loopBand = el("div", { class: "loop-band", style: { display: "none" } });
    this.track.appendChild(this.loopBand);
    this.viewport = el("div", { class: "viewport" });
    this.track.appendChild(this.viewport);
    this.play = el("div", { class: "play", style: { left: "0%" } });
    this.track.appendChild(this.play);

    const refresh = () => this._refresh();
    viewState.on("change", refresh);
    new ResizeObserver(refresh).observe(this.host);
    refresh();

    this._wireDrag();
  }

  _wireDrag() {
    let dragging = false;
    let mode = "seek";   // "seek" = clicked track → center viewport on cursor
                         // "viewport" = grabbed the viewport box → drag with offset
    let viewportGrabFrac = 0;

    const seekTo = (clientX, useGrabOffset) => {
      const rect = this.track.getBoundingClientRect();
      const dur = this.trackData.meta.durationSec;
      const wrap = document.querySelector("#roll-frame .canvas-wrap");
      const px = wrap ? wrap.getBoundingClientRect().width : 800;
      const vpSec = px / this.viewState.zoomH;
      let cursorFrac = (clientX - rect.left) / rect.width;
      cursorFrac = Math.max(0, Math.min(1, cursorFrac));
      let targetSec;
      if (useGrabOffset) {
        // Drag the viewport: keep the grab point under the cursor.
        targetSec = cursorFrac * dur - viewportGrabFrac * vpSec;
      } else {
        // Click on empty area: center viewport on the cursor.
        targetSec = cursorFrac * dur - vpSec / 2;
      }
      this.viewState.scrollSec = Math.max(0, Math.min(Math.max(0, dur - vpSec), targetSec));
      this.viewState.autoScroll = false;
    };

    this.track.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      dragging = true;
      const trackRect = this.track.getBoundingClientRect();
      const vpRect = this.viewport.getBoundingClientRect();
      const onViewport = e.clientX >= vpRect.left && e.clientX <= vpRect.right;
      mode = onViewport ? "viewport" : "seek";
      if (onViewport) {
        viewportGrabFrac = (e.clientX - vpRect.left) / Math.max(1, vpRect.width);
      } else {
        viewportGrabFrac = 0;
      }
      seekTo(e.clientX, mode === "viewport");
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      seekTo(e.clientX, mode === "viewport");
    });

    window.addEventListener("mouseup", () => { dragging = false; });
  }

  setCurrentTime(t) {
    if (!this.play) return;
    const frac = t / this.trackData.meta.durationSec;
    this.play.style.left = `${(frac * 100).toFixed(2)}%`;
  }

  _refresh() {
    if (!this.viewport || !this.viewState) return;
    const dur = this.trackData.meta.durationSec;
    const trackRect = this.track.getBoundingClientRect();
    const vpSec = this._viewportSec(trackRect.width);
    const left = (this.viewState.scrollSec / dur * 100).toFixed(2) + "%";
    const width = (vpSec / dur * 100).toFixed(2) + "%";
    this.viewport.style.left = left;
    this.viewport.style.width = width;
    if (this.loopBand) {
      if (this.viewState.loopStart == null || this.viewState.loopEnd == null) {
        this.loopBand.style.display = "none";
      } else {
        const dur = this.trackData.meta.durationSec;
        const left = (this.viewState.loopStart / dur * 100).toFixed(2) + "%";
        const width = ((this.viewState.loopEnd - this.viewState.loopStart) / dur * 100).toFixed(2) + "%";
        this.loopBand.style.left = left;
        this.loopBand.style.width = width;
        this.loopBand.style.display = "";
      }
    }
  }

  _viewportSec(_minimapWidth) {
    const wrap = document.querySelector("#roll-frame .canvas-wrap");
    const px = wrap ? wrap.getBoundingClientRect().width : 800;
    return px / this.viewState.zoomH;
  }
}
