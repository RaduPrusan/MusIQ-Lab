"""Stage 5: chord recognition via lv-chordia.

Output: cache_dir/chords.json — list of {start, end, label} dicts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from analyze import sidecar

CANONICAL = "chords.json"
SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "chords", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> list[dict]:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path, **params) -> list[dict]:
    p = {**DEFAULT_PARAMS, **params}
    from lv_chordia.chord_recognition import chord_recognition
    try:
        raw = chord_recognition(str(mp3), chord_dict_name="submission")
    finally:
        # lv-chordia loads a 5-snapshot ChordNet ensemble (CNN + BiLSTM) and
        # for each snapshot allocates a full Adam optimizer state directly
        # onto CUDA — see lv_chordia/mir/nn/train.py:66 (get_optimizer) and
        # train.py:80 (optimizer.load_state_dict). The 5 NetworkInterface
        # instances created in chord_recognition.py:63 are loop-local and go
        # out of scope on return, but nn.Module forms reference cycles
        # through _parameters/_modules/_backward_hooks that defer collection
        # to the cyclic GC. On WSL2 this lets the dxgkrnl driver strand the
        # full ~5 GB working set after the stage completes (measured
        # 2026-05-02). Two gc passes break the cycles before empty_cache
        # returns the freed blocks to the driver.
        import gc
        gc.collect()
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
    chords = [
        {
            "start": float(item.get("start_time", item.get("start", 0.0))),
            "end": float(item.get("end_time", item.get("end", 0.0))),
            "label": str(item.get("chord", item.get("label", "N"))),
        }
        for item in raw
    ]
    (cache_dir / CANONICAL).write_text(json.dumps(chords, indent=2))
    sidecar.write(cache_dir, "chords", p, schema_version=SCHEMA_VERSION)
    return chords


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    chords = run(mp3, cd)
    print(f"{len(chords)} chord events")
    for c in chords[:8]:
        print(f"  {c['start']:6.2f}-{c['end']:6.2f}: {c['label']}")
