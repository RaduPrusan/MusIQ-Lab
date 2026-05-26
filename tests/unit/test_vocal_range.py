from pathlib import Path

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from analyze.derived.vocal_range import (
    INSTRUMENTAL_VOCAL_RATIO,
    is_instrumental,
    midi_number_to_pitch_name,
    vocal_range_from_midi,
)


def _write_sine(path: Path, amplitude: float, *, duration_sec: float = 1.0, sr: int = 22050) -> None:
    """Write a 440 Hz sine of the given amplitude. Used as a controllable RMS source for stem WAVs."""
    t = np.arange(int(duration_sec * sr)) / sr
    y = (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    sf.write(str(path), y, sr)


def _make_bsroformer_stems(tmp_path: Path, vocals_amp: float, instrumental_amp: float) -> Path:
    stems = tmp_path / "stems_bsroformer"
    stems.mkdir()
    _write_sine(stems / "song_(Vocals)_model_bs_roformer.wav", vocals_amp)
    _write_sine(stems / "song_(Instrumental)_model_bs_roformer.wav", instrumental_amp)
    return stems


def test_midi_to_pitch_name_middle_c():
    assert midi_number_to_pitch_name(60) == "C4"


def test_midi_to_pitch_name_a440():
    assert midi_number_to_pitch_name(69) == "A4"


def test_midi_to_pitch_name_low_octave():
    assert midi_number_to_pitch_name(36) == "C2"


def test_midi_to_pitch_name_with_sharp():
    assert midi_number_to_pitch_name(61) == "C♯4"


def test_vocal_range_from_midi_synthetic(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    # add notes spanning G3 (55) to D5 (74)
    for pitch in [55, 60, 67, 72, 74]:
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    pm.instruments.append(inst)
    midi_path = tmp_path / "vocals.mid"
    pm.write(str(midi_path))

    rng = vocal_range_from_midi(midi_path)
    assert rng == {"low": "G3", "high": "D5"}


def test_vocal_range_from_empty_midi_returns_none(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    pm.instruments.append(inst)
    midi_path = tmp_path / "vocals_empty.mid"
    pm.write(str(midi_path))
    assert vocal_range_from_midi(midi_path) is None


def test_vocal_range_from_missing_midi_returns_none(tmp_path):
    midi_path = tmp_path / "absent.mid"
    assert vocal_range_from_midi(midi_path) is None


def test_is_instrumental_true_when_vocals_far_below_instrumental(tmp_path):
    # Vocals at 1% of instrumental — well below the 15% threshold.
    stems = _make_bsroformer_stems(tmp_path, vocals_amp=0.005, instrumental_amp=0.5)
    assert is_instrumental(stems) is True


def test_is_instrumental_false_when_vocals_match_instrumental(tmp_path):
    stems = _make_bsroformer_stems(tmp_path, vocals_amp=0.5, instrumental_amp=0.5)
    assert is_instrumental(stems) is False


def test_is_instrumental_just_above_threshold_is_vocal(tmp_path):
    # Ratio ~ 1.5× the threshold — should be classified as vocal.
    stems = _make_bsroformer_stems(
        tmp_path, vocals_amp=0.5 * INSTRUMENTAL_VOCAL_RATIO * 1.5, instrumental_amp=0.5
    )
    assert is_instrumental(stems) is False


def test_is_instrumental_just_below_threshold_is_instrumental(tmp_path):
    # Ratio ~ 0.5× the threshold — should be classified as instrumental.
    stems = _make_bsroformer_stems(
        tmp_path, vocals_amp=0.5 * INSTRUMENTAL_VOCAL_RATIO * 0.5, instrumental_amp=0.5
    )
    assert is_instrumental(stems) is True


def test_is_instrumental_false_when_vocals_stem_missing(tmp_path):
    # Conservative fallback: if we can't measure vocals, don't suppress vocal_range.
    stems = tmp_path / "stems_bsroformer"
    stems.mkdir()
    _write_sine(stems / "song_(Instrumental)_model_bs_roformer.wav", 0.5)
    assert is_instrumental(stems) is False


def test_is_instrumental_false_when_instrumental_stem_missing(tmp_path):
    # Same conservative fallback in the other direction — no denominator is no decision.
    stems = tmp_path / "stems_bsroformer"
    stems.mkdir()
    _write_sine(stems / "song_(Vocals)_model_bs_roformer.wav", 0.001)
    assert is_instrumental(stems) is False


def test_is_instrumental_false_when_instrumental_silent(tmp_path):
    # Edge case: instrumental stem RMS = 0 — would be a divide by zero, must short-circuit.
    stems = _make_bsroformer_stems(tmp_path, vocals_amp=0.0, instrumental_amp=0.0)
    assert is_instrumental(stems) is False
