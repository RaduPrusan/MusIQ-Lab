import { el, clear } from "./dom.js";
import { api } from "../api.js";

export class LyricsTab {
  constructor(host) {
    this.host = host;
    this.slug = null;
    this.engine = null;
    this.viewState = null;
    this.data = null;
    this.activeIndex = -1;
    this._scrollSuspendedUntil = 0;
    this._fetchInFlight = false;
    this._mounted = false;
    this._scrollEl = null;
    // Pre-fetch seed for the header. Read by _buildHeader when this.data
    // hasn't loaded yet, so the very first render shows the rename's
    // artist/title instead of "Unknown · Unknown".
    this._seedMeta = null;
  }

  mount(trackData, viewState, engine) {
    this.slug = trackData.meta.slug;
    this.viewState = viewState;
    this.engine = engine;
    this._mounted = true;
    this._seedMeta = _splitDisplayName(trackData.meta.displayName);
    this._render();
    // Cross-tab handoff: the topbar rename modal calls this after a save so
    // the lyrics header reflects the new artist/title. Same pattern as
    // window.__musiqClaudeAsk. If a fresh artist/title is passed, merge it
    // into the in-memory data so the user sees an immediate header update;
    // otherwise (e.g. tab not yet activated) drop the cache and lazy-load.
    window.__musiqLyricsRefreshMeta = (newMeta) => {
      if (newMeta) {
        // Update the seed so the header stays correct even before lyrics data
        // (re)loads — covers both the data-present and data-absent paths.
        this._seedMeta = { artist: newMeta.artist || "", title: newMeta.title || "" };
      }
      if (newMeta && this.data?.meta) {
        Object.assign(this.data.meta, newMeta);
        this._render();
      } else {
        this.data = null;
        this._lazyLoad();
      }
    };
  }

  // Called when the tab becomes active. Lazy-load on first activation.
  onActivate() {
    if (!this.data && !this._fetchInFlight) this._lazyLoad();
  }

