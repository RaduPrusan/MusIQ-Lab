"""Tests for analyze/derived/vocal_consensus/octave.py."""
import numpy as np
import pytest

from analyze.derived.vocal_consensus.octave import correct_octaves
from tests.unit._vocal_synth import VocalSynth, synth_steady_note


# ---------- Helpers -----------------------------------------------------

def _frames_for(t_start, t_end, fps):
    """Frame indices [i0, i1) for a time span."""
    return int(round(t_start * fps)), int(round(t_end * fps))


# ---------- Happy path: no corrections needed ---------------------------

class TestNoCorrectionNeeded:
    def test_steady_note_unchanged(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        f, p, c = correct_octaves(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(f, clip.fcpe)
        np.testing.assert_array_equal(p, clip.pesto)
        assert (c == 0).all()

    def test_silence_unchanged(self):
        # No notes at all — everything is silence
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.5, t_end=0.9, midi=69)
            .render()
        )
        # Now wipe basic_pitch_notes to simulate "no anchor"
        f, p, c = correct_octaves(clip.fcpe, clip.pesto, [], clip.fps)
        np.testing.assert_array_equal(f, clip.fcpe)
        np.testing.assert_array_equal(p, clip.pesto)
        assert (c == 0).all()

    def test_unvoiced_frames_skipped(self):
        # Octave glitch in unvoiced region — nothing to correct
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        # Unvoiced frames stay zero; no correction should fire
        f, p, c = correct_octaves(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.0, 0.5, clip.fps)
        assert (f[i0:i1] == 0).all()
        assert (p[i0:i1] == 0).all()
        assert (c[i0:i1] == 0).all()


# ---------- FCPE octave glitches ----------------------------------------

