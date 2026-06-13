import pytest

from analyze.stages.essentia_extract import compute_agreement


def test_bpm_agreement_within_one_bpm():
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"extracted": True, "tempo": {"bpm": 120.4}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["bpm"]["ok"] is True
    assert agreement["bpm"]["delta"] == pytest.approx(0.4, abs=0.01)


def test_bpm_disagreement_when_delta_above_threshold():
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"extracted": True, "tempo": {"bpm": 90.0}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["bpm"]["ok"] is False
    assert agreement["bpm"]["delta"] == pytest.approx(30.0, abs=0.01)


def test_bpm_half_tempo_caught_as_disagreement():
    """Essentia at 60, pipeline at 120 — Essentia is at half tempo."""
    pipeline = {"tempo_bpm": 120.0}
    essentia = {"extracted": True, "tempo": {"bpm": 60.0}, "key": {"krumhansl": ["A", "minor", 0.81]}}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["bpm"]["ok"] is False


def test_key_agreement_uses_best_estimator_consensus():
    """key.ok when at least 2 of 3 Essentia estimators agree with pipeline."""
    pipeline = {"key": "A:minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["A", "minor", 0.81],
            "temperley": ["A", "minor", 0.77],
            "edma": ["E", "major", 0.42],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is True
    assert agreement["key"]["analyze"] == "A:minor"
    assert agreement["key"]["essentia_consensus"] == "A:minor"


def test_key_disagreement_when_essentia_estimators_split():
    # Adapted after the relative-key equivalence fix: the previous setup had
    # krumhansl say C:major (highest strength), which IS the relative major of
    # A minor and now legitimately counts as agreement. Replace with three
    # genuinely-disagreeing estimators where the strongest pick (E:major) is
    # not relative to A minor (A minor's relative is C major).
    pipeline = {"key": "A:minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["E", "major", 0.9],
            "temperley": ["D", "major", 0.8],
            "edma": ["G", "major", 0.4],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is False


def test_agreement_skipped_when_essentia_not_extracted():
    pipeline = {"tempo_bpm": 120.0, "key": "A:minor"}
    essentia = {"extracted": False, "reason": "not installed"}
    agreement = compute_agreement(pipeline, essentia)
    assert agreement == {}


def test_relative_keys_treated_as_equivalent_minor_to_major():
    """F minor and Ab major share the same diatonic pc-set — relative keys.
    Cross-check should mark ok=True for any consensus that's relative to the
    pipeline's key. The Gorillaz smoke test surfaced this case (pipeline =
    F:minor, Essentia consensus = Ab:major)."""
    pipeline = {"key": "F:minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 107.0},
        "key": {
            "krumhansl": ["Ab", "major", 0.74],
            "temperley": ["Ab", "major", 0.77],
            "edma": ["Ab", "major", 0.72],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is True, (
        f"F minor and Ab major are relative keys — should be equivalent. "
        f"Got: {agreement['key']}"
    )
    # essentia_consensus field stays as the literal value Essentia produced
    assert agreement["key"]["essentia_consensus"] == "Ab:major"
    assert agreement["key"]["analyze"] == "F:minor"


def test_relative_keys_major_to_minor():
    """C major and A minor are equivalent."""
    pipeline = {"key": "C:major"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["A", "minor", 0.80],
            "temperley": ["A", "minor", 0.78],
            "edma": ["E", "major", 0.50],  # outlier
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is True


def test_parallel_keys_NOT_equivalent():
    """C major and C minor share the tonic but have DIFFERENT pc sets
    (C major has E, A, B; C minor has Eb, Ab, Bb). Parallel keys are
    NOT equivalent for cross-check purposes — they're genuinely different
    tonal contexts."""
    pipeline = {"key": "C:major"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["C", "minor", 0.85],
            "temperley": ["C", "minor", 0.80],
            "edma": ["C", "minor", 0.70],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is False


def test_unrelated_keys_NOT_equivalent():
    """A minor and G major are NOT relative (A minor's relative is C major).
    Should still flag disagreement."""
    pipeline = {"key": "A:minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["G", "major", 0.81],
            "temperley": ["G", "major", 0.77],
            "edma": ["G", "major", 0.50],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is False


def test_existing_exact_match_still_works():
    """The original 2-of-3-agree case still passes (sanity / no regression)."""
    pipeline = {"key": "A:minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["A", "minor", 0.81],
            "temperley": ["A", "minor", 0.77],
            "edma": ["E", "major", 0.42],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    assert agreement["key"]["ok"] is True


def test_key_agreement_with_canonical_scale_string_pipeline_key():
    """track.key now arrives as 'E♭ natural minor' (canonical form). The
    cross-check must still parse it and compute equivalence — not fall into
    _keys_equivalent's except→False path. Eb minor's relative major is Gb
    major; a Gb-major consensus is equivalent (relative) → ok."""
    pipeline = {"key": "E♭ natural minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["Gb", "major", 0.80],
            "temperley": ["Gb", "major", 0.78],
            "edma": ["B", "major", 0.40],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    # Gb major is the relative major of Eb minor → equivalent → ok.
    assert agreement["key"]["ok"] is True
    assert agreement["key"]["analyze"] == "E♭ natural minor"
