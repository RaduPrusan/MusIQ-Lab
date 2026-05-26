#!/usr/bin/env bash
# Re-run analyze on every MP3 in tests/mp3. Drums stage will re-run because
# the v1 cache fails the cached() schema check; everything else is cached
# and loads in <1s per track.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
total=0
gated=0
ran=0
for mp3 in tests/mp3/*.mp3; do
  total=$((total+1))
  name=$(basename "$mp3")
  echo "=================================================================="
  echo "[$total] $name"
  echo "=================================================================="
  .venv/bin/python -m analyze "$(realpath "$mp3")" 2>&1 | grep -E "(Stage drums|Wrote .*summary.json)" | head -3 || true
done
echo "=================================================================="
echo "DONE — re-analyzed $total tracks"
