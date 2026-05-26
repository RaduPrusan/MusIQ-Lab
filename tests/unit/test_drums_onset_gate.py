"""Tests for the drums stage's second-stage onset-count gate.

The first-stage gate (RMS-ratio) is covered in test_drums.py. This file
covers the second-stage gate that fires when total ADTOF onsets across all
5 substems is below MIN_ONSETS_THRESHOLD — catching false positives on
percussive non-drum content (acoustic guitar attacks, vocal plosives) that
slipped past the first-stage RMS gate.

Concrete failure case this guards: Sting "Shape of My Heart" (4:42 acoustic
guitar + vocal, no drums) — htdemucs Drums-stem leakage keeps ratio_db at
-23.1 dB (above the -40 dB first-stage threshold), then ADTOF emits 1
onset (false positive on a guitar attack). Without this gate the webui
renders a meaningless "1 hit" Drums row.

ADTOF and LarsNet are heavyweight (TF/Keras + GPU), so both are mocked at
the module level — no existing drums-stage tests mock these (test_drums.py
covers the gated branch which short-circuits before either is invoked), so
this file establishes the pattern.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from analyze.stages import drums


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache(tmp_path: Path) -> Path:
    """Set up a minimal cache layout so run() can locate a drums stem path
    via the legacy stems_6s glob fallback."""
    s6 = tmp_path / "stems_6s"
    s6.mkdir()
    (s6 / "track_(Drums)_htdemucs_6s.wav").write_bytes(b"RIFF")
    (s6 / "track_(Vocals)_htdemucs_6s.wav").write_bytes(b"RIFF")
    return tmp_path


def _adtof_events(n: int) -> list[dict]:
    """Build n ADTOF events on the kick class (35) at evenly spaced times."""
    return [
        {"time": 0.5 * i, "midi_class": 35, "velocity": 0.0, "confidence": 0.0}
        for i in range(n)
    ]


def _run_drums_with_n_onsets(tmp_path: Path, n_onsets: int) -> dict:
    """Drive run() with the first-stage gate forced open and ADTOF mocked
    to emit n_onsets events. _emit_larsnet_substems is also mocked since
    we don't want to invoke the real GPU pipeline."""
    cache_dir = _make_cache(tmp_path)
    # Force first-stage gate to pass (ratio above -40 dB).
    with patch.object(drums, "_check_gate", return_value=(-30.0, -10.0, -20.0)), \
         patch.object(drums, "_emit_larsnet_substems"), \
         patch.object(drums, "_run_adtof", return_value=_adtof_events(n_onsets)):
        return drums.run(Path("fake.mp3"), cache_dir)


# ---------------------------------------------------------------------------
# Constant
# ---------------------------------------------------------------------------

def test_min_onsets_threshold_is_ten():
    """Calibrated: any legitimate drum track sits well above this floor.
    Bump this test if recalibrating against new corpus data."""
    assert drums.MIN_ONSETS_THRESHOLD == 10


# ---------------------------------------------------------------------------
# Gate firing / passing
# ---------------------------------------------------------------------------

def test_onset_gate_fires_below_threshold(tmp_path: Path):
    """5 onsets (below threshold of 10) → gated with adtof_total_onsets=5."""
    result = _run_drums_with_n_onsets(tmp_path, 5)

    assert result["transcribed"] is False
    assert "5 ADTOF onset" in result["reason"]
    assert result["adtof_total_onsets"] == 5
    assert result["min_onsets_threshold"] == drums.MIN_ONSETS_THRESHOLD
    # Diagnostic fields from the first-stage gate measurement are preserved
    # so downstream consumers can trace the full gate chain.
    assert result["drums_stem_db"] == -30.0
    assert result["max_other_stem_db"] == -10.0
    assert result["ratio_db"] == -20.0
    assert result["threshold_db"] == drums.GATE_THRESHOLD_DB
    assert result["version"] == drums.SCHEMA_VERSION
    assert result["model"] == "adtof+larsnet"


def test_onset_gate_passes_above_threshold(tmp_path: Path):
    """50 onsets → not gated; summary contains stems block."""
    result = _run_drums_with_n_onsets(tmp_path, 50)

    assert result["transcribed"] is True
    assert "stems" in result
    # All 50 events were on the kick class.
    assert result["stems"]["kick"]["n_onsets"] == 50
    for substem in ("snare", "toms", "hihat", "cymbals"):
        assert result["stems"][substem]["n_onsets"] == 0
    # No second-stage diagnostic fields on the pass path.
    assert "adtof_total_onsets" not in result
    assert "min_onsets_threshold" not in result


def test_onset_gate_boundary_at_threshold_minus_one(tmp_path: Path):
    """9 onsets (one below threshold) → gated. Confirms strict less-than."""
    result = _run_drums_with_n_onsets(tmp_path, 9)

    assert result["transcribed"] is False
    assert result["adtof_total_onsets"] == 9
    assert "9 ADTOF onset" in result["reason"]


def test_onset_gate_boundary_at_threshold(tmp_path: Path):
    """10 onsets (exactly at threshold) → NOT gated. The threshold is an
    exclusive lower bound (gate fires on `< threshold`), so the boundary
    case lands on the legit side."""
    result = _run_drums_with_n_onsets(tmp_path, 10)

    assert result["transcribed"] is True
    assert "stems" in result
    assert result["stems"]["kick"]["n_onsets"] == 10


def test_onset_gate_zero_onsets_still_emits_summary(tmp_path: Path):
    """0 onsets → gated with adtof_total_onsets=0; summary.json on disk."""
    cache_dir = _make_cache(tmp_path)

    with patch.object(drums, "_check_gate", return_value=(-30.0, -10.0, -20.0)), \
         patch.object(drums, "_emit_larsnet_substems"), \
         patch.object(drums, "_run_adtof", return_value=[]):
        result = drums.run(Path("fake.mp3"), cache_dir)

    assert result["transcribed"] is False
    assert result["adtof_total_onsets"] == 0
    assert "0 ADTOF onset" in result["reason"]

    # Summary persisted to disk so cached() can short-circuit on next call.
    summary_path = cache_dir / drums.CANONICAL
    assert summary_path.exists()
    on_disk = json.loads(summary_path.read_text())
    assert on_disk["transcribed"] is False
    assert on_disk["adtof_total_onsets"] == 0
    assert on_disk["version"] == drums.SCHEMA_VERSION
