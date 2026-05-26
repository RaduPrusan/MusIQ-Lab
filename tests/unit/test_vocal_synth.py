"""Tests for the vocal-synth test fixture itself.

The synth is a test helper, not production code, but it underpins every
vocal_consensus test downstream — so we test it directly to make sure the
ground truth it produces actually matches what we promise.
"""
import numpy as np
import pytest

from tests.unit._vocal_synth import (
    DEFAULT_FPS,
    SILENCE_RMS,
    SynthClip,
    VocalSynth,
    synth_steady_note,
)


class TestVocalSynthConstruction:
    def test_zero_duration_rejected(self):
        with pytest.raises(ValueError, match="duration"):
            VocalSynth(duration=0)

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError, match="duration"):
            VocalSynth(duration=-1.0)

    def test_note_outside_clip_rejected(self):
        synth = VocalSynth(duration=2.0)
        with pytest.raises(ValueError, match="outside clip duration"):
            synth.add_note(t_start=1.5, t_end=2.5, midi=69)

    def test_note_with_invalid_midi_rejected(self):
        synth = VocalSynth(duration=2.0)
        with pytest.raises(ValueError, match="midi"):
            synth.add_note(t_start=0.0, t_end=1.0, midi=200)

    def test_note_with_inverted_span_rejected(self):
        synth = VocalSynth(duration=2.0)
        with pytest.raises(ValueError, match="outside clip"):
            synth.add_note(t_start=1.0, t_end=0.5, midi=69)


class TestSteadyNoteRendering:
    def test_clip_shape_matches_duration_and_fps(self):
        clip = synth_steady_note(midi=69, clip_duration=2.0, fps=100.0)
        assert clip.n_frames == 200
        assert clip.fcpe.shape == (200,)
        assert clip.pesto.shape == (200,)
        assert clip.rms.shape == (200,)
        assert clip.fps == 100.0
        assert clip.duration_sec == 2.0

    def test_silence_outside_note(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        # Frames before the note: silent
        i_before = int(0.4 * clip.fps)
        assert clip.fcpe[i_before] == 0.0
        assert clip.pesto[i_before] == 0.0
        assert clip.rms[i_before] == pytest.approx(SILENCE_RMS)
        # Frames after the note: silent
        i_after = int(1.5 * clip.fps)
        assert clip.fcpe[i_after] == 0.0
        assert clip.pesto[i_after] == 0.0
        assert clip.rms[i_after] == pytest.approx(SILENCE_RMS)

    def test_note_frames_have_target_hz(self):
        # A4 = MIDI 69 = 440 Hz
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        # Sample a frame in the middle of the note
        i_mid = int(0.7 * clip.fps)
        assert clip.fcpe[i_mid] == pytest.approx(440.0, abs=1e-3)
        assert clip.pesto[i_mid] == pytest.approx(440.0, abs=1e-3)

    def test_cents_offset_honored_in_f0(self):
        # +30¢ above A4 = 440 * 2^(30/1200) ≈ 447.69 Hz
        expected = 440.0 * (2.0 ** (30.0 / 1200.0))
        clip = synth_steady_note(midi=69, cents=30.0, t_start=0.5, duration=0.4)
        i_mid = int(0.7 * clip.fps)
        assert clip.fcpe[i_mid] == pytest.approx(expected, rel=1e-6)
        assert clip.pesto[i_mid] == pytest.approx(expected, rel=1e-6)

    def test_basic_pitch_note_matches_timing(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        assert len(clip.basic_pitch_notes) == 1
        bp = clip.basic_pitch_notes[0]
        assert bp.start == 0.5
        assert bp.end == 0.9
        assert bp.pitch == 69

    def test_basic_pitch_pitch_quantized_to_semitone_within_50_cents(self):
        # +30¢ stays on the original semitone (basic-pitch quantizes)
        clip = synth_steady_note(midi=69, cents=30.0)
        assert clip.basic_pitch_notes[0].pitch == 69

    def test_basic_pitch_pitch_jumps_at_50_cents(self):
        # +50¢ is the boundary — basic-pitch would round up
        clip = synth_steady_note(midi=69, cents=50.0)
        assert clip.basic_pitch_notes[0].pitch == 70
        # And -50¢ should round down
        clip = synth_steady_note(midi=69, cents=-50.0)
        assert clip.basic_pitch_notes[0].pitch == 68

    def test_rms_during_note_matches_vel_peak(self):
        clip = synth_steady_note(midi=69, vel_peak=0.5, t_start=0.5, duration=0.4)
        i_mid = int(0.7 * clip.fps)
        assert clip.rms[i_mid] == pytest.approx(0.5)

    def test_basic_pitch_velocity_scaled_to_midi_range(self):
        clip = synth_steady_note(midi=69, vel_peak=0.7)
        assert clip.basic_pitch_notes[0].velocity == round(0.7 * 127)


class TestMultiNoteRendering:
    def test_two_notes_in_sequence(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69)
            .add_note(t_start=1.0, t_end=1.4, midi=72)
            .render()
        )
        assert len(clip.basic_pitch_notes) == 2
        assert clip.basic_pitch_notes[0].pitch == 69
        assert clip.basic_pitch_notes[1].pitch == 72

        # Frame inside the gap between them: silent
        i_gap = int(0.8 * clip.fps)
        assert clip.fcpe[i_gap] == 0.0
        assert clip.rms[i_gap] == pytest.approx(SILENCE_RMS)

    def test_unsorted_notes_get_sorted_in_truth_list(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=1.0, t_end=1.4, midi=72)
            .add_note(t_start=0.2, t_end=0.6, midi=69)
            .render()
        )
        # notes_truth should be ordered by t_start regardless of add order
        assert [n.midi for n in clip.notes_truth] == [69, 72]

    def test_returned_clip_is_dataclass_with_expected_fields(self):
        clip = synth_steady_note(midi=69)
        assert isinstance(clip, SynthClip)
        # Spot-check critical fields exist
        assert hasattr(clip, "fcpe")
        assert hasattr(clip, "pesto")
        assert hasattr(clip, "basic_pitch_notes")
        assert hasattr(clip, "rms")
        assert hasattr(clip, "notes_truth")


class TestDtypes:
    def test_arrays_are_float32(self):
        clip = synth_steady_note(midi=69)
        assert clip.fcpe.dtype == np.float32
        assert clip.pesto.dtype == np.float32
        assert clip.rms.dtype == np.float32


class TestDefaults:
    def test_default_fps_is_100(self):
        # Real FCPE / PESTO / dynamics all run at 100 fps; default matches
        assert DEFAULT_FPS == 100.0

    def test_default_silence_rms_matches_real_noise_floor(self):
        # Real-world stem silence sits around -60 dB ≈ 0.001 linear
        assert SILENCE_RMS == pytest.approx(0.001)
