import { el, clear, attachDrag } from "./dom.js";
import { parseKey, reformatRootedName, respellPitchString, formatChordShorthand } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";
import { getF0Prefs, setF0Prefs } from "../music/f0-prefs.js";
import { pitchChildren } from "./pitch-label.js";
import { renderMetadataCard } from "../sidebar/metadata-card.js";
import { renderTagsSection } from "../sidebar/tags-row.js";
import { renderAcousticProfile } from "../sidebar/acoustic-profile.js";
import { renderCrosscheckCard } from "../sidebar/crosscheck-card.js";
import { effectiveTrackData, getXcheck } from "../state/xcheck.js";
import { MicRow } from "./mic-row.js";

// Mount a card whose renderer returns a pre-escaped HTML string into `host`.
// Every renderer wired through here (Metadata, Cross-check, Acoustic Profile,
// Last.fm) runs all interpolated values through escapeHtml at the source — see
// each module's escapeHtml usage — so parsing via a <template> element does
// not introduce an XSS path. Empty/falsy `html` is a no-op so callers can pass
// renderer output directly without a guard.
function _mountCardHtml(host, html) {
  if (!html) return;
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  host.appendChild(tpl.content);
}

const STEM_COLORS = {
  vocals: "var(--stem-vocals)", piano: "var(--stem-piano)", other: "var(--stem-other)",
  guitar: "var(--stem-guitar)", bass: "var(--stem-bass)", drums: "var(--stem-drums)",
};
const STEM_LABEL = { vocals: "Vocals", piano: "Piano", other: "Other", guitar: "Guitar", bass: "Bass", drums: "Drums" };

export class Sidebar {
  constructor(host) {
    this.host = host;
    // _origTrackData is the pristine input from main.js; this.trackData is
    // the active *view* derived via effectiveTrackData() at mount time. Two
    // copies because the view's key-dependent fields swap when the xcheck
    // toggle flips, but the source of truth for the swap is the original.
    this._origTrackData = null;
    this.trackData = null;
    this.viewState = null;
    this.engine = null;
    this.sectNow = null;
    this.sectTracks = null;
    this.currentChord = null;
    this.stemStatus = {};   // name -> "loading" | "loaded" | "missing"
    this.showSuppressed = false;  // toggle state for suppressed rows
    this._lastT = 0;
    this._vsHandler = null;       // tracked so remount can detach cleanly
    // Re-render the whole sidebar when the user toggles their pitch-notation
    // preference: chord labels, idle tonic, vocal range, and scale string
    // all show pitch text and need to follow the new system.
    document.addEventListener("musiq:notation-changed", () => {
      if (this._origTrackData) this.mount(this._origTrackData, this.viewState, this.engine);
    });
    // Cross-check (Key/BPM) toggle — remount with the alt-key view applied.
    // We filter by slug so a stray event for a different track (no current
    // user pattern, but cheap defense) doesn't blow away our state.
    document.addEventListener("musiq:xcheck-changed", (ev) => {
      if (!this._origTrackData) return;
      if (ev.detail?.slug && ev.detail.slug !== this._origTrackData.meta?.slug) return;
      this.mount(this._origTrackData, this.viewState, this.engine);
    });
    // Keep each stem's M button in sync when its mute is toggled from another
    // surface (e.g. the Live Input strip on the Lyrics tab). One delegated
    // listener on the persistent Sidebar instance — no per-row leak.
    document.addEventListener("musiq:stem-mute-changed", (ev) => {
      const stem = ev.detail?.stem;
      if (!stem || !this.sectTracks) return;
      const btn = this.sectTracks.querySelector(`.track-row[data-stem="${stem}"] .btn.m`);
      if (btn) btn.classList.toggle("on", !!ev.detail.muted);
    });
  }

  setStemStatus(name, status, detail) {
    this.stemStatus[name] = status;
    if (!this.sectTracks) return;
    const row = this.sectTracks.querySelector(`.track-row[data-stem="${name}"]`);
    if (!row) return;
    row.classList.remove("stem-loading", "stem-loaded", "stem-missing");
    row.classList.add(`stem-${status}`);
    const dot = row.querySelector(".status-dot");
    if (dot) {
      dot.title = status === "missing"
        ? `Audio not available${detail ? ` — ${detail}` : ""}`
        : status === "loading" ? "Loading audio…"
        : "Audio loaded";
    }
    if (status === "missing") {
      const count = row.querySelector(".count");
      if (count) count.textContent = "no audio";
    }
  }

