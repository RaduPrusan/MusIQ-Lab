"""Round 2 tests for the identify pipeline overhaul.

Covers the 13-item Round 2 deliverable list from
``docs/superpowers/identify-overhaul/round-1-review.md``:

  - Walker fix (sort desc, skip unlinked, threshold respected)
  - Per-result recording selector (closest duration, fallback to [0])
  - Threshold recalibration (0.85 -> 0.65)
  - httpx transport errors converted to AcoustIDError
  - fpcalc output validation (FpcalcError on missing keys / JSON decode)
  - AcoustID error code surfacing
  - Atomic writes (same-dir tmp + os.replace) in identify + sidecar
  - SCHEMA_VERSION = 2
  - Legacy-cache sidecar synthesis bridge
  - Structured log line on success + failure
  - Raw AcoustID JSON caching
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest


# webui tests run with the worktree as cwd via pytest invocation; importing
# analyze.* requires either WSL py3.11 or the override env var. The Round 2
# implementation lives in analyze/, so we depend on the import succeeding.
# (If this module fails to import on Windows host py3.13, run pytest under
# the WSL .venv as described in webui/tests/README.md.)
from analyze import sidecar as analyze_sidecar
from analyze.clients import acoustid as acoustid_client
from analyze.stages import identify as identify_stage


# ----------------------------------------------------------------------------
# Walker + recording selector
# ----------------------------------------------------------------------------

def _fake_acoustid_response(results):
    """Build a real AcoustID v2 lookup response body."""
    return {"status": "ok", "results": results}


class _FakeResp:
    def __init__(self, status_code: int, body: dict | str):
        self.status_code = status_code
        if isinstance(body, dict):
            self._json = body
            self.text = json.dumps(body)
        else:
            self._json = None
            self.text = body

    def json(self):
        return self._json


class _FakeClient:
    """Minimal httpx.Client stand-in that returns a pre-canned response."""
    def __init__(self, resp: _FakeResp | Exception):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


@pytest.fixture
def _api_key(monkeypatch):
    """Force a non-empty AcoustID API key so lookup() doesn't bail early."""
    monkeypatch.setattr(
        acoustid_client.keys, "get_acoustid_key", lambda: "FAKEKEY"
    )


def _patch_httpx(monkeypatch, resp_or_exc):
    monkeypatch.setattr(
        acoustid_client.httpx, "Client",
        lambda *a, **kw: _FakeClient(resp_or_exc),
    )


def test_walker_returns_second_result_when_first_unlinked(monkeypatch, _api_key):
    """Bucket-C bug: skip max-score result if it has no recordings."""
    body = _fake_acoustid_response([
        {"id": "first", "score": 0.984, "recordings": []},
        {
            "id": "second", "score": 0.951,
            "recordings": [{"id": "rec-x", "duration": 200}],
        },
    ])
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    out = acoustid_client.lookup("AQADtest", 200.0)
    assert out is not None
    assert out["mbid_recording"] == "rec-x"
    assert out["acoustid_id"] == "second"
    assert abs(out["acoustid_score"] - 0.951) < 1e-6


def test_walker_returns_none_when_all_unlinked(monkeypatch, _api_key):
    body = _fake_acoustid_response([
        {"id": "a", "score": 0.99, "recordings": []},
        {"id": "b", "score": 0.80, "recordings": []},
    ])
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    assert acoustid_client.lookup("AQADtest", 200.0) is None


def test_walker_respects_threshold(monkeypatch, _api_key):
    """A high-score unlinked + a linked-but-below-threshold = None."""
    body = _fake_acoustid_response([
        {"id": "a", "score": 0.99, "recordings": []},
        {"id": "b", "score": 0.40, "recordings": [{"id": "rec", "duration": 200}]},
    ])
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    assert acoustid_client.lookup("AQADtest", 200.0) is None


def test_recording_selector_prefers_closest_duration(monkeypatch, _api_key):
    body = _fake_acoustid_response([
        {
            "id": "winner", "score": 0.92,
            "recordings": [
                {"id": "rec-a", "duration": 100},
                {"id": "rec-b", "duration": 240},
            ],
        },
    ])
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    out = acoustid_client.lookup("AQADtest", 240.0)
    assert out["mbid_recording"] == "rec-b"


def test_recording_selector_falls_back_when_no_duration(monkeypatch, _api_key):
    body = _fake_acoustid_response([
        {
            "id": "winner", "score": 0.92,
            "recordings": [{"id": "rec-a"}, {"id": "rec-b"}],
        },
    ])
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    out = acoustid_client.lookup("AQADtest", 240.0)
    assert out["mbid_recording"] == "rec-a"


def test_threshold_default_is_065():
    assert acoustid_client.DEFAULT_MIN_SCORE == 0.65


# ----------------------------------------------------------------------------
# httpx transport-error wrapping
# ----------------------------------------------------------------------------

def test_httpx_request_error_converted_to_acoustid_error(monkeypatch, _api_key):
    err = httpx.ConnectError("DNS broke")
    _patch_httpx(monkeypatch, err)
    with pytest.raises(acoustid_client.AcoustIDError) as excinfo:
        acoustid_client.lookup("AQADtest", 200.0)
    assert "transport" in str(excinfo.value)


