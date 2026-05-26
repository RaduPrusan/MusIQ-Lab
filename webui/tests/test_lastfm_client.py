import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from webui import lastfm


def _mock_resp(payload):
    return httpx.Response(200, json=payload)


def test_fetch_track_info_returns_tags(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    # Mark .env load as already done so the live .env doesn't clobber the
    # monkeypatched env var.
    monkeypatch.setattr(lastfm, "_loaded", True)
    payload = {
        "track": {
            "name": "Silent Running",
            "toptags": {"tag": [
                {"name": "hip-hop", "count": 100},
                {"name": "alternative", "count": 50},
            ]},
        },
    }
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _mock_resp(payload))
    result = lastfm.fetch_track_info(mbid_recording="rec-mbid")
    assert result["tags"] == ["hip-hop", "alternative"]


def test_fetch_similar_artists(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    monkeypatch.setattr(lastfm, "_loaded", True)
    payload = {
        "similarartists": {"artist": [
            {"name": "Blur", "match": "0.95", "mbid": "blur-mbid"},
            {"name": "Beck", "match": "0.78", "mbid": "beck-mbid"},
        ]},
    }
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _mock_resp(payload))
    result = lastfm.fetch_similar_artists(mbid_artist="gorillaz-mbid", limit=10)
    assert len(result) == 2
    assert result[0] == {"name": "Blur", "match": 0.95, "mbid": "blur-mbid"}


def test_fetch_track_info_no_api_key(monkeypatch):
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    # Poison the .env loader so it doesn't repopulate LASTFM_API_KEY from
    # the real project .env on disk.
    monkeypatch.setattr(lastfm, "_loaded", True)
    with pytest.raises(lastfm.LastFmError, match="no api key"):
        lastfm.fetch_track_info(mbid_recording="x")


def test_fetch_track_info_404(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    monkeypatch.setattr(lastfm, "_loaded", True)
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json={"error": 6, "message": "not found"}),
    )
    with pytest.raises(lastfm.LastFmError, match="not found"):
        lastfm.fetch_track_info(mbid_recording="missing")


def test_load_cache_returns_payload_within_ttl(tmp_path):
    payload = {"tags": ["a"], "similar_artists": []}
    cache_file = tmp_path / "lastfm.json"
    cache_file.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400 * 7)
    assert result == payload


def test_load_cache_returns_none_past_ttl(tmp_path):
    payload = {"tags": ["a"]}
    cache_file = tmp_path / "lastfm.json"
    old_ts = time.time() - 86400 * 30  # 30 days ago
    cache_file.write_text(json.dumps({"fetched_at": old_ts, "payload": payload}))
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400 * 7)
    assert result is None


def test_load_cache_returns_none_when_missing(tmp_path):
    assert lastfm.load_cache(tmp_path, ttl_seconds=86400) is None


def test_write_cache_roundtrips(tmp_path):
    payload = {"tags": ["a", "b"], "similar_artists": [{"name": "X"}]}
    lastfm.write_cache(tmp_path, payload)
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400)
    assert result == payload


def test_default_ttl_respects_env_var(monkeypatch):
    monkeypatch.setenv("LASTFM_TTL_DAYS", "1")
    # The getter must read the env var at call time (not import time),
    # so monkeypatching the env after import still works.
    assert lastfm.get_default_ttl_seconds() == 86400


def test_default_ttl_falls_back_to_seven_days(monkeypatch):
    monkeypatch.delenv("LASTFM_TTL_DAYS", raising=False)
    assert lastfm.get_default_ttl_seconds() == 7 * 86400


def test_default_ttl_handles_invalid_value(monkeypatch):
    monkeypatch.setenv("LASTFM_TTL_DAYS", "not_a_number")
    assert lastfm.get_default_ttl_seconds() == 7 * 86400  # falls back on parse error
