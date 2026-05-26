"""Unit tests for the stems orchestrator's pure-Python parts.

The audio-separator subprocess calls are heavyweight (GPU + minutes per track),
so we don't exercise run() end-to-end here. The tests cover the dispatch
logic that would otherwise hide bugs."""
from __future__ import annotations
from pathlib import Path
import json
import pytest

from analyze.stages import stems


def test_unknown_quality_raises():
    with pytest.raises(ValueError, match="unknown stems quality"):
        stems._resolve_quality_params("garbage")


def test_models_per_preset_includes_bsroformer_in_all():
    """BS-RoFormer is the vocals routing target; must run in every preset."""
    for preset, model_list in stems.MODELS_PER_PRESET.items():
        assert any("bs_roformer" in m for m, _sub in model_list), preset


def test_normal_preset_includes_htdemucs_ft():
    assert any("htdemucs_ft" in m for m, _sub in stems.MODELS_PER_PRESET["normal"])


def test_best_preset_includes_htdemucs_ft():
    assert any("htdemucs_ft" in m for m, _sub in stems.MODELS_PER_PRESET["best"])


def test_fast_preset_excludes_htdemucs_ft():
    assert not any("htdemucs_ft" in m for m, _sub in stems.MODELS_PER_PRESET["fast"])


def test_default_routing_covers_all_six_stems():
    expected = {"vocals", "drums", "bass", "guitar", "piano", "other"}
    assert set(stems.DEFAULT_ROUTING) == expected


def test_fast_preset_routing_falls_back_to_stems_6s_for_drums_bass_other():
    fast_routing = stems._routing_for_preset("fast")
    assert fast_routing["drums"]["subdir"] == "stems_6s"
    assert fast_routing["bass"]["subdir"] == "stems_6s"
    assert fast_routing["other"]["subdir"] == "stems_6s"


def test_normal_preset_routing_uses_htdemucs_ft_for_drums_bass_other():
    normal_routing = stems._routing_for_preset("normal")
    assert normal_routing["drums"]["subdir"] == "stems_htdemucs_ft"
    assert normal_routing["bass"]["subdir"] == "stems_htdemucs_ft"
    assert normal_routing["other"]["subdir"] == "stems_htdemucs_ft"


def test_vocals_always_routes_to_bsroformer():
    """Vocals should use BS-RoFormer in all presets (highest SDR)."""
    for preset in stems.MODELS_PER_PRESET:
        routing = stems._routing_for_preset(preset)
        assert routing["vocals"]["subdir"] == "stems_bsroformer", preset


def test_guitar_and_piano_always_route_to_stems_6s():
    """htdemucs_ft is 4-stem only; guitar/piano only come from htdemucs_6s."""
    for preset in stems.MODELS_PER_PRESET:
        routing = stems._routing_for_preset(preset)
        assert routing["guitar"]["subdir"] == "stems_6s", preset
        assert routing["piano"]["subdir"] == "stems_6s", preset


def test_current_params_includes_models():
    """Models list in sidecar so adding/removing a model invalidates cache."""
    p = stems._current_params("normal")
    assert "models" in p
    assert any("htdemucs_ft" in m for m in p["models"])


def test_current_params_fast_excludes_htdemucs_ft():
    p = stems._current_params("fast")
    assert not any("htdemucs_ft" in m for m in p["models"])


def test_current_params_includes_quality_shifts_overlap():
    p = stems._current_params("normal")
    assert p["quality"] == "normal"
    assert p["shifts"] == 4
    assert p["overlap"] == 0.5


def test_write_routing_emits_relative_paths(tmp_path: Path):
    """_write_routing builds correct routing dict from on-disk WAVs."""
    (tmp_path / "stems_6s").mkdir()
    (tmp_path / "stems_6s" / "foo_(Piano)_htdemucs_6s.wav").touch()
    (tmp_path / "stems_6s" / "foo_(Guitar)_htdemucs_6s.wav").touch()
    (tmp_path / "stems_htdemucs_ft").mkdir()
    (tmp_path / "stems_htdemucs_ft" / "foo_(Drums)_htdemucs_ft.wav").touch()
    (tmp_path / "stems_htdemucs_ft" / "foo_(Bass)_htdemucs_ft.wav").touch()
    (tmp_path / "stems_htdemucs_ft" / "foo_(Other)_htdemucs_ft.wav").touch()
    (tmp_path / "stems_bsroformer").mkdir()
    (tmp_path / "stems_bsroformer" / "foo_(Vocals)_bs.wav").touch()

    stems._write_routing(tmp_path, "normal")
    routing = json.loads((tmp_path / "stems_routing.json").read_text())
    assert routing["version"] == 1
    assert routing["preset"] == "normal"
    assert routing["routing"]["vocals"]["path"].startswith("stems_bsroformer/")
    assert routing["routing"]["drums"]["path"].startswith("stems_htdemucs_ft/")
    assert routing["routing"]["piano"]["path"].startswith("stems_6s/")
    # POSIX separators only
    assert "\\" not in routing["routing"]["vocals"]["path"]
    assert "\\" not in routing["routing"]["drums"]["path"]


