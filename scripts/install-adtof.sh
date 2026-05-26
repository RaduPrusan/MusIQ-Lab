#!/usr/bin/env bash
# Install ADTOF (from GitHub — not published on PyPI) into the project venv
# and verify the package imports.
#
# ADTOF depends on TensorFlow (not PyTorch), so there is no Torch version
# conflict. TensorFlow 2.21.0 is already present in this venv (pulled in by
# other deps). The risk flagged in the WI-4 spec (Torch < 2.7 conflict) did
# not materialise — ADTOF is TF-based, not Torch-based.
#
# If pip resolution fails for any reason, this script exits 1 immediately and
# reports BLOCKED — it does NOT attempt workarounds without instruction.
#
# Idempotent — re-running is safe; pip skips already-installed packages.
set -euo pipefail

# Resolve project root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Activating venv: ${PROJECT_ROOT}/.venv"
# shellcheck source=/dev/null
source "${PROJECT_ROOT}/.venv/bin/activate"

# adtof is NOT on PyPI — install from upstream GitHub.
# Torch conflict risk: not applicable (ADTOF uses TensorFlow, not Torch).
ADTOF_URL="git+https://github.com/MZehren/ADTOF.git"

echo "==> Installing adtof from ${ADTOF_URL}..."
# Capture pip output so we can surface the conflict message clearly.
PIP_OUT="$(mktemp)"
if ! pip install "${ADTOF_URL}" 2>&1 | tee "$PIP_OUT"; then
    echo "" >&2
    echo "!! FAIL: adtof install failed. pip output (last 40 lines):" >&2
    tail -40 "$PIP_OUT" >&2
    echo "" >&2
    echo "!! BLOCKED: Investigate the pip error above before retrying." >&2
    echo "!! Options if dep conflict:" >&2
    echo "!!   (1) Fork ADTOF and patch its dependency declarations." >&2
    echo "!!   (2) Install in a sub-venv (.venv-adtof) and shell out from drums.py." >&2
    rm -f "$PIP_OUT"
    exit 1
fi
rm -f "$PIP_OUT"

echo "==> Smoke test: verify adtof is importable..."
python - <<'PY'
import importlib
m = importlib.import_module("adtof")
version = getattr(m, "__version__", "?")
print(f"OK: ADTOF {version} importable.")
PY

echo "==> Verifying Torch version was not downgraded..."
python - <<'PY'
import torch
v = torch.__version__
print(f"Torch version post-install: {v}")
if not v.startswith("2.7"):
    raise RuntimeError(
        f"FAIL: Torch version changed to {v}! adtof install must have downgraded Torch. "
        "Investigate and restore torch==2.7.1+cu126 before proceeding."
    )
print("OK: Torch 2.7 preserved.")
PY

echo "==> OK: ADTOF is installed, importable, and Torch 2.7 is intact."