class TestFCPEOctaveCorrection:
    def test_fcpe_one_octave_low_gets_folded_up(self):
        # Build a steady A4 note, then push FCPE down an octave for the note span
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i0:i1] = clip.fcpe[i0:i1] / 2.0  # A3 instead of A4

        f, p, c = correct_octaves(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # FCPE should be back at A4 (440 Hz) within float tolerance
        np.testing.assert_allclose(f[i0:i1], 440.0, atol=1e-3)
        # PESTO untouched
        np.testing.assert_array_equal(p, clip.pesto)
        # corrections: column 0 = +1 across the note span, 0 elsewhere
        assert (c[i0:i1, 0] == 1).all()
        assert (c[i0:i1, 1] == 0).all()
        assert (c[:i0, 0] == 0).all() and (c[i1:, 0] == 0).all()

    def test_fcpe_one_octave_high_gets_folded_down(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i0:i1] = clip.fcpe[i0:i1] * 2.0  # A5 instead of A4

        f, p, c = correct_octaves(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_allclose(f[i0:i1], 440.0, atol=1e-3)
        assert (c[i0:i1, 0] == -1).all()

    def test_two_octave_glitch_corrected_when_explicitly_allowed(self):
        # ±2 octaves correction works ONLY when max_abs_octave_shift is
        # raised. Default of 1 leaves them alone (separate test below).
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i0:i1] = clip.fcpe[i0:i1] * 4.0  # A6 instead of A4

        f, p, c = correct_octaves(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            max_abs_octave_shift=2,
        )
        np.testing.assert_allclose(f[i0:i1], 440.0, atol=1e-3)
        assert (c[i0:i1, 0] == -2).all()

    def test_two_octave_glitch_NOT_corrected_at_default_cap(self):
        # With default max_abs_octave_shift=1, a 2-octave glitch is left
        # untouched — this protects against poisoned anchors (basic-pitch
        # hallucinating a high "vocal" note while F0 is actually low).
        # Multi-octave folds in real audio almost always indicate the
        # anchor itself is wrong, not the F0 estimator.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i0:i1] = clip.fcpe[i0:i1] * 4.0  # A6 instead of A4

        f, p, c = correct_octaves(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # FCPE remains at glitched A6, NOT folded back
        np.testing.assert_allclose(f[i0:i1], 1760.0, atol=1e-3)
        # No correction recorded
        assert (c[i0:i1, 0] == 0).all()

    def test_max_abs_octave_shift_must_be_positive(self):
        clip = synth_steady_note(midi=69)
        with pytest.raises(ValueError, match="max_abs_octave_shift"):
            correct_octaves(
                clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
                max_abs_octave_shift=0,
            )


# ---------- PESTO glitches (symmetric to FCPE) -------------------------

class TestPESTOOctaveCorrection:
    def test_pesto_one_octave_low_gets_folded_up(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        glitched_pesto = clip.pesto.copy()
        glitched_pesto[i0:i1] = clip.pesto[i0:i1] / 2.0

        f, p, c = correct_octaves(
            clip.fcpe, glitched_pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(f, clip.fcpe)  # FCPE untouched
        np.testing.assert_allclose(p[i0:i1], 440.0, atol=1e-3)
        assert (c[i0:i1, 1] == 1).all()
        assert (c[i0:i1, 0] == 0).all()


# ---------- Both estimators glitched ------------------------------------

class TestBothGlitched:
    def test_both_octave_low_both_folded_up(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        gf = clip.fcpe.copy(); gf[i0:i1] /= 2.0
        gp = clip.pesto.copy(); gp[i0:i1] /= 2.0

        f, p, c = correct_octaves(gf, gp, clip.basic_pitch_notes, clip.fps)
        np.testing.assert_allclose(f[i0:i1], 440.0, atol=1e-3)
        np.testing.assert_allclose(p[i0:i1], 440.0, atol=1e-3)
        assert (c[i0:i1, 0] == 1).all() and (c[i0:i1, 1] == 1).all()

    def test_opposite_directions_each_folded_toward_anchor(self):
        # FCPE goes UP an octave (glitch high), PESTO goes DOWN an octave
        # (glitch low). Both should fold back to the anchor's octave (A4).
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        gf = clip.fcpe.copy(); gf[i0:i1] *= 2.0
        gp = clip.pesto.copy(); gp[i0:i1] /= 2.0

        f, p, c = correct_octaves(gf, gp, clip.basic_pitch_notes, clip.fps)
        np.testing.assert_allclose(f[i0:i1], 440.0, atol=1e-3)
        np.testing.assert_allclose(p[i0:i1], 440.0, atol=1e-3)
        assert (c[i0:i1, 0] == -1).all()  # folded down
        assert (c[i0:i1, 1] == 1).all()   # folded up


# ---------- Pitch-class mismatch (NOT an octave error) ------------------

class TestPitchClassMismatch:
    def test_different_note_pc_not_corrected(self):
        # FCPE reports a Bb4 (466 Hz, MIDI 70) while basic-pitch says A4 (69).
        # PCs differ (10 vs 9) → this is NOT an octave error, just a different
        # note. Algorithm must NOT fire (would be a false correction).
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        bad_fcpe = clip.fcpe.copy()
        bad_fcpe[i0:i1] = 466.0  # Bb4

        f, p, c = correct_octaves(
            bad_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # FCPE should be UNCHANGED — the algorithm only octave-corrects,
        # not note-corrects. The bad value stays in for downstream
        # confidence scoring to penalize.
        np.testing.assert_array_equal(f, bad_fcpe)
        assert (c[i0:i1, 0] == 0).all()


# ---------- No basic-pitch anchor ---------------------------------------

class TestNoAnchor:
    def test_octave_glitch_during_silence_not_corrected(self):
        # FCPE reports a (glitched) frequency in a region where basic-pitch
        # says nothing. Without an anchor, no correction can fire —
        # conservative by design.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i_silence_start, i_silence_end = _frames_for(0.05, 0.45, clip.fps)
        bad_fcpe = clip.fcpe.copy()
        bad_fcpe[i_silence_start:i_silence_end] = 880.0  # A5 hallucinated in silence

        f, p, c = correct_octaves(
            bad_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(f, bad_fcpe)
        assert (c == 0).all()


# ---------- Multi-note ---------------------------------------------------

class TestMultipleNotes:
    def test_each_note_corrected_independently(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69)   # A4
            .add_note(t_start=1.0, t_end=1.4, midi=72)   # C5
            .render()
        )
        i0a, i1a = _frames_for(0.2, 0.6, clip.fps)
        i0b, i1b = _frames_for(1.0, 1.4, clip.fps)

        # Glitch FCPE down on the A4 note, up on the C5 note
        gf = clip.fcpe.copy()
        gf[i0a:i1a] /= 2.0  # A3 instead of A4
        gf[i0b:i1b] *= 2.0  # C6 instead of C5

        f, p, c = correct_octaves(
            gf, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # Both notes corrected to their respective anchors
        np.testing.assert_allclose(f[i0a:i1a], 440.0, atol=1e-3)             # A4
        np.testing.assert_allclose(f[i0b:i1b], 523.2511, atol=1e-2)          # C5
        assert (c[i0a:i1a, 0] == 1).all()    # folded up
        assert (c[i0b:i1b, 0] == -1).all()   # folded down


# ---------- Input validation -------------------------------------------

class TestInputValidation:
    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="shape mismatch"):
            correct_octaves(
                np.zeros(100, dtype=np.float32),
                np.zeros(99, dtype=np.float32),
                [],
                100.0,
            )

    def test_2d_input_raises(self):
        with pytest.raises(ValueError, match="1-D"):
            correct_octaves(
                np.zeros((10, 2), dtype=np.float32),
                np.zeros((10, 2), dtype=np.float32),
                [],
                100.0,
            )

    def test_inputs_not_mutated(self):
        # Defensive: callers shouldn't have their arrays modified
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        gf = clip.fcpe.copy()
        gf[i0:i1] /= 2.0
        gf_before = gf.copy()

        _f, _p, _c = correct_octaves(
            gf, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(gf, gf_before)


# ---------- Output shape -----------------------------------------------

class TestOutputShape:
    def test_corrections_shape_and_dtype(self):
        clip = synth_steady_note(midi=69)
        _f, _p, c = correct_octaves(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert c.shape == (clip.n_frames, 2)
        assert c.dtype == np.int8

    def test_outputs_are_independent_arrays(self):
        # Modifying one of the outputs must NOT affect the input
        clip = synth_steady_note(midi=69)
        f, _p, _c = correct_octaves(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        f[0] = 12345.0  # mutate output
        assert clip.fcpe[0] != 12345.0
