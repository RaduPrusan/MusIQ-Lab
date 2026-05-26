"""Round 4 tests — shared slug parser at analyze/text/slug_parser.py.

The parser lives in the analyze package so identify.run() can seed its
MB text-search fallback without depending on webui. webui/webui/lyrics.py
loads the same module via importlib so test_lyrics.py still works on
Windows py3.13 (which can't import analyze.* normally).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Module loader — same trick webui.lyrics uses; verifies it works in tests too.
# ---------------------------------------------------------------------------


def _load_slug_parser():
    repo_root = Path(__file__).resolve().parents[2]
    parser_path = repo_root / "analyze" / "text" / "slug_parser.py"
    assert parser_path.is_file(), f"missing: {parser_path}"
    spec = importlib.util.spec_from_file_location(
        "_test_slug_parser", parser_path,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


slug_parser = _load_slug_parser()


# ---------------------------------------------------------------------------
# _strip_yt_id_tail — covered by existing test_lyrics but pinned here for
# the shared-module contract.
# ---------------------------------------------------------------------------


def test_strip_yt_id_tail_with_digit_marker():
    out = slug_parser._strip_yt_id_tail("foo-bar-p3jb998acqo")
    assert out == "foo-bar"


def test_strip_yt_id_tail_mixed_case_no_digit():
    """YT IDs aren't required to contain digits — many are all-letter with
    mixed case. The heuristic strips them via the underscore + mixed-case
    markers."""
    out = slug_parser._strip_yt_id_tail("Track-Jpz_gUyImhw")
    assert out == "Track"


def test_strip_yt_id_tail_preserves_plain_word():
    """A trailing 11-letter all-lowercase word like 'unmedicated' must NOT
    be stripped — it's a title word, not a YT ID."""
    out = slug_parser._strip_yt_id_tail("Baleen - Unmedicated")
    assert out == "Baleen - Unmedicated"


# ---------------------------------------------------------------------------
# _parse_filename — corpus regression coverage.
# ---------------------------------------------------------------------------


def test_slug_parser_handles_charlie_puth():
    """The Charlie Puth slug has no `-` separator and no ID tail — the
    parser must produce a non-empty title (artist falls through as empty)."""
    artist, title = slug_parser._parse_filename("charlie_puth_attention")
    assert title  # non-empty — load-bearing for the fallback seed
    # Artist remains empty for this slug form; we rely on MB's search
    # parsing the title as artist+track. The test pins title contents:
    assert "charlie" in title.lower()
    assert "puth" in title.lower()
    assert "attention" in title.lower()


def test_slug_parser_handles_warhaus():
    """Real corpus track: `_` slug form + YT id tail."""
    artist, title = slug_parser._parse_filename(
        "warhaus_love_s_a_stranger_official_video_gsjdhd0stag"
    )
    # The slug has no `-` separator either, so artist falls through empty
    # and the full prettified slug ends up as title. The (Official Video)
    # noise gets stripped at the next stage (clean_title).
    assert title
    assert "warhaus" in title.lower()
    assert "love" in title.lower()
    assert "stranger" in title.lower()


def test_slug_parser_handles_moderat():
    """Slug with `-` separator → artist/title boundary detected. Note the
    11-char all-lowercase YT ID ``cjwsnuoazug`` is preserved (no digits
    or underscore → fails the strip gate, treated as title text)."""
    # Use a more typical YT ID with digits so the stripper engages.
    artist, title = slug_parser._parse_filename(
        "moderat-reminder_official_video-cjwsn8oa2ug"
    )
    assert artist == "Moderat"
    assert title == "Reminder Official Video"


def test_slug_parser_id3_fallback(tmp_path, monkeypatch):
    """When ID3 tags are present, identify_track_from_slug prefers them
    over the slug — even for slugs that would parse cleanly."""
    fake_mp3 = tmp_path / "moderat-reminder_official_video-cjwsnuoazug.mp3"
    fake_mp3.write_bytes(b"")

    class FakeTags(dict):
        pass

    fake_tags = FakeTags({
        "artist": ["Moderat"], "title": ["Reminder"], "album": ["II"],
    })

    monkeypatch.setattr(slug_parser, "_mutagen_file", lambda p, easy=True: fake_tags)
    result = slug_parser.identify_track_from_slug(fake_mp3, duration_sec=300.0)
    assert result["artist"] == "Moderat"
    assert result["title"] == "Reminder"
    assert result["album"] == "II"
    assert result["duration_sec"] == 300.0


