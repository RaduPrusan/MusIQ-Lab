from webui.lyrics import parse_lrc


def test_parse_lrc_simple_two_lines():
    text = "[00:01.50]first line\n[00:04.20]second line\n"
    result = parse_lrc(text)
    assert result["has_sync"] is True
    assert result["lines"] == [
        {"time_sec": 1.5, "text": "first line"},
        {"time_sec": 4.2, "text": "second line"},
    ]
    assert result["plain_text"] == "first line\nsecond line"


def test_parse_lrc_with_minutes():
    text = "[02:13.99]a verse line\n"
    result = parse_lrc(text)
    assert result["lines"][0]["time_sec"] == 2 * 60 + 13.99


def test_parse_lrc_section_marker_kept_in_text():
    text = "[00:00.00]\n[00:01.00][Verse 1]\n[00:05.00]She walked\n"
    result = parse_lrc(text)
    assert result["lines"][0]["text"] == "[Verse 1]"
    assert result["lines"][1]["text"] == "She walked"


def test_parse_lrc_metadata_lines_dropped():
    text = "[ar:Some Artist]\n[ti:Some Title]\n[00:01.00]hello\n"
    result = parse_lrc(text)
    assert len(result["lines"]) == 1
    assert result["lines"][0]["text"] == "hello"


def test_parse_lrc_blank_text_kept_with_empty_string():
    text = "[00:01.00]\n[00:05.00]first\n"
    result = parse_lrc(text)
    assert result["lines"][0] == {"time_sec": 1.0, "text": ""}


def test_parse_lrc_plain_text_no_brackets():
    text = "first line\nsecond line\n"
    result = parse_lrc(text)
    assert result["has_sync"] is False
    assert result["lines"] == []
    assert result["plain_text"] == "first line\nsecond line"


def test_parse_lrc_mixed_synced_and_plain_treated_as_synced():
    # Real LRCLIB files sometimes have header notes interleaved.
    # Any timestamped line makes the file synced; non-timestamped lines drop.
    text = "Lyrics by Someone\n[00:01.00]first\n[00:05.00]second\n"
    result = parse_lrc(text)
    assert result["has_sync"] is True
    assert len(result["lines"]) == 2


from pathlib import Path

from webui.lyrics import identify_track


def test_identify_from_id3_tags(tmp_path, monkeypatch):
    fake_path = tmp_path / "track.mp3"
    fake_path.write_bytes(b"")  # mutagen.File on empty returns None — we monkeypatch instead

    class FakeTags(dict):
        pass

    fake_tags = FakeTags({"artist": ["Some Artist"], "title": ["Some Title"], "album": ["Some Album"]})

    def fake_mutagen_file(path, easy=True):
        return fake_tags

    monkeypatch.setattr("webui.lyrics._mutagen_file", fake_mutagen_file)
    result = identify_track(fake_path, duration_sec=212.0)
    assert result == {"artist": "Some Artist", "title": "Some Title", "album": "Some Album", "duration_sec": 212.0}


def test_identify_filename_fallback_with_dash(tmp_path, monkeypatch):
    fake_path = tmp_path / "Gorillaz - Silent Running.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=180.0)
    assert result["artist"] == "Gorillaz"
    assert result["title"] == "Silent Running"


def test_identify_filename_fallback_underscore(tmp_path, monkeypatch):
    fake_path = tmp_path / "olivia_dean_dive.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=180.0)
    # Slug form (no spaces, no `-`): underscores become spaces, words title-cased.
    # No `" - "` separator emerges, so it falls into title-only — but the title
    # is now display-cased rather than the raw slug.
    assert result["artist"] == ""
    assert result["title"] == "Olivia Dean Dive"


def test_identify_filename_strips_yt_id_tail(tmp_path, monkeypatch):
    """yt-dlp's ``-<11-char id>`` suffix must not leak into the LRCLIB query."""
    fake_path = tmp_path / "Balthazar - Changes (Official Video)-P3Jb998ACQo.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=200.0)
    assert result["artist"] == "Balthazar"
    assert result["title"] == "Changes (Official Video)"


def test_identify_filename_preserves_eleven_letter_word_without_digit(tmp_path, monkeypatch):
    """Coincidental 11-letter trailing words (no digits, single case, no
    specials) are NOT YT IDs and must be preserved — the heuristic gate
    classifies them as title words."""
    fake_path = tmp_path / "Baleen - Unmedicated.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=180.0)
    assert result["artist"] == "Baleen"
    assert result["title"] == "Unmedicated"


def test_identify_filename_strips_yt_id_without_digit(tmp_path, monkeypatch):
    """YT IDs aren't required to contain digits — many are all-letter with
    mixed case (e.g. ``Jpz_gUyImhw``). The heuristic strips them via the
    underscore + mixed-case markers."""
    fake_path = tmp_path / "The National - Graceless-Jpz_gUyImhw.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=240.0)
    assert result["artist"] == "The National"
    assert result["title"] == "Graceless"


def test_identify_filename_slug_with_dash_separator(tmp_path, monkeypatch):
    """Slug form with `-` between word chars marks an artist/title boundary
    and renders as ``" - "`` after prettification."""
    fake_path = tmp_path / "balthazar-changes_official_video-p3jb998acqo.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=200.0)
    assert result["artist"] == "Balthazar"
    assert result["title"] == "Changes Official Video"


