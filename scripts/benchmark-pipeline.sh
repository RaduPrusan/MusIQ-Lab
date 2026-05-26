#!/usr/bin/env bash
# Phase A benchmark harness.
#
# Stages:
#   1. Verify all corpus mp3s are present (fetch via yt-dlp if missing).
#   2. Run pipeline on each corpus track.
#   3. Snapshot summary.jsons to tests/corpus/snapshots/$1/.
#   4. Render Markdown delta to install-logs/phase-a-validation.md.
#
# Usage (run from WSL):
#   bash scripts/benchmark-pipeline.sh <snapshot-label>
#
#   <label> is the snapshot directory name (e.g. "baseline" or "phaseA").
#   The first invocation should use "baseline" — that snapshot becomes the
#   reference. Subsequent runs (e.g. "phaseA") generate the delta vs baseline.
#
# Convention (per analyze/README.md): run this script FROM WSL with the
# project .venv active, or let it activate the venv itself.
#
# Example:
#   wsl -- bash -c 'cd "<PROJECT_WSL_PATH>" && \
#       source .venv/bin/activate && \
#       bash scripts/benchmark-pipeline.sh baseline 2>&1 | tail -30'
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <snapshot-label>" >&2
    exit 1
fi
LABEL="$1"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORPUS_DIR="$ROOT/tests/corpus"
SOURCES="$CORPUS_DIR/sources.txt"
LABELS_DIR="$CORPUS_DIR/labels"
SNAPSHOT_DIR="$CORPUS_DIR/snapshots"
BASELINE_DIR="$SNAPSHOT_DIR/baseline"
CANDIDATE_DIR="$SNAPSHOT_DIR/$LABEL"
CACHE_ROOT="$ROOT/cache"

mkdir -p "$BASELINE_DIR" "$CANDIDATE_DIR"

# ---------------------------------------------------------------------------
# 1. Fetch corpus mp3s (idempotent — skips if present).
#    fetch-test-fixtures.sh handles missing/empty sources.txt gracefully.
# ---------------------------------------------------------------------------
echo "==> Stage 1: fetching corpus fixtures"
bash "$ROOT/scripts/fetch-test-fixtures.sh"

# ---------------------------------------------------------------------------
# 2. Run pipeline on each corpus track.
#    Per project memory ytdlp_print_vs_ondisk_filename.md:
#    --print after_move:filepath mangles fullwidth chars on Windows.
#    Locate mp3 by globbing tests/mp3/*-<yt_id>.mp3 instead.
# ---------------------------------------------------------------------------
echo "==> Stage 2: running pipeline"

if [ ! -f "$SOURCES" ]; then
    echo "[warn] $SOURCES not found — skipping pipeline run" >&2
else
    while IFS= read -r url; do
        [ -z "$url" ] && continue
        [[ "$url" =~ ^# ]] && continue

        # Extract 11-char YouTube video ID from ?v=ID or youtu.be/ID forms
        yt_id="$(echo "$url" | sed -E 's@.*[?&]v=([A-Za-z0-9_-]{11}).*@\1@; s@.*youtu\.be/([A-Za-z0-9_-]{11}).*@\1@')"
        mp3="$(ls "$ROOT/tests/mp3/"*"-$yt_id.mp3" 2>/dev/null | head -n1 || true)"

        if [ -z "$mp3" ]; then
            echo "[warn] missing mp3 for $url (yt_id=$yt_id) — skipping" >&2
            continue
        fi

        echo "[analyze] $mp3"
        # Activate venv if not already active (idempotent)
        if [ -f "$ROOT/.venv/bin/activate" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
            # shellcheck disable=SC1091
            source "$ROOT/.venv/bin/activate"
        fi
        python -u -m analyze "$mp3"
    done < "$SOURCES"
fi

# ---------------------------------------------------------------------------
# 3. Snapshot all summary.jsons from cache/ into the candidate snapshot dir.
# ---------------------------------------------------------------------------
echo "==> Stage 3: snapshotting summaries to $CANDIDATE_DIR"
shopt -s nullglob
snapshot_count=0
for f in "$CACHE_ROOT"/*/*.summary.json; do
    cp "$f" "$CANDIDATE_DIR/"
    snapshot_count=$((snapshot_count + 1))
done
shopt -u nullglob
echo "    snapshotted $snapshot_count summary file(s)"

# Establish baseline on first run when the label IS "baseline" and the
# baseline dir is still empty (i.e., we just populated candidate == baseline).
if [ "$LABEL" = "baseline" ] && [ -z "$(ls -A "$BASELINE_DIR" 2>/dev/null)" ]; then
    echo "    (first baseline run — copying candidate → baseline)"
    cp -r "$CANDIDATE_DIR/." "$BASELINE_DIR/"
fi

# ---------------------------------------------------------------------------
# 4. Render delta Markdown.
# ---------------------------------------------------------------------------
echo "==> Stage 4: rendering delta"
if [ -f "$ROOT/.venv/bin/activate" ] && [ -z "${VIRTUAL_ENV:-}" ]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
fi

# `python -m scripts.lib.benchmark_compare` requires CWD = project root for
# the `scripts` package to be importable.
( cd "$ROOT" && python -m scripts.lib.benchmark_compare \
    "$BASELINE_DIR" "$CANDIDATE_DIR" \
    --labels "$LABELS_DIR" \
    --out "$ROOT/install-logs/phase-a-validation.md" )

echo "==> Done. Delta written to install-logs/phase-a-validation.md"
