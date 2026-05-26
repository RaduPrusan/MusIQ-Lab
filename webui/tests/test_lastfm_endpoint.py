import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from webui import server
from webui import lastfm


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_CACHE_DIR", str(tmp_path))
    return TestClient(server.app), tmp_path


def _seed_track(cache_dir: Path, *, mbid_rec=None, mbid_art=None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "duration_sec": 180.0, "tempo_bpm": 120.0, "key": "A:minor",
        "scale": "A natural minor", "stems_enriched": {}, "warnings": [],
    }
    (cache_dir / f"{cache_dir.name}.summary.json").write_text(json.dumps(summary))
    if mbid_rec or mbid_art:
        (cache_dir / "identify.json").write_text(json.dumps({
            "identified": True,
            "mbid_recording": mbid_rec, "mbid_artist": mbid_art,
            "title": "T", "artist": "A",
        }))


def test_endpoint_uses_cached_payload(client):
    tc, root = client
    cache = root / "my-track"
    _seed_track(cache, mbid_rec="r", mbid_art="a")
    payload = {"tags": ["rock"], "similar_artists": [{"name": "X", "match": 0.9, "mbid": ""}]}
    lastfm.write_cache(cache, payload)

    r = tc.get("/api/track/my-track/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["tags"] == ["rock"]


def test_endpoint_returns_unavailable_when_no_identify(client):
    tc, root = client
    cache = root / "no-mbid"
    _seed_track(cache)  # no identify.json

    r = tc.get("/api/track/no-mbid/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "mbid" in body["reason"].lower()


def test_endpoint_404_for_unknown_slug(client):
    tc, _ = client
    r = tc.get("/api/track/nonexistent/lastfm")
    assert r.status_code == 404


def test_endpoint_fetches_when_cache_missing(client, monkeypatch):
    tc, root = client
    cache = root / "fresh-fetch"
    _seed_track(cache, mbid_rec="r", mbid_art="a")

    monkeypatch.setattr(lastfm, "fetch_track_info", lambda *, mbid_recording: {"tags": ["a", "b"]})
    monkeypatch.setattr(lastfm, "fetch_similar_artists", lambda *, mbid_artist, limit=10: [
        {"name": "Sim", "match": 0.5, "mbid": ""},
    ])

    r = tc.get("/api/track/fresh-fetch/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["tags"] == ["a", "b"]
    assert body["similar_artists"][0]["name"] == "Sim"
    # And: the cache file should now exist.
    assert (cache / "lastfm.json").exists()


def test_endpoint_unavailable_when_lastfm_errors(client, monkeypatch):
    tc, root = client
    cache = root / "errors-out"
    _seed_track(cache, mbid_rec="r", mbid_art="a")

    def boom(**_kw):
        raise lastfm.LastFmError("no api key")
    monkeypatch.setattr(lastfm, "fetch_track_info", boom)

    r = tc.get("/api/track/errors-out/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "api key" in body["reason"]