  mount(trackData, viewState, engine) {
    // Detach any previous viewState listener before remounting, so notation
    // toggles don't leak handlers (mount can be called repeatedly).
    if (this._vsHandler && this.viewState) {
      this.viewState.off("change", this._vsHandler);
    }
    // Remember the original so xcheck-toggle remounts can re-derive the view
    // from the same source. effectiveTrackData returns the input unchanged
    // when the toggle is "analyze" (default) so this is free in the common case.
    this._origTrackData = trackData;
    this.trackData = effectiveTrackData(trackData);
    this.viewState = viewState;
    this.engine = engine;
    clear(this.host);
    this.sectNow = this._buildNowSection();
    this.sectTracks = this._buildTracksSection();
    const sectLoop = this._buildLoopSection();
    const sectFunction = this._buildFunctionSection();
    const sectHarm = this._buildHarmonyStatsSection();
    this.host.appendChild(this.sectNow);
    this.host.appendChild(this.sectTracks);
    this.host.appendChild(sectLoop);
    if (sectFunction) this.host.appendChild(sectFunction);
    this.host.appendChild(sectHarm);
    // Plan C Task 5 (sidebar surfacing): Cross-check card — persistent
    // tempo/key second-opinion vs the Essentia stage. Sits ABOVE the
    // Acoustic Profile because the cross-check is the "trust signal" for
    // the analysis numbers shown in Harmony stats / Now playing — a yellow
    // ⚠ on tempo or key here means "the pipeline number above might be
    // wrong; look at the second opinion." No-op when essentiaAgreement
    // is null/empty (Essentia stage skipped / failed).
    // Pass the current xcheck state so the card can annotate which side is
    // active. getXcheck returns sensible defaults when the slug is unset.
    _mountCardHtml(
      this.host,
      renderCrosscheckCard(
        trackData.essentiaAgreement,
        trackData.meta?.slug ? getXcheck(trackData.meta.slug) : null,
        getNotationSystem(),
      ),
    );
    // Plan A Task 11: Metadata card from summary.identify. Pure HTML-string
    // renderer; returns "" when the track wasn't identified, so this is a
    // no-op for unmatched tracks. The string is pre-escaped at the source
    // (renderMetadataCard runs every interpolated value through escapeHtml),
    // so parsing it via a <template> is safe — no untrusted text reaches
    // the DOM. Sits directly above the Acoustic Profile so the two
    // identity/profile cards read as a pair (request 2026-05-12).
    _mountCardHtml(this.host, renderMetadataCard(trackData));
    // Plan C Task 7: Essentia Acoustic Profile (tempo / LUFS / range /
    // dyn. complexity + optional danceability + mood pills). Sits BELOW
    // the cross-check (raw second-opinion values, no comparison) and ABOVE
    // the Last.fm card (pipeline-derived signal rather than external
    // context). No-op when the essentia stage didn't run (extracted=false).
    _mountCardHtml(this.host, renderAcousticProfile(trackData));
    // Plan B Task 4: Last.fm tags + similar artists. External context, so it
    // sits BELOW the analysis sections. No-op when lastfm.available is false
    // or no tags/similar exist.
    _mountCardHtml(this.host, renderTagsSection(trackData.lastfm));
    this._vsHandler = () => this._refreshTracks();
    viewState.on("change", this._vsHandler);
    // Render the now-card with track-level context immediately on mount so
    // the idle state shows tonic/scale/vocal range instead of a placeholder.
    // Use the last known playhead time so a remount (e.g. notation toggle
    // mid-playback) doesn't snap the time display back to 0:00.
    this._refreshNow(this._lastT);
  }

  setCurrentTime(t) {
    this._lastT = t;
    const c = (this.trackData?.chords ?? []).find((c) => c.start <= t && t < c.end) ?? null;
    if (c?.label === this.currentChord?.label && c?.start === this.currentChord?.start) return;
    this.currentChord = c;
    this._refreshNow(t);
  }

