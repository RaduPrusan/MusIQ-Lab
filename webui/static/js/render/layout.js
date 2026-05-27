// Vertical layout constants shared by the renderer and the inspector.
//
//   0 ────────── chord strip ──────────  CHORD_H
//   CHORD_H ─── piano roll ───────────── h - drumH
//   h - drumH ─ drum lane (optional) ── h
//
// drumH = user-configured DRUM_LANE_H (default 60) when the track has
// transcribed drums, 0 otherwise. The height is read on every call so a
// Settings → Layout slider change is picked up on the next render frame
// without needing to invalidate cached state.

import { getDrumLaneHeight } from "../ui/drum-layout-prefs.js";

export const CHORD_H = 48;
export const DRUM_LANE_H_DEFAULT = 60;
export const DRUM_SUBSTEMS = ["kick", "snare", "toms", "hihat", "cymbals"];

export function drumLaneHeight(trackData) {
  if (!(trackData?.notes?.drums?.transcribed && trackData.notes.drums.drums)) return 0;
  return getDrumLaneHeight();
}
