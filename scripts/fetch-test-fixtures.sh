#!/usr/bin/env bash
# Fetch all corpus mp3s listed in tests/corpus/sources.txt to tests/mp3/.
# Uses the project's standard yt-dlp invocation from CLAUDE.md.
# Idempotent: skips tracks already on disk (matched by the 11-char YT id).
#
# Run from Windows Git Bash or WSL bash:
#   bash scripts/fetch-test-fixtures.sh
#
# Note: the yt-dlp path uses single quotes so $WinSoft/$tools are NOT
# expanded by bash (CLAUDE.md: "Always single-quote the path in Bash tool calls").
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCES="$ROOT/tests/corpus/sources.txt"
OUT_DIR="$ROOT/tests/mp3"
# Single-quoted so bash does not expand $WinSoft / $tools (CLAUDE.md rule)
YT_DLP='C:/$WinSoft/$tools/yt-dlp/yt-dlp.exe'

mkdir -p "$OUT_DIR"

if [ ! -f "$SOURCES" ]; then
    echo "[warn] $SOURCES not found — nothing to fetch" >&2
    exit 0
fi

while IFS= read -r url; do
    [ -z "$url" ] && continue
    [[ "$url" =~ ^# ]] && continue
    # Extract 11-char YouTube video ID from ?v=ID or youtu.be/ID forms
    yt_id="$(echo "$url" | sed -E 's@.*[?&]v=([A-Za-z0-9_-]{11}).*@\1@; s@.*youtu\.be/([A-Za-z0-9_-]{11}).*@\1@')"
    if ls "$OUT_DIR"/*-"$yt_id".mp3 >/dev/null 2>&1; then
        echo "[skip] already have $yt_id"
        continue
    fi
    echo "[fetch] $url (id=$yt_id)"
    "$YT_DLP" \
        -x --audio-format mp3 --audio-quality 0 \
        --no-update \
        -o "$OUT_DIR/%(title)s-%(id)s.%(ext)s" \
        "$url"
done < "$SOURCES"
