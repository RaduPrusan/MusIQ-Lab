#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
total=0; ok=0; missing=0
for d in cache.old/*/; do
  total=$((total+1))
  slug=$(basename "$d")
  if [ -f "$d$slug.mp3" ]; then
    ok=$((ok+1))
    echo "OK   $slug"
  else
    missing=$((missing+1))
    echo "MISS $slug"
  fi
done
echo "----"
echo "$total total, $ok with mp3, $missing missing"
