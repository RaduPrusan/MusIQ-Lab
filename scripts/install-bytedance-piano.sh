#!/usr/bin/env bash
# Install piano_transcription_inference (ByteDance HR-Piano, PyPI) into the
# project venv and verify the model loads and runs inference on synthetic audio.
#
# The package downloads its weights (~165 MB) to its own user cache on first
# model instantiation — we don't fight that, the smoke test exercises it.
#
# Idempotent — re-running is safe; pip skips already-installed packages.
set -euo pipefail

# Resolve project root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Activating venv: ${PROJECT_ROOT}/.venv"
# shellcheck source=/dev/null
source "${PROJECT_ROOT}/.venv/bin/activate"

echo "==> Installing piano_transcription_inference>=0.0.6..."
pip install 'piano_transcription_inference>=0.0.6'

echo "==> Smoke test: load model, run inference on 1 s of silence..."
# Note: transcribe() takes a numpy float32 array at sample_rate (16000 Hz),
# NOT a file path. The model downloads its weights (~165 MB) to
# ~/piano_transcription_inference_data/ on first instantiation.
python - <<'PY'
import numpy as np
from piano_transcription_inference import PianoTranscription, sample_rate

# 1 second of silence at the model's expected sample rate (16000 Hz)
audio = np.zeros(sample_rate, dtype=np.float32)

mid_path = "/tmp/_bytedance_smoke.mid"
transcriber = PianoTranscription(device="cuda")
out = transcriber.transcribe(audio, mid_path)
print(f"OK: ByteDance HR-Piano loaded and ran on 1s silence. Output keys: {list(out.keys())}")

import os
try:
    os.unlink(mid_path)
except FileNotFoundError:
    pass
PY

echo "==> OK: piano_transcription_inference is installed and functional."
