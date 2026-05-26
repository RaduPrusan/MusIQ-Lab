import os
from pathlib import Path

from webui import _paths


def test_project_root_resolves_to_musiq_lab(tmp_path, monkeypatch):
    """project_root() resolves up from the package location."""
    root = _paths.project_root()
    assert root.name == "MusIQ-Lab"
    assert (root / "webui").is_dir()
    assert (root / "analyze").is_dir() or (root / "cache").is_dir()


def test_cache_dir_default_is_project_root_cache():
    monkeypatch_pop = os.environ.pop("WEBUI_CACHE_DIR", None)
    try:
        cd = _paths.cache_dir()
        assert cd == _paths.project_root() / "cache"
    finally:
        if monkeypatch_pop:
            os.environ["WEBUI_CACHE_DIR"] = monkeypatch_pop


def test_cache_dir_env_override(monkeypatch, tmp_path):
    """WEBUI_CACHE_DIR overrides the default."""
    monkeypatch.setenv("WEBUI_CACHE_DIR", str(tmp_path))
    assert _paths.cache_dir() == tmp_path
