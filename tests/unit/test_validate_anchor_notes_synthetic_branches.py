"""Branch-coverage tests for `_validate_anchor_notes`.

Each test hits exactly one decision branch in the validator (see
analyze/stages/vocal_consensus_contour.py::_validate_anchor_notes for
the docstring listing branches 1-3 and their sub-cases). The branch
being exercised is called out in a one-line comment on each test.

These complement the broader scenarios in
tests/unit/test_vocal_consensus_contour_stage.py::TestAnchorPreValidation
by deliberately keeping inputs small and the branch label explicit, so
a future vectorization (item #8a) can map vector-output failures to
specific branches.
"""
from __future__ import annotations

import numpy as np
import pretty_midi
import pytest

from analyze.stages.vocal_consensus_contour import _validate_anchor_notes


FPS = 100.0


def _f0(n: int, *, voiced_span: tuple[int, int], hz: float) -> np.ndarray:
    arr = np.zeros(n, dtype=np.float32)
    i0, i1 = voiced_span
    arr[i0:i1] = hz
    return arr


def _conf_full(n: int, *, voiced_span: tuple[int, int], value: float = 1.0) -> np.ndarray:
    arr = np.zeros(n, dtype=np.float32)
    i0, i1 = voiced_span
    arr[i0:i1] = value
    return arr


def _note(midi: int, t_start: float, t_end: float) -> pretty_midi.Note:
    return pretty_midi.Note(velocity=90, pitch=midi, start=t_start, end=t_end)


def _midi_to_hz(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


# ---------------------------------------------------------------------
# Branch 1: insufficient validation frames after middle-60% trim
# ---------------------------------------------------------------------


def test_note_too_short_after_middle_trim_kept_as_is():
    # Branch 1: middle 60% has fewer than min_validation_frames=5 → keep.
    # Note span 0.50-0.54 = 4 frames at fps=100. Middle 60% = 2 frames < 5.
    n = 100
    fcpe = _f0(n, voiced_span=(0, n), hz=_midi_to_hz(99))  # F0 strongly disagrees
    pesto = _f0(n, voiced_span=(0, n), hz=_midi_to_hz(99))
    fcpe_conf = _conf_full(n, voiced_span=(0, n))
    pesto_conf = _conf_full(n, voiced_span=(0, n))
    note = _note(midi=69, t_start=0.50, t_end=0.54)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
        min_validation_frames=5,
    )
    assert info == {"kept": 1, "corrected": 0, "dropped": 0}
    assert kept[0].pitch == 69  # unmodified (insufficient evidence to validate)


# ---------------------------------------------------------------------
# Branch 2a: both medians within ±50¢ of MIDI → keep
# ---------------------------------------------------------------------


def test_both_medians_near_midi_kept():
    # Branch 2a: FCPE+PESTO both ≈ MIDI 69 (within ±50¢) → keep unchanged.
    n = 100
    fcpe = _f0(n, voiced_span=(10, 90), hz=440.0)   # exactly A4
    pesto = _f0(n, voiced_span=(10, 90), hz=440.0)
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = _conf_full(n, voiced_span=(10, 90))
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 1, "corrected": 0, "dropped": 0}
    assert kept[0].pitch == 69


# ---------------------------------------------------------------------
# Branch 2c (drop): both medians agree on a DIFFERENT pitch class,
# ≥7 semitones from basic-pitch's label, NOT a harmonic ratio → drop
# ---------------------------------------------------------------------


def test_both_medians_agree_different_pc_large_delta_dropped():
    # Branch 2c: F0 unanimously at MIDI 50 (D3), basic-pitch labelled MIDI 69 (A4).
    # 19 semitones apart, different pitch class, ratio D3/A4 ≈ 0.33 (not harmonic).
    # → strong evidence basic-pitch hallucinated; drop.
    n = 100
    hz_d3 = _midi_to_hz(50)
    fcpe = _f0(n, voiced_span=(10, 90), hz=hz_d3)
    pesto = _f0(n, voiced_span=(10, 90), hz=hz_d3)
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = _conf_full(n, voiced_span=(10, 90))
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 0, "corrected": 0, "dropped": 1}
    assert kept == []


# ---------------------------------------------------------------------
# Branch 2b (correct): both medians agree on same PC, octave below
# basic-pitch's label → correct downward
# ---------------------------------------------------------------------


def test_octave_error_avg_below_midi_corrected_downward():
    # Branch 2b: F0 unanimously at MIDI 57 (A3) one octave below MIDI 69 (A4).
    # Same pitch class, avg_midi BELOW note.pitch → correct to 57.
    n = 100
    fcpe = _f0(n, voiced_span=(10, 90), hz=220.0)  # A3
    pesto = _f0(n, voiced_span=(10, 90), hz=220.0)
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = _conf_full(n, voiced_span=(10, 90))
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 0, "corrected": 1, "dropped": 0}
    assert len(kept) == 1
    assert kept[0].pitch == 57  # corrected one octave down


# ---------------------------------------------------------------------
# Guard 1 (harmonic-lock): integer-ratio between avg_hz and target_hz
# in [2, 8] band → keep
# ---------------------------------------------------------------------


def test_harmonic_lock_pattern_kept():
    # Guard 1: F0 estimators locked on the 3rd harmonic of MIDI 69
    # (≈1320 Hz). ratio = 3.0 (integer in [1.5, 8.5]); different PC than A4.
    # Keep basic-pitch's labelling at the fundamental.
    n = 100
    hz_3rd = 440.0 * 3.0
    fcpe = _f0(n, voiced_span=(10, 90), hz=hz_3rd)
    pesto = _f0(n, voiced_span=(10, 90), hz=hz_3rd)
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = _conf_full(n, voiced_span=(10, 90))
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 1, "corrected": 0, "dropped": 0}
    assert kept[0].pitch == 69


# ---------------------------------------------------------------------
# Branch 3 (single witness, near MIDI): only one estimator confident,
# within ±50¢ of MIDI → keep
# ---------------------------------------------------------------------


def test_single_witness_within_50c_kept():
    # Branch 3 (keep): FCPE confident at A4, PESTO entirely unconfident.
    # Single witness within ±50¢ → keep.
    n = 100
    fcpe = _f0(n, voiced_span=(10, 90), hz=440.0)
    pesto = np.zeros(n, dtype=np.float32)  # silent / unconfident
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = np.zeros(n, dtype=np.float32)
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 1, "corrected": 0, "dropped": 0}
    assert kept[0].pitch == 69


# ---------------------------------------------------------------------
# Branch 3 (single witness, beyond MIDI): one estimator confident,
# beyond ±50¢ from MIDI → drop
# ---------------------------------------------------------------------


def test_single_witness_beyond_50c_dropped():
    # Branch 3 (drop): FCPE confident at MIDI 72 (C5 ≈ 523 Hz), PESTO unconfident.
    # Single witness 300¢ from MIDI 69 → drop.
    n = 100
    fcpe = _f0(n, voiced_span=(10, 90), hz=_midi_to_hz(72))
    pesto = np.zeros(n, dtype=np.float32)
    fcpe_conf = _conf_full(n, voiced_span=(10, 90))
    pesto_conf = np.zeros(n, dtype=np.float32)
    note = _note(midi=69, t_start=0.10, t_end=0.90)

    kept, info = _validate_anchor_notes(
        [note], fcpe, pesto, fcpe_conf, pesto_conf, FPS,
    )
    assert info == {"kept": 0, "corrected": 0, "dropped": 1}
    assert kept == []
