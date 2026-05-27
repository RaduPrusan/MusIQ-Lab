import { el, clear } from "./dom.js";
import { xToTime, yToMidi } from "../render/coords.js";
import { CHORD_H, DRUM_SUBSTEMS, drumLaneHeight } from "../render/layout.js";
import { midiToContextualName } from "../render/pianoroll.js";
import { pitchChildren } from "./pitch-label.js";
import { midiToHz, formatHz } from "../music/notation.js";
import { getEffectsEnabled } from "./tooltip-prefs.js";

const DRUM_LABEL = {
  kick: "Kick", snare: "Snare", toms: "Toms", hihat: "Hi-hat", cymbals: "Cymbals",
};

// Tooltip dimensions used to keep the floating panel inside the canvas
// rect — the multiline layout is wider/taller than the old single-liner,
// so the clamp at the right and bottom edges needs a bigger margin.
const TIP_W_MARGIN = 220;
const TIP_H_MARGIN = 96;

// Time tolerance (s) for picking which onset the cursor is "on". Onset ticks
// are 3px wide; converting to seconds depends on zoom, but at typical zooms
// (~50-200 px/s) this gives ~30-120ms — close enough that the user feels
// it's the hit they're hovering, but tight enough to avoid bleed.
const DRUM_PICK_TOLERANCE_SEC = 0.06;

