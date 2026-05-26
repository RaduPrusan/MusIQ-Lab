#!/usr/bin/env bash
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
source cache/gorillaz_silent_running/env.sh
echo "MP3=[$TEST_MP3]"
echo "DIR=[$TEST_DIR]"
ls -la "$TEST_MP3" 2>&1 | head -3
ffprobe -v error -show_entries format=format_name,duration,bit_rate -of default=nw=1 "$TEST_MP3"
