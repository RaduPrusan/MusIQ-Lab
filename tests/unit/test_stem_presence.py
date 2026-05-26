"""Unit tests for analyze/derived/stem_presence.py.

All audio inputs are synthesized in-process — no real files are used.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from analyze.derived.stem_presence import (
    ACTIVE_FRAME_RATIO_THRESHOLD,
    ACTIVE_FRAME_THRESHOLD_DBFS,
    IN_BAND_FRACTION_THRESHOLD,
    MASKING_THRESHOLD_DB,
    PHANTOM_NOTE_MAX_DUR_SEC,
    PHANTOM_NOTE_MAX_VEL,
    SILENT_DBFS_FLOOR,
    _rms_db,
    filter_phantom_notes,
    measure_stem_presence,
)

# ---------------------------------------------------------------------------
# Synthesis helpers
# ---------------------------------------------------------------------------

SR = 44100
DUR = 3.0  # seconds for all synthesized stems


def _write_sine(path: Path, freq: float = 440.0, dur: float = DUR,
                sr: int = SR, amp: float = 1.0) -> None:
    """Write a mono sine wave to a WAV file."""
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    y = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), y, sr)


def _write_silence(path: Path, dur: float = DUR, sr: int = SR) -> None:
    """Write an all-zeros WAV file."""
    sf.write(str(path), np.zeros(int(sr * dur), dtype=np.float32), sr)


def _note(t: float = 0.0, dur: float = 0.5, midi: int = 60,
          name: str = "C4", vel: float = 0.8) -> dict:
    return {"t": t, "dur": dur, "midi": midi, "name": name, "vel": vel}


# ===========================================================================
# _rms_db — helpers
# ===========================================================================

class TestRmsDb:
    def test_zero_length_returns_floor(self, tmp_path: Path):
        """Case 1: empty WAV (0 samples) → SILENT_DBFS_FLOOR."""
        p = tmp_path / "empty.wav"
        sf.write(str(p), np.zeros(0, dtype=np.float32), SR)
        assert _rms_db(p) == SILENT_DBFS_FLOOR

    def test_unit_amplitude_sine_near_0_dbfs(self, tmp_path: Path):
        """Case 2: amplitude=1.0 sine → RMS ≈ 0 dBFS (within 0.5 dB)."""
        p = tmp_path / "unit.wav"
        _write_sine(p, amp=1.0)
        result = _rms_db(p)
        # RMS of a sine with amplitude 1.0 is 1/sqrt(2) ≈ -3.01 dBFS
        expected = 20.0 * math.log10(1.0 / math.sqrt(2))
        assert result == pytest.approx(expected, abs=0.5)

    def test_known_amplitude_returns_expected_dbfs(self, tmp_path: Path):
        """Case 3: amplitude=0.1 → ~−23 dBFS (RMS = 0.1/sqrt(2) ≈ 0.0707)."""
        p = tmp_path / "quiet.wav"
        _write_sine(p, amp=0.1)
        result = _rms_db(p)
        expected_rms = 0.1 / math.sqrt(2)
        expected_db = 20.0 * math.log10(expected_rms)
        assert result == pytest.approx(expected_db, abs=0.5)


# ===========================================================================
# measure_stem_presence — Signal A (masking)
# ===========================================================================

class TestSignalAMasking:
    def test_real_instrument_not_masked(self, tmp_path: Path):
        """Case 4: stem at 0 dBFS, others at -10 dBFS → masking gate does NOT trip."""
        stem = tmp_path / "stem.wav"
        other1 = tmp_path / "other1.wav"
        other2 = tmp_path / "other2.wav"
        _write_sine(stem, amp=1.0)
        _write_sine(other1, amp=0.316)   # ≈ -10 dBFS
        _write_sine(other2, amp=0.316)
        result = measure_stem_presence(stem, {"bass": other1, "guitar": other2}, "vocals")
        assert "masking" not in result["gates_tripped"]
        assert result["transcribed"] is True

    def test_masked_stem_trips_gate(self, tmp_path: Path):
        """Case 5: stem at -50 dBFS, other at 0 dBFS → masking gate trips."""
        stem = tmp_path / "stem.wav"
        other = tmp_path / "other.wav"
        _write_sine(stem, amp=10 ** (-50.0 / 20))   # ≈ -53 dBFS (sine RMS)
        _write_sine(other, amp=1.0)
        result = measure_stem_presence(stem, {"bass": other}, "vocals")
        assert "masking" in result["gates_tripped"]
        assert result["transcribed"] is False
        # masking_ratio_db must be below MASKING_THRESHOLD_DB
        assert result["masking_ratio_db"] < MASKING_THRESHOLD_DB

    def test_empty_others_no_masking_gate(self, tmp_path: Path):
        """Case 6: no other stems → max_other_rms_db is None, masking gate not tripped."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        result = measure_stem_presence(stem, {}, "vocals")
        assert result["max_other_rms_db"] is None
        assert result["masking_ratio_db"] is None
        assert "masking" not in result["gates_tripped"]


