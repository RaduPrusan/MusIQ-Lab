"""Project-level API key + User-Agent helpers.

Loads .env from the project root once on first call. Tests can override
_PROJECT_ROOT and reset _loaded to force a re-load against a tmp_path.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).parent.parent
_loaded = False
_USER_AGENT = "MusIQ-Lab/0.1 ( https://github.com/RaduPrusan/MusIQ-Lab )"


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    _loaded = True


def get_acoustid_key() -> str | None:
    _ensure_loaded()
    return os.environ.get("ACOUSTID_API_KEY")


def get_lastfm_key() -> str | None:
    _ensure_loaded()
    return os.environ.get("LASTFM_API_KEY")


def get_user_agent() -> str:
    return _USER_AGENT
