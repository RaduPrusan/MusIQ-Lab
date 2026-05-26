"""Tests for analyze/derived/vocal_consensus/intonation.py."""
import math

import numpy as np
import pytest

from analyze.derived.vocal_consensus.intonation import (
    NoteIntonation,
    per_note_intonation,
)
from analyze.derived.vocal_consensus.voicing import consensus_voicing
from tests.unit._vocal_synth import VocalSynth, synth_steady_note


def _votes_for(clip):
    """Convenience: synth-baseline vote_count for use as input."""
    return consensus_voicing(
        clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
    )


# ---------- In-tune notes ----------------------------------------------

class TestInTune:
    def test_perfect_pitch_yields_zero_cents(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=0.0)
        votes = _votes_for(clip)
        results = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )
        assert len(results) == 1
        r = results[0]
        assert abs(r.intonation_cents) < 0.5  # below half-cent tolerance
        assert r.stability_cents < 0.5         # synthetic = perfectly steady
        assert r.confidence == pytest.approx(1.0)
        assert r.n_frames_used > 0

    def test_in_tune_at_different_pitches(self):
        for midi in (48, 60, 69, 72, 84):  # C3, C4, A4, C5, C6
            clip = synth_steady_note(midi=midi, t_start=0.5, duration=0.4, cents=0.0)
            votes = _votes_for(clip)
            r = per_note_intonation(
                clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
            )[0]
            assert abs(r.intonation_cents) < 0.5, f"midi={midi}"


# ---------- Off-pitch notes --------------------------------------------

class TestOffPitch:
    def test_sharp_25_cents(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=25.0)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        assert r.intonation_cents == pytest.approx(25.0, abs=0.5)

    def test_flat_30_cents(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=-30.0)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        assert r.intonation_cents == pytest.approx(-30.0, abs=0.5)

    def test_near_semitone_boundary(self):
        # +49¢ — basic-pitch still reports the original semitone (round
        # bias < +50¢), so intonation reads +49¢ relative to that integer
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=49.0)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        assert r.intonation_cents == pytest.approx(49.0, abs=0.5)

    def test_flat_near_semitone_boundary(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=-49.0)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        assert r.intonation_cents == pytest.approx(-49.0, abs=0.5)


# ---------- Multi-note alignment ---------------------------------------

class TestMultipleNotes:
    def test_results_aligned_with_input(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69, cents_offset=10.0)
            .add_note(t_start=1.0, t_end=1.4, midi=72, cents_offset=-15.0)
            .render()
        )
        votes = _votes_for(clip)
        results = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )
        assert len(results) == 2
        # Per-position alignment with basic_pitch_notes
        assert results[0].intonation_cents == pytest.approx(10.0, abs=0.5)
        assert results[1].intonation_cents == pytest.approx(-15.0, abs=0.5)

    def test_no_notes_yields_empty_list(self):
        n = 100
        results = per_note_intonation(
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.int8),
            [],
            100.0,
        )
        assert results == []


# ---------- Notes that can't be measured -------------------------------

class TestUnmeasurableNotes:
    def test_note_too_short_returns_empty_intonation(self):
        # 20ms note → middle 60% = 12ms = ~1 frame at 100 fps; below min_frames=3
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.5, t_end=0.52, midi=69)
            .render()
        )
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        assert math.isnan(r.intonation_cents)
        assert math.isnan(r.stability_cents)
        assert r.confidence == 0.0
        assert r.n_frames_used == 0

    def test_note_with_unvoiced_F0_returns_empty(self):
        # Build a synth note normally, then wipe F0 to simulate "basic-pitch
        # had a note here but the F0 estimators reject it" (e.g. spectral
        # bleed that fooled basic-pitch but not the pitch trackers).
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        zero_fcpe = np.zeros_like(clip.fcpe)
        zero_pesto = np.zeros_like(clip.pesto)
        zero_votes = np.zeros_like(_votes_for(clip))
        r = per_note_intonation(
            zero_fcpe, zero_pesto, zero_votes,
            clip.basic_pitch_notes, clip.fps,
        )[0]
        assert math.isnan(r.intonation_cents)
        assert r.confidence == 0.0

    def test_fcpe_pesto_disagreement_drops_confidence(self):
        # Force PESTO to disagree by ~100¢ (above the 50¢ threshold) on
        # half the note's frames. Confidence should drop accordingly.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        # Frame indices for the note
        i0 = int(round(0.5 * clip.fps))
        i1 = int(round(0.9 * clip.fps))
        i_mid = (i0 + i1) // 2

        # Bend PESTO ~100¢ flat in second half of note (forces disagreement)
        bent_pesto = clip.pesto.copy()
        bent_pesto[i_mid:i1] = clip.pesto[i_mid:i1] * (2.0 ** (-100.0 / 1200.0))

        votes = consensus_voicing(
            clip.fcpe, bent_pesto, clip.basic_pitch_notes, clip.fps,
        )
        r = per_note_intonation(
            clip.fcpe, bent_pesto, votes,
            clip.basic_pitch_notes, clip.fps,
        )[0]
        # Confidence should be roughly 0.5 (only first half of middle window
        # counts as agreeing). Allow generous tolerance for window edges.
        assert 0.3 < r.confidence < 0.7
        assert r.n_frames_used > 0


