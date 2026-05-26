#!/usr/bin/env bash
# Resume variant of batch-tests-mp3.sh: process only tests/mp3/*.mp3 entries
# whose cache/<slug>/<slug>.summary.json does NOT already exist.
#
# Use after you've removed cache dirs for tracks you want to re-run.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate

MP3_DIR="tests/mp3"

mapfile -t ALL_TRACKS < <(find "$MP3_DIR" -maxdepth 1 -type f -name '*.mp3' -printf '%f\n' | sort)

# Filter to tracks needing work.
TRACKS=()
SKIPPED=()
for t in "${ALL_TRACKS[@]}"; do
  mp3="$(realpath "$MP3_DIR/$t")"
  slug=$(python -c "from pathlib import Path; from analyze.cache import slug_for; print(slug_for(Path('$mp3')))")
  summary="cache/$slug/$slug.summary.json"
  if [ -r "$summary" ]; then
    SKIPPED+=("$t")
  else
    TRACKS+=("$t")
  fi
done

echo "==== batch-tests-mp3-resume starting at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
echo "to process: ${#TRACKS[@]}"
echo "already done (skipped): ${#SKIPPED[@]}"
for s in "${SKIPPED[@]}"; do echo "  skip: $s"; done

for i in "${!TRACKS[@]}"; do
  mp3="$(realpath "$MP3_DIR/${TRACKS[$i]}")"
  short="${TRACKS[$i]%.mp3}"
  echo
  echo "==== [$((i+1))/${#TRACKS[@]}] $(date -u +%H:%M:%SZ): ${short:0:80} ===="

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
echo "==== batch-tests-mp3-resume complete at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===="
