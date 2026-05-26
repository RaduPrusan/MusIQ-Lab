import httpx
import pytest

from analyze.clients import musicbrainz


_SAMPLE_RECORDING = {
    "id": "abc-mbid",
    "title": "Silent Running",
    "first-release-date": "2001-06-12",
    "isrcs": ["GBAYE0100001"],
    "artist-credit": [{"artist": {"id": "artist-mbid", "name": "Gorillaz"}}],
    "releases": [
        {
            "id": "release-mbid",
            "title": "Gorillaz",
            "release-group": {"id": "rg-mbid", "first-release-date": "2001-03-26"},
        }
    ],
}


def test_recording_lookup_extracts_core_fields(monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=_SAMPLE_RECORDING)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = musicbrainz.recording_lookup("abc-mbid")
    assert result["mbid_recording"] == "abc-mbid"
    assert result["title"] == "Silent Running"
    assert result["artist"] == "Gorillaz"
    assert result["mbid_artist"] == "artist-mbid"
    assert result["release"] == "Gorillaz"
    assert result["mbid_release_group"] == "rg-mbid"
    assert result["year"] == 2001
    assert result["isrc"] == "GBAYE0100001"


def test_recording_lookup_404(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(404, json={"error": "not found"}),
    )
    with pytest.raises(musicbrainz.MusicBrainzError, match="404"):
        musicbrainz.recording_lookup("missing-mbid")


def test_recording_lookup_handles_missing_fields(monkeypatch):
    sparse = {"id": "x", "title": "Untitled", "artist-credit": []}
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=sparse),
    )
    result = musicbrainz.recording_lookup("x")
    assert result["title"] == "Untitled"
    assert result["artist"] is None
    assert result["isrc"] is None
    assert result["year"] is None


def test_uses_user_agent_header(monkeypatch):
    captured: dict = {}

    def fake_get(self, url, **kwargs):
        captured["headers"] = kwargs.get("headers", {})
        return httpx.Response(200, json=_SAMPLE_RECORDING)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    musicbrainz.recording_lookup("x")
    assert "User-Agent" in captured["headers"]
    assert captured["headers"]["User-Agent"].startswith("MusIQ-Lab/")


def test_follows_301_redirect(monkeypatch):
    """When MB returns 301 (recording merged), follow_redirects=True
    causes httpx to chase the redirect and return the final 200 body."""
    # httpx.Client with follow_redirects=True automatically follows the
    # 301; from the caller's perspective we just get the final response.
    # Test by mocking get() to return the redirected-to body — the test
    # verifies the client passes follow_redirects=True to httpx, not that
    # we manually handle 301.
    captured = {}
    def fake_get(self, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return httpx.Response(200, json=_SAMPLE_RECORDING)
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    # Also patch the Client __init__ to capture follow_redirects kwarg.
    real_init = httpx.Client.__init__
    init_kwargs = {}
    def fake_init(self, *a, **kw):
        init_kwargs.update(kw)
        return real_init(self, *a, **kw)
    monkeypatch.setattr(httpx.Client, "__init__", fake_init)

    musicbrainz.recording_lookup("any-mbid")
    assert init_kwargs.get("follow_redirects") is True
