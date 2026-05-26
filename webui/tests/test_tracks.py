import json
import time
from pathlib import Path

from webui import tracks


def test_list_tracks_finds_synthetic_track(synthetic_cache):
    entries = tracks.list_tracks()
    assert len(entries) == 1
    e = entries[0]
    assert e.slug == "gorillaz_silent_running"
    assert e.duration_sec == 215.064
    assert e.tempo_bpm == 107.14
    assert e.key == "F minor"
    assert e.scale == "F natural minor"
    assert e.has_vocals is True
    assert e.warnings == []


def test_title_strips_youtube_id(synthetic_cache):
    entries = tracks.list_tracks()
    assert entries[0].title == (
        "Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)"
    )


def test_title_without_youtube_id_falls_back_to_filename(write_track):
    write_track("plain", filename_override="Just a Song.mp3")
    entries = {e.slug: e for e in tracks.list_tracks()}
    assert entries["plain"].title == "Just a Song"


def test_display_title_fallback_strips_youtube_id_and_underscores():
    from webui.tracks import derive_display_title
    assert derive_display_title("gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg") == "Gorillaz Silent Running Ft Adeleye Omotayo Official Video"
    # The stripper now keys on digit / underscore / dash markers (slugs are
    # already lowercased so we can't use mixed-case as a signal here, but
    # YT IDs are random enough that one of the three is almost always
    # present). Use a realistic YT-style ID with a digit.
    assert derive_display_title("simple_track_aBc1eFgHiJk") == "Simple Track"
    # YT IDs without digits are still recognised via the underscore signal
    # — slugifier preserves underscores inside the ID body. Real-world case:
    # "the_national_graceless-jpz_guyimhw" came from "Jpz_gUyImhw".
    assert derive_display_title("the_national_graceless-jpz_guyimhw") == "The National Graceless"
    # if no 11-char trailing token, return as-is with underscores → spaces
    assert derive_display_title("no_id_here") == "No Id Here"
    # All-letter 11-char trailing token (no digit/underscore/dash) is NOT
    # stripped — preserves titles like "Baleen - Unmedicated".
    assert derive_display_title("baleen_unmedicated") == "Baleen Unmedicated"


def test_display_title_fallback_used_when_file_is_slug_form(write_track):
    # When the source filename was already the slug (e.g. cache mirror),
    # the file-derived title is unfriendly; the slug-based fallback fixes it.
    write_track(
        "gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg",
        filename_override="gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg.mp3",
    )
    entries = {e.slug: e for e in tracks.list_tracks()}
    title = entries[
        "gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg"
    ].title
    assert title == "Gorillaz Silent Running Ft Adeleye Omotayo Official Video"


def test_has_vocals_false_when_vocal_range_null(write_track):
    write_track("instr", overrides={"analysis.vocal_range": None})
    entries = {e.slug: e for e in tracks.list_tracks()}
    assert entries["instr"].has_vocals is False


def test_warnings_passthrough(write_track):
    write_track(
        "warned",
        overrides={"provenance.warnings": ["tempo halved", "vocal_range suppressed"]},
    )
    entries = {e.slug: e for e in tracks.list_tracks()}
    assert entries["warned"].warnings == ["tempo halved", "vocal_range suppressed"]


def test_skips_directory_without_summary(synthetic_cache):
    (synthetic_cache / "incomplete").mkdir()
    entries = tracks.list_tracks()
    assert len(entries) == 1
    assert entries[0].slug == "gorillaz_silent_running"


def test_skips_malformed_summary(synthetic_cache):
    bad = synthetic_cache / "broken"
    bad.mkdir()
    (bad / "broken.summary.json").write_text("{not valid json", encoding="utf-8")
    entries = tracks.list_tracks()
    slugs = {e.slug for e in entries}
    assert "broken" not in slugs
    assert "gorillaz_silent_running" in slugs


def test_mtime_cache_short_circuits_re_read(synthetic_cache, monkeypatch):
    tracks.list_tracks()
    counter = {"reads": 0}
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self.name.endswith(".summary.json"):
            counter["reads"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    tracks.list_tracks()
    assert counter["reads"] == 0


def test_mtime_cache_invalidates_on_change(synthetic_cache):
    first = tracks.list_tracks()
    sj = synthetic_cache / "gorillaz_silent_running" / "gorillaz_silent_running.summary.json"
    data = json.loads(sj.read_text(encoding="utf-8"))
    data["track"]["tempo_bpm"] = 999.0
    time.sleep(0.01)  # ensure mtime tick
    sj.write_text(json.dumps(data), encoding="utf-8")
    second = tracks.list_tracks()
    assert first[0].tempo_bpm == 107.14
    assert second[0].tempo_bpm == 999.0


def test_get_summary_returns_full_object(synthetic_cache):
    s = tracks.get_summary("gorillaz_silent_running")
    assert s["track"]["key"] == "F minor"
    assert len(s["chords"]) == 2
    assert s["analysis"]["loop_roman"] == ["i", "v", "♭VI", "♭III"]


def test_get_summary_unknown_slug_raises(synthetic_cache):
    import pytest as _pytest
    with _pytest.raises(KeyError):
        tracks.get_summary("does_not_exist")


def test_get_summary_returns_track_without_display_name_when_no_user_meta(synthetic_cache):
    summary = tracks.get_summary("gorillaz_silent_running")
    assert "display_name" not in summary["track"]


def test_get_summary_merges_display_name_from_user_meta(synthetic_cache):
    from webui import user_meta
    user_meta.write(synthetic_cache / "gorillaz_silent_running", {"display_name": "Charlie Puth - Attention"})
    summary = tracks.get_summary("gorillaz_silent_running")
    assert summary["track"]["display_name"] == "Charlie Puth - Attention"


def test_get_summary_ignores_blank_display_name(synthetic_cache):
    from webui import user_meta
    user_meta.write(synthetic_cache / "gorillaz_silent_running", {"display_name": "   "})
    summary = tracks.get_summary("gorillaz_silent_running")
    assert "display_name" not in summary["track"]


def test_list_tracks_uses_display_name_for_title(synthetic_cache):
    from webui import user_meta
    # Without override, the synthetic track's title is derived from the filename
    [entry] = tracks.list_tracks()
    derived = entry.title  # remember the pre-override title
    # With override, title is the user-authored display_name
    user_meta.write(synthetic_cache / "gorillaz_silent_running", {"display_name": "Charlie Puth - Attention"})
    tracks._cache.clear()  # bypass mtime-based memoization for the assertion
    [entry] = tracks.list_tracks()
    assert entry.title == "Charlie Puth - Attention"
    assert derived != entry.title  # sanity: it actually changed
