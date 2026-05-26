#!/usr/bin/env bash
# Re-derive summary.json + JAMS for each cached track after a derivation-only change.
# All stage caches must already be populated; this script only re-runs the writers
# (and any always-on derivation, including is_instrumental).
#
# Override the MP3 source directory with MUSIQ_MP3_DIR (defaults to
# ~/Music/musiq-lab-test) and the YouTube source dir with MUSIQ_YT_OUT_DIR
# (defaults to ~/Videos/musiq-lab). Filenames below match the maintainer's
# local corpus; substitute your own as needed.

set -uo pipefail
cd "${MUSIQ_PROJECT_DIR:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
source .venv/bin/activate

MP3_DIR="${MUSIQ_MP3_DIR:-$HOME/Music/musiq-lab-test}"
YT_DIR="${MUSIQ_YT_OUT_DIR:-$HOME/Videos/musiq-lab}"

declare -A MP3=(
  [autumn_leaves_chet_baker_paul_desmond_together_sgn7vfxh2gy]="$MP3_DIR/Autumn Leaves - Chet Baker & Paul Desmond Together [sgn7VfXH2GY].mp3"
  [orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a]="$MP3_DIR/Orchestral Suite No. 3 in D Major_ II. Air on a G-String (Arr. for Cello Quintet)-Ing6BtC4S0A.mp3"
  [the_autumn_leaves_gm_130bpm_backing_track]="$MP3_DIR/The Autumn leaves - Gm (130bpm) - Backing Track.mp3"
  [lou_reed_perfect_day_official_audio_9wxi4kk9zyo]="$MP3_DIR/Lou Reed - Perfect Day (Official Audio)-9wxI4KK9ZYo.mp3"
  [charlie_puth_attention]="$MP3_DIR/Charlie Puth - Attention.mp3"
  [gorillaz_silent_running]="$YT_DIR/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3"
)

for slug in "${!MP3[@]}"; do
  echo "=== $slug ==="
  mp3="${MP3[$slug]}"
  if [ ! -r "$mp3" ]; then
    echo "  !! MP3 not readable: $mp3"
    continue
  fi
  python -m analyze --quiet "$mp3" 2>&1 | sed 's/^/    /'
  python - "$slug" <<'PYEOF'
import json, sys
slug = sys.argv[1]
s = json.load(open(f"cache/{slug}/{slug}.summary.json"))
vr = s["analysis"]["vocal_range"]
warns = s["provenance"]["warnings"]
print(f"  vocal_range = {vr}")
for w in warns:
    print(f"  warning: {w}")
PYEOF
done
echo "=== rederive complete ==="
