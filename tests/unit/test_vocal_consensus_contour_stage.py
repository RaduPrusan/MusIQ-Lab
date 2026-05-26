"""Tests for analyze/stages/vocal_consensus_contour.py.

Constructs a synthetic cache layout (vocal_f0.npz + midi/vocals.mid + optional
dynamics/vocals.npz) and runs the stage end-to-end against it.
"""
import json
import math
from pathlib import Path

import numpy as np
import pretty_midi
import pytest

from analyze.stages import vocal_consensus_contour as stage


# ---------- Helpers ----------------------------------------------------

def _write_vocal_f0(cache_dir: Path, fcpe: np.ndarray, pesto: np.ndarray):
    np.savez_compressed(cache_dir / "vocal_f0.npz", fcpe=fcpe, pesto=pesto)
    (cache_dir / "vocal_f0_summary.json").write_text(json.dumps({
        "fcpe_frames": int(len(fcpe)),
        "pesto_frames": int(len(pesto)),
        "agreement_50c": 1.0,
    }))
    # vocal_f0 also expects a sidecar; write a minimal one
    from analyze import sidecar
    sidecar.write(cache_dir, "vocal_f0", {}, schema_version=1)


def _write_basic_pitch_midi(cache_dir: Path, notes: list[tuple[float, float, int]]):
    """notes: list of (start, end, midi). velocity hardcoded to 90."""
    midi_dir = cache_dir / "midi"
    midi_dir.mkdir(exist_ok=True)
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, name="vocals")
    for start, end, pitch in notes:
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    pm.instruments.append(inst)
    pm.write(str(midi_dir / "vocals.mid"))


def _write_dynamics(cache_dir: Path, rms: np.ndarray):
    dyn_dir = cache_dir / "dynamics"
    dyn_dir.mkdir(exist_ok=True)
    np.savez_compressed(dyn_dir / "vocals.npz", rms=rms)
    from analyze import sidecar
    sidecar.write(cache_dir, "stems_dynamics", {}, schema_version=1)


def _make_cache(
    tmp_path: Path,
    *,
    n_frames: int = 200,
    note_at: tuple[float, float, int] = (0.5, 0.9, 69),
    cents_offset: float = 0.0,
    include_rms: bool = True,
) -> Path:
    """Build a minimal cache_dir with all three input streams ready."""
    cache_dir = tmp_path / "track_slug"
    cache_dir.mkdir()

    fcpe = np.zeros(n_frames, dtype=np.float32)
    pesto = np.zeros(n_frames, dtype=np.float32)
    rms = np.full(n_frames, 0.001, dtype=np.float32)  # silence floor

    t_start, t_end, midi = note_at
    i0 = int(round(t_start * 100))
    i1 = int(round(t_end * 100))
    target_hz = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    shifted_hz = target_hz * (2.0 ** (cents_offset / 1200.0))
    fcpe[i0:i1] = shifted_hz
    pesto[i0:i1] = shifted_hz
    rms[i0:i1] = 0.5  # well above default floor

    _write_vocal_f0(cache_dir, fcpe, pesto)
    _write_basic_pitch_midi(cache_dir, [(t_start, t_end, midi)])
    if include_rms:
        _write_dynamics(cache_dir, rms)

    return cache_dir


# ---------- run() end-to-end -------------------------------------------

