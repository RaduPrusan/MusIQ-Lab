#!/usr/bin/env bash
# Bootstrap MusIQ-Lab from a freshly reset (or freshly installed) WSL distribution.
# Wraps Phases 1, 2, 3, 4 of prompts/test-stack-torch27.md into one idempotent run.
#
# Usage from inside WSL:
#   cd "<PROJECT_WSL_PATH>"
#   ./scripts/bootstrap-wsl.sh [--force]
#
# Usage from PowerShell:
#   wsl -- bash "<PROJECT_WSL_PATH>/scripts/bootstrap-wsl.sh"
#
# Phases:
#   1. apt deps (build-essential, ffmpeg, libsndfile, vamp, ...)
#   2. uv (if missing) + Python 3.11 (if missing)
#   3. setup-venv.sh — Torch 2.7/cu126 + the MIR stack (delegated)
#   4. Prewarm model checkpoints (audio-separator, beat-this, torchfcpe, basic-pitch)
#
# Idempotent. Each phase short-circuits if its work is already done.
# --force: passes through to setup-venv.sh, which rebuilds .venv from scratch.
# Safe to run on a healthy stack; serves as a "verify everything is here" pass.

set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ "$(uname -s)" != "Linux" ]; then
  echo "ERROR: this script must run inside Linux/WSL, not $(uname -s)." >&2
  echo "       Invoke from PowerShell as:" >&2
  echo "         wsl -- bash \"<PROJECT_WSL_PATH>/scripts/bootstrap-wsl.sh\"" >&2
  exit 1
fi

# Belt-and-braces: even on a Linux uname, refuse to run outside WSL2 — the
# stack is locked against WSL2 + Python 3.11 + Torch 2.7/cu126 and the venv
# under .venv/ is path-rewritten against /mnt/<drive>/ host bind-mounts.
if ! { [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qiE "microsoft|WSL" /proc/version 2>/dev/null; }; then
  echo "ERROR: kernel does not look like WSL2 (no WSL_DISTRO_NAME, no microsoft tag in /proc/version)." >&2
  echo "       This script is intended for WSL2 Ubuntu only. Aborting." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ─── Phase 1: apt dependencies ───────────────────────────────────────────────

APT_PKGS=(
  build-essential cmake pkg-config
  libsndfile1-dev libsamplerate0-dev libfftw3-dev
  sox vamp-plugin-sdk vamp-examples ffmpeg
)

missing=()
for p in "${APT_PKGS[@]}"; do
  dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done

if [ "${#missing[@]}" -eq 0 ]; then
  echo "==> Phase 1: apt deps already installed (${#APT_PKGS[@]} packages)"
else
  echo "==> Phase 1: installing missing apt packages: ${missing[*]}"
  echo "    (sudo will prompt for your password)"
  sudo -v
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
fi

# ─── Phase 2: uv + Python 3.11 ───────────────────────────────────────────────

# Pick up uv if a previous install added it
if [ -f "$HOME/.local/bin/env" ]; then
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
fi

if command -v uv >/dev/null 2>&1; then
  echo "==> Phase 2: uv already installed ($(uv --version))"
else
  echo "==> Phase 2: installing uv via the official installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env"
fi

if uv python list --only-installed 3.11 2>/dev/null | grep -q "cpython-3.11"; then
  echo "    Python 3.11 already managed by uv"
else
  echo "    installing Python 3.11 via uv"
  uv python install 3.11
fi

# ─── Phase 3: venv + stack (delegated) ───────────────────────────────────────

echo "==> Phase 3: setup-venv.sh"
if [ "$FORCE" -eq 1 ]; then
  bash "$SCRIPT_DIR/setup-venv.sh" --force
else
  bash "$SCRIPT_DIR/setup-venv.sh"
fi

# ─── Phase 4: prewarm model checkpoints ──────────────────────────────────────

echo "==> Phase 4: prewarming model checkpoints"
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.venv/bin/activate"

# audio-separator stem models
# (these go to /tmp/audio-separator-models/ by default — wiped on reboot, so
# Phase 4 re-runs after a host reboot will re-download them; that's expected.)
echo "    audio-separator: BS-Roformer + htdemucs_6s"
audio-separator --download_model_only --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt >/dev/null
audio-separator --download_model_only --model_filename htdemucs_6s.yaml >/dev/null

# beat-this: hf hub cache under ~/.cache/huggingface/, persistent across reboots
echo "    beat-this final0"
python - <<'PY'
from beat_this.inference import File2Beats
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
File2Beats(checkpoint_path="final0", device=device)
print("      OK")
PY

# torchfcpe bundled model: ~/.cache/torch/, persistent
echo "    torchfcpe bundled"
python - <<'PY'
from torchfcpe import spawn_bundled_infer_model
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
spawn_bundled_infer_model(device=device)
print("      OK")
PY

# basic-pitch: ships its model inside the package, no download needed
echo "    basic-pitch ICASSP_2022 (bundled)"
python - <<'PY'
from basic_pitch.inference import predict  # noqa: F401
from basic_pitch import ICASSP_2022_MODEL_PATH
print(f"      OK ({ICASSP_2022_MODEL_PATH.name})")
PY

echo
echo "==> Bootstrap complete."
echo "    activate the venv with:  source .venv/bin/activate"
echo "    run the validation runbook stages from .research/stage*.sh"
