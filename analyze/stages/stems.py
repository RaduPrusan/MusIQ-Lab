"""Stage 1: stem separation via audio-separator.

Runs a configurable set of audio-separator models per quality preset:
  - fast:   htdemucs_6s + bs_roformer_ep_317
  - normal: htdemucs_6s + htdemucs_ft + bs_roformer_ep_317
  - best:   htdemucs_6s + htdemucs_ft + bs_roformer_ep_317

Both are CLI tools (no clean Python API) so we shell out via subprocess.

The MP3 is first transcoded to a temporary PCM WAV via ffmpeg before being
fed to audio-separator. Reason: audio-separator's MP3 reader (libsndfile)
bails on the first malformed Audio-MPEG-Header it hits and silently emits
a truncated stem. This was first observed with Radiohead "creep" — the
original file decodes fully under ffmpeg/mpg123 but audio-separator
stopped at 112.87s of a 286.86s track, silently truncating chords/notes/
drums for everything downstream. ffmpeg is permissive about header
errors and rebuilds the audio cleanly, so transcoding once up front
prevents the truncation regardless of source quality.

Outputs (normal/best preset):
    cache_dir/stems_6s/<basename>_(Vocals)_htdemucs_6s.wav    [+ 5 more stems]
    cache_dir/stems_htdemucs_ft/<basename>_(Drums)_htdemucs_ft.wav  [+ 3 more stems]
    cache_dir/stems_bsroformer/<basename>_(Vocals)_model_bs_roformer_ep_317_sdr_12.wav
    cache_dir/stems_routing.json  <- written LAST; its presence signals full success

Migration note (WI-6):
    Existing caches that pre-date this module (no stems_routing.json) will fail
    cached() and trigger a full stems re-run on the next analyze invocation.
    This is intentional migration behavior: downstream stages (transcription,
    drums, vocal_f0) read stems_routing.json instead of glob-matching stems_6s/,
    so the routing file must exist before they can safely run. The re-run is a
    one-time cost per track.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from analyze import sidecar


# ---------------------------------------------------------------------------
# Quality params (replaces STEMS_QUALITY_PRESETS — renamed for clarity).
# Maps preset name -> {shifts, overlap} for the htdemucs passes. Per spec §3.
# Approximate htdemucs_6s pass time on a 3-min track / RTX 3090:
#   fast:   ~50s   — quick preview
#   normal: ~100s  — default; the floor for a usable bass stem
#   best:   ~200s  — practical ceiling for 6-stem; past this the model is the limit
# ---------------------------------------------------------------------------
STEMS_QUALITY_PARAMS: dict[str, dict] = {
    "fast":   {"shifts": 2, "overlap": 0.5},
    "normal": {"shifts": 4, "overlap": 0.5},
    "best":   {"shifts": 8, "overlap": 0.5},
}
DEFAULT_STEMS_QUALITY = "best"

# ---------------------------------------------------------------------------
# Models to run for a given preset. Each entry is (model_filename, output_subdir).
# Per spec §3.
# ---------------------------------------------------------------------------
MODELS_PER_PRESET: dict[str, list[tuple[str, str]]] = {
    "fast":   [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
    "normal": [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
    "best":   [
        ("htdemucs_6s.yaml",                                  "stems_6s"),
        ("htdemucs_ft.yaml",                                  "stems_htdemucs_ft"),
        ("model_bs_roformer_ep_317_sdr_12.9755.ckpt",         "stems_bsroformer"),
    ],
}

# ---------------------------------------------------------------------------
# Per-stem routing — declares which produced WAV represents each logical stem.
# Used to write stems_routing.json. Per spec §3.
#
# - vocals: bs_roformer is meaningfully cleaner than htdemucs vocals
#   (SDR 12.9 vs 9.4), so prefer it across all presets. For "fast" (which
#   doesn't run htdemucs_ft), bs_roformer is still the vocals source.
# - drums/bass/other: htdemucs_ft outperforms htdemucs_6s by ~0.5 dB SDR
#   on these stems, so prefer it when the preset includes htdemucs_ft.
#   For "fast" (no htdemucs_ft), fall back to htdemucs_6s.
# - guitar/piano: only htdemucs_6s produces these; htdemucs_ft is 4-stem
#   (vocals/drums/bass/other), no guitar/piano output.
# ---------------------------------------------------------------------------
DEFAULT_ROUTING: dict[str, dict] = {
    # Maps logical stem -> {subdir, glob} so the routing-json writer can find
    # the actual produced filename via glob (audio-separator's filename
    # convention varies by model).
    "vocals":  {"subdir": "stems_bsroformer",   "glob": "*(Vocals)*.wav"},
    "drums":   {"subdir": "stems_htdemucs_ft",  "glob": "*(Drums)*.wav"},
    "bass":    {"subdir": "stems_htdemucs_ft",  "glob": "*(Bass)*.wav"},
    "guitar":  {"subdir": "stems_6s",           "glob": "*(Guitar)*.wav"},
    "piano":   {"subdir": "stems_6s",           "glob": "*(Piano)*.wav"},
    "other":   {"subdir": "stems_htdemucs_ft",  "glob": "*(Other)*.wav"},
}

# Fallback routing for "fast" preset which doesn't run htdemucs_ft.
# drums/bass/other route to stems_6s instead.
FAST_PRESET_ROUTING: dict[str, dict] = {
    **DEFAULT_ROUTING,
    "drums": {"subdir": "stems_6s", "glob": "*(Drums)*.wav"},
    "bass":  {"subdir": "stems_6s", "glob": "*(Bass)*.wav"},
    "other": {"subdir": "stems_6s", "glob": "*(Other)*.wav"},
}

SCHEMA_VERSION = 1  # bump when sidecar/routing format changes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _routing_for_preset(preset: str) -> dict[str, dict]:
    return FAST_PRESET_ROUTING if preset == "fast" else DEFAULT_ROUTING


def _resolve_quality_params(quality: str) -> dict:
    if quality not in STEMS_QUALITY_PARAMS:
        raise ValueError(
            f"unknown stems quality {quality!r}; expected one of {sorted(STEMS_QUALITY_PARAMS)}"
        )
    return STEMS_QUALITY_PARAMS[quality]


def _current_params(quality: str) -> dict:
    """The full param dict written to the sidecar — includes the model list
    so that adding/removing a model from MODELS_PER_PRESET invalidates cache."""
    qp = _resolve_quality_params(quality)
    return {
        "quality": quality,
        "shifts": qp["shifts"],
        "overlap": qp["overlap"],
        "models": [m for m, _sub in MODELS_PER_PRESET[quality]],
    }


def _transcode_to_clean_wav(mp3: Path, dst: Path) -> None:
    """Re-encode the MP3 to a 44.1 kHz stereo PCM WAV. ffmpeg recovers
    gracefully from malformed MP3 headers and emits a continuous WAV;
    this is what audio-separator should have been reading from the
    start."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(mp3),
            "-ar", "44100", "-ac", "2",
            "-c:a", "pcm_s16le",
            str(dst),
        ],
        check=True,
    )


