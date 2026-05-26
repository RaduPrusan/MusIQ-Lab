#!/usr/bin/env bash
# Idempotent bootstrap for the MusIQ-Lab music-analysis venv.
# Mirrors Phase 3 of prompts/test-stack-torch27.md.
#
# Usage from PowerShell:
#   wsl -- bash "<PROJECT_WSL_PATH>/scripts/setup-venv.sh" [--force]
#
# Usage from inside WSL (with cwd = project root):
#   ./scripts/setup-venv.sh [--force]
#
# Behavior:
#   - If .venv/ exists and looks healthy, exits 0 without changes.
#   - If .venv/ is missing (or --force is given), creates it and installs the full stack.
#   - On install failure, leaves install-logs/ in place for diagnosis and exits non-zero.

set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Resolve project root as the parent of this script's directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

VENV="$PROJECT_ROOT/.venv"
LOGS="$PROJECT_ROOT/install-logs"

# --- short-circuit: idempotent skip if .venv already looks healthy ---

healthy_venv() {
  [ -x "$VENV/bin/python" ] && [ -f "$VENV/pyvenv.cfg" ]
}

if healthy_venv && [ "$FORCE" -eq 0 ]; then
  echo "==> .venv/ already present at $VENV — skipping (pass --force to rebuild)"
  "$VENV/bin/python" --version
  exit 0
fi

if [ "$FORCE" -eq 1 ] && [ -d "$VENV" ]; then
  echo "==> --force given, removing existing .venv/"
  rm -rf "$VENV"
fi

# --- prerequisites ---

if [ -f "$HOME/.local/bin/env" ]; then
  # uv installs this shim that puts ~/.local/bin on PATH
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is not on PATH. Install it first (https://docs.astral.sh/uv/)." >&2
  exit 1
fi

for f in requirements-linux-cu126.txt constraints-torch27-cu126.txt; do
  if [ ! -f "$PROJECT_ROOT/$f" ]; then
    echo "ERROR: missing $f in project root — Phase 3.2 of the runbook must have produced it." >&2
    exit 1
  fi
done

mkdir -p "$LOGS"

# --- 3.1 venv ---

echo "==> creating venv at $VENV with Python 3.11"
uv venv --python 3.11 --seed --clear .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python --version

# --- 3.3 Torch 2.7 / cu126 ---

echo "==> bootstrap pip/setuptools/wheel/cython (setuptools<81 keeps pkg_resources alive)"
python -m pip install --upgrade pip "setuptools<81" wheel cython 2>&1 | tee "$LOGS/00-bootstrap.log"

echo "==> installing Torch 2.7.1 / torchvision 0.22.1 / torchaudio 2.7.1 (cu126)"
python -m pip install \
  torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 \
  --index-url https://download.pytorch.org/whl/cu126 \
  2>&1 | tee "$LOGS/01-torch-cu126.log"

python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda)
assert torch.__version__.startswith("2.7.1"), torch.__version__
assert torch.cuda.is_available(), "CUDA not available"
print(torch.cuda.get_device_name(0))
PY

# --- 3.4 the rest of the stack ---

echo "==> installing requirements-linux-cu126.txt (constrained)"
python -m pip install -c constraints-torch27-cu126.txt -r requirements-linux-cu126.txt \
  2>&1 | tee "$LOGS/03-requirements.log"

echo "==> installing basic-pitch[onnx] with --no-deps (avoid TensorFlow pull)"
python -m pip install --no-deps "basic-pitch[onnx]" \
  2>&1 | tee "$LOGS/04-basic-pitch-nodeps.log"

echo "==> pip check (allowing only the intentional basic-pitch TF metadata complaint)"
set +e
python -m pip check 2>&1 | tee "$LOGS/05-pip-check.log"
pip_check_status=${PIPESTATUS[0]}
set -e
if [ "$pip_check_status" -ne 0 ]; then
  unexpected="$(grep -v -E "^basic-pitch .* requires tensorflow" "$LOGS/05-pip-check.log" || true)"
  if [ -n "$unexpected" ]; then
    echo "pip check reported unexpected issues:" >&2
    echo "$unexpected" >&2
    exit "$pip_check_status"
  fi
  echo "(ignored: basic-pitch TF metadata; ONNX path is installed intentionally without TF)"
fi

# --- 3.5 import verify + lock ---

echo "==> verifying imports"
python - <<'PY'
import importlib
import torch

print("torch:", torch.__version__, "| CUDA build:", torch.version.cuda)
assert torch.__version__.startswith("2.7.1"), torch.__version__
assert torch.cuda.is_available(), "CUDA not available"
print("GPU:", torch.cuda.get_device_name(0))
print("VRAM free GB:", round(torch.cuda.mem_get_info()[0] / 1e9, 1))

modules = [
    ("numpy", "__version__"),
    ("torch", "__version__"),
    ("torchaudio", "__version__"),
    ("librosa", "__version__"),
    ("soundfile", None),
    ("jams", "__version__"),
    ("madmom", None),
    ("lv_chordia", None),
    ("torchfcpe", None),
    ("pesto", None),
    ("audio_separator", None),
    ("demucs", None),
    ("beat_this", None),
    ("skey", None),
    ("basic_pitch", None),
    ("basic_pitch.inference", None),
    ("onnxruntime", "__version__"),
]

failed = []
for name, attr in modules:
    try:
        mod = importlib.import_module(name)
        value = getattr(mod, attr, "OK") if attr else "OK"
        print(f"OK {name}: {value}")
    except Exception as exc:
        failed.append((name, type(exc).__name__, str(exc)[:200]))

if failed:
    print("FAILED IMPORTS:")
    for row in failed:
        print(row)
    raise SystemExit(1)
PY

echo "==> writing requirements.lock"
python -m pip freeze > requirements.lock
echo "    $(wc -l < requirements.lock) packages locked"

echo
echo "==> .venv ready at $VENV"
echo "    activate with:  source .venv/bin/activate"
