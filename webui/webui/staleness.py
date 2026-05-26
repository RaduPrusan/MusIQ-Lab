"""Read-only staleness probe for analyzed tracks.

Walks cache/<slug>/ and reports which analyze stages are stale relative to
the manifest. "Stale" means the stage's output is present but its
sidecar/embedded version says it was produced by an older schema or with
different params — i.e. `cached()` would return False if the pipeline ran
again. This module never invokes WSL; it's pure file I/O + JSON compare.

Three statuses per stage:
    "fresh"   — output present, version + params match manifest
    "stale"   — output present, version OR params disagree with manifest
    "skipped" — no output and no sidecar (optional stage didn't run)

Only "stale" stages should drive the small re-analyze button on the
library row. "skipped" optional stages are deliberately left alone (the
user might have chosen to skip drums by not installing LarsNet, etc.).

Required stages on a never-fully-analyzed cache could in principle be
"skipped" too, but in practice we only reach this code via /api/tracks,
which already filters to slugs that have a summary.json — so all required
stages will have outputs.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from . import stage_manifest

log = logging.getLogger(__name__)


# Memoize stale lists by (cache mtime tuple). Cleared whenever the summary
# changes (the same trigger tracks.py uses) — populated lazily, capped by
# the natural cache size (~one entry per analyzed track).
_cache: dict[str, tuple[tuple[int, ...], list[str]]] = {}


def _read_sidecar(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _stage_status(cache_dir: Path, entry: dict[str, Any]) -> str:
    """Return 'fresh' | 'stale' | 'skipped' for one manifest entry."""
    canonical_paths = [cache_dir / c for c in entry["canonical"]]
    has_output = all(p.exists() for p in canonical_paths)

    if entry.get("version_kind") == "embedded_json":
        # Drums-style: version key inside the canonical JSON itself. If the
        # file is missing it's skipped (or absent for required stages);
        # if the embedded version is older it's stale.
        if not has_output:
            return "skipped" if entry.get("optional") else "stale"
        canonical = canonical_paths[0]
        data = _read_sidecar(canonical)
        if not isinstance(data, dict):
            # Can't read the file but it exists — treat as stale so a
            # rerun rewrites it.
            return "stale"
        on_disk_version = data.get(entry.get("version_key", "version"), 0)
        return "fresh" if on_disk_version >= entry["schema_version"] else "stale"

    # Sidecar-style stages (the common case).
    sidecar_path = cache_dir / entry["sidecar"]
    has_sidecar = sidecar_path.is_file()

    if not has_output and not has_sidecar:
        return "skipped" if entry.get("optional") else "stale"
    if has_output and not has_sidecar:
        # Pre-sidecar cache: the analyze package's cached() also returns
        # False here (no sidecar to compare against), so we surface as
        # stale and let the rerun lay down the sidecar.
        return "stale"
    sidecar = _read_sidecar(sidecar_path)
    if not isinstance(sidecar, dict):
        return "stale"  # corrupt sidecar — easier to rerun than to recover
    if sidecar.get("schema_version") != entry["schema_version"]:
        return "stale"
    expected_params = entry.get("params")
    if expected_params is not None and sidecar.get("params") != expected_params:
        return "stale"
    if not has_output:
        # Sidecar says we ran but the output is gone (manually deleted?).
        # Same disposition as a sidecar mismatch — rerun.
        return "stale"
    return "fresh"


def _cache_key(cache_dir: Path) -> tuple[int, ...]:
    """Compose a mtime tuple over every file we read so a change to any of
    them invalidates the memoized stale list. Cheap: at most ~25 stats per
    cache dir."""
    parts: list[int] = []
    for entry in stage_manifest.STAGES:
        for c in entry["canonical"]:
            p = cache_dir / c
            try:
                parts.append(p.stat().st_mtime_ns)
            except OSError:
                parts.append(0)
        sidecar = entry.get("sidecar")
        if sidecar:
            try:
                parts.append((cache_dir / sidecar).stat().st_mtime_ns)
            except OSError:
                parts.append(0)
    return tuple(parts)


def stale_stages(cache_dir: Path) -> list[str]:
    """List of stage names that are stale for this cache. Empty when fresh.

    Optional stages that never ran (no output AND no sidecar) are NOT
    included — they're "skipped", not "stale". The UI only acts on
    stale stages.
    """
    if not cache_dir.is_dir():
        return []
    slug = cache_dir.name
    key = _cache_key(cache_dir)
    cached = _cache.get(slug)
    if cached and cached[0] == key:
        return cached[1]
    t0 = time.monotonic()
    stale: list[str] = []
    for entry in stage_manifest.STAGES:
        if _stage_status(cache_dir, entry) == "stale":
            stale.append(entry["name"])
    elapsed_ms = (time.monotonic() - t0) * 1000
    if elapsed_ms > 10:  # only log when the probe is slow
        log.debug("staleness probe for %s: %d stale, %.1f ms", slug, len(stale), elapsed_ms)
    _cache[slug] = (key, stale)
    return stale
