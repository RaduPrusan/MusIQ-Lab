#!/usr/bin/env bash
# Sample VRAM and active stage-runner / audio-separator child every 3s.
set -u
n="${1:-12}"
for ((i=0; i<n; i++)); do
  ts=$(date +%T)
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null)
  child=$(pgrep -af 'analyze._stage_runner|audio-separator|basic_pitch|onnx' 2>/dev/null \
          | grep -v 'pgrep\|grep' \
          | head -1 \
          | awk '{
              for (j=1;j<=NF;j++) {
                if ($j ~ /_stage_runner/) { print "stage_runner=" $(j+1); next }
                if ($j ~ /audio-separator/) { print "audio-separator"; next }
                if ($j ~ /basic_pitch/) { print "basic_pitch"; next }
                if ($j ~ /onnx/) { print "onnx"; next }
              }
            }')
  printf '%s  vram=%6s MiB  child=%s\n' "$ts" "$used" "$child"
  sleep 3
done
