import { TabBar } from "./tabs.js";
import { Sidebar } from "./sidebar.js";
import { LyricsTab } from "./lyrics-tab.js";
import { ClaudeTab } from "./claude-tab.js";

const STORAGE_KEY = "musiq:activeTab";

/**
 * TabbedSidebar wraps the existing Sidebar (Tab 1) and stubs Tabs 2 + 3.
 * The Tab 2 (Claude) and Tab 3 (Lyrics) panels are populated by their
 * dedicated modules in later tasks.
 */
export class TabbedSidebar {
  constructor(host) {
    this.host = host;
    this.bar = null;
    this.trackSidebar = null;
    this.claudeTab = null;
    this.lyricsTab = null;
  }

  mount(trackData, viewState, engine) {
    this.host.replaceChildren();

    // Closure trick: lyricsTabInstance is captured by the onActivate callback
    // before this.lyricsTab exists, since TabBar reads onActivate from the
    // tabs array at construction time.
    let lyricsTabInstance = null;

    this.bar = new TabBar(this.host, [
      { id: "track",  label: "Track" },
      { id: "lyrics", label: "Lyrics", onActivate: () => lyricsTabInstance?.onActivate() },
      { id: "claude", label: "Assistant" },
    ], { persist: STORAGE_KEY });

    // Tab 1 — existing sidebar
    this.trackSidebar = new Sidebar(this.bar.panelFor("track"));
    this.trackSidebar.mount(trackData, viewState, engine);

    // Tab 3 — Lyrics (built before Claude so Tab 2 can reference it for
    // cross-tab handoff and ui_action dispatch).
    this.lyricsTab = new LyricsTab(this.bar.panelFor("lyrics"));
    this.lyricsTab.mount(trackData, viewState, engine);
    lyricsTabInstance = this.lyricsTab;

    // Tab 2 — Claude
    this.claudeTab = new ClaudeTab(this.bar.panelFor("claude"));
    this.claudeTab.mount({
      trackData,
      viewState,
      engine,
      tabbedSidebar: this,
      lyricsTab: this.lyricsTab,
    });

    // Restore last-used tab (and trigger its onActivate if applicable).
    let active = "track";
    try { active = localStorage.getItem(STORAGE_KEY) || "track"; } catch {}
    this.bar.activate(active);
  }

  // Pass-through methods the rest of main.js calls.
  setCurrentTime(t) {
    this.trackSidebar?.setCurrentTime(t);
    this.lyricsTab?.setCurrentTime?.(t);
  }
  setStemStatus(name, status, detail) {
    this.trackSidebar?.setStemStatus(name, status, detail);
  }
  get stemStatus() { return this.trackSidebar?.stemStatus ?? {}; }
}
