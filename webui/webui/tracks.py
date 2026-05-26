import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from . import _paths
from . import user_meta
from .identify import read_identify

log = logging.getLogger(__name__)

_YOUTUBE_ID_SUFFIX = re.compile(r"-[A-Za-z0-9_-]{11}\.mp3$")
# Slugs are lowercased filenames; the trailing YouTube-ID token is normally
# 11 chars but the slugifier collapses adjacent runs, so an ID that itself
# starts with `_` (a legal YT-ID character) can land in the slug as 10 visible
# chars after the separator. The new slug rule uses "-" as the boundary; old
# slugs used "_". Accept either separator and either tail length for backward
# compatibility during the migration window.
_YT_ID_SUFFIX = re.compile(r"[-_][A-Za-z0-9_-]{10,11}$")


@dataclass(frozen=True)
class TrackEntry:
    slug: str
    title: str
    duration_sec: float
    tempo_bpm: float
    key: str
    scale: str
    has_vocals: bool
    warnings: list[str]
    summary_mtime_ns: int


_cache: dict[str, tuple[tuple[int, int], TrackEntry]] = {}


def _looks_like_yt_id_tail_filename(tail: str) -> bool:
    """A "-<11-char>.mp3" tail looks like a YT ID iff the 11-char body has
    high-entropy markers: a digit, an underscore, an internal dash, OR mixed
    case. Plain English words (single case, all letters, no specials) fall
    through and are preserved as titles. Catches real YT IDs that happen to
    contain no digit, e.g. ``Jpz_gUyImhw`` (mixed case + underscore)."""
    body = tail[1:-4]  # strip leading "-" and trailing ".mp3"
    if any(c.isdigit() or c in "_-" for c in body):
        return True
    return any(c.isupper() for c in body) and any(c.islower() for c in body)


def _looks_like_yt_id_tail_slug(tail: str) -> bool:
    """Slug-form variant: slugs are lowercased so mixed-case is gone, but
    underscores and dashes inside a YT ID survive the slugifier. Accept any
    digit/underscore/internal-dash as a YT-ID signal — pure English words
    won't trip this."""
    body = tail.lstrip("-_")
    return any(c.isdigit() or c in "_-" for c in body)


def _derive_title(file_field: str) -> str:
    # YT IDs are 11 chars from a base64-url-safe alphabet. We classify a
    # trailing "-<11>.mp3" as an ID iff it has digit/underscore/dash/mixed-case
    # markers — that strips real IDs (incl. ones without digits, e.g.
    # ``Jpz_gUyImhw``) without amputating coincidental 11-char title words
    # (e.g. "Baleen - Unmedicated.mp3" — single-case, no specials → preserved).
    m = _YOUTUBE_ID_SUFFIX.search(file_field)
    if m and _looks_like_yt_id_tail_filename(m.group()):
        return file_field[: m.start()]
    return file_field.removesuffix(".mp3")


def derive_display_title(slug: str) -> str:
    """Fallback display title from a slug.

    Strips a trailing YouTube-ID token if present (gated on digit/underscore/
    dash markers — slugs are lowercased so we can't use a mixed-case signal,
    but YT IDs are random enough that an underscore or digit is essentially
    always present), then renders the slug as a human title: "-" between word
    chars becomes " - ", "_" becomes " ", each word title-cased.
    """
    m = _YT_ID_SUFFIX.search(slug)
    base = slug[: m.start()] if (m and _looks_like_yt_id_tail_slug(m.group())) else slug
    base = re.sub(r"(\w)-(\w)", r"\1 - \2", base)
    return base.replace("_", " ").title()


def _canonical_title_from_identify(identify: dict | None) -> str | None:
    """Return '<artist> — <title>' (em-dash U+2014) when identify.json claims a
    positive ID with a title; just the title when no artist; None otherwise."""
    if not identify or not identify.get("identified"):
        return None
    title = identify.get("title")
    if not title:
        return None
    artist = identify.get("artist")
    return f"{artist} — {title}" if artist else title


def _build_entry(
    slug: str,
    summary: dict,
    mtime_ns: int,
    display_override: str | None = None,
    identify: dict | None = None,
) -> TrackEntry:
    track = summary["track"]
    analysis = summary.get("analysis", {})
    provenance = summary.get("provenance", {})
    canonical = _canonical_title_from_identify(identify)
    file_title = _derive_title(track["file"])
    derived = file_title if " " in file_title else derive_display_title(slug)
    title = display_override or canonical or derived
    return TrackEntry(
        slug=slug,
        title=title,
        duration_sec=float(track["duration_sec"]),
        tempo_bpm=float(track["tempo_bpm"]),
        key=track["key"],
        scale=analysis.get("scale", ""),
        has_vocals=analysis.get("vocal_range") is not None,
        warnings=list(provenance.get("warnings", [])),
        summary_mtime_ns=mtime_ns,
    )


def _summary_path(slug: str, cache: Path) -> Path:
    return cache / slug / f"{slug}.summary.json"


def list_tracks(cache: Path | None = None) -> list[TrackEntry]:
    cache = cache or _paths.cache_dir()
    if not cache.is_dir():
        return []
    entries: list[TrackEntry] = []
    for child in cache.iterdir():
        if not child.is_dir():
            continue
        sj = _summary_path(child.name, cache)
        if not sj.is_file():
            continue
        try:
            summary_mtime = sj.stat().st_mtime_ns
        except OSError as exc:
            log.warning("stat failed for %s: %s", sj, exc)
            continue
        # Include user_meta.json mtime in the cache key so a rename invalidates
        # the cached entry without requiring an explicit pop. Missing file → 0.
        um_path = user_meta.path_for(child)
        try:
            um_mtime = um_path.stat().st_mtime_ns if um_path.is_file() else 0
        except OSError:
            um_mtime = 0
        key = (summary_mtime, um_mtime)
        cached = _cache.get(child.name)
        if cached and cached[0] == key:
            entries.append(cached[1])
            continue
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            display_override = (user_meta.read(child).get("display_name") or "").strip() or None
            identify = read_identify(child)
            entry = _build_entry(
                child.name, data, summary_mtime,
                display_override=display_override, identify=identify,
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            log.warning("skipping %s: %s", sj, exc)
            continue
        _cache[child.name] = (key, entry)
        entries.append(entry)
    return entries


def get_summary(slug: str, cache: Path | None = None) -> dict:
    cache = cache or _paths.cache_dir()
    sj = _summary_path(slug, cache)
    if not sj.is_file():
        raise KeyError(slug)
    summary = json.loads(sj.read_text(encoding="utf-8"))
    # Merge user-authored display_name override (separate file so it survives
    # reanalyze, which regenerates summary.json from scratch).
    from . import user_meta
    um = user_meta.read(cache / slug)
    dn = (um.get("display_name") or "").strip()
    if dn:
        summary.setdefault("track", {})["display_name"] = dn
    return summary