  setCurrentTime(t) {
    if (!this.data?.has_sync) return;
    const lines = this.data.lines;
    if (!lines.length) return;
    let lo = 0, hi = lines.length - 1, idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].time_sec <= t) { idx = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    if (idx !== this.activeIndex) {
      this.activeIndex = idx;
      this._refreshActive();
    }
  }

  highlightLineByIndex(idx) {
    this.activeIndex = idx;
    this._refreshActive(true);
  }

  async _lazyLoad() {
    // _fetchInFlight gates _render: while true, the body shows "Loading…"
    // and the header keeps the last good meta. Set to false BEFORE each
    // _render call that has data, so the gate doesn't suppress the lyrics
    // body. The finally is a safety net for the catch path.
    this._fetchInFlight = true;
    this._render();
    try {
      const cached = await api.getLyrics(this.slug);
      if (cached) {
        this.data = cached;
        this._fetchInFlight = false;
        this._render();
        return;
      }
      const fetched = await api.fetchLyrics(this.slug, {});
      this.data = fetched;
      this._fetchInFlight = false;
      this._render();
    } catch (e) {
      this._renderError(e.message || "fetch failed");
    } finally {
      this._fetchInFlight = false;
    }
  }

  _render() {
    clear(this.host);
    const header = this._buildHeader();
    const scroll = el("div", { class: "lyrics-scroll" });
    this.host.appendChild(header);
    this.host.appendChild(scroll);
    this._scrollEl = scroll;

    // While a fetch is in flight, show a body-level loader and bail before
    // rendering lines/plain-text. The header still reflects the last good
    // meta (set by the rename) — important so a Refetch doesn't visually
    // wipe the rename to "Unknown" mid-request.
    if (this._fetchInFlight) {
      scroll.appendChild(el("div", { class: "lyrics-empty", text: "Loading lyrics…" }));
      return;
    }
    if (!this.data) {
      scroll.appendChild(el("div", { class: "lyrics-empty", text: "Open this tab to load lyrics." }));
      return;
    }
    if (this.data.has_sync) {
      this.data.lines.forEach((line, i) => {
        const lineEl = el("div", {
          class: "lyric-line",
          text: line.text || "·",
          attrs: { "data-i": String(i) },
          onClick: () => {
            // Engage auto-scroll BEFORE seek so the synchronous "time"
            // event handler sees autoScroll=true and snaps the canvas
            // to the lyric's position. Without this, a paused lyric
            // click would jump engine.currentTime but leave the cursor
            // offscreen. Mirrors the scrub-bar reorder in transport.js.
            this.viewState?.update({ autoScroll: true });
            this.viewState?.triggerGlide?.();
            this.engine?.seek(line.time_sec);
          },
        });
        scroll.appendChild(lineEl);
      });
      // After render, reflect the current playhead position if any.
      this._refreshActive();
    } else if (this.data.plain_text) {
      const pre = el("pre", { class: "lyrics-plain", text: this.data.plain_text });
      scroll.appendChild(pre);
      scroll.appendChild(el("div", { class: "lyrics-banner", text: "No timing data — only plain text." }));
    } else {
      scroll.appendChild(el("div", { class: "lyrics-empty", text: "No lyrics found." }));
    }
    scroll.addEventListener("scroll", () => {
      this._scrollSuspendedUntil = performance.now() + 4000;
    }, { passive: true });
  }

  _renderError(msg) {
    clear(this.host);
    this.host.appendChild(this._buildHeader());
    this.host.appendChild(el("div", { class: "lyrics-empty lyrics-error", text: msg }));
  }

  _buildHeader() {
    // Prefer real lyrics meta when present; otherwise fall back to the
    // mount-time seed (split from the rename's display_name) so the header
    // shows correct artist/title during the initial fetch.
    const meta = this.data?.meta ?? this._seedMeta ?? {};
    const head = el("div", { class: "lyrics-header" });

    // Read-only display: the rename pencil in the topbar is the canonical
    // edit surface. We render placeholders only when the field is genuinely
    // unknown (server's identify_track can return ("", stem) for filenames
    // without ` - `, so a title that equals the slug is treated as missing).
    const titleIsFallback = !meta.title || meta.title === this.slug;
    const artistIsFallback = !meta.artist;
    const ARTIST_PLACEHOLDER = "Unknown artist";
    const TITLE_PLACEHOLDER = "Unknown title";

    const artist = el("div", {
      class: "lyrics-artist" + (artistIsFallback ? " is-placeholder" : ""),
      text: artistIsFallback ? ARTIST_PLACEHOLDER : meta.artist,
    });
    const sep = el("span", { class: "lyrics-sep", text: "·" });
    const title = el("div", {
      class: "lyrics-title" + (titleIsFallback ? " is-placeholder" : ""),
      text: titleIsFallback ? TITLE_PLACEHOLDER : meta.title,
    });

    const refreshWrap = el("div", { class: "lyrics-refresh-wrap" });
    const refreshBtn = el("button", { class: "lyrics-refresh", text: "⟳ ▾", attrs: { type: "button", title: "Refresh options" } });

    const menu = el("div", { class: "lyrics-refresh-menu hidden" });

    const itemRefetch = el("button", {
      class: "menu-item", attrs: { type: "button" }, text: "Refetch from LRCLIB",
      onClick: async () => {
        menu.classList.add("hidden");
        // Empty body: server consults its source-of-truth chain
        // (cached lyrics meta → user_meta.json display_name → filename).
        // Don't null this.data — the header reads meta from it, and going
        // to null would flash "Unknown artist · Unknown title" mid-request
        // even though the rename is still on disk. _render's _fetchInFlight
        // branch shows a body-level loader and leaves the header alone.
        this._fetchInFlight = true;
        this._render();
        try {
          await api.deleteLyrics(this.slug);
          this.data = await api.fetchLyrics(this.slug, {});
        } catch (e) {
          this._fetchInFlight = false;
          this._renderError(e.message || "fetch failed");
          return;
        } finally {
          this._fetchInFlight = false;
        }
        this._render();
      },
    });

    const itemAskClaude = el("button", {
      class: "menu-item", attrs: { type: "button" }, text: "Ask Claude to find lyrics",
      onClick: () => {
        menu.classList.add("hidden");
        // Cross-tab handoff. The Claude tab (Task 20) will register
        // window.__musiqClaudeAsk; until then this is a graceful no-op.
        if (!window.__musiqClaudeAsk) return;
        // Read from cached meta (set by the rename or a prior fetch). Treat
        // a title equal to the slug as "unknown" — same fallback rule the
        // header uses — so we never echo the slug into the prompt.
        const m = this.data?.meta ?? {};
        const a = m.artist || "";
        const t = (m.title && m.title !== this.slug) ? m.title : "";
        // Always force a re-fetch from this entry point — the user
        // explicitly asked Claude to find lyrics, which usually means the
        // cached set is wrong or missing. force=true makes fetch_lyrics
        // invalidate the cache before hitting LRCLIB.
        let text;
        if (a && t) {
          text = `Please find lyrics for "${t}" by ${a} and call fetch_lyrics with force=true.`;
        } else {
          const hints = [];
          if (a) hints.push(`artist is "${a}"`);
          if (t) hints.push(`title is "${t}"`);
          const hint = hints.length ? ` Known so far: ${hints.join(", ")}.` : "";
          text = `Please find lyrics for the current track. Infer the artist and song title from its slug "${this.slug}" (web-search if unsure).${hint} Then call fetch_lyrics with force=true.`;
        }
        window.__musiqClaudeAsk(text);
      },
    });

    const itemPaste = el("button", {
      class: "menu-item", attrs: { type: "button" }, text: "Paste lyrics manually",
      onClick: () => {
        menu.classList.add("hidden");
        this._showPasteDialog();
      },
    });

    menu.appendChild(itemRefetch);
    menu.appendChild(itemAskClaude);
    menu.appendChild(itemPaste);

    refreshBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.classList.toggle("hidden");
    });
    // Close on outside-click. Bind once per header build; the listener checks
    // that the menu is currently open so it's a cheap no-op when not.
    const closeOnOutside = (e) => {
      if (!refreshWrap.contains(e.target)) menu.classList.add("hidden");
    };
    document.addEventListener("click", closeOnOutside);
    // Stash the listener on the wrap so re-renders don't accumulate global handlers.
    if (this._closeOnOutside) document.removeEventListener("click", this._closeOnOutside);
    this._closeOnOutside = closeOnOutside;

    refreshWrap.appendChild(refreshBtn);
    refreshWrap.appendChild(menu);

    head.appendChild(artist);
    head.appendChild(sep);
    head.appendChild(title);
    head.appendChild(refreshWrap);
    return head;
  }

  _showPasteDialog() {
    const overlay = el("div", { class: "paste-overlay" });
    const card = el("div", { class: "paste-card" });
    const ta = el("textarea", { class: "paste-textarea", attrs: { rows: "14", placeholder: "Paste plain or LRC lyrics here…" } });
    const submit = el("button", { class: "btn", attrs: { type: "button" }, text: "Save" });
    const cancel = el("button", { class: "btn", attrs: { type: "button" }, text: "Cancel" });
    const close = () => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); };
    submit.addEventListener("click", async () => {
      const text = ta.value.trim();
      if (!text) { close(); return; }
      try {
        this.data = await api.pasteLyrics(this.slug, text);
        close();
        this._render();
      } catch (e) {
        close();
        this._renderError(e.message || "paste failed");
      }
    });
    cancel.addEventListener("click", close);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    card.appendChild(ta);
    card.appendChild(el("div", { class: "row" }, [submit, cancel]));
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    ta.focus();
  }

  _refreshActive(forceScroll = false) {
    if (!this._scrollEl) return;
    for (const node of this._scrollEl.querySelectorAll(".lyric-line")) {
      const i = +node.dataset.i;
      node.classList.toggle("active", i === this.activeIndex);
    }
    if (this.activeIndex >= 0 && (forceScroll || performance.now() > this._scrollSuspendedUntil)) {
      const node = this._scrollEl.querySelector(`.lyric-line[data-i="${this.activeIndex}"]`);
      if (node) {
        const top = node.offsetTop - this._scrollEl.clientHeight * 0.33;
        this._scrollEl.scrollTo({ top, behavior: "smooth" });
      }
    }
  }
}

// Mirror of webui/webui/user_meta.py split_artist_title — split on FIRST
// " - ". No separator means "all title" so we don't invent an artist.
// Returns null for empty/missing input so callers can use ?? for fallback.
function _splitDisplayName(name) {
  if (!name) return null;
  const i = name.indexOf(" - ");
  if (i === -1) return { artist: "", title: name.trim() };
  return { artist: name.slice(0, i).trim(), title: name.slice(i + 3).trim() };
}
