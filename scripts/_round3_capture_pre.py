"""Capture pre-Round-3 state of every cache/<slug>/identify.json.

Snapshots: slug, identified, mbid_recording, title, artist, reason, score.
Output: docs/superpowers/identify-overhaul/round-3-pre-state.json
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "cache"
OUT = REPO / "docs" / "superpowers" / "identify-overhaul" / "round-3-pre-state.json"


def main() -> None:
    slugs = []
    identified_count = 0
    for d in sorted(p for p in CACHE.iterdir() if p.is_dir()):
        ij = d / "identify.json"
        if not ij.exists():
            continue
        try:
            data = json.loads(ij.read_text())
        except json.JSONDecodeError:
            data = {}
        rec = {
            "slug": d.name,
            "identified": bool(data.get("identified")),
            "mbid_recording": data.get("mbid_recording"),
            "title": data.get("title"),
            "artist": data.get("artist"),
            "reason": data.get("reason"),
            "score": data.get("acoustid_score"),
        }
        slugs.append(rec)
        if rec["identified"]:
            identified_count += 1
    payload = {
        "schema": 1,
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "+00:00",
        "cache_dir": str(CACHE),
        "slug_count": len(slugs),
        "identified_count": identified_count,
        "slugs": slugs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT} — {len(slugs)} slugs, {identified_count} identified")


if __name__ == "__main__":
    main()
