"""Last.fm API client + per-track disk cache.

Loads LASTFM_API_KEY from the project-root .env via python-dotenv. (We
inline the .env-loading logic here rather than depend on `analyze.keys`,
because the webui venv does not have the analyze package on its
sys.path.) The cache lives at cache/<slug>/lastfm.json with a default
TTL of 7 days.

Failure modes
-------------
- No API key:        raises LastFmError; endpoint catches and returns available=false
- HTTP non-200:      raises LastFmError
- Last.fm error obj: raises LastFmError (Last.fm returns 200 with {"error": N, "message": "..."})
- Cache stale:       returns None from load_cache; caller re-fetches
- Cache corrupt:     returns None (caller re-fetches)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_TTL_SECONDS = 7 * 86400  # back-compat: prefer get_default_ttl_seconds()
CACHE_FILE = "lastfm.json"
log = logging.getLogger(__name__)


def get_default_ttl_seconds() -> int:
    """Read LASTFM_TTL_DAYS at call time; fall back to 7 days on missing/invalid."""
    days = os.environ.get("LASTFM_TTL_DAYS")
    if days:
        try:
            return int(days) * 86400
        except ValueError:
            pass
    return 7 * 86400

# Project root is two levels up from this file: webui/webui/lastfm.py -> project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_loaded = False


def _ensure_env_loaded() -> None:
    global _loaded
    if _loaded:
        return
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    _loaded = True


class LastFmError(RuntimeError):
    pass


def _get_key() -> str:
    _ensure_env_loaded()
    key = os.environ.get("LASTFM_API_KEY")
    if not key:
        raise LastFmError("no api key (set LASTFM_API_KEY in .env)")
    return key


def _request(params: dict) -> dict:
    params = {"api_key": _get_key(), "format": "json", **params}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(ENDPOINT, params=params)
    if resp.status_code != 200:
        raise LastFmError(f"HTTP {resp.status_code}")
    data = resp.json()
    if "error" in data:
        raise LastFmError(f"Last.fm error {data['error']}: {data.get('message', '')}")
    return data


def fetch_track_info(*, mbid_recording: str) -> dict:
    """Fetch toptags for a recording MBID. Returns {tags: [str, ...]}."""
    data = _request({"method": "track.getInfo", "mbid": mbid_recording})
    tags_raw = (data.get("track") or {}).get("toptags") or {}
    tag_list = tags_raw.get("tag") or []
    if isinstance(tag_list, dict):  # Last.fm returns dict if only 1 tag
        tag_list = [tag_list]
    return {"tags": [t["name"] for t in tag_list if t.get("name")]}


def fetch_similar_artists(*, mbid_artist: str, limit: int = 10) -> list[dict]:
    """Fetch similar artists for an artist MBID. Returns list of dicts."""
    data = _request({
        "method": "artist.getSimilar",
        "mbid": mbid_artist,
        "limit": limit,
    })
    artists_raw = (data.get("similarartists") or {}).get("artist") or []
    if isinstance(artists_raw, dict):
        artists_raw = [artists_raw]
    out = []
    for a in artists_raw:
        out.append({
            "name": a.get("name", ""),
            "match": float(a.get("match", 0.0)),
            "mbid": a.get("mbid", ""),
        })
    return out


def load_cache(cache_dir: Path, *, ttl_seconds: int | None = None) -> dict | None:
    if ttl_seconds is None:
        ttl_seconds = get_default_ttl_seconds()
    path = cache_dir / CACHE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.warning("lastfm.json corrupt at %s: %s", path, e)
        return None
    fetched_at = data.get("fetched_at", 0)
    if time.time() - fetched_at > ttl_seconds:
        return None
    return data.get("payload")


def write_cache(cache_dir: Path, payload: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / CACHE_FILE).write_text(
        json.dumps({"fetched_at": time.time(), "payload": payload}, indent=2)
    )
