"""Tests for analyze/derived/vocal_consensus/voicing.py."""
import numpy as np
import pytest

from analyze.derived.vocal_consensus.voicing import consensus_voicing
from tests.unit._vocal_synth import VocalSynth, synth_steady_note


def _frames_for(t_start, t_end, fps):
    return int(round(t_start * fps)), int(round(t_end * fps))


# ---------- Trivial cases ----------------------------------------------

class TestEmptyInputs:
    def test_all_silence_yields_zero_votes(self):
        zeros = np.zeros(200, dtype=np.float32)
        votes = consensus_voicing(zeros, zeros, [], 100.0)
        assert votes.shape == (200,)
        assert (votes == 0).all()

    def test_single_zero_length_array(self):
        empty = np.array([], dtype=np.float32)
        votes = consensus_voicing(empty, empty, [], 100.0)
        assert votes.shape == (0,)


# ---------- All-three-agree happy path ---------------------------------

class TestAllAgree:
    def test_steady_note_3_votes_during_note_0_outside(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 3).all()
        assert (votes[:i0] == 0).all()
        assert (votes[i1:] == 0).all()


# ---------- Single-source voicing (1 vote) -----------------------------

class TestSingleSource:
    def test_only_fcpe_voiced_yields_one_vote(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        # Wipe PESTO and basic-pitch to leave only FCPE voiced
        votes = consensus_voicing(
            clip.fcpe, np.zeros_like(clip.pesto), [], clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 1).all()
        assert (votes[:i0] == 0).all()

    def test_only_pesto_voiced_yields_one_vote(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            np.zeros_like(clip.fcpe), clip.pesto, [], clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 1).all()

    def test_only_basic_voiced_yields_one_vote(self):
        # basic-pitch hallucinating in silence — F0 estimators agree it's silent
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            np.zeros_like(clip.fcpe), np.zeros_like(clip.pesto),
            clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 1).all()

    def test_voicing_decision_rejects_lone_basic_pitch(self):
        # The voicing decision (>= 2) must NOT accept basic-pitch alone
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            np.zeros_like(clip.fcpe), np.zeros_like(clip.pesto),
            clip.basic_pitch_notes, clip.fps,
        )
        decision = votes >= 2
        assert not decision.any()


# ---------- Two-source voicing (2 votes) -------------------------------

class TestTwoSources:
    def test_fcpe_plus_pesto_yields_2_votes(self):
        # F0 estimators agree, basic-pitch silent (e.g. between basic-pitch
        # notes but F0 still reads voiced — common in legato passages where
        # basic-pitch's onset detector hasn't fired but the singer is sounding)
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, [], clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 2).all()
        # And the voicing decision says "voiced"
        decision = votes >= 2
        assert decision[i0:i1].all()

    def test_fcpe_plus_basic_yields_2_votes(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            clip.fcpe, np.zeros_like(clip.pesto),
            clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 2).all()

    def test_pesto_plus_basic_yields_2_votes(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        votes = consensus_voicing(
            np.zeros_like(clip.fcpe), clip.pesto,
            clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 2).all()


# ---------- Mixed regions ----------------------------------------------

class TestMixedRegions:
    def test_partial_voicing_dropout_in_fcpe(self):
        # Simulate FCPE losing voicing in the middle of a note (real-world
        # case: percussive consonant in middle of a sung word, FCPE drops
        # but basic-pitch + PESTO carry through). Vote count should
        # transition from 3 → 2 → 3 across the dropout, decision stays True.
        clip = synth_steady_note(midi=69, t_start=0.4, duration=0.6)  # 0.4-1.0s
        i0, i1 = _frames_for(0.4, 1.0, clip.fps)
        # Inject FCPE dropout in middle 100ms
        i_drop_a, i_drop_b = _frames_for(0.65, 0.75, clip.fps)
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i_drop_a:i_drop_b] = 0.0

        votes = consensus_voicing(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # Before dropout: 3 votes. During dropout: 2 (PESTO + basic). After: 3.
        assert (votes[i0:i_drop_a] == 3).all()
        assert (votes[i_drop_a:i_drop_b] == 2).all()
        assert (votes[i_drop_b:i1] == 3).all()
        # Voicing decision stays True throughout — dropout doesn't break the note
        assert (votes[i0:i1] >= 2).all()

    def test_two_notes_with_silence_between(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69)
            .add_note(t_start=1.0, t_end=1.4, midi=72)
            .render()
        )
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0a, i1a = _frames_for(0.2, 0.6, clip.fps)
        i0b, i1b = _frames_for(1.0, 1.4, clip.fps)
        assert (votes[i0a:i1a] == 3).all()    # first note all-voiced
        assert (votes[i1a:i0b] == 0).all()    # gap fully silent
        assert (votes[i0b:i1b] == 3).all()    # second note all-voiced


# ---------- Output shape & dtype ---------------------------------------

class TestOutputShape:
    def test_output_dtype_is_int8(self):
        clip = synth_steady_note(midi=69)
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert votes.dtype == np.int8

    def test_output_shape_matches_input(self):
        for n in (50, 100, 1000, 17):
            zeros = np.zeros(n, dtype=np.float32)
            votes = consensus_voicing(zeros, zeros, [], 100.0)
            assert votes.shape == (n,)

    def test_value_range_is_0_to_3(self):
        clip = synth_steady_note(midi=69)
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert votes.min() >= 0
        assert votes.max() <= 3


