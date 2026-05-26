#!/usr/bin/env bash
# Fetch all corpus mp3s listed in tests/corpus/sources.txt to tests/mp3/.
# Uses the project's standard yt-dlp invocation from CLAUDE.md.
# Idempotent: skips tracks already on disk (matched by the 11-char YT id).
#
# Run from Windows Git Bash or WSL bash:
#   bash scripts/fetch-test-fixtures.sh
#
# yt-dlp binary lookup (in order):
#   1. $MUSIQ_YTDLP_BIN if set (matches .env.example)
#   2. `yt-dlp` on PATH
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCES="$ROOT/tests/corpus/sources.txt"
OUT_DIR="$ROOT/tests/mp3"
YT_DLP="${MUSIQ_YTDLP_BIN:-yt-dlp}"

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
