import { el } from "./dom.js";

/**
 * TabBar — manages a horizontal tab strip and a panel container that
 * shows one panel at a time. Each tab gets a host element (a div) that
 * persists across activations; consumers render into it.
 */
export class TabBar {
  constructor(host, tabs, opts = {}) {
    this.host = host;
    this.tabs = tabs; // [{ id, label, onActivate?, onDeactivate? }]
    this.opts = opts;
    this.panelHosts = new Map();
    this._currentId = null;
    this._build();
  }

  _build() {
    this.strip = el("div", { class: "tab-strip" });
    this.panels = el("div", { class: "tab-panels" });
    this.host.appendChild(this.strip);
    this.host.appendChild(this.panels);

    for (const t of this.tabs) {
      const btn = el("button", {
        class: "tab",
        text: t.label,
        attrs: { type: "button", "data-tab": t.id },
        onClick: () => this.activate(t.id),
      });
      this.strip.appendChild(btn);
      const panel = el("div", { class: "tab-panel", attrs: { "data-tab": t.id } });
      this.panels.appendChild(panel);
      this.panelHosts.set(t.id, panel);
    }
  }

  /** Returns the host element (div) for tab `id`, even when inactive. */
  panelFor(id) { return this.panelHosts.get(id); }

  current() { return this._currentId; }

  activate(id) {
    if (this._currentId === id) return;
    if (!this.panelHosts.has(id)) return;
    const prev = this.tabs.find((t) => t.id === this._currentId);
    if (prev?.onDeactivate) prev.onDeactivate();
    for (const btn of this.strip.querySelectorAll(".tab")) {
      btn.classList.toggle("active", btn.dataset.tab === id);
    }
    for (const p of this.panels.querySelectorAll(".tab-panel")) {
      p.classList.toggle("active", p.dataset.tab === id);
    }
    this._currentId = id;
    const next = this.tabs.find((t) => t.id === id);
    if (next?.onActivate) next.onActivate();
    if (this.opts.persist) {
      try { localStorage.setItem(this.opts.persist, id); } catch {}
    }
  }
}
