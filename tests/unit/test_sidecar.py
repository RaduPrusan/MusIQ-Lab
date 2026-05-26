from pathlib import Path
import json
from analyze import sidecar


def test_write_creates_sidecar(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert (tmp_path / ".params_beats.json").exists()
    data = json.loads((tmp_path / ".params_beats.json").read_text())
    assert data == {"schema_version": 1, "params": {"fps": 100}}


def test_matches_returns_true_for_identical_params(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 100}, expected_schema_version=1) is True


def test_matches_returns_false_when_params_differ(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 50}, expected_schema_version=1) is False


def test_matches_returns_false_when_schema_version_differs(tmp_path: Path):
    sidecar.write(tmp_path, "beats", {"fps": 100}, schema_version=1)
    assert sidecar.matches(tmp_path, "beats", {"fps": 100}, expected_schema_version=2) is False


def test_matches_returns_false_when_sidecar_absent(tmp_path: Path):
    assert sidecar.matches(tmp_path, "beats", {}, expected_schema_version=1) is False


def test_stems_uses_subdir_path(tmp_path: Path):
    """stems lives at cache/stems_6s/.params.json (existing convention)."""
    (tmp_path / "stems_6s").mkdir()
    sidecar.write(tmp_path, "stems", {"quality": "best"}, schema_version=1)
    assert (tmp_path / "stems_6s" / ".params.json").exists()


def test_matches_with_corrupt_json_returns_false(tmp_path: Path):
    (tmp_path / ".params_beats.json").write_text("{ bad json")
    assert sidecar.matches(tmp_path, "beats", {}, expected_schema_version=1) is False


def test_key_order_insensitive(tmp_path: Path):
    """Param dicts compared as dicts, not as JSON strings."""
    sidecar.write(tmp_path, "x", {"a": 1, "b": 2}, schema_version=1)
    assert sidecar.matches(tmp_path, "x", {"b": 2, "a": 1}, expected_schema_version=1) is True
