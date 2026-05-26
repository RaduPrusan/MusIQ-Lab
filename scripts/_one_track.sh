#!/usr/bin/env bash
# Run analyze --force on a single cache.old/<slug>/<slug>.mp3, log to a
# per-track file. Used by the supervisor (claude) to drive the batch one
# track at a time, verifying before moving to the next.
#
# Usage: _one_track.sh <slug>
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

slug="${1:?slug required}"
src="cache.old/$slug/$slug.mp3"
if [ ! -f "$src" ]; then
  echo "MISSING: $src" >&2
  exit 2
fi

mkdir -p install-logs/per-track
log="install-logs/per-track/${slug}.log"
abs=$(realpath "$src")

echo "==> $slug" | tee "$log"
echo "    src: $abs" | tee -a "$log"
start=$(date +%s)
if python -m analyze --force "$abs" >> "$log" 2>&1; then
  elapsed=$(( $(date +%s) - start ))
  echo "OK ${elapsed}s" | tee -a "$log"
  exit 0
else
  rc=$?
  elapsed=$(( $(date +%s) - start ))
  echo "FAIL rc=$rc ${elapsed}s" | tee -a "$log"
  exit $rc
fi
