#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

python - <<'PY'
import json, os
out = {
    "status": "deferred",
    "reason": "No segmenter installed in this stack; allin1 dropped due to NATTEN ABI/API breakage.",
}
with open(os.path.join(os.environ["TEST_DIR"], "sections.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
PY
