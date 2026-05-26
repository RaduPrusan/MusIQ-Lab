"""Numeric primitives for vocal consensus analysis.

Pure functions, no I/O, no side effects. These are the lowest-level building
blocks; the voicing, octave, segmentation, intonation, and dynamics modules
all sit on top of them.

Convention: NaN propagates as the "unvoiced / no-data" sentinel for
frequency-valued functions, so callers can use NaN-aware numpy ops or
`math.isnan(x)` instead of overloading 0.0 with two meanings (zero Hz vs
unvoiced). Pitch-class returns -1 for unvoiced (since pc must be int).
"""
from __future__ import annotations

import math


def hz_to_midi(hz: float) -> float:
    """Convert frequency in Hz to (continuous) MIDI note number.

    Returns float — e.g. 69.5 represents A4 + 50¢. Returns NaN for
    non-positive input so callers can compose without explicit guards.
    """
    if hz <= 0:
        return math.nan
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def midi_to_hz(midi: float) -> float:
    """Convert MIDI note number (int or float) to frequency in Hz.

    Defined for any real-valued midi (no clamping). Inverse of hz_to_midi
    on positive inputs.
    """
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def cents_between(hz_a: float, hz_b: float) -> float:
    """Cents from B to A (positive when A is higher than B).

    Returns NaN if either input is non-positive.
    """
    if hz_a <= 0 or hz_b <= 0:
        return math.nan
    return 1200.0 * math.log2(hz_a / hz_b)


def pitch_class(hz: float) -> int:
    """Integer pitch class (C=0, C#=1, …, B=11) of a frequency.

    Returns -1 for non-positive input. Rounds to nearest semitone before
    taking mod 12, so a +30¢ A4 still maps to PC 9.
    """
    if hz <= 0:
        return -1
    midi_int = round(69.0 + 12.0 * math.log2(hz / 440.0))
    return midi_int % 12


def fold_cents(cents: float) -> float:
    """Fold cents into the [-600, 600] range to absorb octave errors.

    A +1218¢ value (one octave + 18¢, typical FCPE octave-glitch
    signature) becomes +18¢; a -1185¢ becomes +15¢. Used by intonation
    code that should be octave-agnostic — the actual pitch class is
    determined separately by pitch_class().

    Boundary policy: ±600¢ exactly maps to itself; just past the boundary
    folds to the opposite sign (e.g. 601 → -599).
    """
    return ((cents + 600.0) % 1200.0) - 600.0
