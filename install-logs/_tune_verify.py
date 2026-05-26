"""Re-evaluate the per-stem gate decisions on existing summaries against the
NEW thresholds, without re-running the pipeline. The raw signal values are
already in summary.json under stems.<name>.presence, so we just re-apply the
boolean rule.
"""
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / "cache"

# Parse threshold constants out of stem_presence.py with a regex so this script
# always reflects the current tuned values without dragging in the full
# pipeline's heavy deps (pretty_midi, scipy — only in the WSL venv).
import re
_src = (Path(__file__).parent.parent / "analyze" / "derived" / "stem_presence.py").read_text(encoding="utf-8")
def _read_const(name: str) -> float:
    m = re.search(rf"^{name}\s*:\s*float\s*=\s*(-?\d+(?:\.\d+)?)", _src, re.MULTILINE)
    if m is None:
        raise RuntimeError(f"could not find {name} in stem_presence.py")
    return float(m.group(1))
MASKING_THRESHOLD_DB = _read_const("MASKING_THRESHOLD_DB")
ACTIVE_FRAME_RATIO_THRESHOLD = _read_const("ACTIVE_FRAME_RATIO_THRESHOLD")
IN_BAND_FRACTION_THRESHOLD = _read_const("IN_BAND_FRACTION_THRESHOLD")

print(f"Re-evaluating with: masking < {MASKING_THRESHOLD_DB} dB, "
      f"active < {ACTIVE_FRAME_RATIO_THRESHOLD}, "
      f"in_band < {IN_BAND_FRACTION_THRESHOLD}")
print()

flips_to_pass = []   # was suppressed, now passes
flips_to_gate = []   # was passing, now suppressed
unchanged_pass = []
unchanged_gate = []

for d in sorted(CACHE.iterdir()):
    if not d.is_dir():
        continue
    sj = d / f"{d.name}.summary.json"
    if not sj.exists():
        continue
    data = json.loads(sj.read_text(encoding="utf-8"))
    stems = data.get("stems", {})
    for stem_name in ("vocals", "bass", "guitar", "piano", "other"):
        info = stems.get(stem_name)
        if not isinstance(info, dict):
            continue
        pres = info.get("presence")
        if not pres:
            continue

        old_transcribed = bool(info.get("transcribed"))

        masking = pres.get("masking_ratio_db")
        active = pres.get("active_frame_ratio")
        in_band = pres.get("in_band_fraction")

        new_tripped = []
        if masking is not None and masking < MASKING_THRESHOLD_DB:
            new_tripped.append("masking")
        if active is not None and active < ACTIVE_FRAME_RATIO_THRESHOLD:
            new_tripped.append("active")
        if in_band is not None and in_band < IN_BAND_FRACTION_THRESHOLD:
            new_tripped.append("in_band")
        new_transcribed = len(new_tripped) == 0

        rec = (d.name, stem_name, masking, active, in_band, new_tripped)
        if old_transcribed and not new_transcribed:
            flips_to_gate.append(rec)
        elif not old_transcribed and new_transcribed:
            flips_to_pass.append(rec)
        elif new_transcribed:
            unchanged_pass.append(rec)
        else:
            unchanged_gate.append(rec)

def show(label, rows):
    print(f"=== {label} ({len(rows)}) ===")
    for slug, stem, m, a, ib, tripped in rows:
        print(f"  {slug[:50]:<50} {stem:<7}  mask={m}  act={a}  ib={ib}  tripped={tripped}")
    print()

show("WAS GATED, NOW PASSES (false-positive fixes)", flips_to_pass)
show("WAS PASSING, NOW GATED (regressions)", flips_to_gate)
show("UNCHANGED — still gated (true-absence rules)", unchanged_gate)
print(f"unchanged-pass: {len(unchanged_pass)} (omitted)")