  _refreshNow(t) {
    if (!this.sectNow) return;
    const card = this.sectNow.querySelector(".now-card");
    if (!card) return;
    clear(card);
    const c = this.currentChord;
    const isNoChord = !c || c.label === "N" || c.label === "";

    const system = getNotationSystem();
    // Two-column main row: name on the left, function on the right, both
    // big and centered. Below them, a meta row with the function-category
    // tag (TONIC/DOMINANT/...) on the left and the playhead time on the
    // right. Idle state mirrors the structure with tonic letter on the
    // left and scale text on the right (smaller, since scale strings can
    // be long like "E natural minor").
    let leftCol, rightCol, tagEl;
    if (isNoChord) {
      const td = this.trackData;
      const tonicRaw = tonicFromKey(td?.meta?.key);
      const tonic = tonicRaw ? reformatRootedName(tonicRaw, system) : "—";
      const scaleText = reformatRootedName(td?.meta?.scale || "", system);
      leftCol = el("div", { class: "now-col now-col-name now-col-tonic", text: tonic });
      rightCol = el("div", { class: "now-col now-col-fn now-col-scale", text: scaleText });
      if (td?.vocalRange?.low && td?.vocalRange?.high) {
        const keyParse = parseKey(td?.meta?.key ?? "");
        const lo = respellPitchString(td.vocalRange.low, keyParse, system);
        const hi = respellPitchString(td.vocalRange.high, keyParse, system);
        tagEl = el("span", { class: "tag tag-context" }, [
          "vocal range ",
          ...pitchChildren(lo),
          "–",
          ...pitchChildren(hi),
        ]);
      }
    } else {
      const keyParse = parseKey(this.trackData?.meta?.key ?? "");
      const chordName = reformatRootedName(formatChordShorthand(c.label), system, keyParse);
      const roman = (c.roman && c.roman.length) ? c.roman : "—";
      leftCol = el("div", { class: "now-col now-col-name", text: chordName });
      rightCol = el("div", { class: "now-col now-col-fn", text: roman });
      tagEl = c.fn ? el("span", { class: `tag fn-${c.fn}`, text: fnLabel(c.fn) }) : null;
    }
    const main = el("div", { class: "now-main" }, [leftCol, rightCol]);
    // The meta row reserves height (via min-height in CSS) even when there's
    // no tag, so the card doesn't jump in height between chord changes that
    // have/lack fn tags. Time uses margin-left: auto to stay right-aligned
    // whether the tag is present or not.
    const metaRow = el("div", { class: "now-meta-row" }, [
      tagEl,
      el("span", { class: "now-time", text: formatNowTime(t) }),
    ]);
    card.appendChild(main);
    card.appendChild(metaRow);
  }

  _refreshTracks() {
    if (!this.sectTracks) return;
    for (const row of this.sectTracks.querySelectorAll(".track-row")) {
      const stem = row.dataset.stem;
      row.classList.toggle("highlighted", stem === this.viewState.highlightedStem);
    }
  }

  _buildNowSection() {
    // Placeholder content gets replaced immediately by _refreshNow(0) on
    // mount — kept minimal here so an unmounted card briefly shows neutral
    // dashes rather than empty whitespace.
    const sect = el("div", { class: "side-section" }, [
      el("h4", { text: "Now playing" }),
      el("div", { class: "now-card" }, [
        el("div", { class: "now-main" }, [
          el("div", { class: "now-col now-col-name", text: "—" }),
          el("div", { class: "now-col now-col-fn", text: "—" }),
        ]),
        el("div", { class: "now-meta-row" }, [
          el("span", { class: "now-time", text: "0:00.00" }),
        ]),
      ]),
    ]);
    return sect;
  }

