"""Tests for analyze/derived/vocal_consensus/contour.py."""
import math

import numpy as np
import pytest

from analyze.derived.vocal_consensus.contour import (
    ContourResult,
    process_contour,
)
from analyze.derived.vocal_consensus.intonation import NoteIntonation
from tests.unit._vocal_synth import VocalSynth, synth_steady_note


def _frames_for(t_start, t_end, fps):
    return int(round(t_start * fps)), int(round(t_end * fps))


# ---------- Happy path -------------------------------------------------

class TestHappyPath:
    def test_steady_note_produces_consensus_during_note_nan_outside(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=10.0)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        # Inside the note: consensus_f0 is finite (synth's exact target Hz)
        target_hz = 440.0 * (2.0 ** (10.0 / 1200.0))  # +10¢ above A4
        np.testing.assert_allclose(result.consensus_f0[i0:i1], target_hz, atol=1e-3)
        # Outside: NaN
        assert np.isnan(result.consensus_f0[:i0]).all()
        assert np.isnan(result.consensus_f0[i1:]).all()

    def test_steady_note_yields_one_intonation_entry(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4, cents=10.0)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert len(result.note_intonation) == 1
        assert result.note_intonation[0].intonation_cents == pytest.approx(10.0, abs=0.5)
        assert result.note_intonation[0].confidence == pytest.approx(1.0)

    def test_no_corrections_needed(self):
        # Steady note, no glitches → octave_corrections all 0
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert (result.octave_corrections == 0).all()

    def test_vote_count_is_3_during_note(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        assert (result.vote_count[i0:i1] == 3).all()


# ---------- Octave glitch end-to-end -----------------------------------

class TestOctaveGlitchEndToEnd:
    def test_fcpe_glitch_is_corrected_before_consensus_built(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)

        # Force FCPE up an octave during the note
        glitched_fcpe = clip.fcpe.copy()
        glitched_fcpe[i0:i1] *= 2.0

        result = process_contour(
            glitched_fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        # FCPE was corrected back to A4 (440 Hz)
        np.testing.assert_allclose(
            result.fcpe_corrected[i0:i1], 440.0, atol=1e-3,
        )
        # consensus_f0 emerges normally — corrected FCPE matches PESTO
        np.testing.assert_allclose(
            result.consensus_f0[i0:i1], 440.0, atol=1e-3,
        )
        # octave_corrections logs the -1 fold
        assert (result.octave_corrections[i0:i1, 0] == -1).all()
        # Intonation reads as in-tune (corrected pitch matches MIDI)
        assert abs(result.note_intonation[0].intonation_cents) < 1.0


# ---------- Disagreement / no-consensus regions ------------------------

class TestNoConsensus:
    def test_step2_fallback_disagreement_no_anchor_yields_nan_consensus(self):
        # Step 2 fallback contract: disagreement without anchor → NaN
        # (the heuristic builder defers; it has no continuity prior).
        # Viterbi (default in Step 4) instead picks one of the F0s using
        # transition smoothing — see TestViterbiBehavior below.
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0
        pesto[50:100] = 440.0 * (2.0 ** (-80.0 / 1200.0))  # 80¢ flat

        result = process_contour(fcpe, pesto, [], fps, viterbi_enabled=False)
        assert np.isnan(result.consensus_f0[50:100]).all()
        assert (result.agreement_strength[50:100] == 0).all()


# ---------- Agreement-strength bucket semantics (Phase 0c Step 2) ------

class TestAgreementStrengthStep2Fallback:
    """The Step 2 heuristic builder's bucket contract.

    Exercised via `viterbi_enabled=False`. Step 4 (Viterbi, default-on)
    re-uses the same `agreement_strength` slot but produces continuous
    `exp(−emission_cost)` values rather than these discrete buckets —
    see TestViterbiBehavior below for the new behavior.
    """
    def test_strong_when_both_f0_agree(self):
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            viterbi_enabled=False,
        )
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        # Synth puts FCPE = PESTO (perfect agreement) → strength ≈ 1.0
        assert (result.agreement_strength[i0:i1] >= 0.9).all()

    def test_strength_decreases_with_cents_disagreement(self):
        # Linear from 1.0 (0¢ diff) to 0.7 (at 50¢ threshold)
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0
        # 25¢ apart → strength = 1.0 - (25/50)*0.3 = 0.85
        pesto[50:100] = 440.0 * (2.0 ** (25.0 / 1200.0))

        result = process_contour(fcpe, pesto, [], fps, viterbi_enabled=False)
        finite = np.isfinite(result.consensus_f0[50:100])
        assert finite.all()
        np.testing.assert_allclose(
            result.agreement_strength[50:100], 0.85, atol=0.01,
        )

    def test_medium_when_anchor_breaks_disagreement_tie(self):
        # PESTO 80¢ flat (beyond threshold), FCPE on pitch, anchor active →
        # FCPE wins by anchor proximity, strength = 0.4
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        bent_pesto = clip.pesto.copy()
        bent_pesto[i0:i1] = clip.pesto[i0:i1] * (2.0 ** (-80.0 / 1200.0))

        result = process_contour(
            clip.fcpe, bent_pesto, clip.basic_pitch_notes, clip.fps,
            viterbi_enabled=False,
        )
        # Consensus picks FCPE (closer to MIDI 69)
        np.testing.assert_allclose(
            result.consensus_f0[i0:i1], clip.fcpe[i0:i1], atol=1e-3,
        )
        np.testing.assert_allclose(
            result.agreement_strength[i0:i1], 0.4, atol=1e-6,
        )

    def test_medium_when_only_one_f0_with_anchor(self):
        # Only FCPE voiced in note region, anchor active → strength = 0.5
        from tests.unit._vocal_synth import SynthBPNote
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0  # voiced, in range
        bp_notes = [SynthBPNote(start=0.5, end=1.0, pitch=69)]

        result = process_contour(fcpe, pesto, bp_notes, fps, viterbi_enabled=False)
        np.testing.assert_allclose(
            result.consensus_f0[50:100], 440.0, atol=1e-3,
        )
        np.testing.assert_allclose(
            result.agreement_strength[50:100], 0.5, atol=1e-6,
        )

    def test_weak_when_only_one_f0_no_anchor(self):
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0

        result = process_contour(fcpe, pesto, [], fps, viterbi_enabled=False)
        np.testing.assert_allclose(
            result.consensus_f0[50:100], 440.0, atol=1e-3,
        )
        np.testing.assert_allclose(
            result.agreement_strength[50:100], 0.25, atol=1e-6,
        )

    def test_zero_strength_when_all_unvoiced(self):
        n = 200
        fps = 100.0
        result = process_contour(
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
            [], fps,
            viterbi_enabled=False,
        )
        assert (result.agreement_strength == 0.0).all()
        assert np.isnan(result.consensus_f0).all()

    def test_partial_disagreement_yields_strong_then_medium(self):
        # First half of the note: FCPE/PESTO agree → strong.
        # Second half: PESTO bent 80¢ flat, anchor active → medium (0.4).
        clip = synth_steady_note(midi=69, t_start=0.5, duration=0.4)
        i0, i1 = _frames_for(0.5, 0.9, clip.fps)
        i_mid = (i0 + i1) // 2
        bent_pesto = clip.pesto.copy()
        bent_pesto[i_mid:i1] = clip.pesto[i_mid:i1] * (2.0 ** (-80.0 / 1200.0))

        result = process_contour(
            clip.fcpe, bent_pesto, clip.basic_pitch_notes, clip.fps,
            viterbi_enabled=False,
        )
        # First half: both in agreement → strong (≥0.9)
        assert (result.agreement_strength[i0:i_mid] >= 0.9).all()
        # Second half: anchor-tied disagreement → medium (0.4)
        np.testing.assert_allclose(
            result.agreement_strength[i_mid:i1], 0.4, atol=1e-6,
        )
        # All frames produce a finite consensus (no fragmenting on disagreement)
        assert np.isfinite(result.consensus_f0[i0:i1]).all()

    def test_rms_veto_zeros_strength_even_when_f0_voiced(self):
        # Frames muted by RMS-floor veto must have strength 0 / consensus NaN
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        rms = np.full(n, 0.001, dtype=np.float32)  # below floor everywhere
        fcpe[50:100] = 220.0
        pesto[50:100] = 220.0

        result = process_contour(
            fcpe, pesto, [], fps, rms=rms, rms_floor_db=-45.0,
            viterbi_enabled=False,
        )
        assert (result.agreement_strength == 0.0).all()
        assert np.isnan(result.consensus_f0).all()


# ---------- Viterbi-flow behavior (Phase 0c Step 4, default-on) --------

class TestViterbiBehavior:
    """Step 4 default behavior. The Viterbi pass replaces the heuristic
    bucket builder; agreement_strength is now exp(−emission_cost), and
    disagreement-without-anchor is resolved by temporal continuity
    rather than left as NaN."""

    def test_viterbi_resolves_disagreement_no_anchor(self):
        # 80¢ apart, no anchor — Viterbi's transition smoothing picks one
        # F0 (the more confident one when synthesized confidence is equal,
        # both options are 50¢ off the mean — Viterbi commits to one and
        # holds it). Result: finite consensus_f0 (NOT NaN as in Step 2).
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0
        pesto[50:100] = 440.0 * (2.0 ** (-80.0 / 1200.0))
        result = process_contour(fcpe, pesto, [], fps)
        # All frames in the voiced region produce a finite consensus
        assert np.isfinite(result.consensus_f0[50:100]).all()

    def test_viterbi_zero_strength_in_silence(self):
        n = 200
        fps = 100.0
        result = process_contour(
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
            [], fps,
        )
        # Unvoiced state forces strength to 0 (post-clip in viterbi_smooth)
        assert (result.agreement_strength == 0.0).all()
        assert np.isnan(result.consensus_f0).all()

    def test_viterbi_rms_veto_zeros_strength(self):
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        rms = np.full(n, 0.001, dtype=np.float32)  # below floor everywhere
        fcpe[50:100] = 220.0
        pesto[50:100] = 220.0
        result = process_contour(
            fcpe, pesto, [], fps, rms=rms, rms_floor_db=-45.0,
        )
        # RMS-vetoed frames: confidence forcibly zeroed → Viterbi picks
        # unvoiced → strength 0, consensus NaN.
        assert (result.agreement_strength == 0.0).all()
        assert np.isnan(result.consensus_f0).all()

    def test_viterbi_source_is_int8_with_valid_codes(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert result.viterbi_source.dtype == np.int8
        # Values are slot indices 0..7
        assert result.viterbi_source.min() >= 0
        assert result.viterbi_source.max() < 8

    def test_fallback_source_uses_sentinel(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
            viterbi_enabled=False,
        )
        # Step 2 fallback: voiced frames get sentinel 127, NaN frames get
        # SOURCE_UNVOICED (7).
        from analyze.derived.vocal_consensus.viterbi import SOURCE_UNVOICED
        finite = np.isfinite(result.consensus_f0)
        assert (result.viterbi_source[finite] == 127).all()
        assert (result.viterbi_source[~finite] == SOURCE_UNVOICED).all()


# ---------- RMS floor gate ---------------------------------------------

class TestRMSFloorIntegration:
    def test_rms_below_floor_zeros_consensus_in_silence(self):
        # F0 hallucinated in silence + RMS at noise floor → consensus stays NaN
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        rms = np.full(n, 0.001, dtype=np.float32)  # -60 dBFS

        # Inject a "hallucinated" voiced reading on both estimators in silence
        # (vote_count would be 2 without the floor gate)
        fcpe[50:100] = 220.0
        pesto[50:100] = 220.0

        result = process_contour(
            fcpe, pesto, [], fps, rms=rms, rms_floor_db=-45.0,
        )
        # Without the gate, consensus_f0 would be 220 there. With the gate,
        # vote_count is forced to 0, so no consensus emerges.
        assert np.isnan(result.consensus_f0).all()


# ---------- Multi-note --------------------------------------------------

class TestMultiNote:
    def test_each_note_gets_its_own_intonation_entry(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69, cents_offset=10.0)
            .add_note(t_start=1.0, t_end=1.4, midi=72, cents_offset=-25.0)
            .render()
        )
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert len(result.note_intonation) == 2
        assert result.note_intonation[0].intonation_cents == pytest.approx(10.0, abs=0.5)
        assert result.note_intonation[1].intonation_cents == pytest.approx(-25.0, abs=0.5)

    def test_consensus_present_during_each_note_nan_in_gap(self):
        clip = (
            VocalSynth(duration=2.0)
            .add_note(t_start=0.2, t_end=0.6, midi=69)
            .add_note(t_start=1.0, t_end=1.4, midi=72)
            .render()
        )
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        i0a, i1a = _frames_for(0.2, 0.6, clip.fps)
        i0b, i1b = _frames_for(1.0, 1.4, clip.fps)
        assert np.isfinite(result.consensus_f0[i0a:i1a]).all()
        assert np.isfinite(result.consensus_f0[i0b:i1b]).all()
        # Silence gap between notes: no consensus
        assert np.isnan(result.consensus_f0[i1a:i0b]).all()


# ---------- Output dataclass -------------------------------------------

class TestOutputShape:
    def test_returns_contour_result(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert isinstance(result, ContourResult)

    def test_array_fields_match_input_length(self):
        clip = synth_steady_note(midi=69)
        n = clip.n_frames
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert result.fcpe_corrected.shape == (n,)
        assert result.pesto_corrected.shape == (n,)
        assert result.consensus_f0.shape == (n,)
        assert result.agreement_strength.shape == (n,)
        assert result.vote_count.shape == (n,)
        assert result.octave_corrections.shape == (n, 2)

    def test_agreement_strength_is_float32_in_unit_range(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert result.agreement_strength.dtype == np.float32
        assert result.agreement_strength.min() >= 0.0
        assert result.agreement_strength.max() <= 1.0

    def test_consensus_f0_is_float32(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert result.consensus_f0.dtype == np.float32

    def test_note_intonation_is_list_of_dataclasses(self):
        clip = synth_steady_note(midi=69)
        result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        assert isinstance(result.note_intonation, list)
        assert all(isinstance(x, NoteIntonation) for x in result.note_intonation)


# ---------- Input independence ----------------------------------------

class TestInputIndependence:
    def test_inputs_not_mutated(self):
        clip = synth_steady_note(midi=69)
        fcpe_before = clip.fcpe.copy()
        pesto_before = clip.pesto.copy()
        _result = process_contour(
            clip.fcpe, clip.pesto, clip.basic_pitch_notes, clip.fps,
        )
        np.testing.assert_array_equal(clip.fcpe, fcpe_before)
        np.testing.assert_array_equal(clip.pesto, pesto_before)


# ---------- Validation -------------------------------------------------

class TestInputValidation:
    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="shape mismatch"):
            process_contour(
                np.zeros(100, dtype=np.float32),
                np.zeros(99, dtype=np.float32),
                [], 100.0,
            )

    def test_2d_input_raises(self):
        with pytest.raises(ValueError, match="1-D"):
            process_contour(
                np.zeros((10, 2), dtype=np.float32),
                np.zeros((10, 2), dtype=np.float32),
                [], 100.0,
            )


# ---------- Empty inputs -----------------------------------------------

class TestEmpty:
    def test_no_notes_yields_empty_intonation_list(self):
        n = 200
        result = process_contour(
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
            [], 100.0,
        )
        assert result.note_intonation == []
        assert np.isnan(result.consensus_f0).all()
        assert (result.vote_count == 0).all()


# ---------- Vocal-frequency hard clamp (last-line defense) -------------

class TestConsensusHzClamp:
    def test_consensus_clamped_when_both_estimators_agree_above_range(self):
        # FCPE and PESTO BOTH glitch up to ~3000 Hz (way above vocal range).
        # Even though they "agree" within 50¢, consensus_f0 must stay NaN
        # because the agreed pitch is implausible for human voice.
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        # Both at 3000 Hz (≈ MIDI 102, F#7) for frames 50-100
        fcpe[50:100] = 3000.0
        pesto[50:100] = 3000.0

        # We pass a basic-pitch note in the same span at MIDI 69 to make
        # vote_count == 3, but the consensus must still be vetoed by the
        # frequency clamp.
        from tests.unit._vocal_synth import SynthBPNote
        bp_notes = [SynthBPNote(start=0.5, end=1.0, pitch=69)]

        # Step 2 fallback path: clamp wins because the heuristic builder
        # has no anchor candidate independent of FCPE/PESTO. (Under
        # Viterbi the anchor is its own candidate slot at 440 Hz, so the
        # path follows the anchor — different but valid behavior; tested
        # implicitly by the no-clamp Viterbi cases.)
        result = process_contour(
            fcpe, pesto, bp_notes, fps, viterbi_enabled=False,
        )
        # Even though vote_count is 2 (FCPE+PESTO voiced) or 3 (with bp),
        # consensus_f0 should be NaN due to the >1500 Hz clamp
        assert np.isnan(result.consensus_f0[50:100]).all()

    def test_consensus_clamped_when_both_estimators_agree_below_range(self):
        # Both at 30 Hz (≈ MIDI 22, way below human voice — likely an
        # F0-estimator artifact on a sub-bass instrument bleeding into
        # the vocals stem)
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 30.0
        pesto[50:100] = 30.0

        result = process_contour(fcpe, pesto, [], fps)
        assert np.isnan(result.consensus_f0[50:100]).all()

    def test_consensus_emerges_in_normal_vocal_range(self):
        # 440 Hz (A4) is firmly in vocal range; should produce consensus
        n = 200
        fps = 100.0
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe[50:100] = 440.0
        pesto[50:100] = 440.0

        result = process_contour(fcpe, pesto, [], fps)
        # Vote count is 2 (no basic-pitch), consensus_f0 should be 440
        np.testing.assert_allclose(result.consensus_f0[50:100], 440.0, atol=1e-3)
