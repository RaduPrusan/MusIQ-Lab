"""Unit tests for analyze_runner helpers."""
from __future__ import annotations

import pytest
from pathlib import Path

from webui import analyze_runner


def test_slug_for_filename_basic():
    assert analyze_runner.slug_for_filename("Bohemian_Rhapsody.mp3") == "bohemian_rhapsody"
    assert analyze_runner.slug_for_filename("Bohemian Rhapsody.flac") == "bohemian_rhapsody"


def test_slug_for_filename_handles_dots_in_title():
    # Path("Track 1.0 (Live)").stem returns "Track 1" — a real bug.
    # slug_for_filename must synthesize a .mp3 suffix before calling slug_for
    # so that .stem captures the full intended title.
    assert analyze_runner.slug_for_filename("Track 1.0 (Live).mp3") != "track_1"
    assert "1_0" in analyze_runner.slug_for_filename("Track 1.0 (Live).mp3")


def test_slug_for_filename_handles_yt_id_suffix():
    # yt-dlp template: "<title>-<11char-id>.mp3"
    s = analyze_runner.slug_for_filename("Some Song-AbCdEfGhIjK.mp3")
    assert s.endswith("-abcdefghijk")


def test_find_first_free_slug_returns_dash_2_for_no_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze_runner._paths, "cache_dir", lambda: tmp_path)
    (tmp_path / "foo").mkdir()
    assert analyze_runner.find_first_free_slug("foo") == "foo-2"


def test_find_first_free_slug_walks_to_first_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze_runner._paths, "cache_dir", lambda: tmp_path)
    for name in ("foo", "foo-2", "foo-3", "foo-5"):
        (tmp_path / name).mkdir()
    assert analyze_runner.find_first_free_slug("foo") == "foo-4"


def test_find_first_free_slug_skips_existing_dash_2_only(tmp_path, monkeypatch):
    # Base doesn't exist on disk but foo-2 does — verify we walk past it
    # to foo-3 (proves the function only checks the dash-N suffixes).
    monkeypatch.setattr(analyze_runner._paths, "cache_dir", lambda: tmp_path)
    (tmp_path / "foo-2").mkdir()
    assert analyze_runner.find_first_free_slug("foo") == "foo-3"


def test_slug_for_filename_strips_non_audio_extension():
    # Defense-in-depth: even if a non-audio filename reaches the helper
    # (the API endpoint rejects these at the door with 415, but callers
    # of the helper directly should still get sensible output), the
    # original extension must NOT leak into the slug.
    assert "pdf" not in analyze_runner.slug_for_filename("Track 1.0.pdf")
    assert "m4a" not in analyze_runner.slug_for_filename("recording.m4a")
    assert "ogg" not in analyze_runner.slug_for_filename("audio.ogg")


import asyncio


def test_transcode_to_mp3_invokes_ffmpeg(tmp_path, monkeypatch):
    """Verify the argv list and that yielded events include phase markers."""
    captured: dict = {}

    class FakeProc:
        returncode = 0
        async def wait(self):
            return 0

        class _StreamEnd:
            async def readline(self):
                return b""

        stdout = _StreamEnd()
        stderr = _StreamEnd()

    async def fake_spawn(*argv, **kw):
        captured["argv"] = argv
        # Touch the output file so the post-check passes.
        Path(argv[-1]).write_bytes(b"\xff\xfb\x90")  # MP3 frame header bytes
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    src = tmp_path / "in.wav"
    src.write_bytes(b"\x00" * 44)  # placeholder WAV header
    out = tmp_path / "out.mp3"

    events = asyncio.run(_collect(analyze_runner.transcode_to_mp3(src, out)))

    assert captured["argv"][0] == "ffmpeg"
    assert "-c:a" in captured["argv"]
    assert "libmp3lame" in captured["argv"]
    assert "-q:a" in captured["argv"]
    assert "0" in captured["argv"]
    # Phase markers
    assert any(_event(e)["type"] == "phase" and _event(e)["name"] == "transcode" and _event(e)["status"] == "start" for e in events)
    assert any(_event(e)["type"] == "phase" and _event(e)["name"] == "transcode" and _event(e)["status"] == "end" for e in events)


