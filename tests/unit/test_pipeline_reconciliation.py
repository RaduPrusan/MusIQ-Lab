"""Unit tests for analyze.pipeline._compute_reconciliation.

The helper computes stack-consistency metrics across stage outputs:
chord-start vs downbeat alignment, and madmom-vs-beat-this beat agreement.
All inputs are optional — missing inputs cleanly omit their entries
rather than raising. Each test below probes one branch of that contract.
"""
from __future__ import annotations

import pytest

from analyze.pipeline import _compute_reconciliation


def _chord(start: float, end: float, label: str) -> dict:
    return {"start": start, "end": end, "label": label}


# ---------- chord_downbeat_alignment ----------

def test_chord_downbeat_alignment_perfect():
    """Every chord starts exactly on a downbeat → alignment = 1.0."""
    results = {
        "beats": {"downbeats": [0.0, 2.0, 4.0, 6.0]},
        "chords": [
            _chord(0.0, 2.0, "C:maj"),
            _chord(2.0, 4.0, "G:maj"),
            _chord(4.0, 6.0, "A:min"),
            _chord(6.0, 8.0, "F:maj"),
        ],
    }
    out = _compute_reconciliation(results)
    assert out["chord_downbeat_alignment_pct"] == 1.0
    assert out["chord_downbeat_n_chords"] == 4
    assert out["chord_downbeat_tolerance_ms"] == 50


def test_chord_downbeat_alignment_jittered():
    """Chord starts 30 ms after each downbeat (within 50 ms tolerance)."""
    results = {
        "beats": {"downbeats": [0.0, 2.0, 4.0, 6.0]},
        "chords": [
            _chord(0.030, 2.030, "C:maj"),
            _chord(2.030, 4.030, "G:maj"),
            _chord(4.030, 6.030, "A:min"),
            _chord(6.030, 8.030, "F:maj"),
        ],
    }
    out = _compute_reconciliation(results)
    assert out["chord_downbeat_alignment_pct"] == 1.0


def test_chord_downbeat_alignment_partial():
    """Two of four chords aligned — fraction should be 0.5."""
    results = {
        "beats": {"downbeats": [0.0, 2.0, 4.0, 6.0]},
        "chords": [
            _chord(0.000, 2.0, "C:maj"),   # aligned (0 ms off)
            _chord(2.040, 4.0, "G:maj"),   # aligned (40 ms off, < 50)
            _chord(4.500, 6.0, "A:min"),   # NOT aligned (500 ms off)
            _chord(6.200, 8.0, "F:maj"),   # NOT aligned (200 ms off)
        ],
    }
    out = _compute_reconciliation(results)
    assert out["chord_downbeat_alignment_pct"] == 0.5
    assert out["chord_downbeat_n_chords"] == 4


def test_chord_downbeat_excludes_n_chord():
    """The 'N' (no-chord) event must be excluded; only C:maj counts."""
    results = {
        "beats": {"downbeats": [0.0, 4.0, 8.0]},
        "chords": [
            _chord(0.0, 4.0, "N"),
            _chord(4.0, 8.0, "C:maj"),
        ],
    }
    out = _compute_reconciliation(results)
    assert out["chord_downbeat_n_chords"] == 1
    assert out["chord_downbeat_alignment_pct"] == 1.0


# ---------- beat_xcheck ----------

def test_beat_xcheck_perfect_agreement():
    """Identical beat lists → agreement = 1.0, median diff = 0.0 ms."""
    beats_list = [0.5, 1.0, 1.5, 2.0, 2.5]
    results = {
        "beats": {"downbeats": [], "beats": list(beats_list)},
        "beats_xcheck": {"beats": list(beats_list)},
    }
    out = _compute_reconciliation(results)
    assert out["beat_xcheck_agreement_pct"] == 1.0
    assert out["beat_xcheck_median_diff_ms"] == 0.0
    assert out["beat_xcheck_tolerance_ms"] == 20
    assert out["beat_xcheck_n_beats_matched"] == len(beats_list)


def test_beat_xcheck_systematic_offset():
    """beat-this beats systematically 15 ms after madmom → agreement = 1.0,
    median = 15.0 ms."""
    madmom_beats = [0.5, 1.0, 1.5, 2.0, 2.5]
    bt_beats = [b + 0.015 for b in madmom_beats]
    results = {
        "beats": {"downbeats": [], "beats": madmom_beats},
        "beats_xcheck": {"beats": bt_beats},
    }
    out = _compute_reconciliation(results)
    assert out["beat_xcheck_agreement_pct"] == 1.0
    assert out["beat_xcheck_median_diff_ms"] == 15.0


def test_beat_xcheck_partial_agreement():
    """Half within 20 ms, half not → agreement ~0.5."""
    madmom_beats = [0.5, 1.0, 1.5, 2.0]
    # 0.5 → 0.510 (10 ms, agrees)
    # 1.0 → 1.005 (5 ms, agrees)
    # 1.5 → 1.600 (100 ms, fails)
    # 2.0 → 2.080 (80 ms, fails)
    bt_beats = [0.510, 1.005, 1.600, 2.080]
    results = {
        "beats": {"downbeats": [], "beats": madmom_beats},
        "beats_xcheck": {"beats": bt_beats},
    }
    out = _compute_reconciliation(results)
    assert out["beat_xcheck_agreement_pct"] == 0.5
    assert out["beat_xcheck_n_beats_matched"] == 4


# ---------- contract: missing inputs / empty inputs ----------

def test_reconciliation_missing_xcheck_returns_partial():
    """Only beats + chords (no beats_xcheck) → output has chord_downbeat_*
    keys but NO beat_xcheck_* keys, and no exception."""
    results = {
        "beats": {"downbeats": [0.0, 2.0]},
        "chords": [_chord(0.0, 2.0, "C:maj"), _chord(2.0, 4.0, "G:maj")],
    }
    out = _compute_reconciliation(results)
    assert "chord_downbeat_alignment_pct" in out
    assert "chord_downbeat_n_chords" in out
    assert not any(k.startswith("beat_xcheck_") for k in out)


def test_reconciliation_empty_inputs_returns_empty():
    """Empty results dict → {} returned, no crash."""
    assert _compute_reconciliation({}) == {}
    # Also: stages present but empty data inside.
    assert _compute_reconciliation({"beats": {}, "chords": []}) == {}
    assert _compute_reconciliation({"beats": {"downbeats": []}, "chords": []}) == {}