// Build a single tooltip line as a <div class="tip-row tip-{kind}"> with
// the given children. Centralised so every line gets the same row class
// and styling hook in track.css.
function tipRow(kind, children) {
  const row = el("div", { class: `tip-row tip-${kind}` });
  for (const c of children) {
    if (c == null) continue;
    row.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return row;
}

export class Inspector {
  constructor(canvasWrap, trackData, viewState) {
    this.canvasWrap = canvasWrap;
    this.trackData = trackData;
    this.viewState = viewState;
    this.keyText = trackData?.meta?.key ?? "";
    this.tip = el("div", { class: "hover-tip" });
    this.rowBand = el("div", { class: "hover-row" });
    canvasWrap.appendChild(this.rowBand);
    canvasWrap.appendChild(this.tip);
    this._hoveredMidi = null;
    // Last cursor position over the canvas, captured on every mousemove and
    // cleared on mouseleave. Used to re-pick when viewState changes (zoom,
    // scroll, stem switch) without waiting for the user to wiggle the mouse.
    this._lastClient = null;
    canvasWrap.addEventListener("mousemove", (e) => this._onMove(e));
    canvasWrap.addEventListener("mouseleave", () => this._clearHover());
    // Re-position row band AND re-run picking on zoom/scroll. The cursor's
    // pixel position is stable but the time/midi under it has changed, so
    // the tooltip readout (time, frequency, scale degree, hovered note)
    // becomes stale without a re-pick. Guarded on _lastClient so we don't
    // run picking when the cursor is outside the canvas.
    this._onVS = () => {
      this._refreshBand();
      if (this._lastClient) this._repickAtLastClient();
    };
    viewState.on("change", this._onVS);
    // Drum-lane height change (Settings → Layout slider) shifts the band
    // origin and the hover-region split between piano roll and drum lane.
    // Re-position the band + re-pick under the cursor if hovering.
    document.addEventListener("musiq:drum-layout-changed", this._onVS);
  }

  _clearHover() {
    this.tip.classList.remove("show");
    this.rowBand.classList.remove("show");
    this._hoveredMidi = null;
    this._lastClient = null;
    this._highlightGutter(null);
    if (this.viewState.hoveredEvent) {
      this.viewState.update({ hoveredEvent: null });
    }
  }

  // Re-run the tooltip pick at the cached cursor position. Called by the
  // viewState 'change' handler so the readout follows zoom/scroll without
  // needing a fresh mousemove. Synthesises a minimal event-shaped object —
  // _onMove only reads clientX/clientY, so a plain literal is sufficient.
  _repickAtLastClient() {
    if (!this._lastClient) return;
    this._onMove({ clientX: this._lastClient.x, clientY: this._lastClient.y });
  }

  _highlightGutter(midi) {
    const gutter = document.querySelector("#roll-frame .gutter-labels");
    if (!gutter) return;
    for (const row of gutter.querySelectorAll(".gutter-row.hovered")) {
      row.classList.remove("hovered");
    }
    if (midi == null) return;
    // Match by data-midi (set in pianoroll._drawGutter) rather than by label
    // textContent — the label's spelling depends on the notation system and
    // the key (solfège, flat keys), so a text match would silently break
    // outside scientific-notation sharp keys.
    const row = gutter.querySelector(`.gutter-row[data-midi="${midi}"]`);
    if (row) row.classList.add("hovered");
  }

  _refreshBand() {
    if (this._hoveredMidi == null) { this.rowBand.classList.remove("show"); return; }
    const rect = this.canvasWrap.getBoundingClientRect();
    const drumH = drumLaneHeight(this.trackData);
    const innerH = rect.height - CHORD_H - drumH;
    const y = CHORD_H + (innerH / 2 - (this._hoveredMidi - this.viewState.midiCenter) * this.viewState.zoomV);
    const h = this.viewState.zoomV;
    this.rowBand.style.top = (y - h / 2) + "px";
    this.rowBand.style.height = h + "px";
    // The gutter is rebuilt on every viewState change, so re-apply the hovered class.
    this._highlightGutter(this._hoveredMidi);
  }

  // Replace `.hover-tip` modifier classes atomically — the three states
  // (on-grid / on-note / on-drum) are mutually exclusive, so flipping them
  // one-at-a-time here keeps the CSS rules simple.
  _setTipState(state) {
    this.tip.classList.remove("on-grid", "on-note", "on-drum");
    this.tip.classList.add(state);
  }

  // Position the tooltip below+right of the cursor, clamped to the
  // canvas-wrap rect so it never overflows the visible canvas.
  _positionTip(x, yTotal, rect) {
    const tipX = Math.min(rect.width  - TIP_W_MARGIN, x + 14);
    const tipY = Math.min(rect.height - TIP_H_MARGIN, yTotal + 12);
    this.tip.style.left = Math.max(0, tipX) + "px";
    this.tip.style.top  = Math.max(0, tipY) + "px";
  }

  _onMove(e) {
    this._lastClient = { x: e.clientX, y: e.clientY };
    const rect = this.canvasWrap.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const yTotal = e.clientY - rect.top;
    const drumH = drumLaneHeight(this.trackData);
    const drumLaneTop = rect.height - drumH;
    const t = xToTime(x, this.viewState);

    // Region 1: chord strip → no tooltip
    if (yTotal < CHORD_H) { this._clearHover(); return; }

    // Region 3: drum lane (only when drums transcribed)
    if (drumH > 0 && yTotal >= drumLaneTop) {
      this._showDrumTip(x, yTotal, t, drumLaneTop, drumH, rect);
      return;
    }

    // Region 2: piano roll
    const innerH = rect.height - CHORD_H - drumH;
    const y = yTotal - CHORD_H;
    const midiF = yToMidi(y, this.viewState, innerH);
    const midi = Math.round(midiF);
    const note = this._findNoteAt(t, midi);

    if (midi !== this._hoveredMidi) {
      this._hoveredMidi = midi;
      this._highlightGutter(midi);
    }
    this.rowBand.classList.add("show");
    this._refreshBand();

    this.tip.classList.add("show");
    this._positionTip(x, yTotal, rect);

    if (note) {
      this._renderNoteTip(note);
      this._setTipState("on-note");
      // Signal the canvas to enlarge this note (skipped when the user has
      // disabled hover effects in Settings).
      const next = getEffectsEnabled()
        ? { kind: "note", stem: note.stem, idx: note.idx }
        : null;
      this._publishHover(next);
    } else {
      this._renderGridTip(midi, t);
      this._setTipState("on-grid");
      this._publishHover(null);
    }
  }

  // Cheap shallow-equality check before assigning hoveredEvent — avoids
  // a viewState 'change' fire (and full canvas repaint) on every pixel of
  // mouse movement that lands on the same note.
  _publishHover(next) {
    const cur = this.viewState.hoveredEvent;
    const same =
      (cur == null && next == null) ||
      (cur && next && cur.kind === next.kind && cur.stem === next.stem && cur.idx === next.idx);
    if (!same) this.viewState.update({ hoveredEvent: next });
  }

  // Multiline DOM for "cursor over a melodic note". Lines:
  //   1. Pitch (head + <sub>octave</sub>)
  //   2. Frequency · MIDI #
  //   3. Stem · velocity
  //   4. Start time + duration
  //   5. Scale degree · role  (only when at least one is present)
  _renderNoteTip(note) {
    clear(this.tip);
    const name = midiToContextualName(note.midi, this.keyText);
    this.tip.appendChild(tipRow("head", pitchChildren(name)));
    const hz = midiToHz(note.midi);
    this.tip.appendChild(tipRow("physics", [`${formatHz(hz)} Hz · MIDI ${note.midi}`]));
    const vel = note.vel != null ? ` · v=${note.vel.toFixed(2)}` : "";
    this.tip.appendChild(tipRow("event", [`${note.stem}${vel}`]));
    const dur = note.dur != null ? ` + ${note.dur.toFixed(2)}s` : "";
    this.tip.appendChild(tipRow("timing", [`${note.t.toFixed(2)}s${dur}`]));
    const deg = note.meta.scale_deg;
    const role = note.meta.role;
    if (deg != null || role) {
      const parts = [];
      if (deg != null) parts.push(String(deg));
      if (role) parts.push(role);
      this.tip.appendChild(tipRow("analysis", [parts.join(" · ")]));
    }
  }

  // Multiline DOM for "cursor over an empty grid cell" (no detected note).
  // Same physics block as on-note, but the timing line uses "at" to signal
  // the absence of a duration, and there's no event/analysis row.
  _renderGridTip(midi, t) {
    clear(this.tip);
    const name = midiToContextualName(midi, this.keyText);
    this.tip.appendChild(tipRow("head", pitchChildren(name)));
    const hz = midiToHz(midi);
    this.tip.appendChild(tipRow("physics", [`${formatHz(hz)} Hz · MIDI ${midi}`]));
    this.tip.appendChild(tipRow("timing", [`at ${t.toFixed(2)}s`]));
  }

  _showDrumTip(x, yTotal, t, drumLaneTop, drumH, rect) {
    // Identify which substem row the cursor is in (5 equal rows top→bottom).
    const rowH = drumH / DRUM_SUBSTEMS.length;
    const rowIdx = Math.min(DRUM_SUBSTEMS.length - 1, Math.max(0, Math.floor((yTotal - drumLaneTop) / rowH)));
    const substem = DRUM_SUBSTEMS[rowIdx];
    const hit = this._findDrumHitAt(substem, t);

    // Hide pitch row band when in the drum lane (it's irrelevant here).
    this._hoveredMidi = null;
    this.rowBand.classList.remove("show");
    this._highlightGutter(null);

    this.tip.classList.add("show");
    this._positionTip(x, yTotal, rect);

    // Tint the on-drum tooltip with the substem's own color (kick/snare/…),
    // so the border + head + halo match the lane row the cursor is over.
    // CSS reads --tip-drum-color via a status-error fallback, so themes
    // without per-piece tokens still get a sane red.
    this.tip.style.setProperty("--tip-drum-color", `var(--drum-${substem})`);

    clear(this.tip);
    if (hit) {
      this.tip.appendChild(tipRow("head", [DRUM_LABEL[substem]]));
      this.tip.appendChild(tipRow("timing", [`${hit.t.toFixed(2)}s · v=${hit.vel.toFixed(2)}`]));
      this._setTipState("on-drum");
      const next = getEffectsEnabled()
        ? { kind: "drum", stem: substem, idx: hit.idx }
        : null;
      this._publishHover(next);
    } else {
      this.tip.appendChild(tipRow("head", [`${DRUM_LABEL[substem]} lane`]));
      this.tip.appendChild(tipRow("timing", [`${t.toFixed(2)}s`]));
      this._setTipState("on-grid");
      this._publishHover(null);
    }
  }

  _findDrumHitAt(substem, t) {
    const sub = this.trackData.notes.drums?.drums?.[substem];
    if (!sub || sub.t.length === 0) return null;
    // Linear scan with tolerance — drum onset arrays are typically a few
    // hundred to a few thousand entries; binary search isn't worth it here.
    let bestI = -1;
    let bestDt = DRUM_PICK_TOLERANCE_SEC;
    for (let i = 0; i < sub.t.length; i++) {
      const dt = Math.abs(sub.t[i] - t);
      if (dt < bestDt) { bestDt = dt; bestI = i; }
    }
    if (bestI < 0) return null;
    return { t: sub.t[bestI], vel: sub.vel[bestI], idx: bestI };
  }

  _findNoteAt(t, midi) {
    const stem = this.viewState.highlightedStem;
    const pack = this.trackData.notes[stem];
    if (!pack || pack.t.length === 0) return null;
    // Require an exact semitone match — picking with a ±1 tolerance made
    // the hover state "snap" to a neighbouring note when the cursor was a
    // pixel above or below the row, which felt sticky. Same-row only.
    for (let i = 0; i < pack.t.length; i++) {
      if (pack.midi[i] !== midi) continue;
      if (t < pack.t[i] || t > pack.t[i] + pack.dur[i]) continue;
      return {
        stem,
        idx: i,
        t: pack.t[i],
        dur: pack.dur[i],
        vel: pack.vel[i],
        meta: pack.meta[i],
        midi: pack.midi[i],
      };
    }
    return null;
  }
}