def test_transcode_to_mp3_emits_error_on_nonzero_exit(tmp_path, monkeypatch):
    class FakeProc:
        returncode = 1
        async def wait(self):
            return 1

        class _StreamEnd:
            async def readline(self):
                return b""

        stdout = _StreamEnd()
        stderr = _StreamEnd()

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    src = tmp_path / "in.wav"
    src.write_bytes(b"\x00")
    out = tmp_path / "out.mp3"
    events = asyncio.run(_collect(analyze_runner.transcode_to_mp3(src, out)))
    error_events = [_event(e) for e in events if _event(e)["type"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["kind"] == "ffmpeg_failed"


# --- helpers ---------------------------------------------------------------
import json as _json


async def _collect(agen):
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


def _event(chunk: bytes) -> dict:
    return _json.loads(chunk.decode("utf-8").rstrip("\n"))


# --- is_stale_ytdlp_stderr ---------------------------------------------------

@pytest.mark.parametrize("stderr_blob", [
    "ERROR: HTTP Error 403: Forbidden",
    "WARNING: Your yt-dlp version (2024.01.01) is older than 90 days, please update with -U",
    "WARNING: Some web formats have been skipped as they are missing a url\nERROR: download failed",
    "ERROR: Sign in to confirm you're not a bot. Use --cookies",
    "ERROR: Requested format is not available. Use --list-formats for a list of available formats",
])
def test_is_stale_ytdlp_stderr_detects_known_triggers(stderr_blob):
    assert analyze_runner.is_stale_ytdlp_stderr(stderr_blob) is True


@pytest.mark.parametrize("stderr_blob", [
    "",
    "WARNING: video may be age-restricted",
    "ERROR: Video unavailable. This video is private",
    "WARNING: Falling back to generic extractor",
    "Some web formats have been skipped as they are missing a url",  # without download failure
    # Regression: SABR warning + a non-download ERROR.failed line must NOT
    # trigger staleness. ("Failed to extract player response" is a transient
    # extractor error, not a yt-dlp staleness signal.)
    "WARNING: Some web formats have been skipped as they are missing a url\nERROR: Failed to extract any player response",
])
def test_is_stale_ytdlp_stderr_negatives(stderr_blob):
    assert analyze_runner.is_stale_ytdlp_stderr(stderr_blob) is False


def test_youtube_metadata_slug_happy_path(monkeypatch):
    class FakeProc:
        returncode = 0
        async def communicate(self):
            return (b"Bohemian Rhapsody-zXyAbCd1234\n", b"")

    captured = {}

    async def fake_spawn(*argv, **kw):
        captured["argv"] = argv
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is True
    assert result["predicted_slug"] == "bohemian_rhapsody-zxyabcd1234"
    # YT_DLP_BIN defaults to "yt-dlp" (PATH lookup); MUSIQ_YTDLP_BIN env var
    # can override with a full path. Either way the basename matches.
    assert "yt-dlp" in str(captured["argv"][0])
    assert "--skip-download" in captured["argv"]
    assert "--print" in captured["argv"]


def test_youtube_metadata_slug_stale(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"", b"ERROR: HTTP Error 403: Forbidden\n")

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is False
    assert result["kind"] == "ytdlp_stale"


def test_youtube_metadata_slug_other_failure(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"", b"ERROR: Video unavailable\n")

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is False
    assert result["kind"] == "ytdlp_metadata_failed"


def test_youtube_metadata_slug_whitespace_only_stdout(monkeypatch):
    """yt-dlp returncode=0 but produces only whitespace must NOT raise."""
    class FakeProc:
        returncode = 0
        async def communicate(self):
            return (b"   \n", b"")

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)
    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is False
    assert result["kind"] == "ytdlp_metadata_failed"
    assert "no output" in result["stderr"]


def test_youtube_progress_regex_parses_known_format():
    parsed = analyze_runner.parse_ytdlp_progress(
        "[download]  42.7% of   12.34MiB at    3.21MiB/s ETA 00:01:29"
    )
    assert parsed is not None
    assert parsed["pct"] == 42.7
    assert parsed["eta_sec"] == 89
    assert parsed["speed"] == "3.21MiB/s"


def test_youtube_progress_regex_returns_none_for_other_lines():
    assert analyze_runner.parse_ytdlp_progress("[generic] Extracting URL") is None
    assert analyze_runner.parse_ytdlp_progress("") is None


def test_youtube_download_emits_progress_and_filepath(tmp_path, monkeypatch):
    """Mocked yt-dlp emits two progress lines + a final-path line."""
    output_lines = [
        b"[download]  10.0% of   12.34MiB at    3.21MiB/s ETA 00:00:30\n",
        b"[download] 100.0% of   12.34MiB at    3.21MiB/s ETA 00:00:00\n",
        f"{tmp_path}/Cool Song-vidid12345.mp3\n".encode(),
        b"",  # EOF
    ]

    class FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)
        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        returncode = 0
        def __init__(self):
            self.stdout = FakeStream(output_lines)
            self.stderr = FakeStream([b""])
        async def wait(self):
            return 0

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)

    events = asyncio.run(_collect(analyze_runner.youtube_download("https://x")))
    progress_events = [_event(e) for e in events if _event(e)["type"] == "progress"]
    assert len(progress_events) == 2
    assert progress_events[0]["pct"] == 10.0
    assert progress_events[1]["pct"] == 100.0
    final_events = [_event(e) for e in events if _event(e)["type"] == "downloaded"]
    assert len(final_events) == 1
    assert "Cool Song-vidid12345.mp3" in final_events[0]["path"]


