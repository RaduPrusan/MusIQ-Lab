"""Tests for analyze/derived/vocal_consensus/viterbi.py.

Synthetic inputs only — these are isolation tests on the Viterbi
forward pass + candidate building. Real-track validation happens in
install-logs/_phase_0c_step4_rerun.py.
"""
from __future__ import annotations

import numpy as np
import pytest

from analyze.derived.vocal_consensus.viterbi import (
    N_STATES,
    SOURCE_ANCHOR,
    SOURCE_FCPE,
    SOURCE_FCPE_DOWN,
    SOURCE_PESTO,
    SOURCE_UNVOICED,
    _build_candidates,
    viterbi_smooth,
)


def _midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _bp_active_array(n_frames: int, *, span: tuple[int, int] | None = None,
                     midi: int = 60) -> np.ndarray:
    """Build a `bp_active_midi` array with a single active span (MIDI int)."""
    arr = np.full(n_frames, -1, dtype=np.int16)
    if span is not None:
        i0, i1 = span
        arr[i0:i1] = midi
    return arr


# ---------- Candidate building -----------------------------------------

class TestBuildCandidates:
    def test_unavailable_slots_have_emission_inf(self):
        n = 3
        fcpe = np.zeros(n, dtype=np.float32)        # all unvoiced
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.zeros(n, dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = np.full(n, -1, dtype=np.int16)
        cand_hz, cand_voiced, cand_em = _build_candidates(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            hz_min=65.0, hz_max=1500.0,
        )
        # Unvoiced slot is the only one populated
        assert cand_em[:, SOURCE_UNVOICED].max() < 5.0  # ~−log(0.01)=4.6
        for s in range(N_STATES):
            if s == SOURCE_UNVOICED:
                continue
            assert (cand_em[:, s] >= 1e5).all(), f"slot {s} should be EMISSION_INF"
        assert not cand_voiced[:, SOURCE_UNVOICED].any()  # unvoiced is "not voiced"

    def test_fcpe_voiced_slot_populated(self):
        n = 3
        fcpe = np.array([220.0, 220.0, 0.0], dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.array([0.9, 0.9, 0.0], dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n)
        cand_hz, cand_voiced, cand_em = _build_candidates(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            hz_min=65.0, hz_max=1500.0,
        )
        assert cand_voiced[0, SOURCE_FCPE]
        assert cand_voiced[1, SOURCE_FCPE]
        assert not cand_voiced[2, SOURCE_FCPE]
        assert cand_hz[0, SOURCE_FCPE] == pytest.approx(220.0)
        # Emission cost = −log(0.9) ≈ 0.105
        assert cand_em[0, SOURCE_FCPE] == pytest.approx(-np.log(0.9), abs=1e-3)
        assert cand_em[2, SOURCE_FCPE] >= 1e5  # frame 2 unvoiced → EMISSION_INF

    def test_anchor_slot_populated_with_fixed_conf(self):
        n = 4
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.zeros(n, dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n, span=(1, 3), midi=60)  # C4 = 261.6 Hz
        # Disable proximity bonus so we can assert the raw anchor emission;
        # the bonus is exercised in the integration tests below.
        cand_hz, cand_voiced, cand_em = _build_candidates(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            hz_min=65.0, hz_max=1500.0,
            anchor_prox_bonus=0.0,
        )
        assert cand_voiced[1, SOURCE_ANCHOR]
        assert cand_voiced[2, SOURCE_ANCHOR]
        assert not cand_voiced[0, SOURCE_ANCHOR]
        assert cand_hz[1, SOURCE_ANCHOR] == pytest.approx(_midi_to_hz(60), rel=1e-3)
        # Anchor emission = −log(0.7) ≈ 0.357 (no proximity bonus applied)
        assert cand_em[1, SOURCE_ANCHOR] == pytest.approx(-np.log(0.7), abs=1e-3)

    def test_shifted_slot_emission_includes_half_conf_penalty(self):
        n = 1
        fcpe = np.array([200.0], dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.array([0.9], dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n)
        _, _, cand_em = _build_candidates(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            hz_min=65.0, hz_max=1500.0,
        )
        # Raw FCPE: −log(0.9) ≈ 0.105
        # FCPE×0.5: −log(0.9 * 0.5) = −log(0.45) ≈ 0.799
        assert cand_em[0, SOURCE_FCPE] == pytest.approx(-np.log(0.9), abs=1e-3)
        assert cand_em[0, SOURCE_FCPE_DOWN] == pytest.approx(-np.log(0.45), abs=1e-3)

    def test_out_of_range_shifted_slot_marked_inf(self):
        n = 1
        # FCPE at 1400 Hz → ×2 = 2800 Hz, out of range; ×0.5 = 700 Hz, in range
        fcpe = np.array([1400.0], dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.array([0.9], dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n)
        cand_hz, cand_voiced, cand_em = _build_candidates(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            hz_min=65.0, hz_max=1500.0,
        )
        # SOURCE_FCPE_UP slot would be 2800 Hz → EMISSION_INF
        from analyze.derived.vocal_consensus.viterbi import SOURCE_FCPE_UP
        assert cand_em[0, SOURCE_FCPE_UP] >= 1e5
        assert not cand_voiced[0, SOURCE_FCPE_UP]


# ---------- Viterbi forward pass ---------------------------------------

class TestViterbiBasics:
    def test_silence_picks_unvoiced_throughout(self):
        n = 50
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.zeros(n, dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        assert np.isnan(f0).all()
        assert (source == SOURCE_UNVOICED).all()
        # Confidence at unvoiced state ≈ exp(−4.6) ≈ 0.01
        assert (conf < 0.05).all()

    def test_steady_voicing_picks_fcpe_when_full_conf(self):
        n = 50
        target_hz = 220.0
        fcpe = np.full(n, target_hz, dtype=np.float32)
        pesto = np.full(n, target_hz, dtype=np.float32)
        fcpe_conf = np.full(n, 0.95, dtype=np.float32)
        pesto_conf = np.full(n, 0.5, dtype=np.float32)  # FCPE more confident
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        np.testing.assert_allclose(f0, target_hz, rtol=1e-5)
        assert (source == SOURCE_FCPE).all()
        assert (conf > 0.9).all()

    def test_handles_empty_input(self):
        empty = np.zeros(0, dtype=np.float32)
        bp_active = np.zeros(0, dtype=np.int16)
        f0, conf, source = viterbi_smooth(
            empty, empty, empty, empty, bp_active,
        )
        assert f0.shape == (0,)
        assert conf.shape == (0,)
        assert source.shape == (0,)


# ---------- Single-frame octave glitch ---------------------------------

class TestOctaveGlitchRecovery:
    def test_recovers_from_single_frame_octave_glitch_in_fcpe(self):
        """One frame doubled in FCPE; PESTO clean. Viterbi must follow PESTO
        for the glitch frame (or pick FCPE/2 candidate), not the raw FCPE."""
        n = 30
        target_hz = 220.0
        fcpe = np.full(n, target_hz, dtype=np.float32)
        fcpe[15] = target_hz * 2.0  # one-frame octave-up glitch
        pesto = np.full(n, target_hz, dtype=np.float32)
        fcpe_conf = np.full(n, 0.9, dtype=np.float32)
        pesto_conf = np.full(n, 0.9, dtype=np.float32)
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # Frame 15 must NOT be at 440 Hz; should land near 220 Hz.
        # Tolerance: allow either PESTO direct or FCPE/2 — both = 220 Hz.
        assert abs(f0[15] - target_hz) < 1.0, (
            f"frame 15 glitched to {f0[15]} Hz instead of recovering to {target_hz} Hz"
        )

    def test_uses_octave_shifted_candidate_when_fcpe_persistently_off(self):
        """FCPE consistently 2× too high; PESTO at the correct fundamental.
        Viterbi should follow PESTO (lower per-frame cost than FCPE/2 with
        its half-conf penalty)."""
        n = 30
        target_hz = 200.0
        fcpe = np.full(n, target_hz * 2.0, dtype=np.float32)  # always octave-up
        pesto = np.full(n, target_hz, dtype=np.float32)
        fcpe_conf = np.full(n, 0.6, dtype=np.float32)
        pesto_conf = np.full(n, 0.9, dtype=np.float32)
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # Should track 200 Hz, not 400 Hz
        np.testing.assert_allclose(f0, target_hz, rtol=0.01)


# ---------- Anchor influence -------------------------------------------

class TestAnchorInfluence:
    def test_anchor_resolves_octave_split(self):
        """FCPE and PESTO disagree by an octave; anchor breaks the tie.
        FCPE=87, PESTO=174. Anchor MIDI 41 = 87 Hz. Viterbi should land
        on 87 Hz (anchor or FCPE)."""
        n = 30
        anchor_midi = 41  # F2 ≈ 87.3 Hz
        fcpe = np.full(n, _midi_to_hz(anchor_midi), dtype=np.float32)
        pesto = np.full(n, _midi_to_hz(anchor_midi + 12), dtype=np.float32)
        fcpe_conf = np.full(n, 0.7, dtype=np.float32)
        pesto_conf = np.full(n, 0.9, dtype=np.float32)
        bp_active = _bp_active_array(n, span=(0, n), midi=anchor_midi)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # Path should be near 87 Hz (within a quarter-tone)
        cents_off = np.abs(1200.0 * np.log2(f0 / _midi_to_hz(anchor_midi)))
        assert (cents_off < 50.0).all(), (
            f"path off-anchor by {cents_off.max()}¢ — should be on the anchor octave"
        )

    def test_temporal_continuity_persists_after_anchor_silent(self):
        """Anchor active for the first 21 of 30 frames, silent for the
        last 9. F0 estimators are octave-locked (FCPE=PESTO=2×target)
        throughout. Viterbi should pick the anchor octave during the
        anchor span, then ride the FCPE/2 octave-shifted candidate
        through the trailing silence (transition cents=0 → free).

        The clip layout (anchor first, silence after) is the realistic
        Cohen pattern: anchored phrasing followed by inter-phrase
        silences. A clip with anchor sandwiched in the middle would
        require the path to enter via an octave-bump transition (cost
        ~21), which the per-frame anchor bonus over only ~10 frames
        cannot recoup — that's a known, accepted limitation of the
        algorithm and is why benchmark validation on Cohen looks at
        full-track behavior, not single isolated transitions."""
        n = 30
        anchor_end = 21
        anchor_midi = 41
        target_hz = _midi_to_hz(anchor_midi)
        fcpe = np.full(n, target_hz * 2.0, dtype=np.float32)  # always octave-up
        pesto = np.full(n, target_hz * 2.0, dtype=np.float32)
        fcpe_conf = np.full(n, 0.9, dtype=np.float32)
        pesto_conf = np.full(n, 0.9, dtype=np.float32)
        bp_active = _bp_active_array(n, span=(0, anchor_end), midi=anchor_midi)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # Frames 0..20 (anchor active): on the target_hz octave.
        cents_during_anchor = np.abs(
            1200.0 * np.log2(f0[:anchor_end] / target_hz)
        )
        assert (cents_during_anchor < 50.0).all(), (
            f"during-anchor path off-octave: {cents_during_anchor}"
        )
        # Frames 21..29 (anchor silent): path holds the target_hz octave
        # by riding the FCPE/2 candidate (transition cost from anchor=87
        # to FCPE/2=87 is 0 cents). The path should NOT jump back to
        # FCPE=174 — that would require an octave bump.
        cents_post_anchor = np.abs(
            1200.0 * np.log2(f0[anchor_end:] / target_hz)
        )
        assert (cents_post_anchor < 50.0).all(), (
            f"post-anchor path lost the octave: {cents_post_anchor}"
        )


# ---------- Genuine wide leap ------------------------------------------

class TestWideLeap:
    def test_allows_genuine_fifth_leap(self):
        """F0 actually leaps a fifth (700¢) mid-clip — Viterbi should
        follow it. A fifth's transition cost is base = 1.0 * (700/100)² = 49,
        while the alternative (stay at 200 Hz, ignoring the new evidence
        at 300 Hz) accumulates emission cost forever. Eventually the path
        switches. With enough frames at the new pitch and reasonable
        confidence, Viterbi must choose to follow the leap."""
        n = 60
        first_hz = 200.0
        second_hz = first_hz * (2.0 ** (7.0 / 12.0))  # +7 semitones
        fcpe = np.full(n, first_hz, dtype=np.float32)
        fcpe[30:] = second_hz
        pesto = fcpe.copy()
        fcpe_conf = np.full(n, 0.95, dtype=np.float32)
        pesto_conf = np.full(n, 0.95, dtype=np.float32)
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # First half: near first_hz
        np.testing.assert_allclose(f0[:30], first_hz, rtol=0.01)
        # Second half (after settling): near second_hz. Allow 1-2 frames
        # of latency at the boundary as Viterbi commits to the leap.
        np.testing.assert_allclose(f0[35:], second_hz, rtol=0.01)


# ---------- Voicing transitions ----------------------------------------

class TestForceUnvoicedGate:
    def test_force_unvoiced_overrides_active_anchor(self):
        """Even when basic-pitch hallucinates an active note during a
        silent passage, force_unvoiced must drag the path to the
        unvoiced state. This is the Cohen-style failure mode where
        instrumental-only passages get scored as voiced because anchor
        em (0.36) beats unvoiced em (4.6)."""
        n = 30
        fcpe = np.zeros(n, dtype=np.float32)
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.zeros(n, dtype=np.float32)
        pesto_conf = np.zeros(n, dtype=np.float32)
        # Anchor active throughout — would normally produce a 440 Hz line.
        bp_active = _bp_active_array(n, span=(0, n), midi=69)
        # Force-unvoice the middle 10 frames.
        force = np.zeros(n, dtype=bool)
        force[10:20] = True
        f0, _, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            force_unvoiced=force,
        )
        # In the gated window: NaN, source=unvoiced.
        assert np.isnan(f0[10:20]).all()
        assert (source[10:20] == SOURCE_UNVOICED).all()
        # Outside the gated window: anchor still wins (440 Hz).
        np.testing.assert_allclose(f0[:10], 440.0, rtol=1e-2)
        np.testing.assert_allclose(f0[20:], 440.0, rtol=1e-2)

    def test_force_unvoiced_overrides_voiced_f0_with_zero_conf(self):
        """Stale Hz with zero confidence (e.g. estimator hallucinated a
        value but the upstream voting layer vetoed the frame) must NOT
        leak through as a tied emission cost. Without the gate, FCPE's
        slot would have em = -log(EPSILON) ≈ 4.6 (same as unvoiced),
        and argmin's lower-index tie-break would pick FCPE."""
        n = 20
        fcpe = np.full(n, 220.0, dtype=np.float32)   # spurious Hz
        pesto = np.zeros(n, dtype=np.float32)
        fcpe_conf = np.zeros(n, dtype=np.float32)    # but zero conf
        pesto_conf = np.zeros(n, dtype=np.float32)
        bp_active = _bp_active_array(n)
        force = np.ones(n, dtype=bool)
        f0, _, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
            force_unvoiced=force,
        )
        assert np.isnan(f0).all()
        assert (source == SOURCE_UNVOICED).all()


class TestVoicingTransitions:
    def test_unvoiced_gap_between_voiced_regions(self):
        """50 frames: voiced 0..15, silent 15..35, voiced 35..50. Viterbi
        should transition cleanly on/off and produce NaN in the gap."""
        n = 50
        target_hz = 220.0
        fcpe = np.zeros(n, dtype=np.float32)
        fcpe[:15] = target_hz
        fcpe[35:] = target_hz
        pesto = fcpe.copy()
        fcpe_conf = np.zeros(n, dtype=np.float32)
        fcpe_conf[:15] = 0.9
        fcpe_conf[35:] = 0.9
        pesto_conf = fcpe_conf.copy()
        bp_active = _bp_active_array(n)
        f0, conf, source = viterbi_smooth(
            fcpe, pesto, fcpe_conf, pesto_conf, bp_active,
        )
        # Voiced regions at target
        np.testing.assert_allclose(f0[:15], target_hz, rtol=0.01)
        np.testing.assert_allclose(f0[35:], target_hz, rtol=0.01)
        # Gap is NaN
        assert np.isnan(f0[20:30]).all()
        assert (source[20:30] == SOURCE_UNVOICED).all()
