from pathlib import Path

import pytest

from analyze import cache


# Slug policy (per analyze.cache.slug_for docstring): each run of non-alnum
# input chars collapses to a SINGLE separator — "-" if the run contained any
# dash, otherwise "_". This preserves the artist-title and yt-dlp <title>-<id>
# boundary as a dash while collapsing other punctuation/whitespace to
# underscores. The same algorithm is duplicated at
# webui/webui/analyze_runner.py:_slug_for_stem so the webui can compute slugs
# without importing the (ML-heavy) analyze package.
def test_slug_for_strips_punctuation_and_lowercases():
    p = Path("Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3")
    # " - " between Gorillaz and Silent → "-"; ")-_" before the YT id → "-"
    assert cache.slug_for(p) == "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg"


def test_slug_for_collapses_runs_and_strips_edges():
    p = Path("___Hello---World___.mp3")
    # "---" run contains "-" → "-"; leading/trailing separators stripped
    assert cache.slug_for(p) == "hello-world"


def test_slug_for_handles_unicode():
    p = Path("Beyoncé - Halo.mp3")
    # "é - " is one non-alnum run (é is non-ascii), contains "-" → "-"
    assert cache.slug_for(p) == "beyonc-halo"


def test_ensure_dir_creates_under_project_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d = cache.ensure_dir("my_song")
    assert d == tmp_path / "cache" / "my_song"
    assert d.is_dir()


def test_ensure_dir_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d1 = cache.ensure_dir("my_song")
    d2 = cache.ensure_dir("my_song")
    assert d1 == d2
    assert d1.is_dir()


def test_clear_removes_contents_preserves_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d = cache.ensure_dir("my_song")
    (d / "stuff.json").write_text("{}")
    (d / "subdir").mkdir()
    (d / "subdir" / "file.wav").write_bytes(b"data")
    cache.clear(d)
    assert d.is_dir()
    assert list(d.iterdir()) == []


def test_is_newer_than_mp3_true_when_file_newer(tmp_path):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    out = tmp_path / "out.json"
    out.write_text("{}")
    # touch out to be slightly newer
    import os, time
    time.sleep(0.01)
    out.touch()
    assert cache.is_newer_than_mp3(out, mp3) is True


def test_is_newer_than_mp3_false_when_mp3_newer(tmp_path):
    out = tmp_path / "out.json"
    out.write_text("{}")
    import time
    time.sleep(0.01)
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    assert cache.is_newer_than_mp3(out, mp3) is False


def test_is_newer_than_mp3_false_when_out_missing(tmp_path):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    out = tmp_path / "missing.json"
    assert cache.is_newer_than_mp3(out, mp3) is False
