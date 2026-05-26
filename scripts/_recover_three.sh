#!/usr/bin/env bash
# Recover the 3 wiped tracks: run analyze on their source MP3s. New cache
# dirs will be created under dash-aware slugs (the old underscore-only
# dirs from the wiped state are orphaned and removed afterwards).
#
# Override MUSIQ_YT_OUT_DIR for the YouTube source dir; defaults to
# ~/Videos/musiq-lab. The two test-fixture MP3s live under tests/mp3/.
set -u
cd "${MUSIQ_PROJECT_DIR:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
source .venv/bin/activate

YT_DIR="${MUSIQ_YT_OUT_DIR:-$HOME/Videos/musiq-lab}"

run_one() {
  local label="$1"
  local src="$2"
  echo "=================================================================="
  echo "$label"
  echo "  source: $src"
  echo "=================================================================="
  if [ ! -f "$src" ]; then
    echo "  MISSING source — skipping"
    return 1
  fi
  python -m analyze "$src"
  echo
}

run_one "[1/3] Angus & Julia Stone — Harvest Moon" \
  "tests/mp3/Angus & Julia Stone - Harvest Moon - 11_17_2017 - Paste Studios, New York, NY-9uIBy71MRQk.mp3"

run_one "[2/3] Autumn Leaves — Chet Baker & Paul Desmond" \
  "tests/mp3/Autumn Leaves - Chet Baker & Paul Desmond Together [sgn7VfXH2GY].mp3"

run_one "[3/3] Queen — Radio Ga Ga (Official Video)" \
  "$YT_DIR/Queen - Radio Ga Ga (Official Video)-azdwsXLmrHE.mp3"

echo "=================================================================="
echo "Recovery sweep complete"
