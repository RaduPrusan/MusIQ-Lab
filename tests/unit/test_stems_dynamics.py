"""Tests for analyze/stages/stems_dynamics.py."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from analyze.stages import stems_dynamics


# ---------- Helpers ----------------------------------------------------

def _write_sine_wav(path: Path, *, duration: float, sr: int = 44100, freq: float = 440.0, amp: float = 0.3):
    """Write a mono sine to disk for stage input."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    audio = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), audio, sr, subtype="PCM_16")


def _setup_cache_with_stems(tmp_path: Path, *, stems: list[str], duration: float = 1.0) -> Path:
    """Build a minimal cache_dir with stems_routing.json + WAV files for each stem."""
    cache_dir = tmp_path / "track_slug"
    cache_dir.mkdir()
    stems_subdir = cache_dir / "stems_6s"
    stems_subdir.mkdir()

    routing = {"version": 1, "preset": "test", "routing": {}}
    for stem in stems:
        wav_path = stems_subdir / f"{stem}.wav"
        _write_sine_wav(wav_path, duration=duration)
        routing["routing"][stem] = {"path": f"stems_6s/{stem}.wav"}

    (cache_dir / "stems_routing.json").write_text(json.dumps(routing))
    return cache_dir


# ---------- run() ------------------------------------------------------

class TestRun:
    def test_creates_dynamics_dir_and_per_stem_npz(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals", "bass"], duration=0.5)
        result = stems_dynamics.run(Path("/dev/null"), cache_dir)

        dyn_dir = cache_dir / "dynamics"
        assert dyn_dir.exists()
        assert (dyn_dir / "vocals.npz").exists()
        assert (dyn_dir / "bass.npz").exists()
        assert "vocals" in result
        assert "bass" in result

    def test_rms_array_frame_count_matches_duration(self, tmp_path):
        # 1-second WAV at fps=100 → ~100 frames (librosa center=True can add ±1)
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=1.0)
        stems_dynamics.run(Path("/dev/null"), cache_dir)

        with np.load(cache_dir / "dynamics" / "vocals.npz") as z:
            rms = z["rms"]
        assert 99 <= len(rms) <= 102  # tolerate small librosa edge effects
        assert rms.dtype == np.float32

    def test_summary_includes_per_stem_stats(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.5)
        result = stems_dynamics.run(Path("/dev/null"), cache_dir)
        s = result["vocals"]
        assert s["n_frames"] > 0
        assert s["duration_sec"] == pytest.approx(s["n_frames"] / 100.0)
        assert s["rms_max"] > 0
        assert s["rms_mean"] > 0

    def test_per_stem_failure_isolated(self, tmp_path):
        # Build a routing with two stems but only write one WAV → second fails
        cache_dir = tmp_path / "track_slug"
        cache_dir.mkdir()
        stems_subdir = cache_dir / "stems_6s"
        stems_subdir.mkdir()
        _write_sine_wav(stems_subdir / "vocals.wav", duration=0.5)
        # bass.wav is intentionally NOT created
        (cache_dir / "stems_routing.json").write_text(json.dumps({
            "version": 1,
            "routing": {
                "vocals": {"path": "stems_6s/vocals.wav"},
                "bass": {"path": "stems_6s/bass.wav"},  # missing
            },
        }))

        result = stems_dynamics.run(Path("/dev/null"), cache_dir)
        assert "n_frames" in result["vocals"]   # vocals succeeded
        assert "error" in result["bass"]        # bass failed
        # Vocals npz exists; bass npz does not
        assert (cache_dir / "dynamics" / "vocals.npz").exists()
        assert not (cache_dir / "dynamics" / "bass.npz").exists()

    def test_writes_sidecar(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.3)
        stems_dynamics.run(Path("/dev/null"), cache_dir)
        sidecar_path = cache_dir / ".params_stems_dynamics.json"
        assert sidecar_path.exists()
        data = json.loads(sidecar_path.read_text())
        assert data["schema_version"] == stems_dynamics.SCHEMA_VERSION
        assert data["params"] == stems_dynamics.DEFAULT_PARAMS


# ---------- cached() ---------------------------------------------------

class TestCached:
    def test_false_before_run(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.3)
        assert stems_dynamics.cached(cache_dir) is False

    def test_true_after_run(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.3)
        stems_dynamics.run(Path("/dev/null"), cache_dir)
        assert stems_dynamics.cached(cache_dir) is True

    def test_false_on_params_change(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.3)
        stems_dynamics.run(Path("/dev/null"), cache_dir)
        # Run was at default fps=100; querying with fps=200 should not cache-hit
        assert stems_dynamics.cached(cache_dir, fps=200) is False

    def test_false_when_dynamics_dir_empty(self, tmp_path):
        # Empty dynamics dir = previous run failed; should NOT be cached
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=0.3)
        (cache_dir / "dynamics").mkdir()
        assert stems_dynamics.cached(cache_dir) is False


# ---------- load() -----------------------------------------------------

class TestLoad:
    def test_load_returns_per_stem_dict(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals", "bass"], duration=0.3)
        stems_dynamics.run(Path("/dev/null"), cache_dir)
        loaded = stems_dynamics.load(cache_dir)
        assert set(loaded.keys()) == {"vocals", "bass"}
        for stem, arr in loaded.items():
            assert arr.dtype == np.float32
            assert arr.ndim == 1

    def test_load_returns_empty_when_dir_missing(self, tmp_path):
        cache_dir = tmp_path / "track_slug"
        cache_dir.mkdir()
        loaded = stems_dynamics.load(cache_dir)
        assert loaded == {}

    def test_load_returns_empty_when_no_npz(self, tmp_path):
        cache_dir = tmp_path / "track_slug"
        cache_dir.mkdir()
        (cache_dir / "dynamics").mkdir()
        loaded = stems_dynamics.load(cache_dir)
        assert loaded == {}


# ---------- Frame-rate alignment with FCPE -----------------------------

class TestFrameRateAlignment:
    def test_default_fps_is_100(self):
        # Documented invariant: dynamics frame rate matches FCPE/PESTO
        assert stems_dynamics.DEFAULT_PARAMS["fps"] == 100

    def test_two_second_clip_yields_two_hundred_frames(self, tmp_path):
        cache_dir = _setup_cache_with_stems(tmp_path, stems=["vocals"], duration=2.0)
        stems_dynamics.run(Path("/dev/null"), cache_dir)
        with np.load(cache_dir / "dynamics" / "vocals.npz") as z:
            rms = z["rms"]
        assert 199 <= len(rms) <= 202


# ---------- Stage protocol -------------------------------------------

class TestStageProtocol:
    def test_module_exposes_cached_run_load(self):
        # Pipeline depends on the (cached, run, load) trio being callable
        assert callable(stems_dynamics.cached)
        assert callable(stems_dynamics.run)
        assert callable(stems_dynamics.load)

    def test_schema_version_is_int(self):
        assert isinstance(stems_dynamics.SCHEMA_VERSION, int)
        assert stems_dynamics.SCHEMA_VERSION >= 1