def test_acoustid_error_includes_error_code(monkeypatch, _api_key):
    body = {"status": "error", "error": {"code": 4, "message": "invalid API key"}}
    _patch_httpx(monkeypatch, _FakeResp(200, body))
    with pytest.raises(acoustid_client.AcoustIDError) as excinfo:
        acoustid_client.lookup("AQADtest", 200.0)
    msg = str(excinfo.value)
    assert "code=4" in msg


# ----------------------------------------------------------------------------
# fpcalc validation
# ----------------------------------------------------------------------------

def _fake_completed(stdout: str, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["fpcalc"], returncode=0, stdout=stdout, stderr=stderr,
    )


def test_run_fpcalc_missing_fingerprint_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(identify_stage, "_FPCALC", tmp_path / "fake_fpcalc")
    (tmp_path / "fake_fpcalc").write_text("")  # presence check passes
    monkeypatch.setattr(
        identify_stage.subprocess, "run",
        lambda *a, **kw: _fake_completed(json.dumps({"duration": 200.0})),
    )
    with pytest.raises(identify_stage.FpcalcError) as excinfo:
        identify_stage._run_fpcalc(tmp_path / "fake.mp3")
    assert "missing required keys" in str(excinfo.value)


def test_run_fpcalc_json_decode_error_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(identify_stage, "_FPCALC", tmp_path / "fake_fpcalc")
    (tmp_path / "fake_fpcalc").write_text("")
    monkeypatch.setattr(
        identify_stage.subprocess, "run",
        lambda *a, **kw: _fake_completed("not json {{{ trash"),
    )
    with pytest.raises(identify_stage.FpcalcError) as excinfo:
        identify_stage._run_fpcalc(tmp_path / "fake.mp3")
    assert "not JSON" in str(excinfo.value)


def test_run_caught_fpcalc_error_does_not_demote(monkeypatch, tmp_path):
    """FpcalcError must be in the run() catch tuple — verify by running the
    full run() with garbled fpcalc output and confirming we got identified=False
    without an unhandled exception."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    monkeypatch.setattr(identify_stage, "_FPCALC", tmp_path / "fake_fpcalc")
    (tmp_path / "fake_fpcalc").write_text("")
    monkeypatch.setattr(
        identify_stage.subprocess, "run",
        lambda *a, **kw: _fake_completed("not json {"),
    )
    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert result["identified"] is False
    assert "FpcalcError" in result["reason"] or "not JSON" in result["reason"]


# ----------------------------------------------------------------------------
# Atomic writes
# ----------------------------------------------------------------------------

def test_preserve_or_write_atomic(tmp_path, monkeypatch):
    """A failed second write must not destroy the previous identify.json."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()

    # Seed an identified=true cache.
    first = {"identified": True, "mbid_recording": "abc", "title": "Foo"}
    identify_stage._preserve_or_write(cache_dir, first, {})
    original_text = (cache_dir / "identify.json").read_text()

    # Now simulate a failure during the second write. Because the second
    # payload is identified=true (so preservation does NOT short-circuit),
    # _atomic_write_text will run. We patch os.replace to raise so the
    # half-written .tmp gets created but the target is never swapped.
    def _boom(src, dst):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(identify_stage.os, "replace", _boom)
    with pytest.raises(OSError):
        identify_stage._preserve_or_write(
            cache_dir, {"identified": True, "mbid_recording": "DIFFERENT"}, {},
        )

    # The original identify.json must be unchanged.
    assert (cache_dir / "identify.json").read_text() == original_text


def test_preserve_or_write_tmp_is_same_dir(tmp_path, monkeypatch):
    """The .tmp file MUST live in the destination directory (NTFS constraint)."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    captured = {}

    real_replace = os.replace

    def _capturing_replace(src, dst):
        captured["src"] = Path(src)
        captured["dst"] = Path(dst)
        real_replace(src, dst)

    monkeypatch.setattr(identify_stage.os, "replace", _capturing_replace)
    identify_stage._preserve_or_write(
        cache_dir, {"identified": True, "mbid_recording": "abc"}, {}
    )
    assert captured["src"].parent == captured["dst"].parent
    assert captured["dst"].parent == cache_dir


def test_sidecar_write_atomic(tmp_path, monkeypatch):
    """sidecar.write must also use the same-dir tmp + os.replace pattern."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    captured = {}
    real_replace = os.replace

    def _capturing_replace(src, dst):
        captured["src"] = Path(src)
        captured["dst"] = Path(dst)
        real_replace(src, dst)

    monkeypatch.setattr(analyze_sidecar.os, "replace", _capturing_replace)
    analyze_sidecar.write(cache_dir, "identify", {}, schema_version=2)
    assert captured["src"].parent == captured["dst"].parent
    assert captured["dst"].name == ".params_identify.json"


# ----------------------------------------------------------------------------
# Schema version + legacy cache bridge
# ----------------------------------------------------------------------------

