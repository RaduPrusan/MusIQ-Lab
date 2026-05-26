"""Tests for the essentia_extract stage.

The Essentia high-level SVM classifiers require gaia2, which is not packaged
on PyPI and isn't present in this WSL build. The stage therefore extracts
low/rhythm/tonal/loudness reliably and reports the SVM/high-level path as
unavailable rather than trying to call it.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from analyze.stages import essentia_extract


def _fake_features_pool():
    """Mock the MusicExtractor return — a Pool-like object with the descriptor keys."""
    descriptors = {
        "rhythm.bpm": 120.1,
        "rhythm.bpm_histogram_first_peak_bpm": 120.0,
        "rhythm.bpm_histogram_first_peak_weight": 0.62,
        "rhythm.beats_count": 240.0,
        "tonal.key_krumhansl.key": "A",
        "tonal.key_krumhansl.scale": "minor",
        "tonal.key_krumhansl.strength": 0.81,
        "tonal.key_temperley.key": "A",
        "tonal.key_temperley.scale": "minor",
        "tonal.key_temperley.strength": 0.77,
        "tonal.key_edma.key": "E",
        "tonal.key_edma.scale": "major",
        "tonal.key_edma.strength": 0.42,
        "lowlevel.loudness_ebu128.integrated": -9.2,
        "lowlevel.loudness_ebu128.loudness_range": 7.4,
        "lowlevel.dynamic_complexity": 4.1,
    }
    pool = MagicMock()
    pool.descriptorNames.return_value = list(descriptors)
    pool.__getitem__.side_effect = lambda k: descriptors[k]
    pool.__contains__.side_effect = lambda k: k in descriptors
    return pool, descriptors


def test_run_writes_slim_essentia_json(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    pool, _descriptors = _fake_features_pool()

    fake_extractor = MagicMock(return_value=(pool, MagicMock()))
    monkeypatch.setattr(essentia_extract, "_build_extractor", lambda: fake_extractor)

    out = essentia_extract.run(mp3, tmp_path)

    assert out["extracted"] is True
    assert out["tempo"]["bpm"] == pytest.approx(120.1)
    assert out["tempo"]["first_peak_bpm"] == pytest.approx(120.0)
    assert out["tempo"]["first_peak_weight"] == pytest.approx(0.62)
    assert out["tempo"]["beats_count"] == 240

    assert out["key"]["krumhansl"][0] == "A"
    assert out["key"]["krumhansl"][1] == "minor"
    assert out["key"]["krumhansl"][2] == pytest.approx(0.81)
    assert out["key"]["edma"][0] == "E"
    assert out["key"]["edma"][1] == "major"
    assert out["key"]["edma"][2] == pytest.approx(0.42)

    assert out["loudness_ebu_r128"]["integrated"] == pytest.approx(-9.2)
    assert out["loudness_ebu_r128"]["range"] == pytest.approx(7.4)
    assert out["loudness_ebu_r128"]["dynamic_complexity"] == pytest.approx(4.1)

    # SVM/high-level path is unavailable in this build (gaia2 not bundled).
    assert out["high_level"]["available"] is False
    assert "gaia2" in out["high_level"]["reason"].lower() or out["high_level"]["reason"]

    on_disk = json.loads((tmp_path / "essentia.json").read_text())
    assert on_disk == out


def test_run_soft_fails_when_essentia_missing(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")

    def explode():
        raise ImportError("essentia not installed")
    monkeypatch.setattr(essentia_extract, "_build_extractor", explode)

    out = essentia_extract.run(mp3, tmp_path)
    assert out["extracted"] is False
    assert "essentia" in out["reason"].lower()
    assert (tmp_path / "essentia.json").exists()


def test_run_soft_fails_on_extractor_error(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    fake_extractor = MagicMock(side_effect=RuntimeError("audio decode failed"))
    monkeypatch.setattr(essentia_extract, "_build_extractor", lambda: fake_extractor)

    out = essentia_extract.run(mp3, tmp_path)
    assert out["extracted"] is False
    assert "audio decode" in out["reason"]


def test_cached_after_run(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")

    def explode():
        raise ImportError("essentia not installed")
    monkeypatch.setattr(essentia_extract, "_build_extractor", explode)

    essentia_extract.run(mp3, tmp_path)
    assert essentia_extract.cached(tmp_path) is True
