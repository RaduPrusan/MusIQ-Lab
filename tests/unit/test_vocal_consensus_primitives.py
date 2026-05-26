"""Tests for analyze/derived/vocal_consensus/primitives.py."""
import math

import pytest

from analyze.derived.vocal_consensus.primitives import (
    cents_between,
    fold_cents,
    hz_to_midi,
    midi_to_hz,
    pitch_class,
)


# ---------- hz_to_midi ----------------------------------------------------

class TestHzToMidi:
    def test_a4_is_midi_69(self):
        assert hz_to_midi(440.0) == pytest.approx(69.0)

    def test_a3_is_midi_57(self):
        assert hz_to_midi(220.0) == pytest.approx(57.0)

    def test_a5_is_midi_81(self):
        assert hz_to_midi(880.0) == pytest.approx(81.0)

    def test_c4_is_midi_60(self):
        # Equal-temperament C4: 261.6256 Hz
        assert hz_to_midi(261.6256) == pytest.approx(60.0, abs=1e-3)

    def test_quarter_tone_above_a4(self):
        # 440 * 2^(0.5/12) ≈ 452.893 Hz -> MIDI 69.5
        hz = 440.0 * (2.0 ** (0.5 / 12.0))
        assert hz_to_midi(hz) == pytest.approx(69.5, abs=1e-9)

    def test_zero_returns_nan(self):
        assert math.isnan(hz_to_midi(0.0))

    def test_negative_returns_nan(self):
        # Defensive: negative shouldn't occur but must not raise/return garbage
        assert math.isnan(hz_to_midi(-100.0))


# ---------- midi_to_hz ----------------------------------------------------

class TestMidiToHz:
    def test_midi_69_is_a4(self):
        assert midi_to_hz(69) == pytest.approx(440.0)

    def test_midi_60_is_c4(self):
        assert midi_to_hz(60) == pytest.approx(261.6256, abs=1e-3)

    def test_round_trip_voiced(self):
        for hz in (110.0, 220.0, 261.6256, 440.0, 880.0, 1760.0):
            assert midi_to_hz(hz_to_midi(hz)) == pytest.approx(hz, rel=1e-9)

    def test_continuous_midi(self):
        # Half-semitone above A4 (MIDI 69.5) should be the quarter-tone freq
        expected = 440.0 * (2.0 ** (0.5 / 12.0))
        assert midi_to_hz(69.5) == pytest.approx(expected, rel=1e-9)


# ---------- cents_between ------------------------------------------------

class TestCentsBetween:
    def test_octave_up_is_1200(self):
        assert cents_between(880.0, 440.0) == pytest.approx(1200.0)

    def test_octave_down_is_negative_1200(self):
        assert cents_between(440.0, 880.0) == pytest.approx(-1200.0)

    def test_unison_is_zero(self):
        assert cents_between(440.0, 440.0) == pytest.approx(0.0)

    def test_50_cents_above(self):
        # The quarter-tone above 440 is +50¢
        hz = 440.0 * (2.0 ** (50.0 / 1200.0))
        assert cents_between(hz, 440.0) == pytest.approx(50.0, abs=1e-9)

    def test_unvoiced_a_returns_nan(self):
        assert math.isnan(cents_between(0.0, 440.0))

    def test_unvoiced_b_returns_nan(self):
        assert math.isnan(cents_between(440.0, 0.0))

    def test_both_unvoiced_returns_nan(self):
        assert math.isnan(cents_between(0.0, 0.0))


# ---------- pitch_class --------------------------------------------------

class TestPitchClass:
    def test_a440_is_pc_9(self):
        # A is the 9th pitch class (C=0)
        assert pitch_class(440.0) == 9

    def test_c4_is_pc_0(self):
        assert pitch_class(261.6256) == 0

    def test_e4_is_pc_4(self):
        # E4 = 329.628 Hz
        assert pitch_class(329.628) == 4

    def test_octaves_share_pitch_class(self):
        # A1, A2, A3, A4, A5 all → PC 9
        assert pitch_class(55.0) == 9
        assert pitch_class(110.0) == 9
        assert pitch_class(220.0) == 9
        assert pitch_class(440.0) == 9
        assert pitch_class(880.0) == 9

    def test_micro_offset_rounds_to_nearest_pc(self):
        # +30¢ above A4 still rounds to PC 9
        hz = 440.0 * (2.0 ** (30.0 / 1200.0))
        assert pitch_class(hz) == 9

    def test_unvoiced_returns_minus_one(self):
        assert pitch_class(0.0) == -1
        assert pitch_class(-1.0) == -1


# ---------- fold_cents ---------------------------------------------------

class TestFoldCents:
    def test_zero_unchanged(self):
        assert fold_cents(0.0) == pytest.approx(0.0)

    def test_within_range_unchanged(self):
        for c in (-500.0, -100.0, 0.0, 100.0, 500.0, 599.999):
            assert fold_cents(c) == pytest.approx(c)

    def test_octave_glitch_above_folds(self):
        # +1218¢ (one octave + 18¢) → +18¢: classic FCPE octave-flip recovery
        assert fold_cents(1218.0) == pytest.approx(18.0)

    def test_octave_glitch_below_folds(self):
        # -1218¢ → -18¢
        assert fold_cents(-1218.0) == pytest.approx(-18.0)

    def test_two_octaves_above_folds(self):
        # +2418¢ (two octaves + 18¢) → +18¢
        assert fold_cents(2418.0) == pytest.approx(18.0)

    def test_just_past_positive_boundary_flips_sign(self):
        # +601¢ folds to -599¢ — by design, exactly half-octave from boundary
        assert fold_cents(601.0) == pytest.approx(-599.0)

    def test_just_inside_negative_boundary_unchanged(self):
        assert fold_cents(-599.0) == pytest.approx(-599.0)

    def test_exact_negative_600_unchanged(self):
        # -600 maps to itself (boundary policy: closed at -600, open at +600)
        assert fold_cents(-600.0) == pytest.approx(-600.0)