  _buildTracksSection() {
    const sect = el("div", {
      class: "side-section",
      attrs: { title: "Click a row to highlight that stem on the canvas" },
    });

    // ---- header row: title + optional "show suppressed" toggle ----
    // We'll insert the toggle (as a flex sibling, not inside the h4) after
    // we know how many suppressed stems there are.
    const heading = el("h4", { text: "Stems" });
    const headerRow = el("div", { class: "side-section-header" }, [heading]);
    sect.appendChild(headerRow);

    // Live Input pseudo-stem row — sits above the regular six. Only mounted
    // if the page has a MicPitch instance attached to window.__musiqMic
    // (wired in main.js). Falling back to "not mounted" keeps existing
    // tests + headless renders unaffected.
    if (window.__musiqMic) {
      const micHost = el("div", { class: "mic-row-host" });
      sect.appendChild(micHost);
      if (this._micRow) this._micRow.unmount();
      this._micRow = new MicRow({
        host: micHost,
        micPitch: window.__musiqMic,
        trackData: this.trackData,
      });
      this._micRow.mount();
    }

    const suppressedStems = [];  // any stem the pipeline declared transcribed:false
                                  // (melodic-presence gate OR drums RMS/onset gate)

    const MELODIC_STEMS = new Set(["vocals", "piano", "other", "guitar", "bass"]);

    for (const stem of ["vocals", "piano", "other", "guitar", "bass", "drums"]) {
      const pack = this.trackData.notes[stem];
      const isCurrent = stem === this.viewState.highlightedStem;

      // Any stem the pipeline declared transcribed:false gets the suppressed
      // visual treatment (faded row, hidden behind "show suppressed" toggle).
      // Two gating paths converge here: the melodic 3-signal presence gate
      // surfaces a `presence` block; the drums RMS / onset-count gate
      // surfaces `ratio_db` (and friends) with no presence block. Either
      // signal counts as "suppressed" for UI purposes.
      const isSuppressed = pack?.transcribed === false && (
        pack?.presence != null ||
        (stem === "drums" && pack?.ratioDb != null)
      );
      // Healthy melodic stem with presence diagnostics (shown as underline + tooltip).
      const isHealthyMelodic = MELODIC_STEMS.has(stem) && pack?.transcribed !== false && pack?.presence != null;

      // Drums has hit counts (onsets across 5 substems) instead of pitched
      // notes — packStem stashes the total in onsetTotal. Other stems show
      // their note count, "no drums" when the gate fired, or "audio" when
      // the stage didn't run at all.
      let countText;
      if (pack?.transcribed === false) {
        // Drums-specific text wins over the generic "(suppressed)" so the user
        // sees the more informative gate-decision reason. The row still gets
        // the suppressed CSS class and toggle-hide behavior either way.
        if (stem === "drums" && pack?.ratioDb != null) {
          countText = "no drums";
        } else if (isSuppressed) {
          countText = "(suppressed)";
        } else {
          countText = "audio";
        }
      } else if (pack?.drums) {
        countText = String(pack.onsetTotal);
      } else {
        countText = String(pack?.t.length ?? 0);
      }
      const initialStatus = this.stemStatus[stem] ?? "loading";

      const guard = (fn) => (e) => {
        e.stopPropagation();
        if (this.stemStatus[stem] === "missing") return;
        if (pack?.transcribed === false) return;  // suppress gate: block controls
        fn(e);
      };

      const muteBtn = el("div", { class: `btn m${this.engine?.muted?.[stem] ? " on" : ""}`, text: "M",
        onClick: guard(() => {
          const next = !this.engine?.muted?.[stem];
          this.engine?.setStemMute(stem, next);
          muteBtn.classList.toggle("on", next);
          document.dispatchEvent(new CustomEvent("musiq:stem-mute-changed", { detail: { stem, muted: next } }));
        }),
      });
      const soloBtn = el("div", { class: "btn s", text: "S",
        onClick: guard(() => {
          const next = !this.engine?.soloed?.[stem];
          this.engine?.setStemSolo(stem, next);
          soloBtn.classList.toggle("on", next);
        }),
      });

      const volFill = el("div", { class: "vol-fill", style: { width: "100%" } });
      const vol = el("div", { class: "vol", attrs: { title: "Volume" } }, [volFill]);
      attachDrag(vol, (frac) => {
        if (this.stemStatus[stem] === "missing") return;
        if (pack?.transcribed === false) return;
        volFill.style.width = `${(frac * 100).toFixed(0)}%`;
        this.engine?.setStemVolume(stem, frac);
      });

      // Build status dot title. For suppressed melodic stems, include the
      // diagnostic signal table as a native title attribute.
      let statusDotTitle = "Loading audio…";
      if (isSuppressed && pack.presence) {
        statusDotTitle = _buildPresenceTitle(pack);
      }

      const statusDot = el("div", {
        class: "status-dot",
        attrs: { title: statusDotTitle },
      });

      // Swatch carries the healthy-stem presence tooltip when applicable so
      // hovering the colored square shows the same diagnostics that
      // suppressed rows surface via the dot.
      const swatchAttrs = isHealthyMelodic
        ? { title: _buildPresenceTitle(pack, { healthy: true }) }
        : {};
      const swatch = el("div", {
        class: "swatch",
        style: { background: STEM_COLORS[stem] },
        attrs: swatchAttrs,
      }, [statusDot]);

      // For suppressed stems, also put the tooltip on the name label so the
      // whole name area is hoverable (not just the tiny dot).
      const nameEl = el("div", {
        class: "name",
        text: STEM_LABEL[stem],
        attrs: isSuppressed ? { title: statusDotTitle } : {},
      });

      let rowClass = `track-row stem-${initialStatus}${isCurrent ? " highlighted" : ""}`;
      if (isSuppressed) rowClass += " stem-suppressed";

      const countCell = el("div", { class: "count", text: countText });

      // Feature 9: f0 FCPE/PESTO agreement indicator for the vocals row.
      let f0Cell = null;
      let f0Toggles = null;
      if (stem === "vocals" && pack?.transcribed !== false) {
        const agree = _computeF0Agreement(this.trackData.f0);
        if (agree) {
          f0Cell = el("div", {
            class: "f0-conf",
            text: `f0 ${Math.round(agree.pct)}%`,
            attrs: {
              title: `FCPE/PESTO agreement within 50¢: ${agree.pct.toFixed(1)}% over ${agree.voiced.toLocaleString()} voiced frames`,
            },
          });
        }
        if (this.trackData.f0?.fcpe) {
          f0Toggles = _buildF0Toggles();
        }
      }

      const rowChildren = [
        swatch,
        nameEl,
        countCell,
        vol,
        el("div", { class: "ms" }, [muteBtn, soloBtn]),
      ];
      const row = el("div", {
        class: rowClass,
        data: { stem },
        onClick: () => { this.viewState.highlightedStem = stem; },
      }, rowChildren);

      // Feature 8: presence underline for healthy melodic stems.
      // Width is proportional to active_frame_ratio (preferred) or whatever
      // the presence block surfaces. For the `other` stem, in_band_fraction
      // can be null but active_frame_ratio is normally present.
      if (isHealthyMelodic) {
        const ratio = pack.presence?.active_frame_ratio ?? null;
        if (ratio != null && Number.isFinite(ratio)) {
          const pct = Math.max(0, Math.min(1, ratio)) * 100;
          row.appendChild(el("div", {
            class: "presence-bar",
            style: { width: `${pct.toFixed(1)}%`, background: STEM_COLORS[stem] },
            attrs: { title: _buildPresenceTitle(pack, { healthy: true }) },
          }));
        }
      }

      // Feature 11: drum-grid tightness sub-line under the drums row.
      if (stem === "drums" && pack?.transcribed !== false && pack?.drums) {
        const tight = _computeDrumTightness(this.trackData);
        if (tight) {
          row.appendChild(el("div", {
            class: "drum-tight",
            text: `tight ±${tight.medianMs} ms`,
            attrs: { title: `Median offset of kick+snare from interpolated 4/4 grid (${tight.n} events)` },
          }));
        }
      }

      // f0 cell sits under the vocals row as a sub-line so it doesn't fight
      // the existing 5-column grid. Toggles render on the same line as the
      // confidence reading when both are present (CSS lays them out as flex
      // siblings via the .f0-meta wrapper).
      if (f0Cell || f0Toggles) {
        const meta = el("div", { class: "f0-meta" });
        if (f0Cell) meta.appendChild(f0Cell);
        if (f0Toggles) meta.appendChild(f0Toggles);
        row.appendChild(meta);
      }

      if (isSuppressed) suppressedStems.push({ stem, row });
      sect.appendChild(row);
    }

    // ---- "show suppressed" toggle: only rendered when there are suppressed stems ----
    if (suppressedStems.length > 0) {
      const applyVisibility = () => {
        for (const { row } of suppressedStems) {
          row.style.display = this.showSuppressed ? "" : "none";
        }
        toggleBtn.textContent = this.showSuppressed ? "hide" : "show suppressed";
      };

      // Outlined pill button placed as a flex sibling to the h4 (not
      // nested inside it). Style is owned by `.show-suppressed-btn` in CSS.
      const toggleBtn = el("button", {
        class: "show-suppressed-btn",
        text: this.showSuppressed ? "hide" : "show suppressed",
        onClick: (e) => {
          e.stopPropagation();
          this.showSuppressed = !this.showSuppressed;
          applyVisibility();
        },
      });
      headerRow.appendChild(toggleBtn);

      // Apply initial state
      applyVisibility();
    }

    return sect;
  }

