"""Tests for tracks.py consulting identify.json to override slug-derived titles.

Plan A Task 10: when cache/<slug>/identify.json has identified=true with a
title (and optionally an artist), the TrackEntry.title is "<artist> — <title>"
(em-dash separator, U+2014). Otherwise the existing slug/filename-derived
fallback path runs unchanged.
"""
import json

from webui import tracks


def test_title_prefers_canonical_when_identified(synthetic_cache):
    """identify.json with identified=true overrides the filename-derived title."""
    track_dir = synthetic_cache / "gorillaz_silent_running"
    payload = {
        "identified": True,
        "title": "Silent Running",
        "artist": "Gorillaz",
        "year": 2023,
    }
    (track_dir / "identify.json").write_text(json.dumps(payload), encoding="utf-8")
    tracks._cache.clear()  # bypass mtime memo: identify.json isn't in the cache key

    entries = tracks.list_tracks()
    assert len(entries) == 1
    assert entries[0].title == "Gorillaz — Silent Running"


def test_title_falls_back_when_not_identified(synthetic_cache):
    """identified=false → existing filename-derived title."""
    track_dir = synthetic_cache / "gorillaz_silent_running"
    payload = {"identified": False, "reason": "no match"}
    (track_dir / "identify.json").write_text(json.dumps(payload), encoding="utf-8")
    tracks._cache.clear()

    entries = tracks.list_tracks()
    assert len(entries) == 1
    # Same as test_title_strips_youtube_id in test_tracks.py — must not regress.
    assert entries[0].title == (
        "Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)"
    )


def test_title_falls_back_when_identify_absent(synthetic_cache):
    """No identify.json → existing filename-derived title (regression guard)."""
    # synthetic_cache has no identify.json at all.
    entries = tracks.list_tracks()
    assert len(entries) == 1
    assert entries[0].title == (
        "Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)"
    )


def test_title_uses_canonical_title_only_when_no_artist(synthetic_cache):
    """identified=true with title but no artist → title is just the title (no em-dash)."""
    track_dir = synthetic_cache / "gorillaz_silent_running"
    payload = {"identified": True, "title": "Silent Running"}  # no artist key
    (track_dir / "identify.json").write_text(json.dumps(payload), encoding="utf-8")
    tracks._cache.clear()

    entries = tracks.list_tracks()
    assert len(entries) == 1
    assert entries[0].title == "Silent Running"