# ===========================================================================
# measure_stem_presence — Signal B (active-frame ratio)
# ===========================================================================

class TestSignalBActiveFrame:
    def test_always_on_stem_not_gated(self, tmp_path: Path):
        """Case 7: full-amplitude continuous sine → active_frame_ratio ≈ 1.0."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        result = measure_stem_presence(stem, {}, "other")
        assert result["active_frame_ratio"] == pytest.approx(1.0, abs=0.05)
        assert "active" not in result["gates_tripped"]

    def test_mostly_silent_trips_active_gate(self, tmp_path: Path):
        """Case 8: 30 ms burst in a 15 s clip → 1 active frame out of ~150
        (≈0.67%) which is below ACTIVE_FRAME_RATIO_THRESHOLD (0.01).

        Clip length is chosen so the test's resolution is finer than the
        threshold — one active frame must be reliably *below* the cutoff,
        not borderline-on. Bumping the threshold tighter would require
        bumping the clip length here too."""
        dur = 15.0
        sr = SR
        samples = int(sr * dur)
        y = np.zeros(samples, dtype=np.float32)
        burst_end = int(0.030 * sr)   # 30 ms
        t = np.arange(burst_end) / sr
        y[:burst_end] = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        stem = tmp_path / "burst.wav"
        sf.write(str(stem), y, sr)
        result = measure_stem_presence(stem, {}, "other")
        assert result["active_frame_ratio"] < ACTIVE_FRAME_RATIO_THRESHOLD
        assert "active" in result["gates_tripped"]

    def test_half_active_not_gated(self, tmp_path: Path):
        """Case 9: 1.5 s sine then 1.5 s silence → ratio ≈ 0.5, gate not tripped."""
        sr = SR
        dur = DUR  # 3 s total: 1.5s sine, 1.5s silence
        samples = int(sr * dur)
        y = np.zeros(samples, dtype=np.float32)
        half = samples // 2
        t = np.arange(half) / sr
        y[:half] = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
        stem = tmp_path / "half.wav"
        sf.write(str(stem), y, sr)
        result = measure_stem_presence(stem, {}, "other")
        # Should be around 0.5 — definitely not below 0.05
        assert result["active_frame_ratio"] == pytest.approx(0.5, abs=0.15)
        assert "active" not in result["gates_tripped"]


# ===========================================================================
# measure_stem_presence — Signal C (in-band energy)
# ===========================================================================

class TestSignalCInBand:
    def test_bass_stem_in_band_content_passes(self, tmp_path: Path):
        """Case 10: 80 Hz sine in a bass stem → in_band_fraction near 1.0."""
        stem = tmp_path / "bass_inband.wav"
        _write_sine(stem, freq=80.0, amp=1.0)
        result = measure_stem_presence(stem, {}, "bass")
        assert result["in_band_fraction"] is not None
        assert result["in_band_fraction"] > 0.5
        assert "in_band" not in result["gates_tripped"]

    def test_bass_stem_out_of_band_trips_gate(self, tmp_path: Path):
        """Case 11: 4000 Hz sine in bass stem (cutoff 30-330 Hz) → in_band gate trips."""
        stem = tmp_path / "bass_outofband.wav"
        _write_sine(stem, freq=4000.0, amp=1.0)
        result = measure_stem_presence(stem, {}, "bass")
        assert result["in_band_fraction"] is not None
        assert result["in_band_fraction"] < IN_BAND_FRACTION_THRESHOLD
        assert "in_band" in result["gates_tripped"]

    def test_other_stem_skips_signal_c(self, tmp_path: Path):
        """Case 12: 'other' stem with out-of-band sine → in_band gate NOT tripped."""
        stem = tmp_path / "other_outofband.wav"
        _write_sine(stem, freq=4000.0, amp=1.0)
        result = measure_stem_presence(stem, {}, "other")
        assert result["in_band_fraction"] is None
        assert result["band_hz"] is None
        assert "in_band" not in result["gates_tripped"]


# ===========================================================================
# measure_stem_presence — Combined gates
# ===========================================================================

class TestCombinedGates:
    def test_multiple_gates_trip_simultaneously(self, tmp_path: Path):
        """Case 13: masked (silent stem) + out-of-band (4 kHz bass) → both gates."""
        # Use a 4000 Hz sine so Signal C trips on bass band,
        # and set it very quiet so Signal A also trips.
        stem = tmp_path / "stem.wav"
        other = tmp_path / "other.wav"
        amp_quiet = 10 ** (-50.0 / 20)
        _write_sine(stem, freq=4000.0, amp=amp_quiet)
        _write_sine(other, amp=1.0)
        result = measure_stem_presence(stem, {"guitar": other}, "bass")
        assert "masking" in result["gates_tripped"]
        assert "in_band" in result["gates_tripped"]
        assert result["transcribed"] is False
        assert result["reason"] is not None
        assert "; " in result["reason"]

    def test_all_gates_pass(self, tmp_path: Path):
        """Case 14: real instrument — no gates should trip."""
        stem = tmp_path / "stem.wav"
        other = tmp_path / "other.wav"
        # Stem louder than others, in-band frequency for bass, fully active
        _write_sine(stem, freq=80.0, amp=1.0)
        _write_sine(other, amp=0.316)   # -10 dB relative
        result = measure_stem_presence(stem, {"guitar": other}, "bass")
        assert result["gates_tripped"] == []
        assert result["transcribed"] is True
        assert result["reason"] is None


# ===========================================================================
# measure_stem_presence — Return shape
# ===========================================================================

class TestReturnShape:
    def test_all_10_keys_present(self, tmp_path: Path):
        """Case 15: returned dict has all 10 documented keys."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=0.5)
        result = measure_stem_presence(stem, {}, "piano")
        expected_keys = {
            "stem_rms_db", "max_other_rms_db", "masking_ratio_db",
            "active_frame_ratio", "in_band_fraction", "band_hz",
            "thresholds", "gates_tripped", "transcribed", "reason",
        }
        assert set(result.keys()) == expected_keys

    def test_thresholds_sub_keys(self, tmp_path: Path):
        """Case 15b: thresholds dict contains masking_db, active_ratio, in_band_fraction."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=0.5)
        result = measure_stem_presence(stem, {}, "piano")
        assert "masking_db" in result["thresholds"]
        assert "active_ratio" in result["thresholds"]
        assert "in_band_fraction" in result["thresholds"]


# ===========================================================================
# filter_phantom_notes
# ===========================================================================

class TestFilterPhantomNotes:
    def test_midi_range_cull(self, tmp_path: Path):
        """Case 16: bass range C1-G4 (24-67), notes 12/36/80 → only 36 survives."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, freq=80.0, amp=1.0)
        notes = [
            _note(midi=12, t=0.0),   # below C1 — culled
            _note(midi=36, t=0.5),   # C2 — in range
            _note(midi=80, t=1.0),   # above G4 — culled
        ]
        result = filter_phantom_notes(notes, stem, "bass")
        assert len(result) == 1
        assert result[0]["midi"] == 36

    def test_per_note_noise_gate_keeps_audible(self, tmp_path: Path):
        """Case 17a: note at t=1.0 with full-amplitude audio → kept."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, freq=80.0, amp=1.0, dur=DUR)   # audio everywhere
        notes = [_note(midi=36, t=1.0, dur=0.5, vel=0.8)]
        result = filter_phantom_notes(notes, stem, "bass")
        assert len(result) == 1

    def test_per_note_noise_gate_drops_silent(self, tmp_path: Path):
        """Case 17b: note at t=1.0 in a silent WAV → dropped by noise gate."""
        stem = tmp_path / "silence.wav"
        _write_silence(stem, dur=DUR)
        notes = [_note(midi=36, t=1.0, dur=0.5, vel=0.8)]
        result = filter_phantom_notes(notes, stem, "bass")
        assert len(result) == 0

    def test_perceptual_insignificance_both_criteria_drops(self, tmp_path: Path):
        """Case 18a: dur < 0.060 AND vel < 0.2 → dropped (click)."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        notes = [_note(midi=60, t=0.5, dur=0.05, vel=0.1)]
        result = filter_phantom_notes(notes, stem, "piano")
        assert len(result) == 0

    def test_perceptual_insignificance_low_dur_high_vel_kept(self, tmp_path: Path):
        """Case 18b: dur < 0.060 but vel >= 0.2 → kept."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        notes = [_note(midi=60, t=0.5, dur=0.05, vel=0.5)]
        result = filter_phantom_notes(notes, stem, "piano")
        assert len(result) == 1

    def test_perceptual_insignificance_high_dur_low_vel_kept(self, tmp_path: Path):
        """Case 18c: dur >= 0.060 but vel < 0.2 → kept (only BOTH criteria drop)."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        notes = [_note(midi=60, t=0.5, dur=0.1, vel=0.1)]
        result = filter_phantom_notes(notes, stem, "piano")
        assert len(result) == 1

    def test_empty_input_returns_empty(self, tmp_path: Path):
        """Case 19: empty notes list → empty list without errors."""
        stem = tmp_path / "stem.wav"
        _write_sine(stem, amp=1.0)
        result = filter_phantom_notes([], stem, "piano")
        assert result == []
