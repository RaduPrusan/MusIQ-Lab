"""Stage: Essentia MusicExtractor — second opinion on tempo / key / loudness.

Output: cache_dir/essentia.json with either
    {"extracted": true,
     "tempo": {"bpm": ..., "first_peak_bpm": ..., "first_peak_weight": ...,
               "beats_count": ...},
     "key": {"krumhansl": [<key>, <scale>, <strength>],
             "temperley": [...],
             "edma": [...]},
     "loudness_ebu_r128": {"integrated": ..., "range": ..., "dynamic_complexity": ...},
     "high_level": {"available": false, "reason": "gaia2 not bundled with essentia build"}}
or, on failure,
    {"extracted": false, "reason": "..."}

Soft-fails to the not-extracted sentinel on any error, same pattern as
analyze/stages/drums.py.

The Essentia high-level SVM classifiers (danceability, mood_*, voice_instrumental,
tonal_atonal) need gaia2, which is not packaged on PyPI. The MTG-hosted .history
files in analyze/vendor/essentia-models/ require the gaia2 runtime library to
load, and Essentia's MusicExtractorSVM segfaults without it. This build (essentia
2.1-beta6-dev installed via pip) does NOT include gaia2, so the SVM path is
unconditionally reported as unavailable rather than attempted. The valuable parts
of the stage — tempo, key, loudness, EBU R128 — work normally.
"""
from __future__ import annotations

import json
from pathlib import Path

from analyze import sidecar

CANONICAL = "essentia.json"
SCHEMA_VERSION = 1
DEFAULT_PARAMS: dict = {}

_MODELS_DIR = Path(__file__).resolve().parents[1] / "vendor" / "essentia-models"

# Reason returned for the high-level path when SVMs are unreachable. Pre-flight
# import-check keeps this honest: if gaia2 ever lands on the system, we can
# revisit running MusicExtractorSVM here.
_HIGHLEVEL_UNAVAILABLE_REASON = (
    "Essentia high-level SVM classifiers require gaia2; this build does not "
    "include it. MTG .history models cannot be loaded without gaia2."
)


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    return sidecar.matches(cache_dir, "essentia_extract", p, expected_schema_version=SCHEMA_VERSION)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def _build_extractor():
    """Construct an Essentia MusicExtractor (low-level features only — no SVMs).

    Separated out so tests can monkeypatch the whole construction step,
    including the underlying essentia import which is heavy and platform-
    specific.
    """
    from essentia.standard import MusicExtractor

    return MusicExtractor()


def _has_key(pool, key) -> bool:
    """Pool membership check that tolerates mocks lacking __contains__."""
    try:
        return key in pool.descriptorNames()
    except Exception:
        return False


def _pick(pool, key, default=None):
    """Safe accessor for Essentia Pool keys that may or may not be present."""
    if _has_key(pool, key):
        try:
            return pool[key]
        except Exception:
            return default
    return default


def _extract_slim(pool) -> dict:
    """Cherry-pick the ~15 useful fields out of the ~500-key Essentia output."""
    return {
        "extracted": True,
        "tempo": {
            "bpm": float(_pick(pool, "rhythm.bpm", 0.0)),
            "first_peak_bpm": float(_pick(pool, "rhythm.bpm_histogram_first_peak_bpm", 0.0)),
            "first_peak_weight": float(_pick(pool, "rhythm.bpm_histogram_first_peak_weight", 0.0)),
            "beats_count": int(float(_pick(pool, "rhythm.beats_count", 0))),
        },
        "key": {
            "krumhansl": [
                _pick(pool, "tonal.key_krumhansl.key", ""),
                _pick(pool, "tonal.key_krumhansl.scale", ""),
                float(_pick(pool, "tonal.key_krumhansl.strength", 0.0)),
            ],
            "temperley": [
                _pick(pool, "tonal.key_temperley.key", ""),
                _pick(pool, "tonal.key_temperley.scale", ""),
                float(_pick(pool, "tonal.key_temperley.strength", 0.0)),
            ],
            "edma": [
                _pick(pool, "tonal.key_edma.key", ""),
                _pick(pool, "tonal.key_edma.scale", ""),
                float(_pick(pool, "tonal.key_edma.strength", 0.0)),
            ],
        },
        "loudness_ebu_r128": {
            "integrated": float(_pick(pool, "lowlevel.loudness_ebu128.integrated", 0.0)),
            "range": float(_pick(pool, "lowlevel.loudness_ebu128.loudness_range", 0.0)),
            "dynamic_complexity": float(_pick(pool, "lowlevel.dynamic_complexity", 0.0)),
        },
        "high_level": {
            "available": False,
            "reason": _HIGHLEVEL_UNAVAILABLE_REASON,
        },
    }


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        extractor = _build_extractor()
    except ImportError as e:
        out = {"extracted": False, "reason": f"essentia not installed: {e}"}
        _write(cache_dir, out, p)
        return out
    except Exception as e:
        out = {"extracted": False, "reason": f"essentia init failed: {type(e).__name__}: {e}"}
        _write(cache_dir, out, p)
        return out

    try:
        pool, _frames = extractor(str(mp3))
    except Exception as e:
        out = {"extracted": False, "reason": f"extractor failed: {type(e).__name__}: {e}"}
        _write(cache_dir, out, p)
        return out

    out = _extract_slim(pool)
    _write(cache_dir, out, p)
    return out