  _buildLoopSection() {
    const sect = el("div", { class: "side-section" });
    const td = this.trackData;
    sect.appendChild(el("h4", { text: `Loop · ${td.loopRoman.length} chords · ${td.loopBands.length} appearances` }));
    const tagRow = el("div");
    for (const r of td.loopRoman) tagRow.appendChild(el("span", { class: "tag rn", text: r }));
    sect.appendChild(tagRow);
    return sect;
  }

  // Feature 6: function distribution. Full-width, labeled segments.
  // Returns null if no chords carry a function tag.
  _buildFunctionSection() {
    const td = this.trackData;
    const fnCounts = { tonic: 0, predominant: 0, dominant: 0, modal_interchange: 0 };
    for (const c of td.chords) {
      if (c.fn && Object.prototype.hasOwnProperty.call(fnCounts, c.fn)) fnCounts[c.fn]++;
    }
    const fnTotal = fnCounts.tonic + fnCounts.predominant + fnCounts.dominant + fnCounts.modal_interchange;
    if (fnTotal === 0) return null;

    const fnColors = {
      tonic: "var(--fn-tonic-fg)",
      predominant: "var(--fn-predominant-fg)",
      dominant: "var(--fn-dominant-fg)",
      modal_interchange: "var(--fn-modal-fg)",
    };
    const fnLabels = {
      tonic: "tonic",
      predominant: "pre-dom",
      dominant: "dominant",
      modal_interchange: "mod-int",
    };
    const fnLabelsLong = {
      tonic: "tonic",
      predominant: "predominant",
      dominant: "dominant",
      modal_interchange: "modal interchange",
    };

    // Compute integer percentages that sum to exactly 100 using the
    // largest-remainder method. Avoids the 101%/99% rounding artifact you
    // get from independent Math.round() calls.
    const order = ["tonic", "predominant", "dominant", "modal_interchange"];
    const raw = order.map((k) => (fnCounts[k] / fnTotal) * 100);
    const floors = raw.map((v) => Math.floor(v));
    let leftover = 100 - floors.reduce((a, b) => a + b, 0);
    const remainders = raw.map((v, i) => ({ i, frac: v - Math.floor(v) }))
      .sort((a, b) => b.frac - a.frac);
    for (let j = 0; j < leftover; j++) floors[remainders[j].i]++;

    const bar = el("div", { class: "fn-bar fn-bar-wide" });
    for (let idx = 0; idx < order.length; idx++) {
      const key = order[idx];
      const n = fnCounts[key];
      if (n === 0) continue;
      const pct = floors[idx];
      bar.appendChild(el("div", {
        class: `fn-seg fn-seg-${key}`,
        style: { width: `${raw[idx].toFixed(3)}%`, background: fnColors[key] },
        attrs: { title: `${fnLabelsLong[key]} — ${n} (${pct}%)` },
      }, [
        el("span", { class: "fn-seg-label", text: fnLabels[key] }),
        el("span", { class: "fn-seg-pct", text: `${pct}%` }),
      ]));
    }

    const sect = el("div", { class: "side-section" }, [
      el("h4", { text: "Function" }),
      bar,
    ]);
    return sect;
  }

