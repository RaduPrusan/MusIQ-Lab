"""Tests for analyze/stages/vocal_f0.py — confidence-array plumbing.

These tests exercise the full FCPE + PESTO inference path. The models are
modest (a few MB each) and run in well under a second on the project GPU,
so the cost per test is acceptable for unit-test cadence. CPU-only fallback
is not exercised — the project assumes CUDA per CLAUDE.md.

The load-fallback test does NOT invoke run(), so it stays cheap and serves
as the regression guard for old-format npz files in the wild.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from analyze import sidecar
from analyze.stages import vocal_f0


def _write_vocal_wav(path: Path, *, duration: float, sr: int = 16000,
                     freq: float = 220.0, amp: float = 0.3) -> None:
    """Synthetic vocal-like sine; PESTO/FCPE both prefer 16 kHz mono input."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    audio = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), audio, sr, subtype="PCM_16")


def _write_silent_wav(path: Path, *, duration: float, sr: int = 16000) -> None:
    audio = np.zeros(int(sr * duration), dtype=np.float32)
    sf.write(str(path), audio, sr, subtype="PCM_16")


def _setup_cache_with_vocals(tmp_path: Path, *, voiced: bool, duration: float = 1.0) -> Path:
    cache_dir = tmp_path / "track_slug"
    cache_dir.mkdir()
    stems_dir = cache_dir / "stems_6s"
    stems_dir.mkdir()
    wav = stems_dir / "vocals.wav"
    if voiced:
        _write_vocal_wav(wav, duration=duration)
    else:
        _write_silent_wav(wav, duration=duration)
    return cache_dir


# ---------- run() smoke + content checks ------------------------------

def test_run_writes_confidence_arrays_and_is_high_on_clean_voicing(tmp_path):
    """Covers spec tests 1 + 3: run() produces fcpe_conf + pesto_conf in
    the npz, and on a clean 220 Hz sine the confidence is high in voiced
    regions."""
    cache_dir = _setup_cache_with_vocals(tmp_path, voiced=True, duration=1.0)
    result = vocal_f0.run(Path("/dev/null"), cache_dir)

    npz_path = cache_dir / vocal_f0.CANONICAL_NPZ
    assert npz_path.exists()
    with np.load(npz_path) as z:
        assert "fcpe_conf" in z.files
        assert "pesto_conf" in z.files
        fcpe_conf = z["fcpe_conf"]
        pesto_conf = z["pesto_conf"]
        fcpe = z["fcpe"]
        pesto = z["pesto"]

    assert fcpe_conf.dtype == np.float32
    assert pesto_conf.dtype == np.float32
    assert fcpe_conf.shape == fcpe.shape
    assert pesto_conf.shape == pesto.shape
    assert fcpe_conf.min() >= 0.0 and fcpe_conf.max() <= 1.0
    assert pesto_conf.min() >= 0.0 and pesto_conf.max() <= 1.0

    voiced_frac_fcpe = float((fcpe_conf > 0.5).mean())
    assert voiced_frac_fcpe > 0.6, f"FCPE conf too sparse on clean sine: {voiced_frac_fcpe:.2f}"

    high_conf_frac_pesto = float((pesto_conf > 0.5).mean())
    assert high_conf_frac_pesto > 0.6, f"PESTO conf too sparse on clean sine: {high_conf_frac_pesto:.2f}"

    assert "fcpe_conf_array" in result
    assert "pesto_conf_array" in result


def test_run_confidence_low_in_silence(tmp_path):
    """Covers spec test 4: silent input → confidence values dominated by
    low-conf frames. Asserted as a majority threshold (rather than ≈0
    pointwise) because PESTO may emit nonzero confidence on edge frames
    even with zero signal."""
    cache_dir = _setup_cache_with_vocals(tmp_path, voiced=False, duration=1.0)
    vocal_f0.run(Path("/dev/null"), cache_dir)

    with np.load(cache_dir / vocal_f0.CANONICAL_NPZ) as z:
        fcpe_conf = z["fcpe_conf"]
        pesto_conf = z["pesto_conf"]

    # FCPE: binary mask from f0 > 0; on silence, threshold gates everything off.
    assert float((fcpe_conf > 0.0).mean()) < 0.05, \
        "FCPE binary conf should be near-zero on silence"

    # PESTO: model output; expect majority of frames below 0.5.
    low_conf_frac = float((pesto_conf < 0.5).mean())
    assert low_conf_frac > 0.5, \
        f"PESTO conf should be mostly low on silence; got low_frac={low_conf_frac:.2f}"


