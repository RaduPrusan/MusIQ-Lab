import json
from pathlib import Path

import pytest


SAMPLE_SUMMARY = {
    "track": {
        "file": "Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3",
        "windows_path": r"C:\fake\path.mp3",
        "wsl_path": "/mnt/c/fake/path.mp3",
        "duration_sec": 215.064,
        "tempo_bpm": 107.14,
        "key": "F minor",
        "key_confidence": 1.0,
        "time_signature": "4/4",
    },
    "sections": [],
    "downbeats": [0.76, 3.01, 5.25],
    "chords": [
        {"start": 0.0, "end": 2.95, "label": "N", "root": None, "bass": None,
         "type": "N", "roman": None, "function": None, "confidence": 1.0,
         "agreement": "single_source"},
        {"start": 2.95, "end": 5.22, "label": "F:min", "root": "F", "bass": "F",
         "type": "min", "roman": "i", "function": "tonic", "confidence": 1.0,
         "agreement": "single_source"},
    ],
    "stems": {
        "vocals": {"notes": [
            {"t": 0.29, "dur": 0.24, "midi": 67, "name": "G4", "vel": 0.6,
             "scale_deg": "2", "in_chord": None, "role": None}
        ]},
        "bass": {"notes": []},
        "guitar": {"notes": []},
        "piano": {"notes": []},
        "other": {"notes": []},
        "drums": {"transcribed": False, "reason": "drums skipped per Stage 6"},
    },
    "analysis": {
        "scale": "F natural minor",
        "modal_interchange_count": 29,
        "predominant_chord_loop": ["F:min", "C:min", "C#:maj", "Ab:maj"],
        "loop_roman": ["i", "v", "♭VI", "♭III"],
        "loop_appearances": [{"start": 2.95, "end": 12.1}],
        "vocal_range": {"low": "F2", "high": "C7"},
    },
    "provenance": {
        "pipeline_version": "0.1.0",
        "models": {"audio-separator": "0.44.1"},
        "warnings": [],
    },
}


def write_summary(cache: Path, slug: str, *, overrides: dict | None = None,
                  filename_override: str | None = None) -> Path:
    """Write a summary.json into cache/<slug>/<slug>.summary.json."""
    summary = json.loads(json.dumps(SAMPLE_SUMMARY))  # deep copy
    if filename_override is not None:
        summary["track"]["file"] = filename_override
    if overrides:
        for key_path, value in overrides.items():
            target = summary
            keys = key_path.split(".")
            for k in keys[:-1]:
                target = target[k]
            target[keys[-1]] = value
    track_dir = cache / slug
    track_dir.mkdir(parents=True, exist_ok=True)
    out = track_dir / f"{slug}.summary.json"
    out.write_text(json.dumps(summary), encoding="utf-8")
    return out


@pytest.fixture
def synthetic_cache(tmp_path, monkeypatch):
    """A cache/ directory with one fully-formed track."""
    cache = tmp_path / "cache"
    cache.mkdir()
    write_summary(cache, "gorillaz_silent_running")
    monkeypatch.setenv("WEBUI_CACHE_DIR", str(cache))
    # Reset the tracks-module mtime cache between tests to avoid leakage:
    from webui import tracks as _tracks
    _tracks._cache.clear()
    return cache


@pytest.fixture
def write_track(synthetic_cache):
    """Function-fixture to add more tracks into the synthetic cache."""
    def _write(slug: str, **kwargs):
        return write_summary(synthetic_cache, slug, **kwargs)
    return _write


@pytest.fixture(autouse=True)
def _reset_chat_registry():
    """Clear the module-level chat actor registry between tests.

    `webui.server._chat_registry` is created once per process and the
    FastAPI TestClient does not always fire shutdown between tests, so a
    ChatActor created in test A would otherwise leak into test B (still
    holding a stale FakeClient with its own consumed scripts).
    """
    yield
    try:
        from webui.server import _chat_registry
    except Exception:
        return
    _chat_registry._actors.clear()