def test_slug_parser_id3_partial_falls_back_to_slug(tmp_path, monkeypatch):
    """Empty ID3 artist falls back to slug-derived artist; ID3 title wins
    when present."""
    fake_mp3 = tmp_path / "moderat-reminder.mp3"
    fake_mp3.write_bytes(b"")

    class FakeTags(dict):
        pass

    monkeypatch.setattr(
        slug_parser, "_mutagen_file",
        lambda p, easy=True: FakeTags({"title": ["Reminder"]}),  # no artist
    )
    result = slug_parser.identify_track_from_slug(fake_mp3, duration_sec=300.0)
    assert result["artist"] == "Moderat"  # from slug
    assert result["title"] == "Reminder"  # from ID3


def test_slug_parser_no_id3_uses_slug(tmp_path, monkeypatch):
    fake_mp3 = tmp_path / "charlie_puth_attention.mp3"
    fake_mp3.write_bytes(b"")
    monkeypatch.setattr(slug_parser, "_mutagen_file", lambda p, easy=True: None)
    result = slug_parser.identify_track_from_slug(fake_mp3, duration_sec=211.0)
    assert result["artist"] == ""
    assert "Charlie Puth Attention" in result["title"]


# ---------------------------------------------------------------------------
# clean_title — Round 4 noise stripper.
# ---------------------------------------------------------------------------


def test_clean_title_strips_official_video():
    assert slug_parser.clean_title("Reminder (Official Video)") == "Reminder"


def test_clean_title_strips_official_audio_with_brackets():
    assert slug_parser.clean_title("Track Name [Official Audio]") == "Track Name"


def test_clean_title_strips_lyric_video():
    assert slug_parser.clean_title("Sample Song (Lyric Video)") == "Sample Song"


def test_clean_title_strips_remastered():
    # "Remastered" is a noise token; trailing connective is trimmed.
    out = slug_parser.clean_title("Hey Jude - Remastered")
    assert out.strip(" -") == "Hey Jude"


def test_clean_title_strips_live_at():
    # "Live at X" is captured up to the first comma/paren — keeps the rest.
    assert slug_parser.clean_title(
        "Shape of My Heart Live at the Rijksmuseum"
    ).startswith("Shape of My Heart")


def test_clean_title_preserves_when_would_empty():
    """If every match would empty the title, return the input unchanged so
    callers can still seed a search with something."""
    assert slug_parser.clean_title("Lyrics") == "Lyrics"
    # Empty input stays empty (cleaner returns the input unchanged).
    assert slug_parser.clean_title("") == ""


def test_clean_title_preserves_live_at_when_part_of_artist_credit():
    """A title without the trigger word stays exactly as-is."""
    assert slug_parser.clean_title("Live and Let Die") == "Live and Let Die"


def test_clean_title_idempotent():
    """Running clean_title twice yields the same string."""
    once = slug_parser.clean_title("Reminder (Official Video)")
    twice = slug_parser.clean_title(once)
    assert once == twice == "Reminder"


# ---------------------------------------------------------------------------
# Lyrics import regression: webui.lyrics MUST re-export the legacy names.
# ---------------------------------------------------------------------------


def test_lyrics_imports_from_slug_parser_still_work():
    """webui.lyrics must continue to expose ``_strip_yt_id_tail``,
    ``_parse_filename``, ``_slug_to_display``, ``_NOISE_TOKEN_RE``,
    ``_YT_ID_TAIL_RE``, ``clean_title``, ``identify_track``, and
    ``_mutagen_file`` after the refactor. Test pinned so a future cleanup
    can't silently drop the bridge.

    Skipped under the analyze WSL venv (which doesn't ship mutagen — a
    webui-only dep). Runs in the webui .venv (Windows py3.13) where
    ``webui.lyrics`` can be imported cleanly.
    """
    pytest.importorskip("mutagen")
    from webui.lyrics import (  # noqa: F401 — assertion is import success
        _NOISE_TOKEN_RE,
        _YT_ID_TAIL_RE,
        _mutagen_file,
        _parse_filename,
        _slug_to_display,
        _strip_yt_id_tail,
        clean_title,
        identify_track,
    )
    # Behavioral identity: same input → same output as the canonical
    # slug_parser module. (Can't compare via `is` because webui.lyrics
    # loads the file under a different module name via importlib, so the
    # function objects aren't identical.)
    assert _strip_yt_id_tail("Track-Jpz_gUyImhw") == slug_parser._strip_yt_id_tail("Track-Jpz_gUyImhw")
    assert _parse_filename("moderat-reminder") == slug_parser._parse_filename("moderat-reminder")
    assert clean_title("Foo (Official Video)") == slug_parser.clean_title("Foo (Official Video)")
