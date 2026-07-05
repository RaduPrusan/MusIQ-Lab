// "Live Input" pseudo-stem row in the sidebar, sitting above the existing
// six stem rows. Mirrors the visual anatomy of the regular stem rows
// (colour swatch + label + M button + status dot) plus an expanded
// control sub-row (reference dropdown + device picker + offset slider).
//
// Settings persisted to localStorage under "musiq.mic.*". No auto-start
// on page load — start() requires the M-click user gesture for the
// browser permission flow.

import { el, clear, attachDrag } from "./dom.js";
import { formatPitch, parseKey } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";

const STEM_LABEL = {
  vocals: "Vocals", piano: "Piano", other: "Other",
  guitar: "Guitar", bass: "Bass", drums: "Drums",
};

const LS_OFFSET    = "musiq.mic.offsetMs";
const LS_REF       = "musiq.mic.referenceStem";
const LS_DEVICE    = "musiq.mic.deviceId";
const LS_META_COLLAPSED = "musiq.mic.metaCollapsed";
const LS_TRANSPOSE = "musiq.mic.transpose";

// Transpose bounds mirror MicPitch.setTranspose's clamp — the row clamps
// too so the displayed value never disagrees with what the mic applied.
const TRANSPOSE_MIN = -24;
const TRANSPOSE_MAX = 24;

