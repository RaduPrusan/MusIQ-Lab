"""Survey post-gate summaries: per-stem gate decisions and signal values.

Usage:  python install-logs/_tune_survey.py
"""
import json
import datetime
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / "cache"

rows = []
for d in CACHE.iterdir():
    if not d.is_dir():
        continue
    s = d / f"{d.name}.summary.json"
    if s.exists():
        rows.append((s.stat().st_mtime, d.name, s))

rows.sort(reverse=True)

print(f"{'mtime':<20} {'slug':<60} has_presence")
print("-" * 100)
fresh = []
for m, n, s in rows:
    raw = s.read_text(encoding="utf-8")
    has = '"presence"' in raw
    when = datetime.datetime.fromtimestamp(m).isoformat(timespec="seconds")
    short = n[:58]
    print(f"{when:<20} {short:<60} {has}")
    if has:
        fresh.append((m, n, s))

print()
print(f"=== {len(fresh)} summaries have presence field ===")
print()

for m, n, s in fresh:
    data = json.loads(s.read_text(encoding="utf-8"))
    stems = data.get("stems", {})
    print(f"\n>>> {n}")
    for stem_name in ("vocals", "bass", "guitar", "piano", "other"):
        info = stems.get(stem_name, {})
        if not isinstance(info, dict):
            continue
        transcribed = info.get("transcribed")
        n_notes = len(info.get("notes") or [])
        pres = info.get("presence")
        if pres:
            ratio = pres.get("masking_ratio_db")
            active = pres.get("active_frame_ratio")
            inband = pres.get("in_band_fraction")
            tripped = pres.get("gates_tripped") or []
            print(
                f"  {stem_name:<7} transcribed={transcribed}  notes={n_notes:>5}  "
                f"masking={ratio}  active={active}  in_band={inband}  tripped={tripped}"
            )
        else:
            print(f"  {stem_name:<7} transcribed={transcribed}  notes={n_notes:>5}  (no presence)")
