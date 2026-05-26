#!/usr/bin/env python3
"""Round 2 baseline snapshot — capture every cache/<slug>/identify.json state.

Writes docs/superpowers/identify-overhaul/round-2-baseline.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKTREE = PROJECT_ROOT
CACHE_DIR = PROJECT_ROOT / "cache"
OUT = WORKTREE / "docs" / "superpowers" / "identify-overhaul" / "round-2-baseline.json"


def _read_sidecar_version(cache_dir: Path) -> int | None:
    sc = cache_dir / "identify.sidecar.json"
    if not sc.is_file():
        return None
    try:
        return json.loads(sc.read_text(encoding="utf-8")).get("schema_version")
    except Exception:
        return None


def main() -> None:
    slugs = []
    for d in sorted(CACHE_DIR.iterdir()):
        if not d.is_dir():
            continue
        p = d / "identify.json"
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            slugs.append({"slug": d.name, "error": f"read failed: {e}"})
            continue
        slugs.append({
            "slug": d.name,
            "identified": bool(data.get("identified", False)),
            "mbid_recording": data.get("mbid_recording"),
            "title": data.get("title"),
            "artist": data.get("artist"),
            "reason": data.get("reason"),
            "score": data.get("acoustid_score"),
            "schema_version": _read_sidecar_version(d),
            "has_acoustid_raw": (d / ".acoustid_raw.json").is_file(),
        })
    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(CACHE_DIR),
        "slug_count": len(slugs),
        "identified_count": sum(1 for s in slugs if s.get("identified")),
        "slugs": slugs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  slug_count={payload['slug_count']}")
    print(f"  identified_count={payload['identified_count']}")


if __name__ == "__main__":
    main()