class TestRun:
    def test_writes_npz_and_json(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        assert (cache_dir / "vocal_consensus.npz").exists()
        assert (cache_dir / "vocal_consensus.json").exists()

    def test_npz_contains_expected_arrays(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        with np.load(cache_dir / "vocal_consensus.npz") as z:
            for key in (
                "fcpe_corrected", "pesto_corrected", "consensus_f0",
                "agreement_strength", "vote_count", "octave_corrections",
            ):
                assert key in z, f"missing array {key}"

    def test_npz_agreement_strength_aligned_with_consensus(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        with np.load(cache_dir / "vocal_consensus.npz") as z:
            cf = z["consensus_f0"]
            ag = z["agreement_strength"]
        assert cf.shape == ag.shape
        # Wherever consensus_f0 is finite, agreement_strength must be > 0.
        assert (ag[np.isfinite(cf)] > 0).all()
        # Wherever consensus_f0 is NaN, agreement_strength must be exactly 0.
        np.testing.assert_array_equal(ag[np.isnan(cf)], 0.0)

    def test_json_contains_intonation_for_each_note(self, tmp_path):
        cache_dir = _make_cache(tmp_path, cents_offset=20.0)
        stage.run(Path("/dev/null"), cache_dir)
        data = json.loads((cache_dir / "vocal_consensus.json").read_text())
        assert data["n_notes"] == 1
        assert len(data["notes"]) == 1
        n = data["notes"][0]
        assert n["midi"] == 69
        assert n["intonation_cents"] == pytest.approx(20.0, abs=0.5)
        assert n["confidence"] == pytest.approx(1.0)

    def test_summary_consensus_stats(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        result = stage.run(Path("/dev/null"), cache_dir)
        cs = result["consensus_summary"]
        # Note covers 0.5–0.9s = 40 frames; rest is silence
        assert cs["frames_vote_3"] == 40
        assert cs["frames_vote_0"] == 160
        assert cs["frames_with_consensus_f0"] == 40
        assert cs["octave_corrections_fcpe"] == 0
        assert cs["octave_corrections_pesto"] == 0

    def test_summary_includes_agreement_strength_buckets(self, tmp_path):
        # Note span has FCPE = PESTO with anchor → strong (1.0).
        cache_dir = _make_cache(tmp_path)
        result = stage.run(Path("/dev/null"), cache_dir)
        cs = result["consensus_summary"]
        assert cs["frames_strength_strong"] == 40
        assert cs["frames_strength_medium"] == 0
        assert cs["frames_strength_weak"] == 0


class TestSchemaVersionGuard:
    def test_schema_version_is_3(self):
        # Phase 0c Step 2 contract — guards the bump from 2 to 3.
        # Step 3 deliberately did not bump (in-memory anchor validation only;
        # npz shape unchanged). The new params in DEFAULT_PARAMS shift the
        # sidecar fingerprint to invalidate caches.
        assert stage.SCHEMA_VERSION == 3


# ---------- Anchor pre-validation (Phase 0c Step 3) -------------------

class TestAnchorPreValidation:
    """Direct unit tests for `_validate_anchor_notes`. Built via tiny
    synthetic F0 arrays + pretty_midi.Note instances; no full stage run.
    """

    @staticmethod
    def _f0(n: int = 100, *, voiced_span: tuple[int, int], hz: float):
        arr = np.zeros(n, dtype=np.float32)
        i0, i1 = voiced_span
        arr[i0:i1] = hz
        return arr

    @staticmethod
    def _conf(n: int = 100, *, voiced_span: tuple[int, int], value: float = 1.0):
        arr = np.zeros(n, dtype=np.float32)
        i0, i1 = voiced_span
        arr[i0:i1] = value
        return arr

    @staticmethod
    def _note(midi: int, t_start: float = 0.1, t_end: float = 0.9):
        return pretty_midi.Note(velocity=90, pitch=midi, start=t_start, end=t_end)

    def _validate(self, notes, fcpe, pesto, *, fps=100.0, **kwargs):
        return stage._validate_anchor_notes(
            notes, fcpe, pesto,
            fcpe_conf=(fcpe > 0).astype(np.float32),
            pesto_conf=(pesto > 0).astype(np.float32),
            fps=fps, **kwargs,
        )

    def test_anchor_at_correct_pitch_is_kept(self):
        # F0 evidence (FCPE+PESTO) at A4 confirms MIDI 69 → keep unchanged.
        fcpe = self._f0(voiced_span=(10, 90), hz=440.0)
        pesto = self._f0(voiced_span=(10, 90), hz=440.0)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert len(kept) == 1
        assert kept[0].pitch == 69

    def test_anchor_one_octave_off_gets_corrected(self):
        # MIDI 69 in basic-pitch's output, but F0 unanimously at MIDI 57
        # (one octave below A4). Validator corrects pitch to 57.
        fcpe = self._f0(voiced_span=(10, 90), hz=220.0)
        pesto = self._f0(voiced_span=(10, 90), hz=220.0)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 0, "corrected": 1, "dropped": 0}
        assert len(kept) == 1
        assert kept[0].pitch == 57  # A3
        # On-disk would be untouched; we verify only the in-memory note.

    def test_anchor_with_unrelated_pitch_is_dropped(self):
        # MIDI 69 in basic-pitch's output, but F0 says MIDI 50 (D3) —
        # 19 semitones away, different pitch class, not a harmonic ratio
        # (D3 / A4 ≈ 0.33). Strongly suggests basic-pitch hallucinated;
        # drop.
        hz_d3 = 440.0 * (2.0 ** ((50 - 69) / 12.0))
        fcpe = self._f0(voiced_span=(10, 90), hz=hz_d3)
        pesto = self._f0(voiced_span=(10, 90), hz=hz_d3)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 0, "corrected": 0, "dropped": 1}
        assert kept == []

    def test_small_disagreement_kept_not_dropped(self):
        # F0 at MIDI 65 (F4) for a note labelled MIDI 69 (A4) — 4 semitones
        # off, different PC, NOT a harmonic ratio. Below the 7-semitone
        # drop threshold (likely note-boundary timing artifact rather
        # than hallucination). Keep.
        hz_f4 = 440.0 * (2.0 ** ((65 - 69) / 12.0))
        fcpe = self._f0(voiced_span=(10, 90), hz=hz_f4)
        pesto = self._f0(voiced_span=(10, 90), hz=hz_f4)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 69

    def test_third_harmonic_lock_keeps_anchor(self):
        # Cohen failure mode: F0 estimators lock on the 3rd harmonic
        # (perfect-fifth-above-octave). Different PC, but the ratio is
        # ~3 — keep basic-pitch's anchor at the fundamental.
        hz_3rd = 440.0 * 3.0  # 1320 Hz; basic-pitch label MIDI 69 (A4)
        fcpe = self._f0(voiced_span=(10, 90), hz=hz_3rd)
        pesto = self._f0(voiced_span=(10, 90), hz=hz_3rd)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 69

    def test_octave_error_only_corrects_downward(self):
        # F0 unanimously at MIDI 81 (one octave ABOVE basic-pitch's MIDI 69).
        # Same PC, but evidence is HIGHER — likely 2nd-harmonic lock, not
        # a real basic-pitch error. Keep, do NOT correct upward.
        fcpe = self._f0(voiced_span=(10, 90), hz=880.0)
        pesto = self._f0(voiced_span=(10, 90), hz=880.0)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 69  # not promoted to 81

    def test_anchor_with_only_one_confident_f0_uses_single_witness(self):
        # FCPE confident at MIDI 69; PESTO completely unvoiced/unconfident.
        # Single witness confirms MIDI → keep.
        fcpe = self._f0(voiced_span=(10, 90), hz=440.0)
        pesto = np.zeros(100, dtype=np.float32)  # silent
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}

    def test_single_witness_disagrees_with_midi_drops(self):
        # FCPE alone, far from MIDI → single-witness rule drops the note.
        fcpe = self._f0(voiced_span=(10, 90), hz=523.0)  # ≈ MIDI 72 (C5)
        pesto = np.zeros(100, dtype=np.float32)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 0, "corrected": 0, "dropped": 1}

    def test_short_anchor_with_no_validation_frames_kept_unchanged(self):
        # Note span is 4 frames, middle 60% is too short for the 5-frame
        # minimum → keep unchanged (insufficient evidence).
        fcpe = self._f0(voiced_span=(0, 100), hz=440.0)
        pesto = self._f0(voiced_span=(0, 100), hz=440.0)
        # 0.50–0.54s = 4 frames at fps=100
        note = self._note(midi=99, t_start=0.5, t_end=0.54)
        kept, info = self._validate([note], fcpe, pesto, min_validation_frames=5)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 99  # not validated, kept as-is

    def test_one_estimator_glitched_one_confirms_keeps_anchor(self):
        # FCPE at MIDI 81 (octave glitch up from MIDI 69), PESTO at MIDI 69.
        # PESTO confirms → keep anchor so correct_octaves can fold FCPE.
        fcpe = self._f0(voiced_span=(10, 90), hz=880.0)
        pesto = self._f0(voiced_span=(10, 90), hz=440.0)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 69  # not corrected; downstream octave fold handles FCPE

    def test_split_estimators_neither_at_midi_keeps_anchor(self):
        # FCPE at MIDI 81 (octave up), PESTO at MIDI 57 (octave down).
        # Common bass-baritone failure mode: one estimator harmonic-locked,
        # the other on the fundamental. Neither agrees with MIDI 69 AND
        # they disagree with each other. The validator must NOT drop —
        # there's no positive evidence the note is wrong, just uncertainty.
        # Step 4 Viterbi resolves splits via temporal continuity.
        fcpe = self._f0(voiced_span=(10, 90), hz=880.0)
        pesto = self._f0(voiced_span=(10, 90), hz=220.0)
        kept, info = self._validate([self._note(midi=69)], fcpe, pesto)
        assert info == {"kept": 1, "corrected": 0, "dropped": 0}
        assert kept[0].pitch == 69

    def test_empty_note_list_returns_empty(self):
        kept, info = self._validate(
            [], np.zeros(50, dtype=np.float32), np.zeros(50, dtype=np.float32),
        )
        assert kept == []
        assert info == {"kept": 0, "corrected": 0, "dropped": 0}


