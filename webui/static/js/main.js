import { api } from "./api.js";
import { el, clear } from "./ui/dom.js";
import { mountTopbar } from "./ui/topbar.js";
import { mountTrackPicker } from "./ui/track-picker.js";
import { buildTrackData } from "./data/track-data.js";
import { effectiveTrackData } from "./state/xcheck.js";
import { createViewState } from "./view/view-state.js";
import { PianoRoll } from "./render/pianoroll.js";
import { F0Overlay } from "./render/f0-overlay.js";
import { MicPitch } from "./audio/mic-pitch.js";
import { MicOverlay } from "./render/mic-overlay.js";
import { TabbedSidebar } from "./ui/tabbed-sidebar.js";
import { Transport } from "./ui/transport.js";
import { Minimap } from "./ui/minimap.js";
import { WebAudioEngine } from "./audio/web-audio-engine.js";
import { createAudioEngine } from "./audio/engine-factory.js";
import { autoScrollFor, xToTime } from "./render/coords.js";
import { dispatchKey, showShortcutsModal } from "./ui/shortcuts.js";
import { applyTheme } from "./theme/apply.js";
import { getTheme, subscribe as subscribeTheme } from "./theme/store.js";
import { initTooltipPrefs } from "./ui/tooltip-prefs.js";
import { initColorPrefs } from "./ui/color-prefs.js";
import { showToast } from "./ui/toast.js";

// Phase 4: human-readable mapping for the FallbackMsg reason codes emitted
// by the WASAPI open-chain orchestrator. Codes are short, machine-parseable
// strings of the form "{stage}_failed:{err_label}" — see
// webui/audio_backend/open_chain.py for the producer.
//
// We map the load-bearing combinations explicitly; anything unknown falls
// back to the raw code so the toast still surfaces *something* and we can
// audit it during smoke-tests.
function humanizeFallbackReason(reason) {
  switch (reason) {
    case "exclusive_failed:device_in_use":
      return "Exclusive mode unavailable (device in use by another app). Using Shared mode.";
    case "exclusive_failed:invalid_sample_rate":
      return "Exclusive mode requires the device's hardware sample rate. Using Shared mode.";
    case "exclusive_failed:device_not_found":
      return "Exclusive device not available. Using Shared mode on the same device.";
    case "wasapi_failed:device_in_use":
      return "WASAPI unavailable (device in use). Using MME (higher latency).";
    case "wasapi_failed:invalid_sample_rate":
      return "WASAPI rejected the sample rate. Using MME (higher latency).";
    case "wasapi_failed:device_not_found":
      return "WASAPI device not available. Using MME on the same device.";
    default:
      // Best-effort: surface the raw code so we can see it during testing.
      return `Audio fallback: ${reason}`;
  }
}

const $topbar = document.getElementById("topbar");
const $body   = document.getElementById("body");

let allTracks = [];

// Engine-swap hook for the Settings → Audio engine radio. menus.js calls
// `window.__musiqEngineRebuild()` after persisting the new engine choice;
// we tear the current engine + UI down and re-call loadTrack(currentSlug),
// which goes through createAudioEngine() and rebuilds against the newly
// active engine. Mid-track restart is the documented behaviour — the
// in-flight song time is not preserved (this matches the spec's
// "switch-back-to-WebAudio mid-track works — track restarts" acceptance).
window.__musiqEngineRebuild = () => {
  const slug = new URLSearchParams(location.search).get("slug");
  if (slug) loadTrack(slug);
};