def test_schema_version_is_at_least_4():
    """R4 set SCHEMA_VERSION=4; R5 bumped to 5. Keep this as a floor so an
    accidental rollback below 4 fails loudly."""
    assert identify_stage.SCHEMA_VERSION >= 4


def test_legacy_cache_synthesizes_sidecar(tmp_path):
    """A pre-sidecar identify.json with identified=true must NOT force a
    re-run on every analyze invocation — cached() should synthesize the
    sidecar in place."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    (cache_dir / "identify.json").write_text(json.dumps({
        "identified": True, "mbid_recording": "abc", "title": "Foo",
    }))
    # No sidecar present — historically cached() returned False here.
    assert not (cache_dir / ".params_identify.json").exists()

    assert identify_stage.cached(cache_dir) is True
    # Sidecar must now exist at the current schema version.
    sidecar_path = cache_dir / ".params_identify.json"
    assert sidecar_path.exists()
    data = json.loads(sidecar_path.read_text())
    assert data["schema_version"] == identify_stage.SCHEMA_VERSION


def test_legacy_cache_bridge_does_not_synthesize_for_identified_false(tmp_path):
    """Identified=false caches without sidecar MUST still re-run (no bridge)."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    (cache_dir / "identify.json").write_text(json.dumps({
        "identified": False, "reason": "no match",
    }))
    assert identify_stage.cached(cache_dir) is False
    assert not (cache_dir / ".params_identify.json").exists()


# ----------------------------------------------------------------------------
# Structured log line
# ----------------------------------------------------------------------------

def _patch_fpcalc_ok(monkeypatch, tmp_path, fingerprint="AQADtest", duration=200.0):
    monkeypatch.setattr(identify_stage, "_FPCALC", tmp_path / "fake_fpcalc")
    (tmp_path / "fake_fpcalc").write_text("")
    monkeypatch.setattr(
        identify_stage.subprocess, "run",
        lambda *a, **kw: _fake_completed(json.dumps({
            "fingerprint": fingerprint, "duration": duration,
        })),
    )


def test_structured_log_emitted_on_failure(monkeypatch, tmp_path, caplog):
    """identified=false path emits the §4.1 one-liner."""
    cache_dir = tmp_path / "myslug"
    cache_dir.mkdir()
    _patch_fpcalc_ok(monkeypatch, tmp_path)

    def _no_match(*a, **kw):
        return None
    monkeypatch.setattr(acoustid_client, "lookup", _no_match)

    with caplog.at_level(logging.INFO, logger=identify_stage.__name__):
        identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    matching = [r for r in caplog.records if "identify: slug=" in r.getMessage()]
    assert matching, "expected an identify: log line, got: " + repr([r.getMessage() for r in caplog.records])
    msg = matching[0].getMessage()
    assert "slug=myslug" in msg
    assert "source=none" in msg
    assert "reason=" in msg


def test_structured_log_emitted_on_success(monkeypatch, tmp_path, caplog):
    """identified=true path emits source=acoustid + score + mbid.

    R5 note: align slug-derived artist/title with the AcoustID-identified
    artist/title so the artist-plausibility gate doesn't demote the
    canonical match.
    """
    cache_dir = tmp_path / "myslug"
    cache_dir.mkdir()
    _patch_fpcalc_ok(monkeypatch, tmp_path)

    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: {
        "mbid_recording": "rec-1",
        "acoustid_score": 0.92,
        "acoustid_id": "ac-1",
    })
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "Myslug Title", "artist": "Myslug",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )
    with caplog.at_level(logging.INFO, logger=identify_stage.__name__):
        identify_stage.run(tmp_path / "myslug-title.mp3", cache_dir)

    matching = [r for r in caplog.records if "identify: slug=" in r.getMessage()]
    assert matching
    msg = matching[0].getMessage()
    assert "slug=myslug" in msg
    assert "source=acoustid" in msg
    assert "mbid=rec-1" in msg


# ----------------------------------------------------------------------------
# Raw AcoustID JSON cache
# ----------------------------------------------------------------------------

def test_raw_acoustid_response_cached(monkeypatch, tmp_path):
    """A successful AcoustID query persists .acoustid_raw.json."""
    cache_dir = tmp_path / "myslug"
    cache_dir.mkdir()
    _patch_fpcalc_ok(monkeypatch, tmp_path, fingerprint="AQADtest_fingerprint")

    raw = _fake_acoustid_response([
        {
            "id": "ac-1", "score": 0.92,
            "recordings": [{"id": "rec-1", "duration": 200}],
        },
    ])
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: {
        "mbid_recording": "rec-1",
        "acoustid_score": 0.92,
        "acoustid_id": "ac-1",
        "raw_response": raw,
    })
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    raw_path = cache_dir / ".acoustid_raw.json"
    assert raw_path.exists(), "expected .acoustid_raw.json sidecar"
    data = json.loads(raw_path.read_text())
    assert data["response"] == raw
    assert "queried_at" in data
    assert "fingerprint_hash" in data
    assert len(data["fingerprint_hash"]) == 12

    # The raw payload must NOT leak into identify.json — it's already saved.
    main = json.loads((cache_dir / "identify.json").read_text())
    assert "raw_response" not in main
