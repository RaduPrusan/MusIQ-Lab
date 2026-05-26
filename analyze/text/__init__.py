"""Pure-string text helpers shared between analyze.* and webui.*.

Currently exports the slug parser (yt-dlp filename → artist/title) plus
the ID3 fallback resolver. These were originally in webui/webui/lyrics.py
but the identify stage (which runs in WSL) needs them too, so they live
here as a webui-independent module.
"""
from analyze.text.slug_parser import (
    _EMPTY_BRACKETS_RE,
    _NOISE_TOKEN_RE,
    _YT_ID_TAIL_RE,
    TrackIdentity,
    _parse_filename,
    _slug_to_display,
    _strip_yt_id_tail,
    clean_title,
    identify_track_from_slug,
)

__all__ = [
    "_EMPTY_BRACKETS_RE",
    "_NOISE_TOKEN_RE",
    "_YT_ID_TAIL_RE",
    "TrackIdentity",
    "_parse_filename",
    "_slug_to_display",
    "_strip_yt_id_tail",
    "clean_title",
    "identify_track_from_slug",
]