async function boot() {
  // Reapply the stored theme to documentElement. The inline pre-paint script
  // already did this from localStorage, but the theme store hasn't run yet
  // at that point — re-running is idempotent and ensures the in-memory cache
  // is consistent with what's painted.
  applyTheme(getTheme().tokens);
  subscribeTheme((theme) => applyTheme(theme.tokens));
  // Mirror the persisted tooltip show-delay into --tooltip-show-delay so
  // the very first hover honours it without waiting for the user to open
  // Settings. Idempotent; safe to call before any track is loaded.
  initTooltipPrefs();

  // Re-apply any stored pitch-line colour overrides before the first
  // overlay paint, so user picks from a previous session land immediately
  // instead of flashing the theme defaults for one frame.
  initColorPrefs();

  try {
    allTracks = await api.listTracks();
  } catch (e) {
    showFatal(`Could not load track list: ${e.message}`);
    return;
  }
  // Rename hook for the topbar. The rename modal's PATCH response carries
  // the new display_name; mirror it into our cached track list so the next
  // picker open reflects the rename without a full reload.
  window.__musiqUpdateTrackTitle = (slug, title) => {
    const t = allTracks.find((x) => x.slug === slug);
    if (t) t.title = title;
  };
  if (!allTracks.length) {
    showEmpty();
    return;
  }

  const params = new URLSearchParams(location.search);
  let slug = params.get("slug");
  if (!slug || !allTracks.some((t) => t.slug === slug)) {
    slug = [...allTracks].sort((a, b) => b.summary_mtime_ns - a.summary_mtime_ns)[0].slug;
    history.replaceState({ slug }, "", `?slug=${encodeURIComponent(slug)}`);
  }

  await loadTrack(slug);
  window.addEventListener("popstate", (e) => {
    const s = (e.state?.slug) || (new URLSearchParams(location.search).get("slug"));
    if (s) loadTrack(s);
  });
}

let viewState = null;
let pianoRoll = null;
let f0Overlay = null;
let micOverlay = null;
let sidebar = null;
let transport = null;
let minimap = null;
let currentEngine = null;
let currentAbort = null;

