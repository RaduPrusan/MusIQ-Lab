// Tiny DOM helper that renders a formatted pitch ("C4", "Fa#5") as a
// list of children with the trailing octave wrapped in <sub>. Used
// wherever the UI displays an octave-suffixed pitch — gutter labels,
// hover tooltip, vocal-range tags — so the visual style stays consistent
// across the app.
//
// Returns an array suitable for the children parameter of `el(...)`.
// Empty input yields an empty array, so callers can spread the result
// unconditionally without guard checks.
//
// Implementation note: the head + <sub> pair is wrapped in a single
// inline <span class="pitch-label">. <sub>'s `vertical-align: sub` only
// has effect inside an inline formatting context, but several call sites
// (e.g. the gutter row) are flex containers — a bare <sub> there becomes
// a flex item and loses its baseline shift, which makes the digit float
// up to look like a superscript. Wrapping in a span keeps the head/sub
// in inline flow regardless of the outer container.

import { el } from "./dom.js";
import { splitPitchOctave } from "../music/notation.js";

export function pitchChildren(s) {
  const { head, octave } = splitPitchOctave(s);
  if (!head && !octave) return [];
  if (!octave) return [el("span", { class: "pitch-label", text: head })];
  return [el("span", { class: "pitch-label" }, [
    head,
    el("sub", { class: "pitch-oct", text: octave }),
  ])];
}
