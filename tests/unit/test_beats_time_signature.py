"""Unit tests for the time_signature recovery added in beats stage SCHEMA_VERSION=2.

The beats stage runs madmom's DBNDownBeatTrackingProcessor with
beats_per_bar=[3, 4]. Madmom commits to ONE meter for the whole bar grid and
emits 1-indexed beat positions: 4/4 cycles 1,2,3,4,...; 3/4 cycles 1,2,3,...

These tests mock the two madmom processors so the logic can be exercised
without loading audio or running RNN inference."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest


def _install_madmom_stub(monkeypatch, beats_with_pos):
    """Install a fake madmom.features.downbeats module that returns
    beats_with_pos when the DBN processor is called."""

    class _RNN:
        def __call__(self, _path):
            return np.zeros((10, 2), dtype=np.float32)

    class _DBN:
        def __init__(self, **_kwargs):
            pass

        def __call__(self, _activations):
            return np.asarray(beats_with_pos, dtype=np.float64)

    fake_madmom = types.ModuleType("madmom")
    fake_features = types.ModuleType("madmom.features")
    fake_downbeats = types.ModuleType("madmom.features.downbeats")
    fake_downbeats.RNNDownBeatProcessor = _RNN
    fake_downbeats.DBNDownBeatTrackingProcessor = _DBN
    fake_madmom.features = fake_features
    fake_features.downbeats = fake_downbeats
    monkeypatch.setitem(sys.modules, "madmom", fake_madmom)
    monkeypatch.setitem(sys.modules, "madmom.features", fake_features)
    monkeypatch.setitem(sys.modules, "madmom.features.downbeats", fake_downbeats)


def test_beats_run_recovers_4_4(tmp_path, monkeypatch):
    from analyze.stages import beats as beats_stage

    # Two bars in 4/4: positions cycle 1,2,3,4,1,2,3,4
    rows = [(0.50 * i, ((i) % 4) + 1) for i in range(8)]
    _install_madmom_stub(monkeypatch, rows)

    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"")
    out = beats_stage.run(mp3, tmp_path)

    assert out["time_signature"] == "4/4"
    assert out["beats_per_bar"] == 4
    assert out["n_beats"] == 8
    assert out["n_downbeats"] == 2
    on_disk = json.loads((tmp_path / "madmom_downbeats.json").read_text())
    assert on_disk["time_signature"] == "4/4"
    assert on_disk["beats_per_bar"] == 4


def test_beats_run_recovers_3_4(tmp_path, monkeypatch):
    from analyze.stages import beats as beats_stage

    # Two bars in 3/4: positions cycle 1,2,3,1,2,3
    rows = [(0.50 * i, ((i) % 3) + 1) for i in range(6)]
    _install_madmom_stub(monkeypatch, rows)

    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"")
    out = beats_stage.run(mp3, tmp_path)

    assert out["time_signature"] == "3/4"
    assert out["beats_per_bar"] == 3
    assert out["n_downbeats"] == 2


def test_beats_run_empty_grid_falls_back_to_4_4(tmp_path, monkeypatch):
    from analyze.stages import beats as beats_stage

    _install_madmom_stub(monkeypatch, [])

    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"")
    out = beats_stage.run(mp3, tmp_path)

    # Defensive fallback: a track that returns no beats still gets a valid TS.
    assert out["time_signature"] == "4/4"
    assert out["beats_per_bar"] == 4
    assert out["n_beats"] == 0


def test_beats_schema_version_bumped():
    from analyze.stages import beats as beats_stage
    # Guards against an accidental rollback of the schema bump.
    assert beats_stage.SCHEMA_VERSION >= 2


def test_summary_writer_reads_time_signature_from_results(tmp_path):
    """summary_writer should propagate beats.time_signature into track.time_signature."""
    from analyze.writers.summary_writer import write_summary

    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    results = {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {
            "bpm": 90.0,
            "time_signature": "3/4",
            "beats_per_bar": 3,
            "beats": [0.0, 0.5, 1.0],
            "downbeats": [0.0],
            "n_beats": 3,
            "n_downbeats": 1,
        },
        "key": {"key": "G major", "confidence": 1.0, "source": "skey", "errors": []},
        "chords": [],
        "transcription": {},
    }
    derived = {
        "scale": "G major",
        "predominant_chord_loop": None,
        "loop_roman": None,
        "loop_appearances": [],
        "modal_interchange_count": 0,
        "vocal_range": None,
        "chords_enriched": [],
        "stems_enriched": {},
    }

    write_summary(out, mp3, results, derived, warnings=[], duration_sec=10.0)
    data = json.loads(out.read_text())
    assert data["track"]["time_signature"] == "3/4"


def test_summary_writer_falls_back_to_4_4_when_missing(tmp_path):
    """Backward-compat: pre-schema-2 results dict (no time_signature) -> '4/4'."""
    from analyze.writers.summary_writer import write_summary

    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    results = {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {  # NOTE: no time_signature / beats_per_bar
            "bpm": 120.0,
            "beats": [0.0, 0.5, 1.0, 1.5],
            "downbeats": [0.0],
            "n_beats": 4,
            "n_downbeats": 1,
        },
        "key": {"key": "C major", "confidence": 1.0, "source": "skey", "errors": []},
        "chords": [],
        "transcription": {},
    }
    derived = {
        "scale": "C major",
        "predominant_chord_loop": None,
        "loop_roman": None,
        "loop_appearances": [],
        "modal_interchange_count": 0,
        "vocal_range": None,
        "chords_enriched": [],
        "stems_enriched": {},
    }

    write_summary(out, mp3, results, derived, warnings=[], duration_sec=10.0)
    data = json.loads(out.read_text())
    assert data["track"]["time_signature"] == "4/4"
