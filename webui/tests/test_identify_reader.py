import json
from pathlib import Path

from webui.identify import read_identify


def test_read_identify_returns_dict(tmp_path):
    cache_dir = tmp_path / "slug-abc"
    cache_dir.mkdir()
    payload = {
        "identified": True, "title": "Track", "artist": "Artist",
        "year": 2001, "mbid_recording": "rec", "mbid_artist": "art",
    }
    (cache_dir / "identify.json").write_text(json.dumps(payload))

    result = read_identify(cache_dir)
    assert result == payload


def test_read_identify_missing_returns_none(tmp_path):
    cache_dir = tmp_path / "slug-abc"
    cache_dir.mkdir()
    assert read_identify(cache_dir) is None


def test_read_identify_not_identified_returns_dict(tmp_path):
    """We do return the payload even if identified: false — caller decides."""
    cache_dir = tmp_path / "slug-abc"
    cache_dir.mkdir()
    payload = {"identified": False, "reason": "no match"}
    (cache_dir / "identify.json").write_text(json.dumps(payload))
    assert read_identify(cache_dir) == payload


def test_read_identify_handles_corrupt_json(tmp_path):
    cache_dir = tmp_path / "slug-abc"
    cache_dir.mkdir()
    (cache_dir / "identify.json").write_text("not valid json {")
    assert read_identify(cache_dir) is None  # corrupt → treat as missing