def test_extract_youtube_id_common_url_forms():
    assert analyze_runner._extract_youtube_id("https://www.youtube.com/watch?v=DEiT-N4Wp-s") == "DEiT-N4Wp-s"
    assert analyze_runner._extract_youtube_id("https://youtu.be/DEiT-N4Wp-s") == "DEiT-N4Wp-s"
    assert analyze_runner._extract_youtube_id("https://www.youtube.com/shorts/DEiT-N4Wp-s") == "DEiT-N4Wp-s"
    assert analyze_runner._extract_youtube_id("https://www.youtube.com/watch?v=DEiT-N4Wp-s&list=foo") == "DEiT-N4Wp-s"
    # Non-matching forms return None
    assert analyze_runner._extract_youtube_id("https://example.com/foo") is None
    # 11-char IDs only — shorter/longer don't match
    assert analyze_runner._extract_youtube_id("https://youtu.be/short") is None


def test_youtube_download_recovers_actual_path_via_id_glob(tmp_path, monkeypatch):
    """yt-dlp's printed `after_move:filepath` mangles fullwidth chars (｜),
    but the on-disk file uses them. Glob by the URL's 11-char video ID
    after success and prefer the on-disk hit over the printed path.
    """
    import asyncio

    # The actual on-disk file has fullwidth bars (yt-dlp's real Windows behavior);
    # the printed path will have regular spaces (the bug we're working around).
    on_disk = tmp_path / "JVKE - golden hour ｜｜ piano cover by keudae-DEiT-N4Wp-s.mp3"
    on_disk.write_bytes(b"\x00")  # contents irrelevant
    printed_wrong = str(tmp_path / "JVKE - golden hour  piano cover by keudae-DEiT-N4Wp-s.mp3")

    output_lines = [
        b"[download] 100.0% of   1.0MiB at    1.0MiB/s ETA 00:00:00\n",
        (printed_wrong + "\n").encode("utf-8"),
        b"",
    ]

    class FakeStream:
        def __init__(self, lines):
            self._lines = list(lines)
        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        returncode = 0
        def __init__(self):
            self.stdout = FakeStream(output_lines)
            self.stderr = FakeStream([b""])
        async def wait(self):
            return 0

    async def fake_spawn(*argv, **kw):
        return FakeProc()

    monkeypatch.setattr(analyze_runner, "_async_spawn", fake_spawn)
    monkeypatch.setattr(analyze_runner, "YT_OUT_DIR", tmp_path)

    events = asyncio.run(_collect(analyze_runner.youtube_download(
        "https://www.youtube.com/watch?v=DEiT-N4Wp-s"
    )))
    final_events = [_event(e) for e in events if _event(e)["type"] == "downloaded"]
    assert len(final_events) == 1
    # Recovered the on-disk path (with ｜｜), not the printed-wrong path.
    assert final_events[0]["path"] == str(on_disk)


