"""Dry-run survey: for every track in cache/, report which stages are stale.

Cheap — calls each stage's `cached()` which only reads the per-stage sidecar
(.params_<stage>.json or stems_6s/.params.json) and checks for output files.
No models load. Safe to run on the head node.

Output: per-track table + a "stale frequency" summary so we can see which
stages have drifted across the corpus.

Usage:
    .venv/bin/python scripts/survey_stale_stages.py
    .venv/bin/python scripts/survey_stale_stages.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit JSON instead of table")
    args = parser.parse_args()

    # Defer imports until after argparse to keep --help fast.
    from analyze import pipeline as pipeline_mod
    from analyze.stages import stems as stems_stage

    project_root = Path(__file__).resolve().parent.parent
    cache_root = project_root / "cache"

    # Stage extra kwargs — mirror what pipeline.analyze() threads through.
    # `stems` needs quality=DEFAULT to know which preset's sidecar to check.
    stage_kwargs: dict[str, dict] = {
        "stems": {"quality": stems_stage.DEFAULT_STEMS_QUALITY},
    }

    rows: list[dict] = []
    stale_counter: Counter = Counter()
    for cache_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
        slug = cache_dir.name
        # Skip dirs without a source MP3 — can't analyze something we don't have.
        mp3 = cache_dir / f"{slug}.mp3"
        has_mp3 = mp3.exists()

        stale: list[str] = []
        per_stage: dict[str, bool] = {}
        for name, module in pipeline_mod._STAGE_EXECUTION_ORDER:
            extra = stage_kwargs.get(name, {})
            try:
                fresh = module.cached(cache_dir, **extra)
            except Exception as e:  # treat probe failure as stale
                fresh = False
                per_stage[name] = False
                stale.append(f"{name}(probe-err:{type(e).__name__})")
                stale_counter[name] += 1
                continue
            per_stage[name] = bool(fresh)
            if not fresh:
                stale.append(name)
                stale_counter[name] += 1

        rows.append({
            "slug": slug,
            "has_mp3": has_mp3,
            "stale_count": len(stale),
            "stale": stale,
            "per_stage": per_stage,
        })

    if args.json:
        json.dump({"tracks": rows, "stale_frequency": stale_counter.most_common()},
                  sys.stdout, indent=2)
        return 0

    # Pretty table.
    all_stage_names = [n for n, _ in pipeline_mod._STAGE_EXECUTION_ORDER]
    print(f"\n{len(rows)} tracks in cache; {len(all_stage_names)} stages per track.\n")

    n_clean = sum(1 for r in rows if r["stale_count"] == 0 and r["has_mp3"])
    n_no_mp3 = sum(1 for r in rows if not r["has_mp3"])
    n_dirty = len(rows) - n_clean - n_no_mp3
    print(f"  Fully fresh:     {n_clean}")
    print(f"  Has stale stages: {n_dirty}")
    print(f"  Missing MP3 (cannot re-run): {n_no_mp3}")

    print("\nStale-frequency across all tracks (which stage is stale most often):")
    for name, count in stale_counter.most_common():
        if count:
            print(f"  {name:30s}  {count:3d} / {len(rows)} tracks")

    print("\nPer-track stale list (missing-mp3 tracks shown last):")
    for r in sorted(rows, key=lambda x: (not x["has_mp3"], -x["stale_count"], x["slug"])):
        flag = " " if r["has_mp3"] else "X"
        if r["stale_count"] == 0:
            print(f"  [{flag}] {r['slug']:80s}  (fresh)")
        else:
            print(f"  [{flag}] {r['slug']:80s}  stale: {', '.join(r['stale'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
