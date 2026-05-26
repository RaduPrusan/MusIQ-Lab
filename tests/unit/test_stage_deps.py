"""Asserts STAGE_DEPS is a conservative superset of actual cross-stage filesystem reads."""
from __future__ import annotations

from pathlib import Path

import pytest

from analyze.pipeline import STAGE_DEPS, downstream_of
from analyze import pipeline

ARTIFACT_TO_STAGE = {
    "stems_routing.json":  "stems",
    "stems_6s":            "stems",
    "stems_bsroformer":    "stems",
    "stems_htdemucs_ft":   "stems",
    "vocal_f0.npz":        "vocal_f0",
    "vocal_f0_summary.json": "vocal_f0",
    "madmom_downbeats.json": "beats",
    "beat_this.json":       "beats_xcheck",
    "skey.json":            "key",
    "chords.json":          "chords",
    "transcription_summary.json": "transcription",
    "drums_summary.json":   "drums",
}

STAGES_DIR = Path(__file__).resolve().parents[2] / "analyze" / "stages"


def _scan_reads(stage_file: Path) -> set[str]:
    src = stage_file.read_text()
    found: set[str] = set()
    for artifact in ARTIFACT_TO_STAGE:
        if artifact in src:
            found.add(artifact)
    return found


def test_stage_deps_is_conservative_superset():
    failures: list[str] = []
    for stage, deps in STAGE_DEPS.items():
        stage_file = STAGES_DIR / f"{stage}.py"
        if not stage_file.exists():
            continue
        reads = _scan_reads(stage_file)
        for artifact in reads:
            producer = ARTIFACT_TO_STAGE[artifact]
            if producer == stage:
                continue
            if producer not in deps:
                failures.append(
                    f"{stage} reads {artifact!r} (produced by {producer}) but "
                    f"STAGE_DEPS[{stage!r}] = {deps} does not include {producer!r}"
                )
    assert not failures, "\n".join(failures)


def test_downstream_of_stems_includes_known_consumers():
    ds = downstream_of("stems")
    assert "transcription" in ds
    assert "vocal_f0" in ds
    assert "drums" in ds


def test_downstream_of_leaf_stage_is_empty():
    # beats_xcheck has no downstream consumers — pure cross-check stage
    assert downstream_of("beats_xcheck") == set()
    # vocal_consensus_contour is the deepest leaf in the current graph
    assert downstream_of("vocal_consensus_contour") == set()


def test_downstream_of_transcription_includes_consensus_contour():
    # vocal_consensus_contour depends on transcription (basic-pitch MIDI)
    assert "vocal_consensus_contour" in downstream_of("transcription")


def test_downstream_of_vocal_f0_includes_consensus_contour():
    assert "vocal_consensus_contour" in downstream_of("vocal_f0")


# ---------------------------------------------------------------------------
# Validation / graph tests moved from tests/integration/test_selective_rerun.py
# These test pure pipeline.analyze() argument validation that runs before any
# audio work — no fixture mp3 required (we touch a tmp file for the mp3-exists
# guard at the top of analyze()).
# ---------------------------------------------------------------------------

def test_unknown_stage_raises(tmp_path: Path):
    """analyze() raises ValueError for unknown stages_only entries."""
    fake_mp3 = tmp_path / "fake.mp3"
    fake_mp3.touch()
    with pytest.raises(ValueError, match="unknown"):
        pipeline.analyze(fake_mp3, slug="test", stages_only={"nonsense"})


def test_downstream_of_stems_invalidation():
    """downstream_of('stems') is a superset of the known direct consumers."""
    ds = downstream_of("stems")
    assert {"transcription", "vocal_f0", "drums"}.issubset(ds), ds