  _buildHarmonyStatsSection() {
    const td = this.trackData;
    const sect = el("div", { class: "side-section" }, [el("h4", { text: "Harmony stats" })]);
    sect.appendChild(el("div", { style: { fontSize: "11px" } }, [
      el("div", { style: { color: "var(--text-muted)", fontSize: "9px" }, text: "SCALE" }),
      el("div", { style: { color: "var(--status-success)" }, text: reformatRootedName(td.meta.scale, getNotationSystem()) }),
    ]));

    // ---- MOD-INT block (count + optional Roman chip line) ----
    const modIntChildren = [
      el("div", { style: { color: "var(--text-muted)", fontSize: "9px" }, text: "MOD-INT" }),
      el("div", { style: { color: "var(--fn-modal-fg)" }, text: `${td.modalInterchange} chords` }),
    ];
    // Feature 10: top-3 Roman numerals among modal_interchange chords.
    if (td.modalInterchange > 0) {
      const counts = new Map();
      for (const c of td.chords) {
        if (c.fn !== "modal_interchange") continue;
        const r = c.roman;
        if (!r) continue;
        counts.set(r, (counts.get(r) ?? 0) + 1);
      }
      const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
      if (top.length > 0) {
        const chipRow = el("div", { style: { marginTop: "4px", display: "flex", flexWrap: "wrap", gap: "4px" } });
        for (const [roman, n] of top) {
          chipRow.appendChild(el("span", {
            class: "tag rn",
            text: roman,
            attrs: { title: `${roman} — ${n}` },
          }));
        }
        modIntChildren.push(chipRow);
      }
    }
    sect.appendChild(el("div", { style: { marginTop: "8px", fontSize: "11px" } }, modIntChildren));

    if (td.vocalRange) {
      const system = getNotationSystem();
      const keyParse = parseKey(td?.meta?.key ?? "");
      const lo = respellPitchString(td.vocalRange.low, keyParse, system);
      const hi = respellPitchString(td.vocalRange.high, keyParse, system);
      sect.appendChild(el("div", { style: { marginTop: "8px" } }, [
        el("div", { style: { color: "var(--text-muted)", fontSize: "9px" }, text: "VOCAL RANGE" }),
        el("div", { style: { color: "var(--stem-vocals)", fontSize: "13px", fontWeight: "600" } }, [
          ...pitchChildren(lo),
          " — ",
          ...pitchChildren(hi),
        ]),
      ]));
    }
    return sect;
  }

}

