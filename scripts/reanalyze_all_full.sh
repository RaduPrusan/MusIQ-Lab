#!/usr/bin/env bash
# Full-pipeline re-analysis of every track in cache/ using --force.
#
# Why we tempdir-stage the source: the analyze pipeline's --force mode calls
# cache.clear() on cache/<slug>/, which would wipe the source mirror if we
# passed that path directly as input. Instead we copy each <slug>.mp3 into a
# fresh tempdir per-track and run analyze on the temp copy. This mirrors the
# webui's reanalyze flow (webui/webui/server.py::_reanalyze_stream) so the
# behavior is identical to clicking "Reanalyze" in the UI.
#
# The pipeline itself was patched (analyze/pipeline.py) to defend the same
# invariant — staging here is belt-and-suspenders, and also matches what the
# webui has always done.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Source venv so subprocess calls (audio-separator, ffmpeg, etc.) resolve
# correctly. Calling .venv/bin/python directly is NOT enough — the python
# binary works, but its child processes inherit PATH from the calling shell.
# shellcheck disable=SC1091
source .venv/bin/activate

LOG_DATE=$(date +%Y-%m-%d-%H%M%S)
LOG_FILE="install-logs/reanalyze-all-${LOG_DATE}.log"
TSV_FILE="install-logs/reanalyze-all-${LOG_DATE}.tsv"

mkdir -p install-logs
echo -e "slug\tstatus\telapsed_sec\tstage_failed" > "$TSV_FILE"

total=0
ok=0
fail=0
skipped=0

for d in cache/*/; do
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
  echo "==================================================================" | tee -a "$LOG_FILE"

  # Stage source out of the cache dir before --force wipes it.
  stage_dir=$(mktemp -d -t musiq_reanalyze_XXXXXX)
  staged_mp3="$stage_dir/$slug.mp3"
  cp -p "$src_mp3" "$staged_mp3"

  start=$(date +%s)
  if python -m analyze --force "$staged_mp3" >> "$LOG_FILE" 2>&1; then
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

  rm -rf "$stage_dir"
done

echo "==================================================================" | tee -a "$LOG_FILE"
echo "DONE — $total tracks: $ok ok, $fail fail, $skipped skipped" | tee -a "$LOG_FILE"
echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
echo "TSV: $TSV_FILE" | tee -a "$LOG_FILE"