// Mic icon for the toggle button. stroke="currentColor" so it inherits
// the button's color across idle / hover / .mic-live states (no extra CSS).
const MIC_ICON_SVG = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="9" y1="21" x2="15" y2="21"/></svg>`;

function loadOffset() {
  const n = Number(localStorage.getItem(LS_OFFSET));
  return Number.isFinite(n) ? n : -30;
}
function loadRef() {
  const v = localStorage.getItem(LS_REF);
  return v == null ? "vocals" : v;     // default reference is vocals
}
function loadDevice() {
  return localStorage.getItem(LS_DEVICE) || null;
}
function loadMetaCollapsed() {
  return localStorage.getItem(LS_META_COLLAPSED) === "1";
}
function loadTranspose() {
  const n = Number(localStorage.getItem(LS_TRANSPOSE));
  if (!Number.isFinite(n)) return 0;
  return Math.max(TRANSPOSE_MIN, Math.min(TRANSPOSE_MAX, Math.round(n)));
}
// Always show the sign on positive values ("+3") so a transposed line is
// visually distinct from the untouched default ("0") at a glance.
function fmtTranspose(n) {
  return n > 0 ? `+${n}` : String(n);
}

function availableStems(trackData) {
  const present = [];
  for (const name of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
    const pack = trackData?.notes?.[name];
    if (pack && (pack.t?.length > 0 || pack.drums)) present.push(name);
  }
  return present;
}

export class MicRow {
  // compact: render a slim variant (no collapse chevron, no Match/Offset
  //   sub-meta) plus a Vocals-mute button next to the mic toggle. Used by the
  //   Lyrics tab so the user can drive the mic + vocals without leaving it.
  // engine: required for the Vocals-mute button (compact mode only).
  constructor({ host, micPitch, trackData, engine = null, compact = false }) {
    this.host = host;
    this.mic = micPitch;
    this.trackData = trackData;
    this.engine = engine;
    this.compact = compact;
    this._readoutEl = null;
    this._statusDotEl = null;
    this._refSelectEl = null;
    this._offsetInputEl = null;
    this._mBtnEl = null;
    this._vocalMuteBtnEl = null;
    this._lastReadoutDetail = null;
    this._onSample = (e) => this._updateReadout(e.detail);
    this._onError = (e) => this._showError(e.detail);
    this._onStarted = () => this._setEnabled(true);
    this._onStopped = () => this._setEnabled(false);
    this._onNotationChanged = null;
    this._onStemMuteChanged = null;
    this._onTransposeChanged = null;
    this._transposeValueEl = null;
  }

  mount() {
    // Remove any listeners attached by a previous mount() so repeated
    // mounts (e.g. via setTrackData on track change) don't leak listeners.
    // mic.* handlers are bound in the constructor and dedupe by reference,
    // but _onNotationChanged is a fresh arrow per mount and would
    // accumulate one document listener per call without explicit removal.
    this.mic.removeEventListener("sample", this._onSample);
    this.mic.removeEventListener("error", this._onError);
    this.mic.removeEventListener("started", this._onStarted);
    this.mic.removeEventListener("stopped", this._onStopped);
    if (this._onNotationChanged) {
      document.removeEventListener("musiq:notation-changed", this._onNotationChanged);
      this._onNotationChanged = null;
    }
    if (this._onStemMuteChanged) {
      document.removeEventListener("musiq:stem-mute-changed", this._onStemMuteChanged);
      this._onStemMuteChanged = null;
    }
    if (this._onTransposeChanged) {
      document.removeEventListener("musiq:mic-transpose-changed", this._onTransposeChanged);
      this._onTransposeChanged = null;
    }
    clear(this.host);

    // Apply persisted settings.
    const offset = loadOffset();
    const ref = loadRef();
    const dev = loadDevice();
    const transpose = loadTranspose();
    this.mic.setOffsetMs(offset);
    this.mic.setTranspose(transpose);
    // Reference is only honoured if it exists in this track; else fall back to first present stem.
    const present = availableStems(this.trackData);
    const refToUse = ref === "none" || present.includes(ref)
      ? ref
      : (present[0] ?? "none");
    this.mic.setReferenceStem(refToUse === "none" ? null : refToUse);
    if (dev) this.mic.setDeviceId(dev);

    // Match the existing stem-row anatomy (.track-row 5-column grid:
    // 12px swatch | 1fr name | 36px count | 56px vol | 52px ms). The
    // mic row tweaks the grid to repurpose the count+vol cells as a
    // wider readout cell (see .track-row.mic in track.css), and uses
    // only an M button (solo of mic input makes no sense).
    const statusDot = el("div", {
      class: "status-dot",
      attrs: { title: "Live microphone input. Tip: wear headphones — speaker playback will bleed into the mic and confuse the pitch detector." },
    });
    this._statusDotEl = statusDot;

    // Swatch uses --mic-no-match (the "match dropdown set to none" stroke
    // colour) as a static row identifier — the same hue the pitch line
    // takes when matching is disabled. Independent of the M-button's
    // green "recording active" indicator, which lives on the status-dot.
    const swatch = el("div", {
      class: "swatch",
      style: { background: "var(--mic-no-match)" },
    }, [statusDot]);

    // Title doubles as the collapse toggle for the sub-meta row. Chevron
    // mirrors track-picker.js's ▾ convention; flips to ▸ when collapsed.
    // In compact mode there is no sub-meta, so the title is a plain label.
    const metaCollapsed = loadMetaCollapsed();
    let nameEl;
    if (this.compact) {
      nameEl = el("div", { class: "name mic-name", text: "Live Input" });
    } else {
      const chev = el("span", { class: "chev", text: metaCollapsed ? "▸" : "▾" });
      nameEl = el("div", {
        class: "name mic-name",
        attrs: { role: "button", "aria-label": "Toggle mic options", title: "Toggle mic options" },
        onClick: () => {
          const row = this.host.querySelector(".track-row.mic");
          if (!row) return;
          const nowCollapsed = !row.classList.contains("mic-meta-collapsed");
          row.classList.toggle("mic-meta-collapsed", nowCollapsed);
          chev.textContent = nowCollapsed ? "▸" : "▾";
          try { localStorage.setItem(LS_META_COLLAPSED, nowCollapsed ? "1" : "0"); } catch {}
        },
      }, [chev, document.createTextNode(" Live Input")]);
    }

    const readout = el("div", { class: "count mic-readout", text: "off" });
    this._readoutEl = readout;

    const mBtn = el("div", {
      class: "btn m",
      innerHTML: MIC_ICON_SVG,
      attrs: { title: "Toggle live mic", role: "button", "aria-label": "Toggle live mic" },
      onClick: () => this._toggle(),
    });
    this._mBtnEl = mBtn;
    const msChildren = [mBtn];
    // Compact (Lyrics-tab) variant: a Vocals-mute toggle sits right of the
    // mic button so vocals can be ducked without leaving the tab. Only when
    // an engine is wired and the track actually has a vocals stem.
    if (this.compact && this.engine && present.includes("vocals")) {
      msChildren.push(this._buildVocalMuteBtn());
    }
    // Compact variant has no sub-meta row, so its transpose spinner sits
    // inline, left of the mic/V buttons (the .ms cell autosizes in CSS).
    if (this.compact) {
      msChildren.unshift(this._buildTransposeSpinner(transpose));
    }
    const ms = el("div", { class: "ms" }, msChildren);

    const row = el("div", {
      class: `track-row mic${this.compact ? " compact" : ""}${metaCollapsed ? " mic-meta-collapsed" : ""}`,
    }, [swatch, nameEl, readout, ms]);

    // Sub-meta line (Match dropdown + Offset slider), mirrors .f0-meta /
    // .drum-tight pattern — spans grid-column 2 / -1 via CSS.
    const refSelect = el("select", { class: "mic-ref" });
    const optsForRef = ["none", ...present];
    for (const v of optsForRef) {
      const opt = el("option", { attrs: { value: v }, text: v === "none" ? "none" : STEM_LABEL[v] });
      if (v === refToUse) opt.selected = true;
      refSelect.appendChild(opt);
    }
    refSelect.addEventListener("change", () => {
      const v = refSelect.value;
      localStorage.setItem(LS_REF, v);
      this.mic.setReferenceStem(v === "none" ? null : v);
    });
    this._refSelectEl = refSelect;

    // Offset slider uses the same .vol + .vol-fill div pair as the regular
    // stem volume rows so all three sliders in the app share one DOM shape
    // and one set of CSS rules — including matching rounded corners on
    // both ends of the fill. attachDrag does the click-and-drag plumbing;
    // the bipolar range (-150..+50 ms) is mapped to/from frac (0..1) by
    // the two helpers below.
    const offsetFill = el("div", { class: "vol-fill", style: { width: "0%" } });
    const offsetSlider = el("div", {
      class: "vol mic-offset",
      attrs: { title: "Mic input latency offset (ms). Drag left if your ribbon lags the song." },
    }, [offsetFill]);
    const offsetLabel = el("span", { class: "mic-offset-label", text: `${offset}ms` });
    const fracFromVal = (v) => Math.max(0, Math.min(1, (v + 150) / 200));
    const valFromFrac = (f) => Math.round(-150 + f * 200);
    const renderOffset = (n) => {
      offsetFill.style.width = `${(fracFromVal(n) * 100).toFixed(2)}%`;
      offsetLabel.textContent = `${n}ms`;
    };
    renderOffset(offset);
    attachDrag(offsetSlider, (frac) => {
      const n = valFromFrac(frac);
      renderOffset(n);
      localStorage.setItem(LS_OFFSET, String(n));
      this.mic.setOffsetMs(n);
    });
    this._offsetInputEl = offsetSlider;

    const meta = el("div", { class: "mic-meta" }, [
      el("span", { class: "mic-meta-label", text: "match" }),
      refSelect,
      el("span", { class: "mic-meta-label", text: "offset" }),
      offsetSlider,
      offsetLabel,
    ]);
    // Transpose gets its OWN meta line: the match/offset line is already at
    // capacity in the ~250px sidebar (measured 309px wanted vs 251px
    // available with the spinner inline — it clipped clean out of view and
    // crushed the offset slider to a sliver). Same .mic-meta class so it
    // inherits the flex styling and the mic-meta-collapsed hide rule.
    const meta2 = el("div", { class: "mic-meta mic-meta-transpose" }, [
      el("span", { class: "mic-meta-label", text: "transpose" }),
      this.compact ? null : this._buildTransposeSpinner(transpose),
    ]);
    // Compact (Lyrics-tab) variant omits the Match/Offset sub-meta entirely —
    // those live on the full Track-tab row. The meta nodes are built but left
    // detached (no listeners fire while they're out of the DOM).
    if (!this.compact) { row.appendChild(meta); row.appendChild(meta2); }

    this.host.appendChild(row);

    // Subscribe.
    this.mic.addEventListener("sample", this._onSample);
    this.mic.addEventListener("error", this._onError);
    this.mic.addEventListener("started", this._onStarted);
    this.mic.addEventListener("stopped", this._onStopped);

    // notation-prefs.js dispatches "musiq:notation-changed" on document (not window).
    this._onNotationChanged = () => {
      // Re-render the last seen sample so the new notation system takes effect.
      if (this._lastReadoutDetail) this._updateReadout(this._lastReadoutDetail);
    };
    document.addEventListener("musiq:notation-changed", this._onNotationChanged);

    // Keep the Vocals-mute button in sync when vocals is toggled elsewhere
    // (the Track-tab stem row). Compact mode only.
    if (this._vocalMuteBtnEl) {
      this._onStemMuteChanged = (e) => {
        if (e.detail?.stem === "vocals") {
          this._vocalMuteBtnEl.classList.toggle("on", !!e.detail.muted);
        }
      };
      document.addEventListener("musiq:stem-mute-changed", this._onStemMuteChanged);
    }

    // Keep this row's transpose spinner in sync when transpose is changed
    // on the OTHER surface (Track-tab full row vs Lyrics-tab compact row).
    // The originating row already called mic.setTranspose + saved to
    // localStorage, so the listener only refreshes the displayed value.
    this._onTransposeChanged = (e) => {
      const v = e.detail?.value;
      if (!Number.isInteger(v) || !this._transposeValueEl) return;
      this._transposeValueEl.textContent = fmtTranspose(v);
    };
    document.addEventListener("musiq:mic-transpose-changed", this._onTransposeChanged);

    this._setEnabled(this.mic.isRunning());
  }

  // Vocals-mute toggle for the compact strip. Mirrors the stem row's M
  // button (.btn.m.on = muted, strikethrough) and shares the engine state +
  // the musiq:stem-mute-changed event so both surfaces stay consistent.
  _buildVocalMuteBtn() {
    const muted = !!this.engine?.muted?.vocals;
    const btn = el("div", {
      class: `btn vox${muted ? " on" : ""}`,
      text: "V",
      attrs: { role: "button", title: "Mute vocals", "aria-label": "Mute vocals" },
      onClick: (e) => {
        e.stopPropagation();
        const next = !this.engine?.muted?.vocals;
        this.engine?.setStemMute("vocals", next);
        btn.classList.toggle("on", next);
        document.dispatchEvent(new CustomEvent("musiq:stem-mute-changed", { detail: { stem: "vocals", muted: next } }));
      },
    });
    this._vocalMuteBtnEl = btn;
    return btn;
  }

  // Semitone transpose spinner (▼ value ▲), shared by both variants: the
  // full row hosts it in the .mic-meta sub-row, the compact row inline
  // next to the mic/V buttons. Custom steppers (not a native
  // <input type="number">) so the control matches the app's dark button
  // aesthetic — native spinner arrows don't restyle reliably.
  _buildTransposeSpinner(initial) {
    const valueEl = el("span", {
      class: "mic-transpose-value",
      text: fmtTranspose(initial),
      attrs: { title: "Live-mic transpose (semitones)" },
    });
    this._transposeValueEl = valueEl;
    const stepBtn = (delta, glyph, label) => el("div", {
      class: `mic-transpose-btn ${delta > 0 ? "up" : "down"}`,
      text: glyph,
      attrs: { role: "button", title: label, "aria-label": label },
      onClick: (e) => {
        e.stopPropagation();
        this._applyTranspose(this.mic.getTranspose() + delta);
      },
    });
    return el("div", { class: "mic-transpose" }, [
      stepBtn(-1, "▼", "Transpose down 1 semitone"),
      valueEl,
      stepBtn(+1, "▲", "Transpose up 1 semitone"),
    ]);
  }

  _applyTranspose(n) {
    const v = Math.max(TRANSPOSE_MIN, Math.min(TRANSPOSE_MAX, Math.round(n)));
    this.mic.setTranspose(v);
    try { localStorage.setItem(LS_TRANSPOSE, String(v)); } catch {}
    if (this._transposeValueEl) this._transposeValueEl.textContent = fmtTranspose(v);
    // Broadcast so the sibling MicRow (other tab) updates its spinner.
    // Mirrors the musiq:stem-mute-changed wiring.
    document.dispatchEvent(new CustomEvent("musiq:mic-transpose-changed", { detail: { value: v } }));
  }

  unmount() {
    this.mic.removeEventListener("sample", this._onSample);
    this.mic.removeEventListener("error", this._onError);
    this.mic.removeEventListener("started", this._onStarted);
    this.mic.removeEventListener("stopped", this._onStopped);
    if (this._onNotationChanged) {
      document.removeEventListener("musiq:notation-changed", this._onNotationChanged);
    }
    if (this._onStemMuteChanged) {
      document.removeEventListener("musiq:stem-mute-changed", this._onStemMuteChanged);
      this._onStemMuteChanged = null;
    }
    if (this._onTransposeChanged) {
      document.removeEventListener("musiq:mic-transpose-changed", this._onTransposeChanged);
      this._onTransposeChanged = null;
    }
    clear(this.host);
  }

  setTrackData(td) {
    this.trackData = td;
    // Re-mount to refresh the reference dropdown's options.
    this.mount();
  }

  async _toggle() {
    if (this.mic.isRunning()) {
      this.mic.stop();
    } else {
      try { await this.mic.start(); }
      catch { /* error event already dispatched */ }
    }
  }

  _setEnabled(on) {
    // Drive a single `.mic-on` modifier on the row; CSS turns the dot
    // green-glow + M button accent in that state. We deliberately do NOT
    // reuse the stem-loaded/missing classes — those carry stem-audio
    // semantics (.stem-missing dims the swatch + disables controls,
    // which would block the M button we want clickable when off).
    const row = this.host.querySelector(".track-row.mic");
    row?.classList.toggle("mic-on", on);
    this._mBtnEl?.classList.toggle("mic-live", on);
    if (!on) this._readoutEl && (this._readoutEl.textContent = "off");
  }

  _updateReadout(detail) {
    if (!this._readoutEl) return;
    this._lastReadoutDetail = detail;
    const { midi, cents } = detail;
    if (!midi || !Number.isFinite(midi)) { this._readoutEl.textContent = "—"; return; }
    const intMidi = Math.round(midi);
    const keyParse = parseKey(this.trackData?.meta?.key ?? "");
    const system = getNotationSystem();
    let name;
    try {
      name = formatPitch(intMidi, keyParse, system);
    } catch {
      // formatPitch may throw on jsdom edge cases or unparseable keys; fall back.
      const noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
      const oct = Math.floor(intMidi / 12) - 1;
      name = `${noteNames[((intMidi % 12) + 12) % 12]}${oct}`;
    }
    let txt = name;
    if (cents !== null && Number.isFinite(cents)) {
      const sign = cents >= 0 ? "+" : "−";
      txt += `  ${sign}${Math.abs(cents).toFixed(0)}¢`;
    }
    this._readoutEl.textContent = txt;
  }

  _showError(detail) {
    if (!this._readoutEl) return;
    const code = detail?.code ?? "unknown";
    const msg = {
      permission: "Mic access denied",
      "no-device": "No microphone found",
      unsupported: "Browser unsupported",
      disconnected: "Mic disconnected",
      "device-busy": "Mic in use by another app",
      "device-constraints": "Mic settings not supported by this device",
    }[code] ?? detail?.message ?? "Mic error";
    this._readoutEl.textContent = msg;
  }
}