async function loadTrack(slug) {
  window.__currentSlug = slug;
  // Tear down the previous track: stop audio, drop listeners.
  if (currentAbort) { currentAbort.abort(); currentAbort = null; }
  if (currentEngine) { try { currentEngine.dispose(); } catch {} currentEngine = null; }
  clear($body);
  $body.classList.remove("viewer-mode");
  $body.appendChild(el("div", { id: "loading", text: `Loading ${slug}…` }));

  let summary, f0;
  try {
    summary = await api.getSummary(slug);
  } catch (e) {
    if (e.status === 404) {
      mountTopbar($topbar, null, { onPickerToggle: openPicker });
      clear($body);
      const available = (e.body?.available || []).join(", ");
      $body.appendChild(el("div", { style: { color: "var(--status-error)", padding: "24px" } }, [
        document.createTextNode("Unknown track: "),
        el("code", { text: slug }),
        document.createTextNode(`. Available: ${available}.`),
      ]));
      return;
    }
    showFatal(`Could not load ${slug}: ${e.message}`);
    return;
  }
  // Fan out the two optional sidecar fetches in parallel — both depend on the
  // summary having succeeded above, but they don't depend on each other.
  // allSettled keeps a slow/broken Last.fm endpoint from blocking F0 (or vice
  // versa); each branch already handles missing data downstream.
  let lastfm;
  [f0, lastfm] = await Promise.all([
    api.getF0(slug).catch(() => null),
    api.getLastfm(slug).catch(() => null),
  ]);

  // Browser tab title — reflect the active track. display_name (user override)
  // beats the on-disk filename; fall back to the file stem if neither is set.
  const tabName = summary?.track?.display_name
    || (summary?.track?.file ? summary.track.file.replace(/\.mp3$/i, "") : null);
  if (tabName) document.title = `${tabName} — MusIQ-Lab`;

  const trackData = buildTrackData(summary, f0, slug, lastfm);
  // Restore the persisted scrollAnchor (edge/center) from a previous session.
  // The transport's anchor pill writes back to this key on every toggle.
  let storedAnchor = "edge";
  try {
    const raw = localStorage.getItem("musiq.scrollAnchor");
    if (raw === "center" || raw === "edge") storedAnchor = raw;
  } catch { /* corrupt/missing — fall back to default */ }
  viewState = createViewState({ scrollAnchor: storedAnchor });
  // Auto-scroll glide state — set true when there's a large gap between
  // the current scroll position and the auto-scroll target (mode toggle,
  // edge crossing, seek, scrub-release). The "time" handler below lerps
  // toward the target until the gap drops under SNAP_THRESHOLD_SEC, then
  // hands off to direct snap-tracking so there's zero steady-state lag.
  let scrollGliding = false;
  viewState.on("glide", () => { scrollGliding = true; });

  const engine = createAudioEngine();
  engine.setDuration(trackData.meta.durationSec);
  currentEngine = engine;
  currentAbort = new AbortController();
  const stemUrls = {
    vocals: api.audioStemUrl(slug, "vocals"),
    bass:   api.audioStemUrl(slug, "bass"),
    guitar: api.audioStemUrl(slug, "guitar"),
    piano:  api.audioStemUrl(slug, "piano"),
    other:  api.audioStemUrl(slug, "other"),
    drums:  api.audioStemUrl(slug, "drums"),
  };
  // NOTE: engine.load() is deferred until after sidebar is mounted (below) —
  // stemLoaded/stemFailed handlers reference `sidebar`, and stems can decode
  // before the sidebar exists. Subscribers must be live before producers start.
  engine.on("time", (t) => {
    if (viewState.autoScroll) {
      const wrap = document.querySelector("#roll-frame .canvas-wrap");
      if (wrap) {
        const w = wrap.getBoundingClientRect().width;
        const target = autoScrollFor(t, viewState, w, trackData.meta.durationSec);
        const delta = target - viewState.scrollSec;
        const SNAP_SEC = 0.005;       // ~5 ms ≈ 0.5 px @ zoom 100 — invisible
        const TRIGGER_SEC = 0.08;     // gap >80 ms → kick off a glide
        const LERP = 0.30;            // per frame; ~140 ms half-life @ 60 Hz
        // Glide depends on a stream of "time" events to drive the lerp
        // to completion. While paused the engine emits ONE "time" event
        // per seek and then goes quiet, so any partial glide would
        // strand the cursor offscreen. Snap directly when not playing.
        if (!engine.isPlaying) {
          viewState.scrollSec = target;
          scrollGliding = false;
        } else if (scrollGliding) {
          if (Math.abs(delta) < SNAP_SEC) {
            scrollGliding = false;
            viewState.scrollSec = target;
          } else {
            viewState.scrollSec = viewState.scrollSec + delta * LERP;
          }
        } else if (Math.abs(delta) > TRIGGER_SEC) {
          scrollGliding = true;
          viewState.scrollSec = viewState.scrollSec + delta * LERP;
        } else {
          // Steady state — direct tracking, zero lag.
          viewState.scrollSec = target;
        }
      }
    }
    setCurrentTime(t);
  });
  engine.on("play",  () => { if (transport) transport.playBtn.textContent = "⏸"; });
  engine.on("pause", () => { if (transport) transport.playBtn.textContent = "▶"; });
  engine.on("stemLoaded", ({ name }) => {
    sidebar?.setStemStatus(name, "loaded");
  });
  engine.on("stemFailed", ({ name, error }) => {
    sidebar?.setStemStatus(name, "missing", error);
  });
  engine.on("stemsReady", ({ failures }) => {
    // Anything that didn't fail and didn't already report loaded had no URL —
    // mark it missing so the user sees the truth instead of a perpetual spinner.
    for (const stem of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
      if (sidebar?.stemStatus?.[stem] === "loading") {
        sidebar.setStemStatus(stem, "missing", failures?.[stem] ?? "no audio");
      }
    }
  });

  // Phase 4: WASAPI engine fallback chain.
  //
  // `fallback` — the server opened a less-specific row than requested
  // (Exclusive → Shared, WASAPI → MME). Surface as a toast so the user
  // knows latency / mode differs from what they picked. The audio still
  // plays.
  engine.on("fallback", (info) => {
    showToast("warning", humanizeFallbackReason(info?.reason));
  });
  // `engineFailed` — the server's open-chain orchestrator could not open
  // any entry. The WasapiEngine is no longer usable; revert the persisted
  // engine choice to "webaudio" and rebuild so the next loadTrack uses
  // the WebAudio engine. This is the documented Phase 4 acceptance — the
  // user sees a toast naming the reason; audio resumes on WebAudio after
  // the rebuild.
  engine.on("engineFailed", (info) => {
    const reason = info?.reason || "unknown";
    console.warn("WASAPI engine unavailable, falling back to WebAudio:", reason);
    try {
      const stored = JSON.parse(localStorage.getItem("musiq.audio") || "{}");
      stored.engine = "webaudio";
      localStorage.setItem("musiq.audio", JSON.stringify(stored));
    } catch { /* corrupt/missing storage — ignore */ }
    showToast("error", `WASAPI engine unavailable: ${reason}. Using WebAudio.`);
    // Defer the rebuild a tick so the current loadTrack call frame can
    // unwind cleanly before we tear everything down to rebuild.
    setTimeout(() => window.__musiqEngineRebuild?.(), 0);
  });

  // Wire view-state loop changes to engine wraparound.
  viewState.on("change", ({ changed }) => {
    if (changed.includes("loopStart") || changed.includes("loopEnd")) {
      engine.setLoop(viewState.loopStart, viewState.loopEnd);
    }
  });

  mountTopbar($topbar, summary, { onPickerToggle: openPicker, slug });
  // Notation toggle (Settings → Pitch notation) re-renders the topbar so
  // the key/scale badges follow the new system. Scoped to the per-track
  // AbortController (aborted at the top of the next loadTrack) so it doesn't
  // accumulate one stale listener per track change.
  document.addEventListener("musiq:notation-changed", () => {
    mountTopbar($topbar, summary, { onPickerToggle: openPicker, slug });
  }, { signal: currentAbort.signal });
  // Cross-check toggle (top-bar K / T pills) — re-render the top-bar so the
  // active segment styling reflects the new choice; refresh the piano-roll
  // with the alt-key view so chord roman + function colors track the active
  // key. Sidebar handles its own remount via a sibling listener in ui/sidebar.js;
  // the f0 overlay + inspector read only key-independent fields.
  document.addEventListener("musiq:xcheck-changed", (ev) => {
    if (ev.detail?.slug !== slug) return;
    mountTopbar($topbar, summary, { onPickerToggle: openPicker, slug });
    if (pianoRoll) {
      // setTrackData marks `dirty=true` internally (pianoroll.js:193); the
      // rAF render loop redraws on the next frame, so the new chord roman +
      // function colors appear without an explicit render() call.
      pianoRoll.setTrackData(effectiveTrackData(trackData));
    }
  }, { signal: currentAbort.signal });

  clear($body);
  const main = el("div", { id: "viewer-main" });
  const side = el("div", { id: "viewer-side" });
  const minimapHost = el("div", { id: "minimap" });
  const rollFrame = el("div", { id: "roll-frame" });
  const transportHost = el("div", { id: "transport" });
  main.appendChild(minimapHost);
  main.appendChild(rollFrame);
  main.appendChild(transportHost);
  const root = el("div", { id: "viewer-root" }, [main, side]);
  $body.classList.add("viewer-mode");
  $body.appendChild(root);

  pianoRoll = new PianoRoll(rollFrame);
  pianoRoll.setTrackData(trackData);
  pianoRoll.setViewState(viewState);

  const canvasWrap = rollFrame.querySelector(".canvas-wrap");
  f0Overlay = new F0Overlay(canvasWrap);
  f0Overlay.setTrackData(trackData);
  f0Overlay.setViewState(viewState);

  // Live mic layer — one MicPitch + one MicOverlay per page load. We
  // attach the MicPitch to window.__musiqMic before the sidebar mounts
  // so sidebar.js can inject the MicRow guarded on its presence.
  if (!window.__musiqMic) {
    window.__musiqMic = new MicPitch({ engine });
  } else {
    // Hot-reload / track-change: keep the existing mic running but
    // re-point its engine reference (engines are re-created per track).
    window.__musiqMic.engine = engine;
    window.__musiqMic.clearBuffer();
  }
  window.__musiqMic.setTrackData(trackData);
  micOverlay?.destroy();
  micOverlay = new MicOverlay(canvasWrap, window.__musiqMic);
  micOverlay.setTrackData(trackData);
  micOverlay.setViewState(viewState);

  // Page-unload cleanup so the OS mic indicator releases promptly. We
  // attach once and idempotently — re-loading a track will re-call this
  // path, but addEventListener with the same handler dedupes by identity
  // and we hold the reference on window so it stays stable.
  if (!window.__musiqMicUnloadAttached) {
    window.__musiqMicUnloadAttached = true;
    window.addEventListener("beforeunload", () => { try { window.__musiqMic?.stop(); } catch { /* */ } });
  }

  new (await import("./ui/inspector.js")).Inspector(canvasWrap, trackData, viewState);

  sidebar = new TabbedSidebar(side);
  sidebar.mount(trackData, viewState, engine);

  minimap = new Minimap(minimapHost);
  minimap.mount(trackData, viewState);

  transport = new Transport(transportHost);
  transport.mount(viewState, engine, trackData.meta.durationSec);

  installInteractions(rollFrame, viewState, trackData, engine, currentAbort.signal);
  setCurrentTime(0);

  // Default vertical view: fit E1..E6 (MIDI 28..88) into the canvas. Wait for
  // the first layout pass so PianoRoll has a real height to fit against; if
  // it's still zero (rare), retry once on the next frame.
  const fitDefault = () => {
    if (!pianoRoll?.fitMidiRange(28, 88)) {
      requestAnimationFrame(() => pianoRoll?.fitMidiRange(28, 88));
    }
  };
  requestAnimationFrame(fitDefault);

  // Now that all subscribers (sidebar, transport, etc) are live, kick off audio.
  engine.load({ sourceUrl: api.audioSourceUrl(slug), stemUrls }).catch((err) => {
    console.error("audio load failed:", err);
  });
}

