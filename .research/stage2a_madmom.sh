#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os
import numpy as np
from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

mp3 = os.environ["TEST_MP3"]

activations = RNNDownBeatProcessor()(mp3)
tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
beats_with_pos = tracker(activations)

beats = [float(t) for t, _ in beats_with_pos]
downbeats = [float(t) for t, pos in beats_with_pos if int(pos) == 1]

if len(beats) >= 2:
    diffs = np.diff(beats)
    median_ibi = float(np.median(diffs))
    bpm = 60.0 / median_ibi if median_ibi > 0 else 0.0
else:
    bpm = 0.0

out = {
    "bpm": float(bpm),
    "beats": beats,
    "downbeats": downbeats,
    "n_beats": len(beats),
    "n_downbeats": len(downbeats),
    "first_8_downbeats": [round(t, 3) for t in downbeats[:8]],
}
with open(os.path.join(os.environ["TEST_DIR"], "madmom_downbeats.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps({k: out[k] for k in ["bpm", "n_beats", "n_downbeats", "first_8_downbeats"]}, indent=2))
PY
