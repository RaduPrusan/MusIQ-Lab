import os
from pathlib import Path

import pytest

from analyze import keys


def test_get_acoustid_key_reads_from_env(monkeypatch):
    monkeypatch.setenv("ACOUSTID_API_KEY", "abc123")
    assert keys.get_acoustid_key() == "abc123"


def test_get_acoustid_key_missing_returns_none(monkeypatch):
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    assert keys.get_acoustid_key() is None


def test_get_user_agent_default():
    ua = keys.get_user_agent()
    assert ua.startswith("MusIQ-Lab/")
    assert "github" in ua.lower() or "raduprusan" in ua.lower()


def test_dotenv_loaded_from_project_root(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ACOUSTID_API_KEY=from_dotenv_file\n")
    monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
    monkeypatch.setattr(keys, "_PROJECT_ROOT", tmp_path)
    keys._loaded = False  # force reload
    assert keys.get_acoustid_key() == "from_dotenv_file"
