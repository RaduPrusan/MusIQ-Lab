#!/usr/bin/env bash
# Isolated single-stage VRAM-leak test.
#
# Usage:  bash install-logs/_test_stage_isolation.sh <stage_name> <mp3> <cache_dir>
#
# Spawns the stage as a fresh subprocess via _stage_runner, samples VRAM at
# baseline / mid-run / post-exit, and prints the delta. The post-exit value is
# what matters: if the stage allocated N MiB during run and N MiB is released
# on exit, the fix works. If less than N is released, the leak persists.
set -eu

stage="$1"
mp3="$2"
cache_dir="$3"

vram() {
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits
}

echo "=== Isolated $stage stage VRAM test ==="
baseline=$(vram)
echo "baseline:        ${baseline} MiB"

# Spawn the subprocess in the background so we can sample VRAM while it runs.
python -u -m analyze._stage_runner "$stage" "$mp3" "$cache_dir" &
pid=$!

# Sample every 1.5s while the subprocess is alive.
peak="$baseline"
while kill -0 "$pid" 2>/dev/null; do
  v=$(vram)
  if [ "$v" -gt "$peak" ]; then peak="$v"; fi
  sleep 1.5
done

# Subprocess has exited. Wait for any straggling dxg reclamation.
wait "$pid" || true
sleep 2
post=$(vram)

echo "peak during run: ${peak} MiB  (delta from baseline: $((peak - baseline)) MiB)"
echo "post-exit:       ${post} MiB  (delta from baseline: $((post - baseline)) MiB)"
echo
allocated=$((peak - baseline))
stranded=$((post - baseline))
if [ "$allocated" -gt 0 ]; then
  pct=$(( 100 * stranded / allocated ))
  echo "stranded fraction: ${stranded}/${allocated} MiB = ${pct}% of working set"
else
  echo "no measurable allocation (allocated=$allocated)"
fi
