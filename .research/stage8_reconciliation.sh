#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os

test_dir = os.environ["TEST_DIR"]
madmom_data = json.load(open(os.path.join(test_dir, "madmom_downbeats.json")))
chords = json.load(open(os.path.join(test_dir, "chords.json")))
key_data = json.load(open(os.path.join(test_dir, "skey.json")))

downbeats = madmom_data["downbeats"]
if not downbeats:
    raise SystemExit("No downbeats available for snapping")

def nearest_downbeat(t):
    return min(downbeats, key=lambda d: abs(d - t))

summary = {
    "key": key_data["key"],
    "key_source": key_data["source"],
    "tempo_bpm": madmom_data["bpm"],
    "first_12_chords_snapped": [],
}
for chord in chords[:12]:
    summary["first_12_chords_snapped"].append({
        "snap_start": round(nearest_downbeat(chord["start"]), 3),
        "original_start": round(chord["start"], 3),
        "label": chord["label"],
    })

with open(os.path.join(test_dir, "reconciliation_preview.json"), "w") as f:
    json.dump(summary, f, indent=2)
print(json.dumps(summary, indent=2))
PY
