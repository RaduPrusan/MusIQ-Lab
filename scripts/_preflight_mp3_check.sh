#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
total=0; ok=0; missing=0
for d in cache/*/; do
  total=$((total+1))
  slug=$(basename "$d")
  if [ -f "$d$slug.mp3" ]; then
    ok=$((ok+1))
  else
    missing=$((missing+1))
    echo "MISSING: $slug"
  fi
done
echo "SUMMARY: $total total, $ok with mp3, $missing missing"
