#!/usr/bin/env bash
# Install LarsNet into analyze/vendor/larsnet/ for the drums analysis stage.
#
# Clones the polimi-ispl/larsnet repo and downloads the pretrained weights
# (562 MB) from Google Drive. Idempotent — safe to re-run; skips work that's
# already done.
#
# License notes:
#   - LarsNet code: no formal license declared on the repo (MZehren default
#     "all rights reserved"). Personal/research use only.
#   - LarsNet weights: CC BY-NC 4.0 (per upstream README). NON-COMMERCIAL.
#
# This script does not redistribute either; it points at the original sources.
set -euo pipefail

# Resolve project root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENDOR_DIR="${PROJECT_ROOT}/analyze/vendor/larsnet"

REPO_URL="https://github.com/polimi-ispl/larsnet.git"
WEIGHTS_GDRIVE_ID="1U8-5924B1ii1cjv9p0MTPzayb00P4qoL"
WEIGHTS_ZIP="${VENDOR_DIR}/larsnet_weights.zip"
WEIGHTS_MARKER="${VENDOR_DIR}/pretrained_larsnet_models/kick/pretrained_kick_unet.pth"

echo "==> LarsNet install target: ${VENDOR_DIR}"
mkdir -p "${VENDOR_DIR}"

# 1. Clone repo (or skip if already there).
if [[ -f "${VENDOR_DIR}/larsnet.py" ]]; then
    echo "==> LarsNet code already present, skipping clone"
else
    echo "==> Cloning ${REPO_URL}"
    tmp_clone="$(mktemp -d)"
    git clone --depth 1 "${REPO_URL}" "${tmp_clone}/larsnet"
    # Drop the cloned repo's .git/ so the parent project doesn't treat
    # analyze/vendor/larsnet/ as a submodule (which would prevent .gitkeep
    # from being tracked and break the gitignore-with-negation pattern).
    rm -rf "${tmp_clone}/larsnet/.git"
    # Move repo contents (not the dir itself) into VENDOR_DIR — preserves
    # .gitkeep that's already there.
    shopt -s dotglob
    mv "${tmp_clone}/larsnet"/* "${VENDOR_DIR}/"
    shopt -u dotglob
    rm -rf "${tmp_clone}"
fi

# 2. Download weights (or skip if already there).
if [[ -f "${WEIGHTS_MARKER}" ]]; then
    echo "==> LarsNet weights already present, skipping download"
else
    echo "==> Downloading weights from Google Drive (~562 MB)"
    # Google Drive's >100 MB warning page requires a confirmation roundtrip.
    cookies="$(mktemp)"
    page="$(mktemp)"
    curl -sL -c "${cookies}" -o "${page}" \
        "https://drive.google.com/uc?id=${WEIGHTS_GDRIVE_ID}&export=download"
    # Extract uuid from the warning page form (rotates per request).
    uuid="$(grep -oE 'name="uuid" value="[^"]+"' "${page}" | sed 's/.*value="\([^"]*\)".*/\1/')"
    if [[ -z "${uuid}" ]]; then
        echo "!! Failed to extract Google Drive confirm token; weights not downloaded." >&2
        echo "!! Download manually from https://drive.google.com/uc?id=${WEIGHTS_GDRIVE_ID}" >&2
        echo "!! and unzip into ${VENDOR_DIR}/" >&2
        rm -f "${cookies}" "${page}"
        exit 1
    fi
    curl -L -b "${cookies}" -o "${WEIGHTS_ZIP}" \
        "https://drive.usercontent.google.com/download?id=${WEIGHTS_GDRIVE_ID}&export=download&confirm=t&uuid=${uuid}"
    rm -f "${cookies}" "${page}"

    echo "==> Extracting weights"
    (cd "${VENDOR_DIR}" && unzip -o "${WEIGHTS_ZIP}" >/dev/null)
    rm -f "${WEIGHTS_ZIP}"
fi

# 3. Sanity check.
echo "==> Verifying install"
required=(
    "${VENDOR_DIR}/larsnet.py"
    "${VENDOR_DIR}/unet.py"
    "${VENDOR_DIR}/config.yaml"
    "${VENDOR_DIR}/pretrained_larsnet_models/kick/pretrained_kick_unet.pth"
    "${VENDOR_DIR}/pretrained_larsnet_models/snare/pretrained_snare_unet.pth"
    "${VENDOR_DIR}/pretrained_larsnet_models/toms/pretrained_toms_unet.pth"
    "${VENDOR_DIR}/pretrained_larsnet_models/hihat/pretrained_hihat_unet.pth"
    "${VENDOR_DIR}/pretrained_larsnet_models/cymbals/pretrained_cymbals_unet.pth"
)
missing=0
for f in "${required[@]}"; do
    if [[ ! -f "${f}" ]]; then
        echo "!! missing: ${f}" >&2
        missing=$((missing + 1))
    fi
done
if (( missing > 0 )); then
    echo "!! Install incomplete (${missing} files missing)." >&2
    exit 1
fi

echo "==> LarsNet installed: $(du -sh "${VENDOR_DIR}" | cut -f1) at ${VENDOR_DIR}"
