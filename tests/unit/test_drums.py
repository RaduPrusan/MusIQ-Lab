"""Unit tests for the drums stage's pure-Python parts.

ADTOF inference is mocked here. LarsNet is also mocked since it requires
GPU and the vendor checkpoint.

These tests cover:
- ADTOF_CLASS_MAP correctness
- cached() / load() cache-invalidation logic
- run() gate branch (no LarsNet or ADTOF invoked)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from analyze.stages import drums


# ---------------------------------------------------------------------------
# ADTOF_CLASS_MAP sanity
# ---------------------------------------------------------------------------

def test_adtof_class_map_covers_all_kit_pieces():
    """Every value in the map is one of the 5 canonical substem names."""
    assert set(drums.ADTOF_CLASS_MAP.values()) == set(drums.SUBSTEMS)


def test_adtof_class_map_handles_kick_aliases():
    assert drums.ADTOF_CLASS_MAP[35] == "kick"
    assert drums.ADTOF_CLASS_MAP[36] == "kick"


def test_adtof_class_map_routes_snare_correctly():
    assert drums.ADTOF_CLASS_MAP[38] == "snare"
    assert drums.ADTOF_CLASS_MAP[40] == "snare"


def test_adtof_class_map_routes_toms_correctly():
    for cls in (41, 43, 45, 47, 48, 50):
        assert drums.ADTOF_CLASS_MAP[cls] == "toms", f"class {cls} should be toms"


def test_adtof_class_map_routes_hihat_correctly():
    for cls in (42, 44, 46):
        assert drums.ADTOF_CLASS_MAP[cls] == "hihat", f"class {cls} should be hihat"


def test_adtof_class_map_routes_cymbals_correctly():
    for cls in (49, 51, 52, 53, 55, 57, 59):
        assert drums.ADTOF_CLASS_MAP[cls] == "cymbals", f"class {cls} should be cymbals"


# ---------------------------------------------------------------------------
# cached() — cache-invalidation logic
# ---------------------------------------------------------------------------

def test_cached_returns_false_when_summary_absent(tmp_path: Path):
    assert drums.cached(tmp_path) is False


def test_cached_returns_true_for_gated_summary(tmp_path: Path):
    summary = {
        "version": drums.SCHEMA_VERSION,
        "transcribed": False,
        "reason": "drum content below gate",
    }
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    assert drums.cached(tmp_path) is True


def test_cached_returns_false_for_old_schema(tmp_path: Path):
    summary = {"version": drums.SCHEMA_VERSION - 1, "transcribed": True}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    assert drums.cached(tmp_path) is False


def test_cached_returns_false_for_schema_version_2(tmp_path: Path):
    """v2 used librosa onsets — must be invalidated so ADTOF runs."""
    summary = {"version": 2, "transcribed": True, "model": "larsnet"}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    assert drums.cached(tmp_path) is False


def test_cached_returns_false_when_substem_wavs_missing(tmp_path: Path):
    summary = {"version": drums.SCHEMA_VERSION, "transcribed": True, "stems": {}}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    assert drums.cached(tmp_path) is False


def test_cached_returns_true_when_summary_and_wavs_present(tmp_path: Path):
    summary = {"version": drums.SCHEMA_VERSION, "transcribed": True, "stems": {}}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    sd = tmp_path / drums.SUBSTEM_DIR
    sd.mkdir()
    for s in drums.SUBSTEMS:
        (sd / f"{s}.wav").touch()
    assert drums.cached(tmp_path) is True


def test_cached_returns_false_when_one_substem_wav_missing(tmp_path: Path):
    summary = {"version": drums.SCHEMA_VERSION, "transcribed": True, "stems": {}}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    sd = tmp_path / drums.SUBSTEM_DIR
    sd.mkdir()
    # Write all substems except cymbals
    for s in drums.SUBSTEMS:
        if s != "cymbals":
            (sd / f"{s}.wav").touch()
    assert drums.cached(tmp_path) is False


def test_cached_returns_false_for_corrupt_json(tmp_path: Path):
    (tmp_path / drums.CANONICAL).write_text("{not valid json}")
    assert drums.cached(tmp_path) is False


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

def test_load_returns_parsed_summary(tmp_path: Path):
    summary = {"version": drums.SCHEMA_VERSION, "transcribed": False, "reason": "test"}
    (tmp_path / drums.CANONICAL).write_text(json.dumps(summary))
    result = drums.load(tmp_path)
    assert result == summary


# ---------------------------------------------------------------------------
# run() — gate branch
# ---------------------------------------------------------------------------

def test_run_gates_when_ratio_below_threshold(tmp_path: Path):
    """When drum stem is much quieter than other stems, run() emits a gated
    summary without invoking LarsNet or ADTOF."""
    s6 = tmp_path / "stems_6s"
    s6.mkdir()
    (s6 / "foo_(Drums)_htdemucs_6s.wav").write_bytes(b"RIFF")
    (s6 / "foo_(Vocals)_htdemucs_6s.wav").write_bytes(b"RIFF")

    # Mock _check_gate to return a sub-threshold ratio
    with patch.object(drums, "_check_gate", return_value=(-70.0, -10.0, -60.0)):
        result = drums.run(Path("fake.mp3"), tmp_path)

    assert result["transcribed"] is False
    assert "below gate" in result["reason"]
    assert result["version"] == drums.SCHEMA_VERSION
    assert result["model"] == "adtof+larsnet"
    # Confirm no LarsNet/ADTOF side effects — substem dir should not exist
    assert not (tmp_path / drums.SUBSTEM_DIR).exists()


def test_run_gate_writes_summary_to_disk(tmp_path: Path):
    """Gated run() must persist the summary so cached() returns True next call."""
    s6 = tmp_path / "stems_6s"
    s6.mkdir()
    (s6 / "track_(Drums).wav").write_bytes(b"RIFF")

    with patch.object(drums, "_check_gate", return_value=(-65.0, -5.0, -60.0)):
        drums.run(Path("fake.mp3"), tmp_path)

    summary_path = tmp_path / drums.CANONICAL
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["transcribed"] is False
    assert summary["version"] == drums.SCHEMA_VERSION


def test_run_gate_summary_has_correct_threshold_db(tmp_path: Path):
    s6 = tmp_path / "stems_6s"
    s6.mkdir()
    (s6 / "track_(Drums).wav").write_bytes(b"RIFF")

    with patch.object(drums, "_check_gate", return_value=(-65.0, -5.0, -60.0)):
        result = drums.run(Path("fake.mp3"), tmp_path)

    assert result["threshold_db"] == drums.GATE_THRESHOLD_DB


# ---------------------------------------------------------------------------
# Schema-version constant
# ---------------------------------------------------------------------------

def test_schema_version_is_4():
    """v4 = ADTOF+LarsNet with second-stage onset-count gate; bump this test
    when the schema changes again."""
    assert drums.SCHEMA_VERSION == 4


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

def test_substems_has_five_entries():
    assert len(drums.SUBSTEMS) == 5


def test_bands_covers_all_substems():
    assert set(drums.BANDS.keys()) == set(drums.SUBSTEMS)


def test_gate_threshold_unchanged():
    """Threshold is calibrated against a 25-track corpus; do not change."""
    assert drums.GATE_THRESHOLD_DB == -40.0
