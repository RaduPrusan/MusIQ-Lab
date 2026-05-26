import json
from pathlib import Path

from webui.essentia import read_essentia


def test_read_essentia_returns_payload(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    payload = {"extracted": True, "tempo": {"bpm": 120.1}, "high_level": {}}
    (cache_dir / "essentia.json").write_text(json.dumps(payload))
    assert read_essentia(cache_dir) == payload


def test_read_essentia_missing_returns_none(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    assert read_essentia(cache_dir) is None


def test_read_essentia_corrupt_returns_none(tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    (cache_dir / "essentia.json").write_text("not json {")
    assert read_essentia(cache_dir) is None
