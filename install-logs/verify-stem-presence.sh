#!/bin/bash
# Re-run analyze on 5 cached tracks to apply the new stem-presence gate.
# All stages cached → only the derivation step (which now includes the gate)
# re-runs and rewrites summary.json.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

SLUGS=(
  gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg
  orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a
  two_fingers_deep_jinx
  olivia_dean_dive_acoustic_yylsa4m2zzm
  charlie_puth_attention
)

for slug in "${SLUGS[@]}"; do
  echo "=== $slug ==="
  mp3="cache/$slug/$slug.mp3"
  if [ -f "$mp3" ]; then
    abs="$(realpath "$mp3")"
    time python -m analyze --quiet "$abs" 2>&1 | tail -5
  else
    echo "MP3 missing: $mp3"
  fi
done
