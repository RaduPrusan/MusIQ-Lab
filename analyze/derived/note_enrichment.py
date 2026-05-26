"""Per-note enrichment: in_chord (which chord covers note's t), role
(chord_tone / passing_tone / neighbor_tone / non_chord_tone), scale_deg
(scale degree relative to key tonic, major-scale relative regardless of mode)."""
from __future__ import annotations

import bisect
from typing import Optional

from analyze.derived.theory import (
    Chord,
    Key,
    parse_chord,
    scale_degree_for,
)


def chord_intervals(chord: Chord) -> set[int]:
    """The set of pitch-class intervals (relative to chord root) that count as chord tones."""
    if chord.is_no_chord or chord.root_pc is None:
        return set()
    intervals: set[int] = {0}
    if chord.quality == "maj":
        intervals.update({4, 7})
    elif chord.quality == "min":
        intervals.update({3, 7})
    elif chord.quality == "dim":
        intervals.update({3, 6})
    elif chord.quality == "aug":
        intervals.update({4, 8})
    elif chord.quality == "sus2":
        intervals.update({2, 7})
    elif chord.quality == "sus4":
        intervals.update({5, 7})
    else:
        intervals.update({4, 7})  # default to major triad
    for ext in chord.extensions:
        if ext == "7":
            intervals.add(10)  # b7 (dominant 7 / minor 7)
        elif ext == "maj7":
            intervals.add(11)
        elif ext == "b5":
            # Altered fifth: replace the perfect fifth with a diminished fifth.
            intervals.discard(7)
            intervals.add(6)
        elif ext == "#5":
            # Altered fifth: replace the perfect fifth with an augmented fifth.
            intervals.discard(7)
            intervals.add(8)
        elif ext.startswith("9"):
            intervals.add(2)
        elif ext.startswith("b9"):
            intervals.add(1)
        elif ext.startswith("11"):
            intervals.add(5)
        elif ext.startswith("#11"):
            intervals.add(6)
        elif ext.startswith("13"):
            intervals.add(9)
    return intervals


def find_chord_at(t: float, chords: list[dict]) -> Optional[dict]:
    """Binary-search the chords array for the chord active at time t.
    Chords are assumed non-overlapping and sorted by start."""
    if not chords:
        return None
    starts = [c["start"] for c in chords]
    idx = bisect.bisect_right(starts, t) - 1
    if idx < 0:
        return None
    chord = chords[idx]
    if chord["end"] <= t:
        return None
    return chord


def _classify_role(
    cur_pc: int,
    prev: Optional[dict],
    next_: Optional[dict],
    chord_tone_intervals: set[int],
    chord_root_pc: int,
) -> str:
    cur_interval = (cur_pc - chord_root_pc) % 12
    if cur_interval in chord_tone_intervals:
        return "chord_tone"
    if prev is None or next_ is None:
        return "non_chord_tone"
    prev_pc = prev["midi"] % 12
    next_pc = next_["midi"] % 12
    prev_interval = (prev_pc - chord_root_pc) % 12
    next_interval = (next_pc - chord_root_pc) % 12
    prev_is_chord_tone = prev_interval in chord_tone_intervals
    next_is_chord_tone = next_interval in chord_tone_intervals

    # neighbor: prev == next, both chord tones, current is ±1 or ±2 semitones from them
    if (
        prev_is_chord_tone
        and next_is_chord_tone
        and prev["midi"] == next_["midi"]
        and abs(cur_pc - prev_pc) in {1, 2}
    ):
        return "neighbor_tone"

    # passing: prev and next both chord tones, current is between them stepwise (<=2 semitones each side, monotonic direction)
    if prev_is_chord_tone and next_is_chord_tone:
        d1 = next_["midi"] - prev["midi"]
        if abs(d1) in {2, 3, 4}:
            # check current is between them and stepwise
            d_prev = cur_pc - prev_pc
            d_next = next_pc - cur_pc
            if 1 <= abs(d_prev) <= 2 and 1 <= abs(d_next) <= 2 and (d_prev * d_next) > 0:
                return "passing_tone"

    return "non_chord_tone"


def enrich_note(
    note: dict,
    *,
    prev: Optional[dict],
    next_: Optional[dict],
    chords: list[dict],
    key: Key,
) -> dict:
    """Return note dict augmented with in_chord, role, scale_deg."""
    out = dict(note)
    chord_dict = find_chord_at(note["t"], chords)
    out["scale_deg"] = scale_degree_for(note["midi"] % 12, key)
    if chord_dict is None or chord_dict["label"] in {"N", "n"}:
        out["in_chord"] = None
        out["role"] = None
        return out
    chord = parse_chord(chord_dict["label"])
    if chord.root_pc is None:
        out["in_chord"] = chord_dict["label"]
        out["role"] = None
        return out
    intervals = chord_intervals(chord)
    out["in_chord"] = chord_dict["label"]
    out["role"] = _classify_role(
        cur_pc=note["midi"] % 12,
        prev=prev,
        next_=next_,
        chord_tone_intervals=intervals,
        chord_root_pc=chord.root_pc,
    )
    return out
