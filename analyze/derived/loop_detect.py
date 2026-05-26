"""Predominant chord loop detection.

Scores all sliding windows of length 2..8 over the chord label sequence
(with consecutive duplicates collapsed). Score = count × length. Returns
the highest-scoring window, or None if no length-≥2 window appears ≥2 times.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional


def _collapse_runs(chords: list[dict]) -> list[dict]:
    """Collapse consecutive identical labels, keeping the first chord's start
    and the last chord's end for each run."""
    if not chords:
        return []
    out = [dict(chords[0])]
    for c in chords[1:]:
        if c["label"] == out[-1]["label"]:
            out[-1]["end"] = c["end"]
        else:
            out.append(dict(c))
    return out


def _find_appearances(chords: list[dict], loop: list[str]) -> list[dict]:
    """Find every contiguous run in `chords` (after collapsing) matching the loop pattern.
    Returns appearances as {start, end}."""
    appearances = []
    L = len(loop)
    n = len(chords)
    i = 0
    while i + L <= n:
        if [c["label"] for c in chords[i:i + L]] == loop:
            appearances.append({
                "start": chords[i]["start"],
                "end": chords[i + L - 1]["end"],
            })
            i += L  # non-overlapping
        else:
            i += 1
    return appearances


def _primitive_period(loop: list[str]) -> list[str]:
    """Return the shortest sub-loop that tiles `loop` exactly.

    E.g. ["A", "B", "A", "B"] → ["A", "B"]
         ["A", "B", "C"]       → ["A", "B", "C"]  (already primitive)
    """
    n = len(loop)
    for p in range(2, n):
        if n % p == 0:
            unit = loop[:p]
            if unit * (n // p) == loop:
                return unit
    return loop


def predominant_chord_loop(
    chords: list[dict],
) -> tuple[Optional[list[str]], list[dict]]:
    collapsed = _collapse_runs(chords)
    labels = [c["label"] for c in collapsed]

    best_loop: Optional[list[str]] = None
    best_score = 3  # require score > 3 (i.e. at least 2 repeats × length 2 = 4)
    best_length = 0

    for L in range(2, 9):
        if L > len(labels):
            break
        windows = [tuple(labels[i:i + L]) for i in range(len(labels) - L + 1)]
        counts = Counter(windows)
        for window, count in counts.items():
            if count < 2:
                continue
            score = count * L
            if score > best_score or (score == best_score and L > best_length):
                best_loop = list(window)
                best_score = score
                best_length = L

    if best_loop is None:
        return None, []

    # Reduce to the primitive (shortest repeating) period.
    best_loop = _primitive_period(best_loop)

    appearances = _find_appearances(collapsed, best_loop)
    return best_loop, appearances