def test_write_routing_skips_missing_stem_models(tmp_path: Path):
    """If a routed model produced no matching glob, the stem is omitted (not crashed)."""
    (tmp_path / "stems_htdemucs_ft").mkdir()
    # No matching files — drums/bass/other will be skipped
    (tmp_path / "stems_bsroformer").mkdir()
    (tmp_path / "stems_bsroformer" / "foo_(Vocals)_bs.wav").touch()

    stems._write_routing(tmp_path, "normal")
    routing = json.loads((tmp_path / "stems_routing.json").read_text())
    assert "vocals" in routing["routing"]
    assert "drums" not in routing["routing"]


def test_write_routing_fast_preset_uses_stems_6s_for_drums(tmp_path: Path):
    """Fast preset routes drums/bass/other through stems_6s."""
    (tmp_path / "stems_6s").mkdir()
    (tmp_path / "stems_6s" / "foo_(Drums)_htdemucs_6s.wav").touch()
    (tmp_path / "stems_6s" / "foo_(Bass)_htdemucs_6s.wav").touch()
    (tmp_path / "stems_bsroformer").mkdir()
    (tmp_path / "stems_bsroformer" / "foo_(Vocals)_bs.wav").touch()

    stems._write_routing(tmp_path, "fast")
    routing = json.loads((tmp_path / "stems_routing.json").read_text())
    assert routing["preset"] == "fast"
    assert routing["routing"]["drums"]["path"].startswith("stems_6s/")
    assert routing["routing"]["bass"]["path"].startswith("stems_6s/")


def test_cached_requires_routing_json(tmp_path: Path):
    """cached() returns False when stems_routing.json is missing even if WAVs exist."""
    (tmp_path / "stems_6s").mkdir()
    (tmp_path / "stems_6s" / "foo_(Piano).wav").touch()
    (tmp_path / "stems_htdemucs_ft").mkdir()
    (tmp_path / "stems_htdemucs_ft" / "foo_(Drums).wav").touch()
    (tmp_path / "stems_bsroformer").mkdir()
    (tmp_path / "stems_bsroformer" / "foo_(Vocals).wav").touch()
    # No sidecar, no routing — cached must be False
    assert stems.cached(tmp_path, quality="normal") is False


def test_cached_false_when_model_dir_missing(tmp_path: Path):
    """cached() is False if any expected model output dir is absent."""
    # Only create stems_6s, leave stems_htdemucs_ft and stems_bsroformer absent
    (tmp_path / "stems_6s").mkdir()
    (tmp_path / "stems_6s" / "foo_(Piano).wav").touch()
    assert stems.cached(tmp_path, quality="normal") is False


def test_cached_false_when_model_dir_empty(tmp_path: Path):
    """cached() is False if a model dir exists but has no WAVs."""
    (tmp_path / "stems_6s").mkdir()
    (tmp_path / "stems_htdemucs_ft").mkdir()
    (tmp_path / "stems_bsroformer").mkdir()
    (tmp_path / "stems_bsroformer" / "foo_(Vocals).wav").touch()
    # stems_6s and stems_htdemucs_ft are empty -> cached False
    assert stems.cached(tmp_path, quality="normal") is False


def test_schema_version_is_1():
    assert stems.SCHEMA_VERSION == 1


def test_quality_params_keys_match_models_per_preset():
    """Every quality preset in STEMS_QUALITY_PARAMS must have a matching MODELS_PER_PRESET entry."""
    assert set(stems.STEMS_QUALITY_PARAMS) == set(stems.MODELS_PER_PRESET)