class TestAnchorValidationStageIntegration:
    """Exercise the validator through the full stage.run() pipeline."""

    def test_validation_info_appears_in_summary(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        result = stage.run(Path("/dev/null"), cache_dir)
        assert "anchor_validation" in result
        av = result["anchor_validation"]
        assert {"kept", "corrected", "dropped"} <= av.keys()
        # The synthetic cache puts a single in-tune note → kept = 1.
        assert av == {"kept": 1, "corrected": 0, "dropped": 0}

    def test_disabling_validation_via_param_keeps_all_notes(self, tmp_path):
        # Flip anchor_validation_enabled off → counts collapse to "kept = N,
        # else 0". Useful for legacy comparison runs.
        cache_dir = _make_cache(tmp_path)
        result = stage.run(
            Path("/dev/null"), cache_dir,
            anchor_validation_enabled=False,
        )
        assert result["anchor_validation"]["corrected"] == 0
        assert result["anchor_validation"]["dropped"] == 0
        assert result["anchor_validation"]["kept"] == 1

    def test_param_change_invalidates_cache(self, tmp_path):
        # Adding the validation params to DEFAULT_PARAMS shifts the sidecar
        # fingerprint; querying `cached()` with any altered validation knob
        # must return False so the stage re-runs.
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        assert stage.cached(cache_dir) is True
        assert stage.cached(cache_dir, anchor_validation_min_frames=10) is False
        assert stage.cached(cache_dir, anchor_validation_enabled=False) is False


# ---------- Soft deps --------------------------------------------------

class TestSoftDeps:
    def test_missing_dynamics_does_not_break_run(self, tmp_path):
        # No dynamics/ → RMS floor gate no-ops; rest still works
        cache_dir = _make_cache(tmp_path, include_rms=False)
        result = stage.run(Path("/dev/null"), cache_dir)
        # Note span still produces consensus
        assert result["consensus_summary"]["frames_with_consensus_f0"] > 0

    def test_missing_vocals_midi_yields_empty_notes(self, tmp_path):
        # Build cache with F0 but NO basic-pitch MIDI
        cache_dir = tmp_path / "track_slug"
        cache_dir.mkdir()
        n = 200
        _write_vocal_f0(
            cache_dir,
            np.zeros(n, dtype=np.float32),
            np.zeros(n, dtype=np.float32),
        )
        result = stage.run(Path("/dev/null"), cache_dir)
        assert result["n_notes"] == 0
        assert result["notes"] == []


# ---------- cached / load ----------------------------------------------

class TestCached:
    def test_false_before_run(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        assert stage.cached(cache_dir) is False

    def test_true_after_run(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        assert stage.cached(cache_dir) is True

    def test_false_on_param_change(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        # Default rms_floor_db is -45; querying with a different value invalidates
        assert stage.cached(cache_dir, rms_floor_db=-30.0) is False


class TestLoad:
    def test_load_returns_arrays_and_summary(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        stage.run(Path("/dev/null"), cache_dir)
        loaded = stage.load(cache_dir)
        for key in (
            "fcpe_corrected", "pesto_corrected", "consensus_f0",
            "agreement_strength", "vote_count", "octave_corrections",
            "summary",
        ):
            assert key in loaded
        # consensus_f0 should be partly NaN (silence) and partly finite (note)
        assert np.isnan(loaded["consensus_f0"]).any()
        assert np.isfinite(loaded["consensus_f0"]).any()

    def test_load_backward_compat_synthesizes_strength_from_vote_count(self, tmp_path):
        # Hand-build a v2-format npz (no agreement_strength key) to verify
        # the load() fallback synthesizes it from vote_count.
        cache_dir = tmp_path / "old_cache"
        cache_dir.mkdir()
        n = 50
        vc = np.zeros(n, dtype=np.int8)
        vc[10:20] = 3   # → 1.0
        vc[20:30] = 2   # → 0.5
        vc[30:40] = 1   # → 0.0
        np.savez_compressed(
            cache_dir / "vocal_consensus.npz",
            fcpe_corrected=np.zeros(n, dtype=np.float32),
            pesto_corrected=np.zeros(n, dtype=np.float32),
            consensus_f0=np.zeros(n, dtype=np.float32),
            vote_count=vc,
            octave_corrections=np.zeros((n, 2), dtype=np.int8),
        )
        (cache_dir / "vocal_consensus.json").write_text(json.dumps({
            "schema_version": 2, "fps": 100.0, "n_frames": n,
            "consensus_summary": {}, "n_notes": 0, "notes": [],
        }))

        loaded = stage.load(cache_dir)
        ag = loaded["agreement_strength"]
        assert ag.dtype == np.float32
        np.testing.assert_array_equal(ag[10:20], 1.0)
        np.testing.assert_array_equal(ag[20:30], 0.5)
        np.testing.assert_array_equal(ag[30:40], 0.0)


# ---------- Octave correction reflected in summary ---------------------

class TestOctaveCorrectionRecorded:
    def test_glitched_fcpe_is_corrected_and_logged(self, tmp_path):
        cache_dir = _make_cache(tmp_path)
        # After cache is built, doctor the FCPE arrays to simulate an
        # octave glitch in the note region
        with np.load(cache_dir / "vocal_f0.npz") as z:
            fcpe, pesto = z["fcpe"].copy(), z["pesto"].copy()
        i0, i1 = 50, 90  # the note's frame range
        fcpe[i0:i1] *= 2.0  # FCPE octave-up glitch
        np.savez_compressed(cache_dir / "vocal_f0.npz", fcpe=fcpe, pesto=pesto)

        result = stage.run(Path("/dev/null"), cache_dir)
        # Octave correction should report 40 corrected frames
        assert result["consensus_summary"]["octave_corrections_fcpe"] == 40
        assert result["consensus_summary"]["octave_corrections_pesto"] == 0
        # And the note should still read as in-tune (corrected pitch matches MIDI)
        assert abs(result["notes"][0]["intonation_cents"]) < 1.0


# ---------- Length-mismatch handling -----------------------------------

class TestLengthMismatch:
    def test_truncates_to_shortest_input(self, tmp_path):
        # vocal_f0 has 200 frames, dynamics has 195 — stage should align to 195
        cache_dir = _make_cache(tmp_path, n_frames=200)
        # Overwrite dynamics with a shorter array
        rms = np.full(195, 0.5, dtype=np.float32)
        np.savez_compressed(cache_dir / "dynamics" / "vocals.npz", rms=rms)
        result = stage.run(Path("/dev/null"), cache_dir)
        assert result["n_frames"] == 195


# ---------- NaN handling in JSON -------------------------------------

class TestVocalRangeFilter:
    def test_basic_pitch_note_outside_vocal_range_filtered_out(self, tmp_path):
        # Build a vanilla cache, then add an extra basic-pitch note at
        # MIDI 100 (out of vocal range). After running the stage, the
        # ghost note must NOT appear in vocal_consensus.json's notes list.
        cache_dir = _make_cache(tmp_path)
        midi_path = cache_dir / "midi" / "vocals.mid"
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(program=0, name="vocals")
        # Real vocal note (MIDI 69 = A4) — should pass filter
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=69, start=0.5, end=0.9))
        # Hallucinated ghost note (MIDI 100 = E7) — should be filtered
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=100, start=0.5, end=0.9))
        pm.instruments.append(inst)
        pm.write(str(midi_path))

        result = stage.run(Path("/dev/null"), cache_dir)
        # Only the in-range note survives
        assert result["n_notes"] == 1
        assert result["notes"][0]["midi"] == 69

    def test_subsonic_basic_pitch_note_filtered_out(self, tmp_path):
        # Below vocal range too: bass-frequency hallucinations
        cache_dir = _make_cache(tmp_path)
        midi_path = cache_dir / "midi" / "vocals.mid"
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(program=0, name="vocals")
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=20, start=0.5, end=0.9))
        pm.instruments.append(inst)
        pm.write(str(midi_path))

        result = stage.run(Path("/dev/null"), cache_dir)
        assert result["n_notes"] == 0

    def test_filter_bounds_can_be_overridden(self, tmp_path):
        # If a caller explicitly relaxes the bounds via params, the wider
        # range applies. Used by tests / specialized callers, not normal
        # production flow. Step 3's anchor pre-validation is disabled here
        # so the test isolates the vocal_midi_min/max mechanism — otherwise
        # the validator would (correctly) drop the MIDI 100 note as
        # inconsistent with the F0 evidence at MIDI 69.
        cache_dir = _make_cache(tmp_path)
        midi_path = cache_dir / "midi" / "vocals.mid"
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(program=0, name="vocals")
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=100, start=0.5, end=0.9))
        pm.instruments.append(inst)
        pm.write(str(midi_path))

        # With default bounds: filtered out
        r_default = stage.run(
            Path("/dev/null"), cache_dir,
            anchor_validation_enabled=False,
        )
        assert r_default["n_notes"] == 0
        # With relaxed bounds: passes through
        r_wide = stage.run(
            Path("/dev/null"), cache_dir,
            vocal_midi_max=120,
            anchor_validation_enabled=False,
        )
        assert r_wide["n_notes"] == 1


class TestJSONSerialization:
    def test_nan_intonation_serialized_as_null(self, tmp_path):
        # A note too short to measure produces NaN intonation; JSON null
        cache_dir = _make_cache(tmp_path)
        # Replace the note with a tiny one (10 ms — below min_frames threshold)
        midi_path = cache_dir / "midi" / "vocals.mid"
        pm = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(program=0, name="vocals")
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=69, start=0.5, end=0.51))
        pm.instruments.append(inst)
        pm.write(str(midi_path))

        stage.run(Path("/dev/null"), cache_dir)
        data = json.loads((cache_dir / "vocal_consensus.json").read_text())
        n = data["notes"][0]
        assert n["intonation_cents"] is None
        assert n["stability_cents"] is None
        assert n["confidence"] == 0.0
