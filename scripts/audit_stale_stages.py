"""Read-only staleness audit: report which cached tracks have stale STAGE
outputs (per the current per-stage SCHEMA_VERSION / DEFAULT_PARAMS), WITHOUT
re-running anything.

This is the planning half of rerun_stale.py with the execution removed — it
reuses that module's exact staleness definition (stage_table / stage_is_stale
/ COUPLING) so the answer matches what an actual rerun would target. `cached()`
checks are pure sidecar I/O + version comparison; no GPU, no writes.

Essentia is intentionally excluded (gaia2 unavailable on the PyPI build), same
as rerun_stale.py, so it is never falsely flagged stale.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# scripts/ dir (for rerun_stale) + project root (for analyze.*).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rerun_stale import (  # noqa: E402
    CACHE,
    COUPLING,
    slug_stems_quality,
    stage_is_stale,
    stage_table,
)


def main() -> int:
    if not CACHE.is_dir():
        print(f"no cache dir at {CACHE.resolve()}")
        return 1
    slugs = sorted(p.name for p in CACHE.iterdir() if p.is_dir())

    stale_by_stage: Counter = Counter()
    tracks_with_stale: list[tuple[str, list[str]]] = []
    no_mp3: list[str] = []

    for slug in slugs:
        d = CACHE / slug
        if not list(d.glob("*.mp3")):
            no_mp3.append(slug)
        quality = slug_stems_quality(d)
        stale: set[str] = set()
        for name, mod, extra in stage_table(quality):
            if stage_is_stale(d, name, mod, extra):
                stale.add(name)
        for src, deps in COUPLING.items():
            if src in stale:
                stale.update(deps)
        if stale:
            tracks_with_stale.append((slug, sorted(stale)))
            for s in stale:
                stale_by_stage[s] += 1

    print("=== stale-stage audit (READ-ONLY; nothing re-run) ===")
    print(f"cached tracks:                {len(slugs)}")
    print(f"tracks with >=1 stale stage:  {len(tracks_with_stale)}")
    print(f"tracks fully fresh:           {len(slugs) - len(tracks_with_stale)}")
    if no_mp3:
        print(f"tracks missing mp3 (cannot reanalyze): {len(no_mp3)} -> {no_mp3}")
    print()
    print("stale count by stage (how many tracks each stage is stale on):")
    if stale_by_stage:
        for stage, n in stale_by_stage.most_common():
            print(f"  {stage:<28} {n}")
    else:
        print("  (none — every stage is fresh on every track)")
    print()
    if tracks_with_stale:
        print("per-track stale stages:")
        for slug, stale in tracks_with_stale:
            print(f"  {slug[:55]:<55} -> {stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
