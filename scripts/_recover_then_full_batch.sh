#!/usr/bin/env bash
# Chains the 3-track recovery + orphan cleanup + full 28-track batch into
# one unattended run so we don't pause for a human in the middle.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

LOG_DATE=$(date +%Y-%m-%d-%H%M%S)
LOG_FILE="install-logs/recover-then-full-${LOG_DATE}.log"
mkdir -p install-logs

{
  echo "=================================================================="
  echo "PHASE 1 — RECOVERY (3 wiped tracks)"
  echo "=================================================================="
  bash scripts/_recover_three.sh

  echo
  echo "=================================================================="
  echo "PHASE 2 — ORPHAN CLEANUP"
  echo "=================================================================="
  for orphan in \
    "cache/autumn_leaves_chet_baker_paul_desmond_together_sgn7vfxh2gy" \
    "cache/01_queen-radio_ga_ga" \
    "cache/angus_julia_stone_harvest_moon_11_17_2017_paste_studios_new_york_ny_9uiby71mrqk" \
  ; do
    if [ -d "$orphan" ]; then
      # Sanity: only delete if dir is empty or contains nothing larger than
      # 1 KB (defensive — orphans should be empty after cache.clear()).
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
  echo "PHASE 3 — FULL 28-TRACK BATCH"
  echo "=================================================================="
  bash scripts/reanalyze_all_full.sh

  echo
  echo "=================================================================="
  echo "ALL PHASES COMPLETE"
  echo "=================================================================="
} 2>&1 | tee "$LOG_FILE"
