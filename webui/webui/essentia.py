"""Read cache/<slug>/essentia.json (written by the analyze pipeline)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def read_essentia(cache_dir: Path) -> dict | None:
    path = cache_dir / "essentia.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.warning("essentia.json corrupt at %s: %s", path, e)
        return None
