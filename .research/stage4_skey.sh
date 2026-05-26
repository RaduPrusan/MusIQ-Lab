#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os

key = conf = src = None
errors = []

try:
    from skey.key_detection import detect_key
    result = detect_key(os.environ["TEST_MP3"], device="cuda", cli=False)
    if result:
        key = result[0] if isinstance(result, list) else str(result)
        conf = 1.0
        src = "skey.detect_key"
except Exception as exc:
    errors.append(f"skey.detect_key failed: {type(exc).__name__}: {exc}")

if not key or key == "error":
    import librosa, numpy as np
    src = "librosa_ks"
    KS_MAJ = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
    KS_MIN = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
    notes = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
    y, sr = librosa.load(os.environ["TEST_MP3"], duration=120)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = max(
        [(notes[i] + ":" + mode, np.corrcoef(np.roll(chroma, -i), profile)[0, 1])
         for i in range(12) for mode, profile in [("major", KS_MAJ), ("minor", KS_MIN)]],
        key=lambda row: row[1],
    )
    key, conf = best[0], float(best[1])

out = {"key": str(key), "confidence": float(conf), "source": src, "errors": errors}
with open(os.path.join(os.environ["TEST_DIR"], "skey.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY
