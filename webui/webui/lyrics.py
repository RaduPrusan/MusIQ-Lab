"""Lyrics fetching, parsing, and cache I/O for the webui.

Slug parsing + ID3 fallback live in ``analyze/text/slug_parser.py`` (so the
analyze pipeline can share them via ``from analyze.text.slug_parser import
...`` inside WSL). The webui runs on Windows py3.13 where ``analyze``
refuses to import (heavy GPU deps); we therefore load the slug parser
file *directly* via ``importlib.util.spec_from_file_location``, bypassing
the ``analyze`` package init. Single source of truth, no duplication, no
host-environment override side effects.
"""
from __future__ import annotations

import importlib.util as _importlib_util
import json
import re
import shutil
import sys as _sys
from pathlib import Path
from typing import TypedDict

import httpx

# Load analyze/text/slug_parser.py without triggering analyze/__init__.py.
# The file path is anchored to this module's location: webui/webui/lyrics.py
# -> repo root -> analyze/text/slug_parser.py. Doing it once at import time
# keeps the rest of the module synchronous + side-effect-free.
_SLUG_PARSER_PATH = Path(__file__).resolve().parents[2] / "analyze" / "text" / "slug_parser.py"
_spec = _importlib_util.spec_from_file_location(
    "_musiq_slug_parser", _SLUG_PARSER_PATH,
)
if _spec is None or _spec.loader is None:  # pragma: no cover — packaging error
    raise ImportError(f"could not load slug_parser from {_SLUG_PARSER_PATH}")
_slug_parser_mod = _importlib_util.module_from_spec(_spec)
_sys.modules["_musiq_slug_parser"] = _slug_parser_mod
_spec.loader.exec_module(_slug_parser_mod)

_NOISE_TOKEN_RE = _slug_parser_mod._NOISE_TOKEN_RE
_YT_ID_TAIL_RE = _slug_parser_mod._YT_ID_TAIL_RE
TrackIdentity = _slug_parser_mod.TrackIdentity
_parse_filename = _slug_parser_mod._parse_filename
_slug_to_display = _slug_parser_mod._slug_to_display
_strip_yt_id_tail = _slug_parser_mod._strip_yt_id_tail
clean_title = _slug_parser_mod.clean_title


class LrcLine(TypedDict):
    time_sec: float
    text: str


class ParsedLyrics(TypedDict):
    has_sync: bool
    lines: list[LrcLine]
    plain_text: str


_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_METADATA_TAG_RE = re.compile(r"^\[(ar|ti|al|au|by|offset|re|ve|length):.*\]\s*$", re.IGNORECASE)


def parse_lrc(text: str) -> ParsedLyrics:
    """Parse an LRC-format string into a structured form.

    Lines beginning with metadata tags ([ar:...], [ti:...], etc.) are dropped.
    Lines with one or more `[mm:ss.xx]` timestamps become synced entries.
    Lines with neither timestamps nor metadata tags are dropped from `lines`
    but still contribute to `plain_text`.
    """
    synced_lines: list[LrcLine] = []
    plain_lines: list[str] = []
    has_any_timestamp = False

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if _METADATA_TAG_RE.match(line):
            continue
        timestamps = list(_TIMESTAMP_RE.finditer(line))
        if not timestamps:
            plain_lines.append(line)
            continue
        has_any_timestamp = True
        # Strip all timestamps from the line; the residue is the lyric text.
        # Multiple-timestamp lines (rare) emit one entry per timestamp with
        # the same text — useful for repeated choruses.
        residue = _TIMESTAMP_RE.sub("", line).lstrip()
        for m in timestamps:
            mm = int(m.group(1))
            ss = int(m.group(2))
            cs = m.group(3) or "0"
            frac = float("0." + cs)
            t = mm * 60 + ss + frac
            # `[00:00.00]` with empty text is a common LRC start anchor and
            # should not be surfaced as a lyric line; keep blank entries
            # only when they have a real (non-zero) timestamp.
            if not residue and t == 0:
                continue
            synced_lines.append({"time_sec": t, "text": residue})
        if residue:
            plain_lines.append(residue)

    synced_lines.sort(key=lambda x: x["time_sec"])
    return {
        "has_sync": has_any_timestamp,
        "lines": synced_lines,
        "plain_text": "\n".join(plain_lines),
    }


def _mutagen_file(path: Path, easy: bool = True):
    """Wrapper for mutagen.File so tests can monkeypatch
    ``webui.lyrics._mutagen_file``. The analyze.text variant uses a parallel
    wrapper internally — we delegate so monkeypatches against THIS module's
    symbol still drive ``identify_track``.

    mutagen is imported lazily so this module loads cleanly under the WSL
    analyze venv (which doesn't ship mutagen — webui-only dep).
    """
    import mutagen  # local import; not required for module load
    return mutagen.File(str(path), easy=easy)


def identify_track(mp3_path: Path, duration_sec: float) -> TrackIdentity:
    """Return artist/title/album for an MP3, preferring ID3 tags and falling
    back to filename parsing for any missing field.

    Inlined here (rather than aliased to ``analyze.text.slug_parser``) so
    tests that monkeypatch ``webui.lyrics._mutagen_file`` still capture
    the ID3 call. ``analyze.text.slug_parser.identify_track_from_slug`` is
    the canonical implementation for the analyze stage; this version stays
    structurally identical to it.
    """
    artist = title = album = ""
    try:
        tags = _mutagen_file(mp3_path, easy=True)
    except Exception:
        tags = None
    if tags:
        artist = (tags.get("artist") or [""])[0] or ""
        title = (tags.get("title") or [""])[0] or ""
        album = (tags.get("album") or [""])[0] or ""
    if not artist or not title:
        fb_artist, fb_title = _parse_filename(mp3_path.stem)
        if not artist:
            artist = fb_artist
        if not title:
            title = fb_title
    return {"artist": artist, "title": title, "album": album, "duration_sec": duration_sec}


LRCLIB_BASE = "https://lrclib.net"
LRCLIB_USER_AGENT = "MusIQ-Lab/0.1 (local single-user music analysis app)"


class LrclibResult(TypedDict, total=False):
    source: str
    has_sync: bool
    synced_lrc: str | None
    plain_text: str | None
    lrclib_id: int | None
    error: str  # "not_found" | "network" | "http_<status>"


async def lrclib_lookup(
    *, artist: str, title: str, duration_sec: float, album: str = "", _transport=None
) -> LrclibResult:
    """Query LRCLIB for lyrics. Tries /api/get first; on 404, falls back to
    /api/search and picks the result with the closest duration. Returns a
    structured dict regardless of outcome — never raises for network/4xx/5xx."""
    headers = {"User-Agent": LRCLIB_USER_AGENT}
    timeout = httpx.Timeout(8.0, connect=4.0)
    client_args = {"base_url": LRCLIB_BASE, "headers": headers, "timeout": timeout}
    if _transport is not None:
        client_args["transport"] = _transport

    try:
        async with httpx.AsyncClient(**client_args) as client:
            params = {
                "artist_name": artist,
                "track_name": title,
                "duration": int(round(duration_sec)),
            }
            if album:
                params["album_name"] = album
            r = await client.get("/api/get", params=params)
            if r.status_code == 200:
                data = r.json()
                return _shape_lrclib_record(data)
            if r.status_code != 404:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": f"http_{r.status_code}",
                }
            # 404 → search fallback
            sr = await client.get(
                "/api/search", params={"artist_name": artist, "track_name": title}
            )
            if sr.status_code != 200:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": f"http_{sr.status_code}",
                }
            results = sr.json() or []
            if not results:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": "not_found",
                }
            best = min(
                results,
                key=lambda x: abs(int(x.get("duration", 0)) - int(round(duration_sec))),
            )
            return _shape_lrclib_record(best)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        return {
            "source": "lrclib", "has_sync": False, "synced_lrc": None,
            "plain_text": None, "lrclib_id": None, "error": "network",
        }


def _shape_lrclib_record(data: dict) -> LrclibResult:
    synced = data.get("syncedLyrics")
    plain = data.get("plainLyrics")
    return {
        "source": "lrclib",
        "has_sync": bool(synced),
        "synced_lrc": synced,
        "plain_text": plain,
        "lrclib_id": data.get("id"),
    }


def cache_dir_for(slug_cache_root: Path) -> Path:
    """Given a cache/<slug>/ path, return the lyrics subdirectory path."""
    return slug_cache_root / "lyrics"


def save_synced(cache: Path, lrc_text: str, meta: dict) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "synced.lrc").write_text(lrc_text, encoding="utf-8")
    meta_with_ts = {**meta, "fetched_at": _utc_now_iso(), "has_sync": True}
    (cache / "meta.json").write_text(json.dumps(meta_with_ts, indent=2), encoding="utf-8")


def save_plain(cache: Path, plain_text: str, meta: dict) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "plain.txt").write_text(plain_text, encoding="utf-8")
    meta_with_ts = {**meta, "fetched_at": _utc_now_iso(), "has_sync": False}
    (cache / "meta.json").write_text(json.dumps(meta_with_ts, indent=2), encoding="utf-8")


def detect_paste_format(text: str) -> str:
    """Return 'lrc' if any line carries a [mm:ss(.cs)?] timestamp, else 'plain'."""
    return "lrc" if _TIMESTAMP_RE.search(text) else "plain"


def save_paste(cache: Path, text: str, meta: dict) -> None:
    if detect_paste_format(text) == "lrc":
        save_synced(cache, text, meta)
    else:
        save_plain(cache, text, meta)


def load_cached(cache: Path) -> dict | None:
    """Return parsed lyrics from the cache, or None if no cache."""
    meta_path = cache / "meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    synced_path = cache / "synced.lrc"
    plain_path = cache / "plain.txt"
    if synced_path.is_file():
        parsed = parse_lrc(synced_path.read_text(encoding="utf-8"))
        return {
            "has_sync": True,
            "lines": parsed["lines"],
            "plain_text": parsed["plain_text"],
            "meta": meta,
        }
    if plain_path.is_file():
        return {
            "has_sync": False,
            "lines": [],
            "plain_text": plain_path.read_text(encoding="utf-8"),
            "meta": meta,
        }
    return None


def clear_cache(cache: Path) -> None:
    if cache.is_dir():
        shutil.rmtree(cache)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
