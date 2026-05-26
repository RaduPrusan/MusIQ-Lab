"""Per-stage parameter sidecar — generalizes the pattern stems already uses.

Every stage that takes parameters writes its resolved params to a sidecar
on the cache after a successful run, and checks the sidecar inside cached().
A sidecar mismatch (different params, different schema_version, or absent)
means cached() returns False and the stage re-runs.

Schema version is per-stage. Bump in the stage module when:
  - Param defaults change in code
  - Param semantics change (a previously-unused field becomes consumed)
  - The sidecar format itself changes
  - Client picking logic or behavior changes — even if the cached payload
    shape is unchanged, a new walker / threshold / selector materially
    affects what gets written, so older caches are stale by definition

Writes are atomic: a sibling ``.tmp`` file is written then renamed via
``os.replace``. The temp file MUST be in the same directory as the
destination (NTFS rejects cross-volume replace with WinError 17).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Stages whose sidecar lives inside their own subdir (matching the existing
# stems convention at stems_6s/.params.json). All others use a top-level
# .params_<stage>.json next to the cache root, which is guaranteed unique.
_STAGE_TO_SUBDIR: dict[str, str] = {
    "stems": "stems_6s",
}


def _sidecar_path(cache_dir: Path, stage: str) -> Path:
    sub = _STAGE_TO_SUBDIR.get(stage)
    if sub:
        return cache_dir / sub / ".params.json"
    return cache_dir / f".params_{stage}.json"


def write(cache_dir: Path, stage: str, params: dict, *, schema_version: int) -> None:
    """Write the sidecar for `stage` after a successful run.

    Atomic: writes to ``<sidecar>.tmp`` in the SAME directory then
    ``os.replace`` swaps it into place. Same-directory is load-bearing on
    NTFS: cross-volume replace fails with ``OSError: [WinError 17]``.
    """
    path = _sidecar_path(cache_dir, stage)
    path.parent.mkdir(exist_ok=True, parents=True)
    payload = {"schema_version": schema_version, "params": params}
    # sort_keys for stable on-disk diffs; doesn't affect equality semantics.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, path)


def matches(
    cache_dir: Path,
    stage: str,
    expected_params: dict,
    *,
    expected_schema_version: int,
) -> bool:
    """True iff sidecar exists, schema_version matches, and params are equal."""
    path = _sidecar_path(cache_dir, stage)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if data.get("schema_version") != expected_schema_version:
        return False
    return data.get("params") == expected_params
