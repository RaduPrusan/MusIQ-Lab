#!/usr/bin/env bash
# Runs after _recover_three.sh completes: orphan cleanup + the full
# 28-track batch. Kept separate from the recovery script so we don't have
# to preempt an in-flight recovery to fire the rest of the pipeline.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=================================================================="
echo "PHASE 2 — ORPHAN CLEANUP"
echo "=================================================================="
for orphan in \
  "cache/autumn_leaves_chet_baker_paul_desmond_together_sgn7vfxh2gy" \
  "cache/01_queen-radio_ga_ga" \
  "cache/angus_julia_stone_harvest_moon_11_17_2017_paste_studios_new_york_ny_9uiby71mrqk" \
; do
  if [ -d "$orphan" ]; then
    size_bytes=$(du -sb "$orphan" 2>/dev/null | awk '{print $1}')
    if [ "${size_bytes:-0}" -lt 4096 ]; then
      echo "  removing orphan: $orphan (${size_bytes:-0} bytes)"
      rm -rf "$orphan"
    else
      echo "  SKIP $orphan — not empty (${size_bytes} bytes); manual review"
    fi
  else
    echo "  already gone: $orphan"
  fi
done

echo
echo "=================================================================="
echo "PHASE 3 — FULL BATCH (every cache/<slug>/<slug>.mp3, --force)"
echo "=================================================================="
bash scripts/reanalyze_all_full.sh

echo
echo "=================================================================="
echo "ALL PHASES COMPLETE"
echo "=================================================================="