# ---------- load() backward-compat ------------------------------------

def test_load_with_old_npz_falls_back_gracefully(tmp_path):
    """Covers spec test 2: a v1-format npz (no fcpe_conf / pesto_conf
    keys) still loads through vocal_f0.load(), with confidence arrays
    synthesized from the voiced mask. This protects analyze runs that
    haven't yet re-cached after the schema bump."""
    cache_dir = tmp_path / "old_cache"
    cache_dir.mkdir()

    # Hand-build a v1-shaped npz: only fcpe + pesto, no conf arrays.
    n = 50
    fcpe_arr = np.zeros(n, dtype=np.float32)
    pesto_arr = np.zeros(n, dtype=np.float32)
    fcpe_arr[10:30] = 220.0   # voiced span
    pesto_arr[15:35] = 220.0  # different voiced span
    np.savez_compressed(cache_dir / vocal_f0.CANONICAL_NPZ, fcpe=fcpe_arr, pesto=pesto_arr)
    (cache_dir / vocal_f0.CANONICAL_SUMMARY).write_text(json.dumps({
        "fcpe_frames": n,
        "pesto_frames": n,
        "agreement_50c": 0.0,
    }))

    out = vocal_f0.load(cache_dir)

    assert "fcpe_conf_array" in out
    assert "pesto_conf_array" in out
    fcpe_conf = out["fcpe_conf_array"]
    pesto_conf = out["pesto_conf_array"]
    assert fcpe_conf.shape == (n,)
    assert pesto_conf.shape == (n,)
    np.testing.assert_array_equal(fcpe_conf, (fcpe_arr > 0).astype(np.float32))
    np.testing.assert_array_equal(pesto_conf, (pesto_arr > 0).astype(np.float32))


def test_load_with_new_npz_returns_stored_confidence(tmp_path):
    """v2 npz: confidence arrays loaded as-is, not re-synthesized from masks."""
    cache_dir = tmp_path / "new_cache"
    cache_dir.mkdir()
    n = 30
    fcpe_arr = np.zeros(n, dtype=np.float32)
    pesto_arr = np.zeros(n, dtype=np.float32)
    fcpe_arr[5:20] = 200.0
    pesto_arr[5:20] = 200.0
    # Non-binary PESTO conf so we can detect re-synthesis vs load.
    pesto_conf = np.full(n, 0.42, dtype=np.float32)
    fcpe_conf = (fcpe_arr > 0).astype(np.float32)
    np.savez_compressed(
        cache_dir / vocal_f0.CANONICAL_NPZ,
        fcpe=fcpe_arr, pesto=pesto_arr,
        fcpe_conf=fcpe_conf, pesto_conf=pesto_conf,
    )
    (cache_dir / vocal_f0.CANONICAL_SUMMARY).write_text(json.dumps({
        "fcpe_frames": n, "pesto_frames": n, "agreement_50c": 1.0,
    }))

    out = vocal_f0.load(cache_dir)
    assert float(out["pesto_conf_array"].mean()) == pytest.approx(0.42)


# ---------- schema version --------------------------------------------

def test_schema_version_is_2():
    """Guards the schema bump — Phase 0c Step 1 contract."""
    assert vocal_f0.SCHEMA_VERSION == 2


def test_cached_invalidates_on_old_sidecar(tmp_path):
    """A sidecar from a v1 run must not satisfy v2 cache check."""
    cache_dir = tmp_path / "stale_cache"
    cache_dir.mkdir()
    (cache_dir / vocal_f0.CANONICAL_NPZ).write_bytes(b"\x00")
    (cache_dir / vocal_f0.CANONICAL_SUMMARY).write_text("{}")
    sidecar.write(cache_dir, "vocal_f0", {}, schema_version=1)
    assert vocal_f0.cached(cache_dir) is False
