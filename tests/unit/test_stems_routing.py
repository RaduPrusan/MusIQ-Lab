from pathlib import Path
import json
import pytest
from analyze.stems_routing import load, path_for, RoutingError


def _write_fixture(d: Path) -> None:
    (d / "stems_6s").mkdir()
    (d / "stems_6s" / "foo_(Piano)_htdemucs_6s.wav").touch()
    (d / "stems_bsroformer").mkdir()
    (d / "stems_bsroformer" / "foo_(Vocals)_bs_roformer.wav").touch()
    (d / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": "normal",
        "routing": {
            "vocals": {"path": "stems_bsroformer/foo_(Vocals)_bs_roformer.wav"},
            "piano":  {"path": "stems_6s/foo_(Piano)_htdemucs_6s.wav"},
        },
    }))


def test_load_returns_routing_dict(tmp_path: Path):
    _write_fixture(tmp_path)
    r = load(tmp_path)
    assert r["preset"] == "normal"
    assert "vocals" in r["routing"]


def test_path_for_returns_absolute_path(tmp_path: Path):
    _write_fixture(tmp_path)
    p = path_for(tmp_path, "vocals")
    assert p.exists()
    assert p.is_absolute()


def test_unknown_stem_raises(tmp_path: Path):
    _write_fixture(tmp_path)
    with pytest.raises(RoutingError, match="unknown stem"):
        path_for(tmp_path, "drums")  # not in fixture


def test_missing_routing_file_raises(tmp_path: Path):
    with pytest.raises(RoutingError, match="not found"):
        load(tmp_path)


def test_corrupt_routing_raises(tmp_path: Path):
    (tmp_path / "stems_routing.json").write_text("{ bad json")
    with pytest.raises(RoutingError, match="parse"):
        load(tmp_path)


def test_referenced_file_missing_raises(tmp_path: Path):
    """A routing file that points to a non-existent stem must fail loudly."""
    (tmp_path / "stems_routing.json").write_text(json.dumps({
        "version": 1,
        "preset": "normal",
        "routing": {"vocals": {"path": "stems_6s/missing.wav"}},
    }))
    with pytest.raises(RoutingError, match="missing on disk"):
        path_for(tmp_path, "vocals")
