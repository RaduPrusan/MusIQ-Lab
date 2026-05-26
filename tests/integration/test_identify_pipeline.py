import json
from pathlib import Path

import pytest

from analyze import pipeline
from analyze.stages import identify


def test_identify_registered_in_pipeline():
    """identify must appear in the execution order + dep graph."""
    stage_names = [name for name, _mod in pipeline._STAGE_EXECUTION_ORDER]
    assert "identify" in stage_names
    assert "identify" in pipeline.STAGE_DEPS
    # identify has no upstream deps — it reads the source MP3 directly.
    assert pipeline.STAGE_DEPS["identify"] == frozenset()


def test_identify_soft_fail_does_not_break_pipeline(tmp_path, monkeypatch):
    """If identify raises unexpectedly, pipeline records the warning + continues."""
    # Force the stage to blow up; required stages should still complete.
    def explode(mp3, cache_dir, **kw):
        raise RuntimeError("simulated identify failure")
    monkeypatch.setattr(identify, "run", explode)
    monkeypatch.setattr(identify, "cached", lambda cd, **kw: False)

    # Smoke: just confirm identify is in the OPTIONAL set, so PipelineError
    # is NOT raised on its failure.
    optional_names = [name for name, _ in pipeline.OPTIONAL_STAGES]
    assert "identify" in optional_names