def test_identify_partial_id3_uses_filename_for_missing(tmp_path, monkeypatch):
    fake_path = tmp_path / "Gorillaz - Silent Running.mp3"
    fake_path.write_bytes(b"")

    class FakeTags(dict):
        pass

    monkeypatch.setattr(
        "webui.lyrics._mutagen_file",
        lambda p, easy=True: FakeTags({"title": ["Silent Running"]}),  # artist missing
    )
    result = identify_track(fake_path, duration_sec=180.0)
    assert result["artist"] == "Gorillaz"  # filled from filename
    assert result["title"] == "Silent Running"  # from id3


import httpx
import pytest

from webui.lyrics import lrclib_lookup


class _FakeTransport(httpx.MockTransport):
    pass


@pytest.mark.asyncio
async def test_lrclib_get_returns_synced(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/get"
        params = dict(request.url.params)
        assert params["artist_name"] == "Gorillaz"
        assert params["track_name"] == "Silent Running"
        return httpx.Response(
            200,
            json={
                "id": 12345,
                "syncedLyrics": "[00:01.00]first\n[00:05.00]second\n",
                "plainLyrics": "first\nsecond",
                "duration": 180,
            },
        )

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="Gorillaz", title="Silent Running", duration_sec=180.0, _transport=transport
    )
    assert result["source"] == "lrclib"
    assert result["has_sync"] is True
    assert result["lrclib_id"] == 12345
    assert "[00:01.00]first" in result["synced_lrc"]


@pytest.mark.asyncio
async def test_lrclib_get_404_falls_back_to_search(monkeypatch):
    calls: list[str] = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/get":
            return httpx.Response(404)
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "duration": 100, "syncedLyrics": None, "plainLyrics": "wrong song"},
                    {"id": 2, "duration": 181, "syncedLyrics": "[00:01.00]right\n", "plainLyrics": "right"},
                ],
            )
        return httpx.Response(500)

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert calls == ["/api/get", "/api/search"]
    assert result["lrclib_id"] == 2  # closest duration to 180
    assert result["has_sync"] is True


@pytest.mark.asyncio
async def test_lrclib_search_handles_null_duration(monkeypatch):
    # LRCLIB can return a search result with duration: null. The sort key must
    # not crash on int(None); the null entry sorts as duration 0.
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "duration": None, "syncedLyrics": "[00:01.00]a\n", "plainLyrics": "a"},
                    {"id": 2, "duration": 181, "syncedLyrics": "[00:01.00]b\n", "plainLyrics": "b"},
                ],
            )
        return httpx.Response(500)

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    # No crash; entry 2 (duration 181) is closest to 180, so it wins.
    assert result["lrclib_id"] == 2


@pytest.mark.asyncio
async def test_lrclib_no_match_returns_not_found(monkeypatch):
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(200, json=[])

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert result == {"source": "lrclib", "has_sync": False, "synced_lrc": None, "plain_text": None, "lrclib_id": None, "error": "not_found"}


@pytest.mark.asyncio
async def test_lrclib_network_error_propagates_as_error_dict(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("simulated network failure")

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert result["error"] == "network"


from webui.lyrics import (
    cache_dir_for, load_cached, save_synced, save_plain, save_paste, clear_cache,
    detect_paste_format,
)


def test_save_and_load_synced(tmp_path):
    cache = tmp_path / "lyrics"
    save_synced(cache, lrc_text="[00:01.00]hello\n", meta={"source": "lrclib", "lrclib_id": 1, "artist": "A", "title": "T", "album": "", "duration_sec": 180})
    loaded = load_cached(cache)
    assert loaded["has_sync"] is True
    assert loaded["meta"]["source"] == "lrclib"


def test_save_and_load_plain(tmp_path):
    cache = tmp_path / "lyrics"
    save_plain(cache, plain_text="line one\nline two", meta={"source": "claude_web", "artist": "A", "title": "T", "album": "", "duration_sec": 180})
    loaded = load_cached(cache)
    assert loaded["has_sync"] is False
    assert loaded["plain_text"] == "line one\nline two"


def test_load_cached_missing_returns_none(tmp_path):
    assert load_cached(tmp_path / "lyrics") is None


def test_detect_paste_lrc_with_timestamps():
    assert detect_paste_format("[00:01.00]hello") == "lrc"


def test_detect_paste_plain_text():
    assert detect_paste_format("just plain words\nno timestamps") == "plain"


def test_save_paste_routes_to_lrc(tmp_path):
    cache = tmp_path / "lyrics"
    save_paste(cache, "[00:01.00]hello\n", meta={"source": "user_paste", "artist": "", "title": "", "album": "", "duration_sec": 0})
    assert (cache / "synced.lrc").is_file()
    assert not (cache / "plain.txt").is_file()


def test_save_paste_routes_to_plain(tmp_path):
    cache = tmp_path / "lyrics"
    save_paste(cache, "no timestamps here", meta={"source": "user_paste", "artist": "", "title": "", "album": "", "duration_sec": 0})
    assert (cache / "plain.txt").is_file()
    assert not (cache / "synced.lrc").is_file()


def test_clear_cache_removes_directory(tmp_path):
    cache = tmp_path / "lyrics"
    save_synced(cache, "[00:01.00]hello\n", meta={"source": "lrclib", "artist": "", "title": "", "album": "", "duration_sec": 0})
    clear_cache(cache)
    assert not cache.exists()