function setCurrentTime(t) {
  pianoRoll?.setCurrentTime(t);
  sidebar?.setCurrentTime(t);
  transport?.setCurrentTime(t);
  minimap?.setCurrentTime(t);
}

function installInteractions(rollFrame, viewState, trackData, engine, signal) {
  const wrap = rollFrame.querySelector(".canvas-wrap");
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.shiftKey) {
      // Shift+wheel = vertical zoom
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      viewState.zoomV = Math.max(4, Math.min(40, viewState.zoomV * factor));
    } else if (e.ctrlKey) {
      // Ctrl+wheel = horizontal zoom (anchored at cursor)
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const before = wrap.getBoundingClientRect();
      const cursorFrac = (e.clientX - before.left) / before.width;
      const tCursor = viewState.scrollSec + (before.width * cursorFrac) / viewState.zoomH;
      viewState.zoomH = Math.max(20, Math.min(2000, viewState.zoomH * factor));
      viewState.scrollSec = Math.max(0, tCursor - (before.width * cursorFrac) / viewState.zoomH);
      viewState.autoScroll = false;
    } else {
      // Plain wheel = horizontal scroll
      const dx = (e.deltaX !== 0 ? e.deltaX : e.deltaY) * 0.5;
      viewState.scrollSec = Math.max(0, viewState.scrollSec + dx / viewState.zoomH);
      viewState.autoScroll = false;
    }
  }, { passive: false, signal });

  const CLICK_SLOP_PX = 3;
  let dragging = false;
  let wasClick = false;
  let dragStartX = 0, dragStartY = 0;
  let dragStartScroll = 0, dragStartCenter = 0;
  wrap.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest(".auto-badge")) return;
    dragging = true;
    wasClick = true;
    dragStartX = e.clientX; dragStartY = e.clientY;
    dragStartScroll = viewState.scrollSec;
    dragStartCenter = viewState.midiCenter;
  }, { signal });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    if (wasClick && (Math.abs(dx) > CLICK_SLOP_PX || Math.abs(dy) > CLICK_SLOP_PX)) {
      wasClick = false;
      wrap.querySelector("canvas")?.classList.add("dragging");
      // First real movement: this is a drag, not a click. Exit auto-scroll.
      // (scrollAnchor is now user-controlled via the transport pill; don't
      // override it here — the drag just turns off auto-scroll.)
      viewState.update({ autoScroll: false });
    }
    if (wasClick) return;
    const nextScroll = Math.max(0, dragStartScroll - dx / viewState.zoomH);
    // Hand-tool convention: dragging the canvas down pulls higher pitches into view
    // from above, so midiCenter increases. (Y-axis is flipped vs. midi.)
    const nextCenter = Math.max(12, Math.min(120, dragStartCenter + dy / viewState.zoomV));
    viewState.update({ scrollSec: nextScroll, midiCenter: nextCenter });
  }, { signal });
  window.addEventListener("mouseup", (e) => {
    if (!dragging) return;
    if (wasClick) {
      const rect = wrap.getBoundingClientRect();
      const t = Math.max(0, Math.min(trackData.meta.durationSec, xToTime(e.clientX - rect.left, viewState)));
      engine.seek(t);
    }
    dragging = false;
    wasClick = false;
    wrap.querySelector("canvas")?.classList.remove("dragging");
  }, { signal });

  document.addEventListener("keydown", (e) => {
    // Don't capture keys when the user is typing in an input/textarea/contenteditable.
    // Without the contenteditable check, canvas shortcuts (space, digits) fire
    // while editing the lyrics-tab artist/title fields and the rename modal.
    if (e.target?.matches?.("input, textarea, [contenteditable=true]")) return;
    dispatchKey(e, {
      togglePlay: () => engine.isPlaying ? engine.pause() : engine.play(),
      nudgeBack:  () => engine.seek(Math.max(0, engine.currentTime - beatLen(trackData, e.shiftKey))),
      nudgeFwd:   () => engine.seek(Math.min(trackData.meta.durationSec, engine.currentTime + beatLen(trackData, e.shiftKey))),
      seekStart:  () => engine.seek(0),
      seekEnd:    () => engine.seek(trackData.meta.durationSec - 0.1),
      zoomHIn:    () => (viewState.zoomH = Math.min(2000, viewState.zoomH * 1.25)),
      zoomHOut:   () => (viewState.zoomH = Math.max(20, viewState.zoomH * 0.8)),
      resetView:  () => {
        viewState.update({ zoomH: 100, scrollSec: 0, autoScroll: true });
        pianoRoll?.fitMidiRange(28, 88);
      },
      muteHi:     () => {
        const s = viewState.highlightedStem;
        if (sidebar?.stemStatus?.[s] === "missing") return;
        engine.setStemMute(s, !engine.muted[s]);
      },
      soloHi:     () => {
        const s = viewState.highlightedStem;
        if (sidebar?.stemStatus?.[s] === "missing") return;
        engine.setStemSolo(s, !engine.soloed[s]);
      },
      "hi:vocals": () => (viewState.highlightedStem = "vocals"),
      "hi:bass":   () => (viewState.highlightedStem = "bass"),
      "hi:guitar": () => (viewState.highlightedStem = "guitar"),
      "hi:piano":  () => (viewState.highlightedStem = "piano"),
      "hi:other":  () => (viewState.highlightedStem = "other"),
      "hi:drums":  () => (viewState.highlightedStem = "drums"),
      openPicker: () => {
        const picker = document.getElementById("track-picker");
        if (!picker) return;
        if (typeof picker.toggle === "function") picker.toggle();
        else openPicker(picker);
      },
      openHelp:   () => showShortcutsModal(),
      closeAny:   () => {
        document.querySelectorAll(".tp-panel").forEach((p) => p.remove());
        document.querySelectorAll("#app + div, body > div[style*='position: fixed']").forEach((o) => o.remove());
      },
    });
  }, { signal });
}

function beatLen(td, isBar) {
  if (td.downbeats.length < 2) return 0.5;
  const avgBar = (td.downbeats[td.downbeats.length - 1] - td.downbeats[0]) / (td.downbeats.length - 1);
  return isBar ? avgBar : avgBar / 4;
}

function openPicker(picker) {
  const slug = new URLSearchParams(location.search).get("slug");
  mountTrackPicker(picker, allTracks, {
    currentSlug: slug,
    onPick: (t) => {
      history.pushState({ slug: t.slug }, "", `?slug=${encodeURIComponent(t.slug)}`);
      loadTrack(t.slug);
    },
  });
  picker.toggle();
}

function showEmpty() {
  clear($topbar);
  clear($body);
  $body.appendChild(el("div", {
    style: { color: "var(--text-muted)", padding: "24px" },
  }, [
    document.createTextNode("No analyzed tracks. Run "),
    el("code", { text: "python -m analyze <mp3>" }),
    document.createTextNode(" in WSL."),
  ]));
}

function showFatal(msg) {
  clear($body);
  $body.appendChild(el("div", { style: { color: "var(--status-error)", padding: "24px" }, text: msg }));
}

boot();
