"""Stage 2a: madmom downbeats and tempo.

Uses madmom's RNNDownBeatProcessor + DBNDownBeatTrackingProcessor. Runs on CPU
(custom inference path, not torch). Plenty fast for offline analysis.

Output: cache_dir/madmom_downbeats.json with bpm, beats, downbeats, n_beats,
n_downbeats, first_8_downbeats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from analyze import sidecar

CANONICAL = "madmom_downbeats.json"
SCHEMA_VERSION = 2  # bumped: time_signature recovered from madmom beat positions
DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "beats", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

    p = {**DEFAULT_PARAMS, **params}

    activations = RNNDownBeatProcessor()(str(mp3))
    tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
    beats_with_pos = tracker(activations)
    beats = [float(t) for t, _ in beats_with_pos]
    downbeats = [float(t) for t, pos in beats_with_pos if int(pos) == 1]

    # Recover the meter madmom's HMM committed to (one of [3, 4]). Position is
    # 1-indexed within the bar; the chosen meter is max position over the track.
    positions = [int(pos) for _t, pos in beats_with_pos]
    beats_per_bar = max(positions) if positions else 4
    time_signature = f"{beats_per_bar}/4"  # madmom denominator is implicit /4

    if len(beats) >= 2:
        diffs = np.diff(beats)
        median_ibi = float(np.median(diffs))
        bpm = 60.0 / median_ibi if median_ibi > 0 else 0.0
    else:
        bpm = 0.0

    out = {
        "bpm": float(bpm),
        "time_signature": time_signature,
        "beats_per_bar": beats_per_bar,
        "beats": beats,
        "downbeats": downbeats,
        "n_beats": len(beats),
        "n_downbeats": len(downbeats),
        "first_8_downbeats": [round(t, 3) for t in downbeats[:8]],
    }
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    sidecar.write(cache_dir, "beats", p, schema_version=SCHEMA_VERSION)
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(f"bpm: {result['bpm']:.2f}, beats: {result['n_beats']}, downbeats: {result['n_downbeats']}")
