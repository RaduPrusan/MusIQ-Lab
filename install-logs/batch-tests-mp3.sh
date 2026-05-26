#!/usr/bin/env bash
# Batch test analyze on all MP3s under tests/mp3/.
# Mirrors install-logs/batch-test.sh but sources tracks from the in-repo fixture
# directory instead of the user's YouTube folder.
#
# NOT -e: a single-track failure shouldn't abort the rest.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

MP3_DIR="tests/mp3"

# Collect tracks (sorted, stable order across runs).
mapfile -t TRACKS < <(find "$MP3_DIR" -maxdepth 1 -type f -name '*.mp3' -printf '%f\n' | sort)

echo "==== batch-tests-mp3 starting at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
echo "tracks: ${#TRACKS[@]}"

for i in "${!TRACKS[@]}"; do
  # NOTE: lv-chordia (chords stage) resolves the MP3 path against its own
  # site-packages dir if given a relative path. Always pass absolute.
  mp3="$(realpath "$MP3_DIR/${TRACKS[$i]}")"
  short="${TRACKS[$i]%.mp3}"
  echo
  echo "==== [$((i+1))/${#TRACKS[@]}] $(date -u +%H:%M:%SZ): ${short:0:80} ===="
  if [ ! -r "$mp3" ]; then
    echo "!!  FILE NOT READABLE: $mp3"
    continue
  fi

  start=$(date +%s)
  python -m analyze "$mp3" 2>&1 | sed 's/^/    /'
  rc=${PIPESTATUS[0]}
  elapsed=$(( $(date +%s) - start ))
  echo "==== exit=$rc, ${elapsed}s ===="

  if [ "$rc" -eq 0 ]; then
    slug=$(python -c "from pathlib import Path; from analyze.cache import slug_for; print(slug_for(Path('$mp3')))")
    summary="cache/$slug/$slug.summary.json"
    if [ -r "$summary" ]; then
      python -c "
import json
s = json.load(open('$summary'))
t = s['track']
a = s['analysis']
print(f\"    key={t['key']} (conf={t['key_confidence']:.2f})\")
print(f\"    tempo={t['tempo_bpm']:.1f} BPM\")
print(f\"    duration={t['duration_sec']:.1f}s\")
print(f\"    scale={a['scale']}\")
print(f\"    chords={len(s['chords'])}\")
print(f\"    loop={a['predominant_chord_loop']}\")
print(f\"    loop_roman={a['loop_roman']}\")
print(f\"    modal_interchange_count={a['modal_interchange_count']}\")
print(f\"    vocal_range={a['vocal_range']}\")
for stem, info in s['stems'].items():
    if 'notes' in info: print(f\"    notes[{stem}]={len(info['notes'])}\")
print(f\"    warnings={s['provenance']['warnings']}\")
"
    fi
  fi
done

echo
echo "==== batch-tests-mp3 complete at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
