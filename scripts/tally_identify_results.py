"""One-shot summary of identify.json across the cache."""
from __future__ import annotations
import json
from pathlib import Path

cache = Path(__file__).resolve().parent.parent / "cache"
identified, unidentified, missing = [], [], []
for d in sorted(p for p in cache.iterdir() if p.is_dir()):
    p = d / "identify.json"
    if not p.exists():
        missing.append(d.name); continue
    data = json.loads(p.read_text())
    if data.get("identified"):
        identified.append((d.name, data.get("title"), data.get("artist")))
    else:
        unidentified.append((d.name, data.get("reason")))

print(f"IDENTIFIED ({len(identified)} tracks):")
for s, t, a in identified:
    print(f"  {s[:64]:64s}  -> {a!r:32s}  {t!r}")
print(f"\nUNIDENTIFIED ({len(unidentified)} tracks):")
for s, r in unidentified:
    print(f"  {s[:64]:64s}  -> {r}")
if missing:
    print(f"\nNO identify.json ({len(missing)} tracks):")
    for s in missing:
        print(f"  {s}")
