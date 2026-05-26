"""Stage: per-stem RMS envelope at frame rate.

Computes a 1-D RMS array for each stem in stems_routing.json, written to
cache/<slug>/dynamics/<stem>.npz. Frame rate matches FCPE/PESTO (100 fps
by default) so cross-pollination between dynamics and pitch evidence is
sample-accurate.

Outputs
-------
    cache_dir/dynamics/<stem>.npz                (one file per stem; key 'rms')
    cache_dir/.params_stems_dynamics.json        (sidecar)

Optional stage
--------------
This stage is OPTIONAL — if it fails, the rest of the pipeline still
runs. Downstream consumers (the consensus voicing floor gate, the future
dynamics-aware metadata) gracefully no-op when dynamics files are
missing. That keeps existing analyses unaffected when this stage lands.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from analyze import sidecar, stems_routing


CANONICAL_DIR = "dynamics"
SCHEMA_VERSION = 1

DEFAULT_PARAMS: dict = {
    "fps": 100,
    "frame_length": 2048,
    "target_sr": 44100,
}


def cached(cache_dir: Path, **params) -> bool:
    """True iff dynamics dir exists, has at least one npz, and sidecar matches.

    Empty dynamics/ directory is treated as not-cached: it likely means the
    previous run failed and we want to retry, not bail out as cached.
    """
    p = {**DEFAULT_PARAMS, **params}
    dyn_dir = cache_dir / CANONICAL_DIR
    if not dyn_dir.exists() or not any(dyn_dir.glob("*.npz")):
        return False
    return sidecar.matches(
        cache_dir, "stems_dynamics", p,
        expected_schema_version=SCHEMA_VERSION,
    )


def load(cache_dir: Path) -> dict[str, np.ndarray]:
    """Return {stem_name: rms_array, ...}.

    Stems whose npz is missing or unreadable are silently omitted —
    callers should handle a stem-level KeyError if they require a
    specific stem (the natural shape for the consumer is "use what's
    there, fall back to no-RMS for stems that aren't").
    """
    dyn_dir = cache_dir / CANONICAL_DIR
    out: dict[str, np.ndarray] = {}
    if not dyn_dir.exists():
        return out
    for npz_path in sorted(dyn_dir.glob("*.npz")):
        try:
            with np.load(npz_path) as z:
                out[npz_path.stem] = z["rms"].astype(np.float32, copy=False)
        except (OSError, KeyError):
            continue
    return out


def _compute_rms(
    wav_path: Path,
    *,
    target_sr: int,
    fps: int,
    frame_length: int,
) -> np.ndarray:
    """Frame-aligned RMS of a stem WAV.

    hop_length = target_sr // fps locks the output to exactly `fps` frames
    per second, matching the F0 grid for sample-accurate cross-modality
    operations downstream.
    """
    import librosa
    audio, _ = librosa.load(str(wav_path), sr=target_sr, mono=True)
    hop_length = target_sr // fps
    rms = librosa.feature.rms(
        y=audio,
        frame_length=frame_length,
        hop_length=hop_length,
        center=True,
    )[0]
    return rms.astype(np.float32)


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    """Compute and persist per-stem RMS envelopes.

    `mp3` is unused — stems live in the cache, not at the original mp3
    path. Argument is kept for stage-protocol compatibility (every
    pipeline stage's run() takes (mp3_path, cache_dir, **params)).
    """
    p = {**DEFAULT_PARAMS, **params}
    dyn_dir = cache_dir / CANONICAL_DIR
    dyn_dir.mkdir(exist_ok=True)

    routing = stems_routing.load(cache_dir)
    stems_dict = routing.get("routing", {})

    summary: dict[str, dict] = {}
    for stem, entry in stems_dict.items():
        rel = entry.get("path") if isinstance(entry, dict) else None
        if not rel:
            continue
        wav_path = (cache_dir / rel).resolve()
        if not wav_path.exists():
            summary[stem] = {"error": f"missing wav: {wav_path}"}
            continue
        try:
            rms = _compute_rms(
                wav_path,
                target_sr=p["target_sr"],
                fps=p["fps"],
                frame_length=p["frame_length"],
            )
            np.savez_compressed(dyn_dir / f"{stem}.npz", rms=rms)
            summary[stem] = {
                "n_frames": int(len(rms)),
                "duration_sec": float(len(rms) / p["fps"]),
                "rms_max": float(rms.max()) if len(rms) > 0 else 0.0,
                "rms_mean": float(rms.mean()) if len(rms) > 0 else 0.0,
            }
        except Exception as exc:
            # Per-stem failure isolates: one bad stem shouldn't kill the
            # batch. Caller can inspect the summary to see which failed.
            summary[stem] = {"error": f"{type(exc).__name__}: {exc}"}

    sidecar.write(
        cache_dir, "stems_dynamics", p,
        schema_version=SCHEMA_VERSION,
    )
    return summary


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    for stem, info in r.items():
        if "error" in info:
            print(f"{stem:<8} ERROR: {info['error']}")
        else:
            print(
                f"{stem:<8} {info['n_frames']} frames  "
                f"max={info['rms_max']:.3f}  mean={info['rms_mean']:.3f}"
            )
