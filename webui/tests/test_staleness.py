"""Unit tests for the staleness probe (webui/webui/staleness.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from webui import stage_manifest, staleness


def _write_sidecar(cache_dir: Path, sidecar_rel: str, *, schema_version: int, params: dict) -> None:
    p = cache_dir / sidecar_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": schema_version, "params": params}), encoding="utf-8")


def _entry(name: str) -> dict:
    e = stage_manifest.by_name(name)
    assert e is not None, name
    return e


def test_stale_stages_empty_for_unanalyzed_dir(tmp_path: Path):
    """A directory with no canonical files and no sidecars: optional stages
    return 'skipped' (not stale), required stages would be 'stale' — but the
    UI never lands here because /api/tracks filters to slugs with summary.json."""
    cache_dir = tmp_path / "ghost"
    # Don't even create the dir.
    assert staleness.stale_stages(cache_dir) == []


def test_stale_stages_empty_when_everything_fresh(tmp_path: Path):
    cache_dir = tmp_path / "fresh"
    cache_dir.mkdir()
    # Lay down all canonical files + matching sidecars for every manifest stage.
    for entry in stage_manifest.STAGES:
        for c in entry["canonical"]:
            target = cache_dir / c
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.get("version_kind") == "embedded_json":
                # Drums: version inside the JSON itself.
                target.write_text(json.dumps({entry["version_key"]: entry["schema_version"], "transcribed": True}), encoding="utf-8")
            elif c.endswith(".json"):
                target.write_text("{}", encoding="utf-8")
            elif c.endswith(".npz"):
                target.write_bytes(b"")
            else:
                # Treat as a directory marker (e.g. "dynamics").
                target.mkdir(exist_ok=True)
        if entry.get("sidecar"):
            params = entry.get("params") if entry.get("params") is not None else {}
            _write_sidecar(cache_dir, entry["sidecar"], schema_version=entry["schema_version"], params=params)
    assert staleness.stale_stages(cache_dir) == []


def test_stale_stages_flags_schema_bump(tmp_path: Path):
    """The bread-and-butter case: sidecar's schema_version is one older
    than the manifest's. Stage should be flagged as stale."""
    cache_dir = tmp_path / "v1_v2"
    cache_dir.mkdir()
    beats_entry = _entry("beats")
    # Canonical present.
    (cache_dir / beats_entry["canonical"][0]).write_text("{}", encoding="utf-8")
    # Sidecar with OLDER schema version.
    _write_sidecar(cache_dir, beats_entry["sidecar"],
                   schema_version=beats_entry["schema_version"] - 1, params={})
    stale = staleness.stale_stages(cache_dir)
    assert "beats" in stale


def test_stale_stages_flags_params_drift(tmp_path: Path):
    """Sidecar schema_version matches but params don't — also stale."""
    cache_dir = tmp_path / "params_drift"
    cache_dir.mkdir()
    vcc = _entry("vocal_consensus_contour")
    # Lay down canonical files.
    for c in vcc["canonical"]:
        (cache_dir / c).write_text("", encoding="utf-8")
    # Sidecar with right schema_version but missing one expected param.
    broken_params = dict(vcc["params"])
    broken_params.pop("viterbi_enabled")
    _write_sidecar(cache_dir, vcc["sidecar"],
                   schema_version=vcc["schema_version"], params=broken_params)
    stale = staleness.stale_stages(cache_dir)
    assert "vocal_consensus_contour" in stale


def test_stale_stages_optional_without_sidecar_is_skipped_not_stale(tmp_path: Path):
    """An optional stage with no sidecar and no output → user chose to skip
    it (e.g. drums without LarsNet). Don't flag it."""
    cache_dir = tmp_path / "skipped_drums"
    cache_dir.mkdir()
    # Lay down all REQUIRED stages so they don't pollute the assertion.
    for entry in stage_manifest.STAGES:
        if entry.get("optional"):
            continue
        for c in entry["canonical"]:
            target = cache_dir / c
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}" if c.endswith(".json") else "", encoding="utf-8")
        params = entry.get("params") if entry.get("params") is not None else {}
        if entry.get("sidecar"):
            _write_sidecar(cache_dir, entry["sidecar"],
                           schema_version=entry["schema_version"], params=params)
    # No drums files. Should not appear in stale.
    stale = staleness.stale_stages(cache_dir)
    assert "drums" not in stale


def test_stale_stages_flags_drums_embedded_version_bump(tmp_path: Path):
    """Drums stores its version inside drums_summary.json. An older value
    must be picked up as stale."""
    cache_dir = tmp_path / "drums_v1"
    cache_dir.mkdir()
    drums = _entry("drums")
    (cache_dir / drums["canonical"][0]).write_text(
        json.dumps({drums["version_key"]: 1, "transcribed": True}),
        encoding="utf-8",
    )
    stale = staleness.stale_stages(cache_dir)
    assert "drums" in stale


def test_stale_stages_legacy_cache_without_sidecar_is_stale(tmp_path: Path):
    """A pre-sidecar cache has the canonical output but no sidecar. cached()
    returns False on this, so we flag it as stale to drive a rerun that
    lays down the sidecar."""
    cache_dir = tmp_path / "legacy"
    cache_dir.mkdir()
    beats_entry = _entry("beats")
    (cache_dir / beats_entry["canonical"][0]).write_text("{}", encoding="utf-8")
    # No sidecar.
    stale = staleness.stale_stages(cache_dir)
    assert "beats" in stale


def test_stale_stages_memoizes_by_mtime(tmp_path: Path, monkeypatch):
    """Same mtime tuple → cached list returned, no recompute."""
    cache_dir = tmp_path / "memo"
    cache_dir.mkdir()
    # Trivial cache: just write one file to make _cache_key non-empty.
    beats_entry = _entry("beats")
    (cache_dir / beats_entry["canonical"][0]).write_text("{}", encoding="utf-8")
    # Prime the cache.
    first = staleness.stale_stages(cache_dir)
    call_count = {"n": 0}
    real = staleness._stage_status
    def tally(*a, **kw):
        call_count["n"] += 1
        return real(*a, **kw)
    monkeypatch.setattr(staleness, "_stage_status", tally)
    second = staleness.stale_stages(cache_dir)
    assert first == second
    assert call_count["n"] == 0, "memoization broken — _stage_status got called on cache hit"