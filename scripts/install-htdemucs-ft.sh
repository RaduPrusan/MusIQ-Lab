#!/usr/bin/env bash
# Pre-warm htdemucs_ft.yaml so the first benchmark run isn't dominated by a
# 100+MB download. audio-separator caches weights per-user; this just primes it.
#
# Idempotent — safe to re-run. If the model cache already contains the weights,
# audio-separator skips the download.
set -euo pipefail

# Resolve project root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Activating venv: ${PROJECT_ROOT}/.venv"
# shellcheck source=/dev/null
source "${PROJECT_ROOT}/.venv/bin/activate"

echo "==> Pre-warming htdemucs_ft via audio-separator..."

SILENT=/tmp/_htdemucs_ft_warmup.wav
OUT_DIR=/tmp/_htdemucs_ft_warmup_out

# Generate 3 seconds of a 440 Hz sine tone (silent audio is rejected by
# audio-separator as "empty or not valid").
ffmpeg -y -loglevel error \
    -f lavfi -i "sine=frequency=440:sample_rate=44100" \
    -ac 2 -t 3 -c:a pcm_s16le "$SILENT"

echo "==> Running audio-separator with htdemucs_ft.yaml (downloads weights on first run)..."
mkdir -p "$OUT_DIR"
audio-separator "$SILENT" \
    --model_filename htdemucs_ft.yaml \
    --output_dir "$OUT_DIR" \
    --output_format WAV >/dev/null

# Verify all four stems were produced.
echo "==> Verifying 4-stem output..."
expected=(Vocals Drums Bass Other)
missing=0
for s in "${expected[@]}"; do
    # audio-separator names stems like: _htdemucs_ft_warmup_(Vocals).wav
    if ! ls "${OUT_DIR}"/*\("${s}"\)*.wav >/dev/null 2>&1; then
        echo "!! FAIL: htdemucs_ft did not produce (${s}) stem" >&2
        missing=$((missing + 1))
    fi
done
if (( missing > 0 )); then
    echo "!! Install incomplete: ${missing} stem(s) missing." >&2
    rm -rf "$OUT_DIR" "$SILENT"
    exit 1
fi

rm -rf "$OUT_DIR" "$SILENT"
echo "==> OK: htdemucs_ft is installed and produces all 4 stems (Vocals/Drums/Bass/Other)."