def _write(cache_dir: Path, payload: dict, params: dict) -> None:
    (cache_dir / CANONICAL).write_text(json.dumps(payload, indent=2))
    sidecar.write(cache_dir, "essentia_extract", params, schema_version=SCHEMA_VERSION)


BPM_TOLERANCE = 1.0  # |Essentia.bpm - pipeline.tempo_bpm| <= 1 -> ok


def _keys_equivalent(k1: str, k2: str) -> bool:
    """True if k1 and k2 represent the same diatonic pc-set.

    Two keys are equivalent iff one is the relative major/minor of the
    other. C major ≡ A minor (relative), F minor ≡ Ab major (relative).
    Parallel keys are NOT equivalent: C major ≢ C minor (different pc sets).
    Exact string match always returns True.
    """
    if k1 == k2:
        return True
    try:
        from analyze.derived.theory import parse_key
        a = parse_key(k1)
        b = parse_key(k2)
    except Exception:
        return False
    if a.tonic_pc is None or b.tonic_pc is None:
        return False
    # Normalize each key to "its relative major's tonic pc": for major
    # keys that's the tonic itself; for minor keys add 3 semitones (so A
    # minor → C, F minor → Ab, etc.). Two keys agree on diatonic content
    # iff their normalized relative-major tonics match.
    norm_a = a.tonic_pc if a.mode == "major" else (a.tonic_pc + 3) % 12
    norm_b = b.tonic_pc if b.mode == "major" else (b.tonic_pc + 3) % 12
    return norm_a == norm_b


def compute_agreement(pipeline_summary: dict, essentia_data: dict) -> dict:
    """Compare Essentia's tempo + key against the analyze pipeline's output.

    Returns ``{}`` if Essentia didn't extract (caller renders nothing).
    Otherwise ``{"bpm": {analyze, essentia, delta, ok}, "key": {analyze, essentia_consensus, ok}}``.

    Key agreement uses 2-of-3 estimator consensus: if at least two of
    krumhansl / temperley / edma agree on (pitch, mode), that pair is the
    "essentia consensus." The cross-check is ok if the consensus matches
    the pipeline's key. EDMA is the most permissive estimator (often
    biased toward major / electronic music), so requiring 2-of-3 protects
    against EDMA single-handedly tipping the result.
    """
    if not essentia_data.get("extracted"):
        return {}

    out: dict = {}

    pipeline_bpm = pipeline_summary.get("tempo_bpm")
    essentia_bpm = essentia_data.get("tempo", {}).get("bpm")
    if pipeline_bpm is not None and essentia_bpm is not None:
        delta = abs(float(essentia_bpm) - float(pipeline_bpm))
        out["bpm"] = {
            "analyze": round(float(pipeline_bpm), 2),
            "essentia": round(float(essentia_bpm), 2),
            "delta": round(delta, 2),
            "ok": delta <= BPM_TOLERANCE,
        }

    pipeline_key = pipeline_summary.get("key")  # "A:minor"
    keys = essentia_data.get("key") or {}
    estimators = [keys.get("krumhansl"), keys.get("temperley"), keys.get("edma")]
    pairs = [(k[0], k[1]) for k in estimators if k and k[0] and k[1]]

    if pipeline_key and pairs:
        from collections import Counter
        counts = Counter(pairs)
        consensus_pair, votes = counts.most_common(1)[0]
        if votes >= 2:
            consensus = f"{consensus_pair[0]}:{consensus_pair[1]}"
        else:
            best = max(
                (k for k in estimators if k),
                key=lambda k: float(k[2] or 0.0),
                default=None,
            )
            consensus = f"{best[0]}:{best[1]}" if best else ""
        out["key"] = {
            "analyze": pipeline_key,
            "essentia_consensus": consensus,
            "ok": _keys_equivalent(consensus, pipeline_key),
        }

    return out
