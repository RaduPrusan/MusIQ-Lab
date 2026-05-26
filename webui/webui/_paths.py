import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def cache_dir() -> Path:
    override = os.environ.get("WEBUI_CACHE_DIR")
    if override:
        return Path(override)
    return project_root() / "cache"
