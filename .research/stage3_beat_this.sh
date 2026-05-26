#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os
from beat_this.inference import File2Beats

model = File2Beats(checkpoint_path="final0", device="cuda")
beats, downbeats = model(os.environ["TEST_MP3"])
out = {
    "beats": [float(t) for t in beats],
    "downbeats": [float(t) for t in downbeats],
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_beats": [round(float(t), 3) for t in beats[:8]],
    "first_8_downbeats": [round(float(t), 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "beat_this.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["n_beats", "n_downbeats", "first_8_beats", "first_8_downbeats"]}, indent=2))
PY
