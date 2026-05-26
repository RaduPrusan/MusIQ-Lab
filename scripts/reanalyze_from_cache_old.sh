#!/usr/bin/env bash
# Re-run the full pipeline on every track in cache.old/, using cache.old's
# source MP3 mirror as input. Output goes to cache/<slug>/.
#
# cache.old IS NOT TOUCHED — analyze() only reads from the input path; its
# cache.clear()/mirror operations target cache/<slug>/, derived from the
# slug. We use shutil.copy2 (not move) at every step.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

LOG_DATE=$(date +%Y-%m-%d-%H%M%S)
LOG_FILE="install-logs/reanalyze-from-cacheold-${LOG_DATE}.log"
TSV_FILE="install-logs/reanalyze-from-cacheold-${LOG_DATE}.tsv"
mkdir -p install-logs
echo -e "slug\tstatus\telapsed_sec\tstage_failed" > "$TSV_FILE"

total=0
ok=0
fail=0
skipped=0

for d in cache.old/*/; do
  slug=$(basename "$d")
  src_mp3="$d$slug.mp3"
  total=$((total+1))

  if [ ! -f "$src_mp3" ]; then
    echo "[$total] SKIP $slug — no mirrored mp3 at $src_mp3" | tee -a "$LOG_FILE"
    echo -e "$slug\tskipped\t0\tno_mp3" >> "$TSV_FILE"
    skipped=$((skipped+1))
    continue
  fi

  echo "==================================================================" | tee -a "$LOG_FILE"
  echo "[$total] $slug" | tee -a "$LOG_FILE"
  echo "  source: $src_mp3" | tee -a "$LOG_FILE"
  echo "==================================================================" | tee -a "$LOG_FILE"

  # lv-chordia (chords stage) breaks on relative paths — always pass absolute.
  abs_mp3=$(realpath "$src_mp3")
  start=$(date +%s)
  if python -m analyze --force "$abs_mp3" >> "$LOG_FILE" 2>&1; then
    elapsed=$(( $(date +%s) - start ))
    echo "  OK  ${elapsed}s" | tee -a "$LOG_FILE"
    echo -e "$slug\tok\t$elapsed\t" >> "$TSV_FILE"
    ok=$((ok+1))
  else
    elapsed=$(( $(date +%s) - start ))
    fail_stage=$(tail -50 "$LOG_FILE" | grep -oE 'Stage [a-z_]+' | tail -1 || true)
    echo "  FAIL ${elapsed}s  ($fail_stage)" | tee -a "$LOG_FILE"
    echo -e "$slug\tfail\t$elapsed\t$fail_stage" >> "$TSV_FILE"
    fail=$((fail+1))
  fi
done

echo "==================================================================" | tee -a "$LOG_FILE"
echo "DONE — $total tracks: $ok ok, $fail fail, $skipped skipped" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "TSV: $TSV_FILE" | tee -a "$LOG_FILE"
