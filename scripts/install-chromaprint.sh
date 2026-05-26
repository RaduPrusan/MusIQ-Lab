#!/usr/bin/env bash
# scripts/install-chromaprint.sh — fetch the fpcalc binary into the vendor dir.
set -euo pipefail

VENDOR_DIR="$(cd "$(dirname "$0")/.." && pwd)/analyze/vendor/chromaprint"
mkdir -p "$VENDOR_DIR"

CP_VERSION="1.5.1"
ARCHIVE="chromaprint-fpcalc-${CP_VERSION}-linux-x86_64.tar.gz"
URL="https://github.com/acoustid/chromaprint/releases/download/v${CP_VERSION}/${ARCHIVE}"

cd "$(mktemp -d)"
echo "Downloading ${URL}..."
curl -sSLf -o "$ARCHIVE" "$URL"
tar xzf "$ARCHIVE"
cp "chromaprint-fpcalc-${CP_VERSION}-linux-x86_64/fpcalc" "$VENDOR_DIR/fpcalc"
chmod +x "$VENDOR_DIR/fpcalc"

echo "Installed: $VENDOR_DIR/fpcalc"
"$VENDOR_DIR/fpcalc" -version