// Build a native `title` string for a melodic stem's presence diagnostics.
// Shows reason (or "Presence (healthy)" when opts.healthy) + a compact
// signal/gate table, with tripped gates flagged.
function _buildPresenceTitle(pack, opts = {}) {
  const p = pack.presence;
  const header = opts.healthy
    ? "Presence (healthy)"
    : (pack.reason ?? "Suppressed by presence gate");
  if (!p) return header;

  const tripped = new Set(p.gates_tripped ?? []);
  const th = p.thresholds ?? {};

  const maskFlag  = tripped.has("masking")    ? " ◀" : "";
  const actFlag   = tripped.has("active")     ? " ◀" : "";
  const bandFlag  = tripped.has("in_band")    ? " ◀" : "";

  const maskLine = `Masking    ${p.masking_ratio_db?.toFixed(1) ?? "??"} dB    (gate ${th.masking_db?.toFixed(1) ?? "??"}  dB)${maskFlag}`;
  const actLine  = `Active     ${p.active_frame_ratio != null ? (p.active_frame_ratio * 100).toFixed(1) : "??"}%     (gate ${th.active_ratio != null ? (th.active_ratio * 100).toFixed(1) : "??"}%)${actFlag}`;
  const bandLine = `In-band    ${p.in_band_fraction != null ? Math.round(p.in_band_fraction * 100) : "??"}%          (gate ${th.in_band_fraction != null ? Math.round(th.in_band_fraction * 100) : "??"}%)${bandFlag}`;

  return [header, "", maskLine, actLine, bandLine].join("\n");
}

