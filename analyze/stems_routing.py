"""Reader for stems_routing.json — the contract between the stems
orchestrator and every downstream stage.

The orchestrator writes this file as the LAST action of stems.run().
Downstream stages read it instead of glob-matching against stems_6s/,
which decouples them from the orchestrator's internal model layout.

Schema (v1):
    {
      "version": 1,
      "preset": "normal",
      "routing": {
        "vocals":  {"path": "<rel/path/to/stem.wav>"},
        "drums":   {"path": "..."},
        "bass":    {"path": "..."},
        "guitar":  {"path": "..."},
        "piano":   {"path": "..."},
        "other":   {"path": "..."}
      }
    }

Paths in the routing file are relative to the cache_dir. path_for() resolves
to absolute and verifies the file exists on disk.
"""
from __future__ import annotations

import json
from pathlib import Path


CANONICAL = "stems_routing.json"


class RoutingError(Exception):
    """Raised when stems_routing.json is missing, malformed, or points to a
    stem file that doesn't exist on disk."""


def load(cache_dir: Path) -> dict:
    """Load and return the routing dict. Raises RoutingError on missing or
    malformed routing file."""
    path = cache_dir / CANONICAL
    if not path.exists():
        raise RoutingError(f"{CANONICAL} not found at {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RoutingError(f"failed to parse {path}: {e}") from e


def path_for(cache_dir: Path, stem: str) -> Path:
    """Return the absolute path to the stem WAV. Raises RoutingError if the
    stem is not in the routing or the referenced file is missing on disk."""
    routing = load(cache_dir)
    entry = routing.get("routing", {}).get(stem)
    if entry is None:
        known = sorted((routing.get("routing") or {}).keys())
        raise RoutingError(f"unknown stem {stem!r}; routing has {known}")
    rel = entry.get("path")
    if not rel:
        raise RoutingError(f"routing entry for {stem!r} missing 'path' field")
    abs_path = (cache_dir / rel).resolve()
    if not abs_path.exists():
        raise RoutingError(f"stem {stem!r} routed to {rel!r} but file is missing on disk: {abs_path}")
    return abs_path
