"""Per-slug user-authored metadata (display_name override etc.).

Lives at cache/<slug>/user_meta.json — separated from analyze-pipeline output
(summary.json, which is regenerated on every reanalyze) so user edits survive
reanalysis. Listed in analyze_runner._clear_cache_dir's PRESERVE set.

Schema is open (an arbitrary JSON object); today the only key is `display_name`.
"""
from __future__ import annotations

import json
from pathlib import Path

_FILENAME = "user_meta.json"
_MAX_DISPLAY_NAME_LEN = 200
_FORBIDDEN_CHARS = ("\\", "/", "\n", "\r", "\x00")


def path_for(slug_cache: Path) -> Path:
    """Given cache/<slug>/, return the user_meta.json path inside it."""
    return slug_cache / _FILENAME


def read(slug_cache: Path) -> dict:
    """Return the parsed user_meta.json contents, or {} if missing/corrupt.

    Corrupt-as-empty matches our other cache reads — a stray bad file should
    never break the API; the user will just see the default behavior and can
    re-rename to overwrite.
    """
    p = path_for(slug_cache)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write(slug_cache: Path, data: dict) -> None:
    """Write user_meta.json. Creates the parent dir if needed."""
    slug_cache.mkdir(parents=True, exist_ok=True)
    path_for(slug_cache).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def validate_display_name(value: object) -> str:
    """Return a trimmed, validated display name. Raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("display_name must be a string")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("display_name is empty")
    if len(trimmed) > _MAX_DISPLAY_NAME_LEN:
        raise ValueError(f"display_name too long (max {_MAX_DISPLAY_NAME_LEN})")
    for ch in _FORBIDDEN_CHARS:
        if ch in trimmed:
            raise ValueError(f"display_name contains invalid character: {ch!r}")
    return trimmed


def split_artist_title(display_name: str) -> tuple[str, str]:
    """Split on the FIRST ' - ' into (artist, title).

    No ' - ' means the user typed a single label; we keep it as the title and
    return an empty artist (predictable: 'what you type is what you get' —
    we don't silently preserve a prior artist value across renames).
    """
    if " - " in display_name:
        artist, _, title = display_name.partition(" - ")
        return artist.strip(), title.strip()
    return "", display_name.strip()