// Feature 9: FCPE/PESTO agreement within 50 cents over voiced frames.
// Returns null if there's no f0 data or no frames are voiced in both estimators.
// Three checkboxes (Consensus / FCPE / PESTO) that drive f0-prefs. Click
// handlers stop propagation so toggling doesn't also fire the row's
// "highlight stem" click. Color swatches were removed at user request —
// the overlay's strokes are the source of truth for which estimator is
// painted in which color, and the redundant pre-label color cues felt
// busy in the vocals row. Matching CSS rules in track.css were dropped
// alongside this.
function _buildF0Toggles() {
  const prefs = getF0Prefs();
  const make = (key, label) => {
    const cb = el("input", { attrs: { type: "checkbox" } });
    cb.checked = prefs[key];
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", () => setF0Prefs({ [key]: cb.checked }));
    return el("label", {
      onClick: (e) => e.stopPropagation(),
    }, [
      cb,
      ` ${label}`,
    ]);
  };
  return el("div", { class: "f0-toggles" }, [
    make("consensus", "Consensus"),
    make("fcpe", "FCPE"),
    make("pesto", "PESTO"),
  ]);
}

function _computeF0Agreement(f0) {
  if (!f0 || !f0.fcpe || !f0.pesto) return null;
  const fcpe = f0.fcpe;
  const pesto = f0.pesto;
  const n = Math.min(fcpe.length, pesto.length);
  let voiced = 0;
  let agree = 0;
  for (let i = 0; i < n; i++) {
    const a = fcpe[i];
    const b = pesto[i];
    if (a > 0 && b > 0) {
      voiced++;
      const cents = Math.abs(1200 * Math.log2(a / b));
      if (cents < 50) agree++;
    }
  }
  if (voiced === 0) return null;
  return { pct: (agree / voiced) * 100, voiced };
}

// Feature 11: median offset of kick+snare onsets from an interpolated 4/4 grid.
// Returns null when the prerequisites aren't met (non-4/4, missing downbeats,
// drums not transcribed, no events).
function _computeDrumTightness(td) {
  if (td?.meta?.timeSig && td.meta.timeSig !== "4/4") return null;
  const d = td?.downbeats;
  if (!d || d.length < 2) return null;
  const drumPack = td?.notes?.drums;
  if (!drumPack?.drums) return null;
  const kick = drumPack.drums.kick?.t;
  const snare = drumPack.drums.snare?.t;
  const events = [];
  if (kick) for (let i = 0; i < kick.length; i++) events.push(kick[i]);
  if (snare) for (let i = 0; i < snare.length; i++) events.push(snare[i]);
  if (events.length === 0) return null;

  // Build interpolated 4/4 beat grid (sorted ascending).
  const beats = [];
  for (let i = 0; i < d.length - 1; i++) {
    const s = (d[i + 1] - d[i]) / 4;
    beats.push(d[i], d[i] + s, d[i] + 2 * s, d[i] + 3 * s);
  }
  beats.push(d[d.length - 1]);

  // Binary search nearest beat for each event.
  const offsetsMs = new Array(events.length);
  for (let i = 0; i < events.length; i++) {
    const t = events[i];
    let lo = 0, hi = beats.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (beats[mid] < t) lo = mid + 1;
      else hi = mid;
    }
    let best = Math.abs(beats[lo] - t);
    if (lo > 0) best = Math.min(best, Math.abs(beats[lo - 1] - t));
    offsetsMs[i] = best * 1000;
  }
  offsetsMs.sort((a, b) => a - b);
  const mid = offsetsMs.length >> 1;
  const median = offsetsMs.length % 2 === 1
    ? offsetsMs[mid]
    : (offsetsMs[mid - 1] + offsetsMs[mid]) / 2;
  return { medianMs: Math.round(median), n: events.length };
}

function fnLabel(fn) {
  return ({
    tonic: "tonic", dominant: "dominant", predominant: "pre-dom",
    modal_interchange: "mod-int",
  })[fn] ?? fn;
}

function formatNowTime(t) {
  const m = Math.floor(t / 60);
  const s = (t - m * 60);
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
}

// Extract just the tonic pitch class from a key string like "F minor" → "F".
// Handles sharps/flats: "C# major" → "C#", "Bb minor" → "Bb".
function tonicFromKey(key) {
  if (!key) return "";
  const m = String(key).match(/^([A-G][#b]?)/);
  return m ? m[1] : "";
}
