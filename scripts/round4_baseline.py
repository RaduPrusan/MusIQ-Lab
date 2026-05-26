"""Generate round-4-baseline.json by walking every cache/<slug>/identify.json.

Shape mirrors round-2-baseline.json (schema=1) but extended with R4 fields.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
CACHE = REPO / "cache"
OUT = REPO / "docs" / "superpowers" / "identify-overhaul" / "round-4-baseline.json"


def main() -> None:
    slugs = []
    identified_count = 0
    for d in sorted(CACHE.iterdir()):
        if not d.is_dir():
            continue
        p = d / "identify.json"
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            slugs.append({"slug": d.name, "error": f"unreadable: {exc}"})
            continue
        rec = {
            "slug": d.name,
            "identified": bool(data.get("identified")),
            "source": data.get("source"),
            "match_method": data.get("match_method"),
            "mbid_recording": data.get("mbid_recording"),
            "title": data.get("title"),
            "artist": data.get("artist"),
            "album": data.get("album"),
            "year": data.get("year"),
            "reason": (data.get("reason") or "")[:200],
            "score": data.get("score"),
            "duration_variance_pct": data.get("duration_variance_pct"),
            "title_similarity": data.get("title_similarity"),
            "schema_version": data.get("schema_version"),
            "has_acoustid_raw": (d / ".acoustid_raw.json").is_file(),
            "has_acoustid_stripped_raw": (d / ".acoustid_stripped_raw.json").is_file(),
        }
        if rec["identified"]:
            identified_count += 1
        slugs.append(rec)

    payload = {
        "schema": 1,
        "round": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(CACHE),
        "slug_count": len(slugs),
        "identified_count": identified_count,
        "slugs": slugs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} (slugs={len(slugs)}, identified={identified_count})")


if __name__ == "__main__":
    main()
