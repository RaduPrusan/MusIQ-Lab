import httpx
import pytest

from analyze.clients import acoustid


def _ok_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_lookup_returns_best_score_match(monkeypatch):
    payload = {
        "status": "ok",
        "results": [
            {"id": "weak", "score": 0.42, "recordings": [{"id": "mbid-weak"}]},
            {"id": "strong", "score": 0.94, "recordings": [{"id": "mbid-strong"}]},
        ],
    }

    def fake_get(self, url, **kwargs):
        return _ok_response(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setenv("ACOUSTID_API_KEY", "test_key")

    result = acoustid.lookup("FAKE_FP", 240.5, min_score=0.85)
    assert result["mbid_recording"] == "mbid-strong"
    assert result["acoustid_score"] == 0.94


def test_lookup_returns_none_below_threshold(monkeypatch):
    payload = {
        "status": "ok",
        "results": [{"id": "weak", "score": 0.42, "recordings": [{"id": "mbid-w"}]}],
    }

    def fake_get(self, url, **kwargs):
        return _ok_response(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setenv("ACOUSTID_API_KEY", "test_key")

    result = acoustid.lookup("FAKE_FP", 240.5, min_score=0.85)
    assert result is None


def test_lookup_returns_none_when_no_results(monkeypatch):
    payload = {"status": "ok", "results": []}
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _ok_response(payload))
    monkeypatch.setenv("ACOUSTID_API_KEY", "test_key")
    assert acoustid.lookup("FAKE_FP", 240.5) is None


def test_lookup_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    # Also poison .env loader so we can't pick one up from disk
    from analyze import keys
    keys._loaded = True
    with pytest.raises(acoustid.AcoustIDError, match="no api key"):
        acoustid.lookup("FAKE_FP", 240.5)


def test_lookup_handles_non_200(monkeypatch):
    # Use 500 + stubbed sleep so retry loop doesn't slow the test.
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(500, text="service unavailable"),
    )
    monkeypatch.setenv("ACOUSTID_API_KEY", "test_key")
    import analyze.clients.acoustid as ac
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    with pytest.raises(acoustid.AcoustIDError, match="500"):
        acoustid.lookup("FAKE_FP", 240.5)


def test_retries_on_5xx_then_succeeds(monkeypatch):
    """Two 503s, then a 200 — lookup should return the 200's body."""
    monkeypatch.setenv("ACOUSTID_API_KEY", "k")
    call_count = {"n": 0}
    def fake_get(self, url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(503, text="upstream connect error")
        return httpx.Response(200, json={
            "status": "ok",
            "results": [{"id": "x", "score": 0.92, "recordings": [{"id": "mbid"}]}],
        })
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    # Speed up the sleep
    import analyze.clients.acoustid as ac
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)

    result = acoustid.lookup("fp", 100.0)
    assert result["mbid_recording"] == "mbid"
    assert call_count["n"] == 3


def test_retries_exhausted_raises(monkeypatch):
    """All 3 attempts return 503 — raises AcoustIDError mentioning the count."""
    monkeypatch.setenv("ACOUSTID_API_KEY", "k")
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(503, text="still down"),
    )
    import analyze.clients.acoustid as ac
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)

    with pytest.raises(acoustid.AcoustIDError, match="after 3 attempts"):
        acoustid.lookup("fp", 100.0)


def test_no_retry_on_4xx(monkeypatch):
    """400 (invalid key) is a final answer — should raise immediately, no retries."""
    monkeypatch.setenv("ACOUSTID_API_KEY", "k")
    call_count = {"n": 0}
    def fake_get(self, url, **kwargs):
        call_count["n"] += 1
        return httpx.Response(400, text="invalid API key")
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    with pytest.raises(acoustid.AcoustIDError, match="HTTP 400"):
        acoustid.lookup("fp", 100.0)
    assert call_count["n"] == 1  # no retries on 4xx
