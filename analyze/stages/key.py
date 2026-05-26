"""Stage 4: key detection via skey, with librosa Krumhansl-Schmuckler fallback.

Output: cache_dir/skey.json with key, confidence, source ('skey.detect_key' or
'librosa_ks'), errors (list).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from analyze import sidecar

CANONICAL = "skey.json"
SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "key", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    key = conf = src = None
    errors: list[str] = []

    try:
        from skey.key_detection import detect_key
        result = detect_key(str(mp3), device="cuda", cli=False)
        if result:
            key = result[0] if isinstance(result, list) else str(result)
            conf = 1.0
            src = "skey.detect_key"
    except Exception as exc:
        errors.append(f"skey.detect_key failed: {type(exc).__name__}: {exc}")

    if not key or key == "error":
        import librosa
        import numpy as np
        src = "librosa_ks"
        KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        y, sr = librosa.load(str(mp3), duration=120)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
        best = max(
            [(notes[i] + ":" + mode, np.corrcoef(np.roll(chroma, -i), profile)[0, 1])
             for i in range(12) for mode, profile in [("major", KS_MAJ), ("minor", KS_MIN)]],
            key=lambda row: row[1],
        )
        key, conf = best[0], float(best[1])

    out = {"key": str(key), "confidence": float(conf), "source": src, "errors": errors}
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    sidecar.write(cache_dir, "key", p, schema_version=SCHEMA_VERSION)
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(json.dumps(result, indent=2))