# ---------- Octave-fold safety net -------------------------------------

class TestOctaveFold:
    def test_octave_glitch_residual_does_not_corrupt_intonation(self):
        # Setup: basic-pitch says A4 (MIDI 69), but FCPE/PESTO are an octave
        # high (A5) and within 50¢ of each other. The cents-from-target
        # would be +1200¢; without folding, the median would be a wildly
        # wrong number. Folded into [-600, 600], it should read ~0¢.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0 = int(round(0.5 * clip.fps))
        i1 = int(round(0.9 * clip.fps))
        glitched_fcpe = clip.fcpe.copy()
        glitched_pesto = clip.pesto.copy()
        glitched_fcpe[i0:i1] *= 2.0
        glitched_pesto[i0:i1] *= 2.0

        votes = consensus_voicing(
            glitched_fcpe, glitched_pesto, clip.basic_pitch_notes, clip.fps,
        )
        r = per_note_intonation(
            glitched_fcpe, glitched_pesto, votes,
            clip.basic_pitch_notes, clip.fps,
        )[0]
        # Folded cents should land near 0 (the octave-up glitch reads as
        # +1200¢ raw, folds to 0¢)
        assert abs(r.intonation_cents) < 1.0


# ---------- Tunable parameters -----------------------------------------

class TestTunableParameters:
    def test_strict_agreement_threshold_drops_confidence(self):
        # Force PESTO to be exactly 30¢ off; with default 50¢ threshold
        # all frames agree, but with a stricter 20¢ threshold none do.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0 = int(round(0.5 * clip.fps))
        i1 = int(round(0.9 * clip.fps))
        bent_pesto = clip.pesto.copy()
        bent_pesto[i0:i1] = clip.pesto[i0:i1] * (2.0 ** (30.0 / 1200.0))

        votes = consensus_voicing(
            clip.fcpe, bent_pesto, clip.basic_pitch_notes, clip.fps,
        )
        loose = per_note_intonation(
            clip.fcpe, bent_pesto, votes, clip.basic_pitch_notes, clip.fps,
            cents_agreement_threshold=50.0,
        )[0]
        strict = per_note_intonation(
            clip.fcpe, bent_pesto, votes, clip.basic_pitch_notes, clip.fps,
            cents_agreement_threshold=20.0,
        )[0]
        assert loose.confidence == pytest.approx(1.0)
        assert strict.confidence == 0.0

    def test_smaller_middle_fraction_reduces_frames_used(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = _votes_for(clip)
        wide = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
            middle_fraction=0.6,
        )[0]
        narrow = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
            middle_fraction=0.3,
        )[0]
        assert narrow.n_frames_used < wide.n_frames_used


# ---------- Validation -------------------------------------------------

class TestInputValidation:
    def test_fcpe_pesto_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="fcpe/pesto shape mismatch"):
            per_note_intonation(
                np.zeros(100, dtype=np.float32),
                np.zeros(99, dtype=np.float32),
                np.zeros(100, dtype=np.int8),
                [], 100.0,
            )

    def test_vote_count_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="vote_count shape mismatch"):
            per_note_intonation(
                np.zeros(100, dtype=np.float32),
                np.zeros(100, dtype=np.float32),
                np.zeros(99, dtype=np.int8),
                [], 100.0,
            )

    def test_2d_input_raises(self):
        with pytest.raises(ValueError, match="1-D"):
            per_note_intonation(
                np.zeros((10, 2), dtype=np.float32),
                np.zeros((10, 2), dtype=np.float32),
                np.zeros((10, 2), dtype=np.int8),
                [], 100.0,
            )

    def test_invalid_middle_fraction_raises(self):
        with pytest.raises(ValueError, match="middle_fraction"):
            per_note_intonation(
                np.zeros(100, dtype=np.float32),
                np.zeros(100, dtype=np.float32),
                np.zeros(100, dtype=np.int8),
                [], 100.0,
                middle_fraction=0.0,
            )
        with pytest.raises(ValueError, match="middle_fraction"):
            per_note_intonation(
                np.zeros(100, dtype=np.float32),
                np.zeros(100, dtype=np.float32),
                np.zeros(100, dtype=np.int8),
                [], 100.0,
                middle_fraction=1.5,
            )


# ---------- Output dataclass -------------------------------------------

class TestOutputShape:
    def test_returns_note_intonation_dataclass(self):
        clip = synth_steady_note(midi=69)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )
        assert all(isinstance(x, NoteIntonation) for x in r)

    def test_dataclass_fields(self):
        # Spot-check the NoteIntonation API
        clip = synth_steady_note(midi=69)
        votes = _votes_for(clip)
        r = per_note_intonation(
            clip.fcpe, clip.pesto, votes, clip.basic_pitch_notes, clip.fps,
        )[0]
        # All four fields exist and have expected types
        assert isinstance(r.intonation_cents, float)
        assert isinstance(r.stability_cents, float)
        assert isinstance(r.confidence, float)
        assert isinstance(r.n_frames_used, int)