def _write_routing(cache_dir: Path, preset: str) -> None:
    """Build the per-stem routing dict and write stems_routing.json.

    Each routing entry's `path` is RELATIVE to cache_dir (per stems_routing
    contract — see analyze/stems_routing.py). POSIX separators are used for
    cross-platform stability."""
    routing: dict[str, dict] = {}
    for stem, spec in _routing_for_preset(preset).items():
        d = cache_dir / spec["subdir"]
        if not d.is_dir():
            continue  # model wasn't run for this preset
        candidates = sorted(d.glob(spec["glob"]))
        if not candidates:
            continue  # model ran but didn't produce this stem (e.g. htdemucs_ft has no piano)
        rel = candidates[0].relative_to(cache_dir)
        routing[stem] = {"path": str(rel).replace("\\", "/")}
    payload = {
        "version": 1,
        "preset": preset,
        "routing": routing,
    }
    (cache_dir / "stems_routing.json").write_text(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# Public API: cached / load / run
# ---------------------------------------------------------------------------

def cached(cache_dir: Path, *, quality: str = DEFAULT_STEMS_QUALITY) -> bool:
    """True iff every model output dir for this preset has its expected files,
    stems_routing.json is present, AND the sidecar matches the current params.

    Old caches that pre-date WI-6 (no stems_routing.json) always return False
    and trigger a re-run — that's the intended one-time migration cost."""
    for _model, subdir in MODELS_PER_PRESET[quality]:
        d = cache_dir / subdir
        if not d.is_dir():
            return False
        if not any(d.glob("*.wav")):  # at least one WAV per model
            return False
    if not (cache_dir / "stems_routing.json").exists():
        return False
    return sidecar.matches(
        cache_dir, "stems", _current_params(quality),
        expected_schema_version=SCHEMA_VERSION,
    )


def load(cache_dir: Path) -> dict:
    """Load stems metadata from cache.

    Returns a dict with:
      - quality: the preset used, or None if unreadable
      - routing: parsed stems_routing.json, or None if absent
      - <subdir>: path string for each model output dir present
      - <subdir>_files: sorted WAV file paths for each model output dir

    Old keys (stems_6s, stems_bsroformer, stems_6s_files, stems_bsroformer_files)
    are preserved for backward-compat with existing callers."""
    routing_path = cache_dir / "stems_routing.json"
    routing = json.loads(routing_path.read_text()) if routing_path.exists() else None

    quality = None
    sidecar_path = cache_dir / "stems_6s" / ".params.json"
    if sidecar_path.exists():
        try:
            quality = json.loads(sidecar_path.read_text()).get("params", {}).get("quality")
        except (json.JSONDecodeError, OSError):
            quality = None

    out: dict = {"quality": quality, "routing": routing}
    # Populate per-subdir keys using the preset's model list (or default if
    # quality is unknown, which covers legacy caches that haven't re-run yet).
    for _model, subdir in MODELS_PER_PRESET.get(quality or DEFAULT_STEMS_QUALITY, []):
        d = cache_dir / subdir
        if d.is_dir():
            out[subdir] = str(d)
            out[f"{subdir}_files"] = sorted(str(p) for p in d.glob("*.wav"))
    return out


def run(mp3: Path, cache_dir: Path, *, quality: str = DEFAULT_STEMS_QUALITY) -> dict:
    """Run all model passes for the given quality preset.

    Order of operations:
      1. Transcode source MP3 to clean WAV (avoids libsndfile truncation bugs).
      2. Run each model in MODELS_PER_PRESET[quality] in sequence.
         htdemucs models receive --demucs_shifts / --demucs_overlap; bs_roformer
         does not (unsupported flags would cause it to error).
      3. Write stems_routing.json LAST — its presence is the sentinel that
         all model passes succeeded. Downstream cached() checks key off its
         presence.
      4. Write the sidecar via the WI-1 primitive (routes "stems" to
         stems_6s/.params.json under the hood).
    """
    qp = _resolve_quality_params(quality)
    shifts, overlap = qp["shifts"], qp["overlap"]

    clean_wav = mp3.with_suffix(".clean.wav")
    try:
        _transcode_to_clean_wav(mp3, clean_wav)
        for model_filename, subdir in MODELS_PER_PRESET[quality]:
            out_dir = cache_dir / subdir
            out_dir.mkdir(exist_ok=True)
            cmd = [
                "audio-separator", str(clean_wav),
                "--model_filename", model_filename,
                "--output_dir", str(out_dir) + "/",
                "--output_format", "WAV",
            ]
            # demucs-specific knobs only apply to htdemucs models
            if model_filename.startswith("htdemucs"):
                cmd += ["--demucs_shifts", str(shifts), "--demucs_overlap", str(overlap)]
            subprocess.run(cmd, check=True)
    finally:
        clean_wav.unlink(missing_ok=True)

    # Write the routing file LAST — its presence is a sentinel that everything
    # before it succeeded. Downstream stages key cache validity off its presence.
    _write_routing(cache_dir, quality)

    # Write the sidecar via the WI-1 primitive (which routes "stems" to
    # stems_6s/.params.json under the hood).
    sidecar.write(cache_dir, "stems", _current_params(quality), schema_version=SCHEMA_VERSION)

    return load(cache_dir)


if __name__ == "__main__":
    import argparse
    from analyze.cache import ensure_dir, slug_for
    parser = argparse.ArgumentParser()
    parser.add_argument("mp3_path", type=Path)
    parser.add_argument(
        "--quality", choices=sorted(STEMS_QUALITY_PARAMS), default=DEFAULT_STEMS_QUALITY,
    )
    args = parser.parse_args(sys.argv[1:])
    cd = ensure_dir(slug_for(args.mp3_path))
    result = run(args.mp3_path, cd, quality=args.quality)
    print(f"quality: {result['quality']}")
    if result.get("routing"):
        for stem, entry in result["routing"]["routing"].items():
            print(f"  {stem}: {entry['path']}")
