// Vertical layout constants shared by the renderer and the inspector.
//
//   0 ────────── chord strip ──────────  CHORD_H
//   CHORD_H ─── piano roll ───────────── h - drumH
//   h - drumH ─ drum lane (optional) ── h
//
// drumH = DRUM_LANE_H when track has transcribed drums, 0 otherwise.

export const CHORD_H = 48;
export const DRUM_LANE_H = 60;
export const DRUM_SUBSTEMS = ["kick", "snare", "toms", "hihat", "cymbals"];

export function drumLaneHeight(trackData) {
  return (trackData?.notes?.drums?.transcribed && trackData.notes.drums.drums) ? DRUM_LANE_H : 0;
}
