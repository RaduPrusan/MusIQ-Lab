"""Stage 3: beat-this (canonical beat tracker, also serves as cross-check).

Output: cache_dir/beat_this.json with beats, downbeats, n_beats, n_downbeats,
first_8_beats, first_8_downbeats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from analyze import sidecar

CANONICAL = "beat_this.json"
SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "beats_xcheck", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    from beat_this.inference import File2Beats

    p = {**DEFAULT_PARAMS, **params}
    model = File2Beats(checkpoint_path="final0", device="cuda")
    beats, downbeats = model(str(mp3))
    out = {
        "beats": [float(t) for t in beats],
        "downbeats": [float(t) for t in downbeats],
        "n_beats": len(beats),
        "n_downbeats": len(downbeats),
        "first_8_beats": [round(float(t), 3) for t in beats[:8]],
        "first_8_downbeats": [round(float(t), 3) for t in downbeats[:8]],
    }
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    sidecar.write(cache_dir, "beats_xcheck", p, schema_version=SCHEMA_VERSION)
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(f"beats: {result['n_beats']}, downbeats: {result['n_downbeats']}")
