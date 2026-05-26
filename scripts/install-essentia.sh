#!/usr/bin/env bash
# scripts/install-essentia.sh — install Essentia + download high-level SVM models.
#
# Run from a WSL shell. Adds essentia to the project .venv and downloads
# the legacy Gaia SVM model tarball (~38 MB compressed) from MTG, then
# extracts only the high-level classifier .history files into
# analyze/vendor/essentia-models/. These are the SVM models that
# Essentia's GaiaTransform / MusicExtractorSVM algorithms consume.
#
# Source: https://essentia.upf.edu/svm_models/  (beta5 release, 2020)
# License: CC BY-NC-SA 4.0 (MTG) — not redistributed through this repo.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="$PROJECT_ROOT/analyze/vendor/essentia-models"
VENV="$PROJECT_ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "ERROR: project .venv not found at $VENV" >&2
  echo "  Activate the WSL .venv first (uv venv .venv inside WSL)." >&2
  exit 1
fi

echo "==> Installing essentia into $VENV"
# Upstream only publishes dev wheels under the 2.1b6 series (no final 2.1b6
# release exists on PyPI yet), so we need --pre to allow them.
"$VENV/bin/pip" install --pre 'essentia>=2.1b6.dev0'

mkdir -p "$MODELS_DIR"

# High-level SVM classifiers we want to keep (the .history file is the
# actual trained model loaded by GaiaTransform; everything else in the
# tarball — .param, .results.html — is metadata we don't need at runtime).
WANTED=(
  danceability
  voice_instrumental
  mood_acoustic
  mood_aggressive
  mood_electronic
  mood_happy
  mood_party
  mood_relaxed
  mood_sad
  tonal_atonal
)

# Skip the download entirely if every wanted model is already on disk.
need_download=0
for name in "${WANTED[@]}"; do
  if [[ ! -f "$MODELS_DIR/$name.history" ]]; then
    need_download=1
    break
  fi
done

if [[ "$need_download" -eq 0 ]]; then
  echo "==> All wanted SVM models already present in $MODELS_DIR — skipping download."
else
  ARCHIVE_URL="https://essentia.upf.edu/svm_models/essentia-extractor-svm_models-v2.1_beta5.tar.gz"
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT
  echo "==> Downloading SVM model archive (~38 MB) to $TMPDIR"
  curl -sSLf -o "$TMPDIR/svm.tar.gz" "$ARCHIVE_URL"
  echo "==> Extracting"
  tar xzf "$TMPDIR/svm.tar.gz" -C "$TMPDIR"
  SRC="$TMPDIR/essentia-extractor-svm_models-v2.1_beta5"
  for name in "${WANTED[@]}"; do
    out="$MODELS_DIR/$name.history"
    if [[ -f "$out" ]]; then
      echo "==> Already present: $name.history"
      continue
    fi
    if [[ ! -f "$SRC/$name.history" ]]; then
      echo "ERROR: expected $name.history not found in tarball" >&2
      exit 1
    fi
    cp "$SRC/$name.history" "$out"
    echo "==> Installed: $name.history"
  done
fi

echo "==> Verifying install"
MODELS_DIR="$MODELS_DIR" "$VENV/bin/python" - <<'PY'
import os
from essentia.standard import MusicExtractor, GaiaTransform
models_dir = os.environ["MODELS_DIR"]
MusicExtractor()  # ensure base extractor instantiates
# Sanity-load one .history to confirm the wheel ships with Gaia support.
GaiaTransform(history=os.path.join(models_dir, "danceability.history"))
print("essentia OK — MusicExtractor + GaiaTransform load cleanly.")
PY

echo "==> Done. Models in: $MODELS_DIR"