# ---------------------------------------------------------------------------
# WI-11: STAGE_ARTIFACTS + selective _clear_cache_dir
# ---------------------------------------------------------------------------

def _populate_cache(cache: Path) -> None:
    """Set up a fixture cache with stems, transcription, and chords artifacts."""
    cache.mkdir(parents=True)
    (cache / "stems_6s").mkdir()
    (cache / "stems_6s" / "foo.wav").touch()
    (cache / "stems_routing.json").touch()
    (cache / "midi").mkdir()
    (cache / "midi" / "vocals.mid").touch()
    (cache / "transcription_summary.json").touch()
    (cache / "chords.json").touch()
    (cache / ".params_chords.json").touch()
    (cache / "chat.json").touch()          # PRESERVED
    (cache / f"{cache.name}.mp3").touch()  # PRESERVED


def test_stage_artifacts_dict_exported():
    """STAGE_ARTIFACTS must be a non-empty dict with string keys and list values."""
    sa = analyze_runner.STAGE_ARTIFACTS
    assert isinstance(sa, dict)
    assert len(sa) > 0
    for stage, globs in sa.items():
        assert isinstance(stage, str)
        assert isinstance(globs, list)
        assert all(isinstance(g, str) for g in globs)


def test_full_clear_preserves_user_artifacts(tmp_path: Path):
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    analyze_runner._clear_cache_dir(cache)
    assert (cache / "chat.json").exists()
    assert (cache / f"{cache.name}.mp3").exists()
    assert not (cache / "stems_6s").exists()
    assert not (cache / "midi").exists()
    assert not (cache / "chords.json").exists()


def test_selective_clear_only_transcription(tmp_path: Path):
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    analyze_runner._clear_cache_dir(cache, only_stages={"transcription"})
    # Transcription artifacts gone
    assert not (cache / "midi").exists()
    assert not (cache / "transcription_summary.json").exists()
    # Other stages preserved
    assert (cache / "stems_6s").exists()
    assert (cache / "chords.json").exists()
    assert (cache / "chat.json").exists()


def test_selective_clear_unknown_stage_raises(tmp_path: Path):
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    with pytest.raises(ValueError, match="unknown"):
        analyze_runner._clear_cache_dir(cache, only_stages={"nonsense"})


def test_selective_clear_multiple_stages(tmp_path: Path):
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    analyze_runner._clear_cache_dir(cache, only_stages={"transcription", "chords"})
    assert not (cache / "midi").exists()
    assert not (cache / "chords.json").exists()
    assert (cache / "stems_6s").exists()


def test_selective_clear_preserves_user_artifacts(tmp_path: Path):
    """Selective clear must also respect the PRESERVE list."""
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    analyze_runner._clear_cache_dir(cache, only_stages={"stems"})
    # PRESERVE items must still be intact
    assert (cache / "chat.json").exists()
    assert (cache / f"{cache.name}.mp3").exists()
    # stems artifacts gone
    assert not (cache / "stems_6s").exists()
    assert not (cache / "stems_routing.json").exists()


def test_selective_clear_empty_stages_set_is_noop(tmp_path: Path):
    """Passing only_stages=set() should delete nothing."""
    cache = tmp_path / "test-slug"
    _populate_cache(cache)
    analyze_runner._clear_cache_dir(cache, only_stages=set())
    assert (cache / "stems_6s").exists()
    assert (cache / "chords.json").exists()
