#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
source cache/gorillaz_silent_running/env.sh

echo "==== htdemucs_6s (6 stems) ===="
audio-separator "$TEST_MP3" \
  --model_filename htdemucs_6s.yaml \
  --output_dir "$TEST_DIR/stems_6s/" \
  --output_format WAV

echo "==== BS-Roformer (vocals/instrumental) ===="
audio-separator "$TEST_MP3" \
  --model_filename model_bs_roformer_ep_317_sdr_12.9755.ckpt \
  --output_dir "$TEST_DIR/stems_bsroformer/" \
  --output_format WAV

echo "==== final stem files ===="
find "$TEST_DIR" -maxdepth 2 -type f -name "*.wav" -printf "%p\n" | sort
