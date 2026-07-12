"""Read cache/<slug>/identify.json (written by the analyze pipeline).

Returns None when missing or corrupt; returns the payload dict otherwise
(caller checks `payload['identified']` for the not-identified sentinel).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def read_identify(cache_dir: Path) -> dict | None:
    path = cache_dir / "identify.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning("identify.json corrupt at %s: %s", path, e)
        return None
