#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os

chords = None
errors = []

try:
    from lv_chordia.chord_recognition import chord_recognition
    raw = chord_recognition(os.environ["TEST_MP3"], chord_dict_name="submission")
    chords = [
        {
            "start": float(item.get("start_time", item.get("start", 0.0))),
            "end": float(item.get("end_time", item.get("end", 0.0))),
            "label": str(item.get("chord", item.get("label", "N"))),
        }
        for item in raw
    ]
except Exception as exc:
    errors.append(f"lv-chordia python API failed: {type(exc).__name__}: {exc}")

if chords is None:
    import subprocess
    out_path = os.path.join(os.environ["TEST_DIR"], "chords.lab")
    try:
        subprocess.run([
            "python", "-m", "lv_chordia",
            os.environ["TEST_MP3"],
            out_path,
            "--chord_dict", "submission",
        ], check=True)
        chords = []
        with open(out_path) as f:
            for line in f:
                s, e, label = line.strip().split("\t")
                chords.append({"start": float(s), "end": float(e), "label": label})
    except Exception as exc:
        errors.append(f"lv-chordia CLI failed: {type(exc).__name__}: {exc}")
        raise SystemExit("\n".join(errors)) from exc

with open(os.path.join(os.environ["TEST_DIR"], "chords.json"), "w") as f:
    json.dump(chords, f, indent=2)

print(f"Found {len(chords)} chord events")
for c in chords[:12]:
    print(f"{c['start']:7.2f}-{c['end']:7.2f}: {c['label']}")
if errors:
    print("Fallback notes:")
    for err in errors:
        print(err)
PY