# ---------- RMS floor gate ---------------------------------------------

class TestRMSFloorGate:
    def test_default_behavior_unchanged_without_rms(self):
        # Calling without `rms` must produce identical output to today
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        a = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        b = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=None,
        )
        np.testing.assert_array_equal(a, b)

    def test_high_rms_does_not_change_vote_count(self):
        # All-loud RMS (well above any sensible floor) leaves votes alone
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        loud = np.full_like(clip.fcpe, 0.5)  # ~-6 dBFS, very loud
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=loud,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 3).all()

    def test_rms_below_floor_zeroes_votes_during_note(self):
        # Pathological case: F0 estimators report voiced AND basic-pitch
        # has a note, but RMS is at silence floor. The veto wins.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        silent = np.full_like(clip.fcpe, 1e-5)  # ~-100 dBFS
        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=silent,
        )
        assert (votes == 0).all()

    def test_rms_gate_catches_f0_hallucination_in_silence(self):
        # The actual real-world failure mode this gate exists for.
        # FCPE hallucinates a voiced reading at -60 dBFS, where neither
        # PESTO nor basic-pitch is voiced. Without the gate: vote_count=1.
        # With the gate: vote_count=0 (vetoed by sub-floor RMS).
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        rms = np.full(n, 0.001, dtype=np.float32)  # ~-60 dBFS, silence

        # Inject FCPE hallucination at frames 50-100 (a "voiced" reading
        # despite -60 dBFS underlying signal)
        fcpe[50:100] = 220.0

        without_gate = consensus_voicing(fcpe, pesto, [], fps)
        with_gate = consensus_voicing(fcpe, pesto, [], fps, rms=rms)

        assert (without_gate[50:100] == 1).all()  # FCPE alone votes voiced
        assert (with_gate == 0).all()             # gate kills the false positive

    def test_rms_floor_applies_only_to_below_floor_frames(self):
        # Frame-by-frame application: above-floor frames keep their votes,
        # below-floor frames get zeroed
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)

        # Build an RMS array: silent everywhere EXCEPT in the first half
        # of the note, where it's loud. Second half should get vetoed.
        rms = np.full_like(clip.fcpe, 1e-5)  # silent floor
        i_mid = (i0 + i1) // 2
        rms[i0:i_mid] = 0.5  # loud first half

        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=rms,
        )
        assert (votes[i0:i_mid] == 3).all()      # first half: vote count preserved
        assert (votes[i_mid:i1] == 0).all()      # second half: vetoed by floor
        assert (votes[:i0] == 0).all()           # outside note: already 0

    def test_custom_floor_threshold(self):
        # With default -45 dBFS floor, RMS=0.01 (-40 dBFS) is ABOVE the
        # floor — votes preserved. With a stricter -30 dBFS floor, the
        # same RMS is BELOW the floor — votes vetoed.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        rms = np.full_like(clip.fcpe, 0.01)  # -40 dBFS

        i0, i1 = _frames_for(0.5, 0.9, clip.fps)

        permissive = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=rms, rms_floor_db=-45.0,
        )
        strict = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=rms, rms_floor_db=-30.0,
        )
        assert (permissive[i0:i1] == 3).all()
        assert (strict[i0:i1] == 0).all()

    def test_floor_is_strict_inequality(self):
        # RMS exactly at the floor should NOT be vetoed (uses strict <,
        # documented behavior). This protects against accidental veto on
        # the boundary frame.
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        floor_db = -45.0
        floor_linear = 10.0 ** (floor_db / 20.0)
        rms = np.full_like(clip.fcpe, floor_linear)  # exactly at floor

        votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=rms, rms_floor_db=floor_db,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (votes[i0:i1] == 3).all()  # exactly-at-floor frames kept

    def test_rms_shape_mismatch_raises(self):
        clip = synth_steady_note(midi=69)
        wrong_shape = np.zeros(clip.n_frames + 1, dtype=np.float32)
        with pytest.raises(ValueError, match="rms shape mismatch"):
            consensus_voicing(
                clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
                rms=wrong_shape,
            )

    def test_rms_input_not_mutated(self):
        clip = synth_steady_note(midi=69)
        rms = np.full_like(clip.fcpe, 1e-5)
        rms_before = rms.copy()
        _votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            rms=rms,
        )
        np.testing.assert_array_equal(rms, rms_before)


# ---------- Input validation -------------------------------------------

class TestInputValidation:
    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="shape mismatch"):
            consensus_voicing(
                np.zeros(100, dtype=np.float32),
                np.zeros(99, dtype=np.float32),
                [], 100.0,
            )

    def test_2d_input_raises(self):
        with pytest.raises(ValueError, match="1-D"):
            consensus_voicing(
                np.zeros((10, 2), dtype=np.float32),
                np.zeros((10, 2), dtype=np.float32),
                [], 100.0,
            )

    def test_inputs_not_mutated(self):
        clip = synth_steady_note(midi=69)
        fcpe_before = clip.fcpe.copy()
        pesto_before = clip.pesto.copy()
        _votes = consensus_voicing(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(clip.fcpe, fcpe_before)
        np.testing.assert_array_equal(clip.pesto, pesto_before)
