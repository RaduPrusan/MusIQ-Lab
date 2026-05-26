"""yt-dlp slug / filename → artist + title heuristics.

Moved here from ``webui/webui/lyrics.py`` so the analyze pipeline (which
runs inside WSL via ``python -m analyze``) can seed the MusicBrainz text-
search fallback from the slug without importing webui. ``webui.lyrics``
re-exports these so existing webui callers keep working.

ID3 fallback (``identify_track_from_slug``) uses ``mutagen`` when the slug
parse yields empty artist or title — for non-ASCII slugs (Romanian /
Turkish releases) the original ID3 tags carry the canonical form.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict


class TrackIdentity(TypedDict):
    artist: str
    title: str
    album: str
    duration_sec: float


# ---------------------------------------------------------------------------
# YouTube-ID tail stripping
# ---------------------------------------------------------------------------

_YT_ID_TAIL_RE = re.compile(r"-[A-Za-z0-9_-]{11}$")


def _strip_yt_id_tail(stem: str) -> str:
    """yt-dlp's output template appends ``-<11-char id>``. Strip it when the
    11-char body looks like a YT ID — gated on digit OR underscore OR an
    internal dash OR mixed case. The previous digit-only gate missed real
    IDs that happened to be all-letter, e.g. ``Jpz_gUyImhw`` (mixed case +
    underscore). Plain English words (single case, all letters, no
    specials) still fall through and are preserved as titles. Mirrors the
    JS heuristic in static/js/ui/topbar.js and static/js/data/track-data.js."""
    m = _YT_ID_TAIL_RE.search(stem)
    if not m:
        return stem
    body = m.group(0)[1:]  # drop the leading "-"
    has_marker = any(c.isdigit() or c in "_-" for c in body)
    mixed_case = any(c.isupper() for c in body) and any(c.islower() for c in body)
    if has_marker or mixed_case:
        return stem[: m.start()]
    return stem


def _slug_to_display(stem: str) -> str:
    """Convert slug-form filenames (no spaces, lowercase) to a display form.
    ``-`` between word chars renders as ``" - "`` (artist/title boundary);
    ``_`` as a space; each word gets title-cased. Strings already containing
    spaces are returned unchanged. Mirrors deriveTitle in topbar.js so the
    LRCLIB query and the topbar pill agree on what the file 'is named'."""
    if " " in stem:
        return stem
    pretty = re.sub(r"(\w)-(\w)", r"\1 - \2", stem)
    pretty = pretty.replace("_", " ")
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), pretty)


def _parse_filename(stem: str) -> tuple[str, str]:
    """Strip the YT id tail, prettify slug-form names, then split on ``" - "``.
    Forms without that separator fall back to title-only.

    Round 5: when there's no ``" - "`` artist/title separator (e.g. the
    ``charlie_puth_attention`` slug), we return ``("", cleaned)`` — the
    caller is then expected to query MB without an artist filter (per
    ``musicbrainz_client.search_recording(artist=None, ...)``) and rely on
    the Round 5 artist-plausibility gate in identify.run() to reject
    wrong-artist matches downstream. We deliberately do NOT guess where the
    artist boundary lies — there's no robust signal in a 3-word title like
    "Charlie Puth Attention" that "Charlie Puth" is the artist vs
    "Attention" being a 3rd member of an artist name. Letting MB's
    artist-credit matching do the work is empirically more accurate."""
    cleaned = _slug_to_display(_strip_yt_id_tail(stem))
    if " - " in cleaned:
        artist, _, title = cleaned.partition(" - ")
        return artist.strip(), title.strip()
    return "", cleaned


# ---------------------------------------------------------------------------
# YouTube noise-token cleaning (for MB search seeding)
# ---------------------------------------------------------------------------
#
# Targets the typical filler in YouTube release titles: "(Official Music
# Video)", "[Lyric Video]", "Remastered", "Feat. Artist", four-digit years
# in brackets, etc. Single-pass regex; if it would empty the title, we
# return the input unchanged so callers can still seed a search.
_NOISE_TOKEN_RE = re.compile(
    r"\b(official\s+(?:music\s+)?video|official\s+audio|lyric\s+video|lyrics|"
    r"acoustic|live\s+at\s+[^,()]+|remastered|"
    r"single\s+version|album\s+version|radio\s+edit|extended\s+(?:mix|version)|"
    r"feat\.?\s+[^,()]+|ft\.?\s+[^,()]+|\(\d{4}\)|\[\d{4}\])",
    re.IGNORECASE,
)


_EMPTY_BRACKETS_RE = re.compile(r"[\(\[\{]\s*[\)\]\}]")


def clean_title(title: str) -> str:
    """Strip noise tokens for MB search seeding. Conservative — only well-
    known YouTube noise patterns. Returns the original title unchanged if
    every match would empty it (load-bearing for short titles like just
    "Lyrics" — better to seed with the literal than nothing).

    Also collapses empty bracket pairs left behind by the regex (so e.g.
    ``"Reminder (Official Video)"`` becomes ``"Reminder"``, not
    ``"Reminder ()"``).
    """
    cleaned = _NOISE_TOKEN_RE.sub("", title)
    # Remove empty paren / bracket pairs the noise regex leaves behind, then
    # collapse whitespace + trim stray connective punctuation at the edges.
    cleaned = _EMPTY_BRACKETS_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned or title


# ---------------------------------------------------------------------------
# ID3-aware identity resolver
# ---------------------------------------------------------------------------


def _mutagen_file(path: Path, easy: bool = True):
    """Wrapper for ``mutagen.File`` so tests can monkeypatch it without
    importing mutagen themselves. Mutagen is an analyze-stack dep already
    (lyrics tab); pulling it in here costs nothing."""
    import mutagen  # local import so analyze.text imports cheaply
    return mutagen.File(str(path), easy=easy)


def identify_track_from_slug(mp3_path: Path, duration_sec: float) -> TrackIdentity:
    """Return artist/title/album for an MP3, preferring ID3 tags and falling
    back to filename parsing for any missing field. Used both by the webui
    LRCLIB query path and by the analyze identify stage's MB text-search
    fallback (Round 4).
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
