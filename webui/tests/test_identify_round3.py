"""Round 3 tests — silence-strip preprocessing + SCHEMA_VERSION=3.

Covers C1's 16-item test plan plus R3 blocker fixes:
  - Gate behavior (crossed / not crossed / disabled)
  - Soft-fail on ffmpeg errors (not found, nonzero exit)
  - Temp WAV cleanup via the outer try/finally
  - Raw-first / stripped-fallback ordering
  - Sidecar param invalidation across the schema bump
  - silence_end > 30s anchor check
  - Post-strip duration < 30s skips the stripped AcoustID lookup
  - source=acoustid_stripped vs source=acoustid log distinction
  - source=acoustid_unenriched on MB error (D3 fold-in)
  - Recording tie-break by recording.id (R2 fold-in)
  - .acoustid_raw.json written on the stripped match path

Plus three integration tests that exercise real ffmpeg + real fpcalc
against the validated corpus tracks. They auto-skip if the corpus MP3s
are not present (so the suite still runs cleanly elsewhere).
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from analyze import sidecar as analyze_sidecar
from analyze.clients import acoustid as acoustid_client
from analyze.stages import identify as identify_stage


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _ok_fpcalc_subprocess(fingerprint: str = "AQADtest", duration: float = 200.0):
    """Build a fake subprocess.CompletedProcess that mimics fpcalc -json."""
    return _fake_completed(
        stdout=json.dumps({"fingerprint": fingerprint, "duration": duration})
    )


def _install_fake_fpcalc_binary(monkeypatch, tmp_path):
    """Make ``_FPCALC.exists()`` return True so ``_run_fpcalc`` doesn't bail
    on the existence check. Caller still monkeypatches ``subprocess.run``."""
    fpcalc_path = tmp_path / "fake_fpcalc"
    fpcalc_path.write_text("")
    monkeypatch.setattr(identify_stage, "_FPCALC", fpcalc_path)


class _SubprocessRouter:
    """Routes ``subprocess.run`` calls based on the first arg of argv:
       'ffmpeg'    -> next ffmpeg fake (silencedetect or silenceremove)
       <fpcalc>    -> next fpcalc fake (returns a JSON-stdout result)

    Each list is consumed FIFO. Calls beyond the planned count raise.
    """

    def __init__(
        self,
        ffmpeg_responses: list,
        fpcalc_responses: list,
        fpcalc_marker: str,
    ):
        self.ffmpeg = list(ffmpeg_responses)
        self.fpcalc = list(fpcalc_responses)
        self.fpcalc_marker = fpcalc_marker
        self.ffmpeg_calls = []
        self.fpcalc_calls = []

    def __call__(self, cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            self.ffmpeg_calls.append(list(cmd))
            if not self.ffmpeg:
                raise AssertionError(
                    f"unexpected ffmpeg call (no more planned): {cmd}"
                )
            response = self.ffmpeg.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        if prog == self.fpcalc_marker or prog.endswith("fake_fpcalc"):
            self.fpcalc_calls.append(list(cmd))
            if not self.fpcalc:
                raise AssertionError(
                    f"unexpected fpcalc call (no more planned): {cmd}"
                )
            response = self.fpcalc.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        raise AssertionError(f"unrouted subprocess call: {cmd}")


@pytest.fixture
def silent_detect_no_silence():
    return _fake_completed(stderr="[no silence events]\n")


@pytest.fixture
def silent_detect_short():
    return _fake_completed(
        stderr="[silencedetect @ 0x] silence_end: 0.1234 | silence_duration: 0.123\n"
    )


@pytest.fixture
def silent_detect_long():
    return _fake_completed(
        stderr="[silencedetect @ 0x] silence_end: 6.4700 | silence_duration: 6.47\n"
    )


@pytest.fixture
def silent_detect_45():
    return _fake_completed(
        stderr="[silencedetect @ 0x] silence_end: 0.453424 | silence_duration: 0.453\n"
    )


# ---------------------------------------------------------------------------
# Schema version regression guard (C1 §11)
# ---------------------------------------------------------------------------


def test_schema_version_is_at_least_3():
    """Regression guard for the Round 3 bump — Round 4 bumped to 4 but the
    silence-strip preprocessing still ships, so the schema floor stays at 3.
    test_schema_version_is_4 (Round 4) asserts the exact current value."""
    assert identify_stage.SCHEMA_VERSION >= 3


# ---------------------------------------------------------------------------
# 1. test_silence_gate_not_crossed (C1 §9 #1)
# ---------------------------------------------------------------------------


def test_silence_gate_not_crossed(monkeypatch, tmp_path, silent_detect_short):
    """silencedetect returns 0.1234s; gate (0.3) NOT crossed; no strip
    invoked; fpcalc called on raw MP3 exactly once."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    router = _SubprocessRouter(
        ffmpeg_responses=[silent_detect_short],
        fpcalc_responses=[_ok_fpcalc_subprocess()],
        fpcalc_marker="fake_fpcalc",
    )
    monkeypatch.setattr(identify_stage.subprocess, "run", router)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    # Only the silencedetect probe should have run, and only one fpcalc on
    # the raw MP3. No silenceremove.
    assert len(router.ffmpeg_calls) == 1
    assert "silencedetect" in " ".join(router.ffmpeg_calls[0])
    assert len(router.fpcalc_calls) == 1


# ---------------------------------------------------------------------------
# 2. test_silence_gate_crossed_strips (C1 §9 #2)
# ---------------------------------------------------------------------------


def test_silence_gate_crossed_strips(monkeypatch, tmp_path, silent_detect_45):
    """silencedetect returns 0.45s; gate crossed; silenceremove fires;
    raw fpcalc called first; if raw AcoustID = None, stripped fpcalc fires."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    # The silenceremove call needs to write the temp WAV that fpcalc later
    # reads — but since we monkeypatch _run_fpcalc to never actually touch
    # the file, we only need silenceremove to "succeed" + leave the temp
    # marker in place. We DO need to fabricate the temp WAV though because
    # _strip_leading_silence's `tempfile.mkstemp` creates one for real.
    def _fake_silenceremove(cmd, *args, **kwargs):
        # output file is the last positional in cmd; write 1 byte so it exists
        out = Path(cmd[-1])
        out.write_bytes(b"\x00")
        return _fake_completed()

    fpcalc_raw = _ok_fpcalc_subprocess(fingerprint="RAW_FP", duration=301.7)
    fpcalc_stripped = _ok_fpcalc_subprocess(
        fingerprint="STRIPPED_FP", duration=301.25
    )

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_45
            return _fake_silenceremove(cmd, *args, **kwargs)
        # fpcalc
        if "RAW_FP" not in _route._raw_done:
            _route._raw_done.append("RAW_FP")
            return fpcalc_raw
        return fpcalc_stripped

    _route._raw_done = []

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    # Raw AcoustID returns None; stripped returns a match.
    lookup_calls = []

    def _lookup(fp, dur, **kw):
        lookup_calls.append((fp, dur))
        if fp == "RAW_FP":
            return None
        return {
            "mbid_recording": "rec-stripped",
            "acoustid_score": 0.92,
            "acoustid_id": "ac-1",
        }

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    # Two AcoustID lookups in order: raw then stripped.
    assert [c[0] for c in lookup_calls] == ["RAW_FP", "STRIPPED_FP"]
    assert result["identified"] is True
    assert result["mbid_recording"] == "rec-stripped"


# ---------------------------------------------------------------------------
# 3. test_silence_strip_disabled (C1 §9 #3)
# ---------------------------------------------------------------------------


def test_silence_strip_disabled(monkeypatch, tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            raise AssertionError("ffmpeg must not be called when disabled")
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    identify_stage.run(
        tmp_path / "fake.mp3", cache_dir, silence_strip_enabled=False,
    )


# ---------------------------------------------------------------------------
# 4. test_soft_fail_ffmpeg_not_found (C1 §9 #4)
# ---------------------------------------------------------------------------


def test_soft_fail_ffmpeg_not_found(monkeypatch, tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    def _route(cmd, *args, **kwargs):
        if str(cmd[0]) == "ffmpeg":
            raise FileNotFoundError("ffmpeg: command not found")
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    # Should not raise; fall through to raw fpcalc.
    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert result["identified"] is False


# ---------------------------------------------------------------------------
# 5. test_soft_fail_ffmpeg_nonzero (C1 §9 #5)
# ---------------------------------------------------------------------------


def test_soft_fail_ffmpeg_nonzero(monkeypatch, tmp_path):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    def _route(cmd, *args, **kwargs):
        if str(cmd[0]) == "ffmpeg":
            return _fake_completed(returncode=1, stderr="codec error\n")
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    # No exception propagated; raw fpcalc ran; AcoustID returned None.
    assert result["identified"] is False


# ---------------------------------------------------------------------------
# 6. test_temp_wav_cleaned_up_after_fpcalc_error (C1 §9 #6, R3 critical)
# ---------------------------------------------------------------------------


def test_temp_wav_cleaned_up_after_fpcalc_error(
    monkeypatch, tmp_path, silent_detect_long,
):
    """Outer try/finally must unlink strip_tmp even when fpcalc on the raw
    MP3 raises FpcalcError and we return early."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    created_temps = []

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            # silenceremove — create the temp WAV
            out = Path(cmd[-1])
            out.write_bytes(b"\x00")
            created_temps.append(out)
            return _fake_completed()
        # fpcalc — fail with non-JSON output
        return _fake_completed(stdout="not json {{{ trash")

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert result["identified"] is False

    # The temp WAV was created during preprocessing; outer finally cleaned it.
    assert created_temps, "silenceremove should have created a temp WAV"
    for t in created_temps:
        assert not t.exists(), f"temp WAV not cleaned up: {t}"


# ---------------------------------------------------------------------------
# 7. test_temp_wav_cleaned_up_after_acoustid_error (C1 §9 #7, R3 critical)
# ---------------------------------------------------------------------------


def test_temp_wav_cleaned_up_after_acoustid_error(
    monkeypatch, tmp_path, silent_detect_long,
):
    """Outer try/finally fires when AcoustID raises on the raw lookup."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    created_temps = []

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            out = Path(cmd[-1])
            out.write_bytes(b"\x00")
            created_temps.append(out)
            return _fake_completed()
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    def _boom(*a, **kw):
        raise acoustid_client.AcoustIDError("transport: simulated")

    monkeypatch.setattr(acoustid_client, "lookup", _boom)

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert result["identified"] is False
    assert "AcoustID error" in result["reason"]
    assert created_temps
    for t in created_temps:
        assert not t.exists(), f"temp WAV not cleaned up: {t}"


# ---------------------------------------------------------------------------
# 8. test_raw_first_stripped_fallback_fires (C1 §9 #8)
# ---------------------------------------------------------------------------


def test_raw_first_stripped_fallback_fires(
    monkeypatch, tmp_path, silent_detect_long,
):
    """When raw AcoustID = None and strip_tmp exists, the stripped lookup
    fires and its match is returned."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    fpcalc_responses = [
        _ok_fpcalc_subprocess(fingerprint="RAW", duration=344.7),
        _ok_fpcalc_subprocess(fingerprint="STRIPPED", duration=338.2),
    ]

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            Path(cmd[-1]).write_bytes(b"\x00")
            return _fake_completed()
        return fpcalc_responses.pop(0)

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    lookups = []

    def _lookup(fp, dur, **kw):
        lookups.append(fp)
        if fp == "RAW":
            return None
        return {
            "mbid_recording": "rec-strip",
            "acoustid_score": 0.91,
            "acoustid_id": "ac-2",
        }

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert lookups == ["RAW", "STRIPPED"]
    assert result["identified"] is True
    assert result["mbid_recording"] == "rec-strip"


# ---------------------------------------------------------------------------
# 9. test_raw_first_no_second_call_if_raw_matches (C1 §9 #9)
# ---------------------------------------------------------------------------


def test_raw_first_no_second_call_if_raw_matches(
    monkeypatch, tmp_path, silent_detect_long,
):
    """Even though strip_tmp would be created (gate crossed), if RAW
    AcoustID returns a match, no second fpcalc + no second AcoustID."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    fpcalc_calls = []

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            Path(cmd[-1]).write_bytes(b"\x00")
            return _fake_completed()
        fpcalc_calls.append(cmd)
        return _ok_fpcalc_subprocess(fingerprint="RAW_OK", duration=344.0)

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    lookup_calls = []

    def _lookup(fp, dur, **kw):
        lookup_calls.append(fp)
        return {
            "mbid_recording": "rec-raw",
            "acoustid_score": 0.92,
            "acoustid_id": "ac-3",
        }

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    assert len(fpcalc_calls) == 1
    assert lookup_calls == ["RAW_OK"]


# ---------------------------------------------------------------------------
# 10. test_raw_first_no_strip_if_gate_not_crossed (C1 §9 #10)
# ---------------------------------------------------------------------------


def test_raw_first_no_strip_if_gate_not_crossed(
    monkeypatch, tmp_path, silent_detect_no_silence,
):
    """Zero-silence track: gate not crossed; raw AcoustID returns None;
    no stripped fallback (strip_tmp is None)."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    ffmpeg_calls = []
    fpcalc_calls = []

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            ffmpeg_calls.append(cmd)
            if "silencedetect" in " ".join(cmd):
                return silent_detect_no_silence
            raise AssertionError("silenceremove must not run when gate not crossed")
        fpcalc_calls.append(cmd)
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    # silencedetect ran exactly once; silenceremove never ran; one fpcalc.
    assert len(ffmpeg_calls) == 1
    assert len(fpcalc_calls) == 1


# ---------------------------------------------------------------------------
# 11. test_silence_strip_params_reach_sidecar (C1 §9 #11)
# ---------------------------------------------------------------------------


def test_silence_strip_params_reach_sidecar(
    monkeypatch, tmp_path, silent_detect_no_silence,
):
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    def _route(cmd, *args, **kwargs):
        if str(cmd[0]) == "ffmpeg":
            return silent_detect_no_silence
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: None)

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    sidecar_path = cache_dir / ".params_identify.json"
    assert sidecar_path.exists()
    data = json.loads(sidecar_path.read_text())
    # Round 4 bumped 3 -> 4; the silence_strip_* params still ship and the
    # sidecar still carries them, so the R3 assertions are widened to
    # "at least 3" here. test_identify_round4 owns the exact-version check.
    assert data["schema_version"] >= 3
    for key in (
        "silence_strip_enabled",
        "silence_strip_threshold_db",
        "silence_strip_min_duration_sec",
        "silence_strip_gate_sec",
    ):
        assert key in data["params"], f"missing param key: {key}"


# ---------------------------------------------------------------------------
# 12. test_schema_v2_sidecar_invalidated_by_new_params (C1 §9 #12)
# ---------------------------------------------------------------------------


def test_schema_v2_sidecar_invalidated_by_new_params(tmp_path):
    """A pre-Round-3 sidecar (schema_version=2, params={}) is not equal to
    the v3 DEFAULT_PARAMS and triggers re-run. The legacy bridge in
    cached() rescues identified=true caches separately (covered by the
    R2 test_legacy_cache_synthesizes_sidecar)."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    # Write a v2 sidecar with empty params (the old default).
    (cache_dir / ".params_identify.json").write_text(json.dumps({
        "schema_version": 2, "params": {},
    }))
    # No identify.json so the legacy bridge does NOT fire.
    assert identify_stage.cached(cache_dir) is False


# ---------------------------------------------------------------------------
# 13. test_silence_end_above_30s_returns_zero (R3 Finding 3E)
# ---------------------------------------------------------------------------


def test_silence_end_above_30s_returns_zero(monkeypatch, tmp_path):
    """silence_end > 30s is an internal gap, not a leading slate. Treat
    it as "no leading silence" so the gate never crosses."""
    fake = _fake_completed(
        stderr="[silencedetect @ 0x] silence_end: 42.5 | silence_duration: 1.2\n"
    )
    monkeypatch.setattr(
        identify_stage.subprocess, "run", lambda *a, **kw: fake,
    )
    result = identify_stage._detect_leading_silence(
        tmp_path / "fake.mp3", threshold_db=-50, min_duration_sec=0.3,
    )
    assert result == 0.0


# ---------------------------------------------------------------------------
# 14. test_post_strip_duration_below_30_skips_stripped_lookup (R3 Finding 8C)
# ---------------------------------------------------------------------------


def test_post_strip_duration_below_30_skips_stripped_lookup(
    monkeypatch, tmp_path, silent_detect_long,
):
    """If the stripped WAV's fingerprint duration is below 30s, the
    stripped AcoustID lookup is skipped. fpcalc accuracy and the AcoustID
    DB both reject short fingerprints."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    fpcalc_responses = [
        _ok_fpcalc_subprocess(fingerprint="RAW", duration=344.0),
        # Stripped fingerprint is suspiciously short — DON'T look it up.
        _ok_fpcalc_subprocess(fingerprint="STRIPPED", duration=12.0),
    ]

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            Path(cmd[-1]).write_bytes(b"\x00")
            return _fake_completed()
        return fpcalc_responses.pop(0)

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    lookups = []

    def _lookup(fp, dur, **kw):
        lookups.append(fp)
        return None  # raw also returns None

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)

    result = identify_stage.run(tmp_path / "fake.mp3", cache_dir)
    # Only RAW was looked up; STRIPPED was NOT (duration guard tripped).
    assert lookups == ["RAW"]
    assert result["identified"] is False


# ---------------------------------------------------------------------------
# 15. test_log_emits_acoustid_stripped_when_stripped_match_wins (R3 Finding 3C)
# ---------------------------------------------------------------------------


def test_log_emits_acoustid_stripped_when_stripped_match_wins(
    monkeypatch, tmp_path, silent_detect_long, caplog,
):
    cache_dir = tmp_path / "myslug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    fpcalc_responses = [
        _ok_fpcalc_subprocess(fingerprint="RAW", duration=344.0),
        _ok_fpcalc_subprocess(fingerprint="STRIPPED", duration=338.0),
    ]

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            Path(cmd[-1]).write_bytes(b"\x00")
            return _fake_completed()
        return fpcalc_responses.pop(0)

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    def _lookup(fp, dur, **kw):
        if fp == "RAW":
            return None
        return {
            "mbid_recording": "rec-strip",
            "acoustid_score": 0.91,
            "acoustid_id": "ac-2",
        }

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    with caplog.at_level(logging.INFO, logger=identify_stage.__name__):
        identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    matching = [r for r in caplog.records if "identify: slug=" in r.getMessage()]
    assert matching, "expected an identify: log line"
    msg = matching[-1].getMessage()
    assert "source=acoustid_stripped" in msg, msg
    assert "mbid=rec-strip" in msg

    # And: the on-disk identify.json must NOT carry the internal flag.
    payload = json.loads((cache_dir / "identify.json").read_text())
    assert "_fingerprint_source" not in payload


# ---------------------------------------------------------------------------
# 16. test_log_emits_acoustid_unenriched_when_mb_fails (D3 fold-in)
# ---------------------------------------------------------------------------


def test_log_emits_acoustid_unenriched_when_mb_fails(
    monkeypatch, tmp_path, silent_detect_no_silence, caplog,
):
    cache_dir = tmp_path / "myslug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    def _route(cmd, *args, **kwargs):
        if str(cmd[0]) == "ffmpeg":
            return silent_detect_no_silence
        return _ok_fpcalc_subprocess()

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)
    monkeypatch.setattr(acoustid_client, "lookup", lambda *a, **kw: {
        "mbid_recording": "rec-mb-fail",
        "acoustid_score": 0.91,
        "acoustid_id": "ac-9",
    })

    def _mb_boom(mbid, **kw):
        raise identify_stage.musicbrainz_client.MusicBrainzError("HTTP 503")

    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup", _mb_boom,
    )

    with caplog.at_level(logging.INFO, logger=identify_stage.__name__):
        identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    matching = [r for r in caplog.records if "identify: slug=" in r.getMessage()]
    assert matching, "expected an identify: log line"
    msg = matching[-1].getMessage()
    assert "source=acoustid_unenriched" in msg, msg
    assert "mbid=rec-mb-fail" in msg


# ---------------------------------------------------------------------------
# 17. test_recording_tiebreak_uses_recording_id_secondary_key (R2 fold-in)
# ---------------------------------------------------------------------------


def test_recording_tiebreak_uses_recording_id_secondary_key(monkeypatch):
    """When two recordings have identical |duration - target| delta, the
    selector must break ties by recording.id (lexicographic) so the
    chosen recording is deterministic across runs."""
    api_key_patch = monkeypatch.setattr(
        acoustid_client.keys, "get_acoustid_key", lambda: "FAKE",
    )
    # Two recordings with the same delta (|200-200|=0 both). Without the
    # secondary key the choice depends on dict iteration order; the fix
    # pins it to the alphabetically smaller id.
    body = {
        "status": "ok",
        "results": [{
            "id": "ac-1", "score": 0.92,
            "recordings": [
                {"id": "zzz-second", "duration": 200},
                {"id": "aaa-first", "duration": 200},
            ],
        }],
    }

    class _Resp:
        status_code = 200
        text = json.dumps(body)

        def json(self):
            return body

    class _Client:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def get(self, *a, **kw): return _Resp()

    monkeypatch.setattr(acoustid_client.httpx, "Client", _Client)
    out = acoustid_client.lookup("AQADtest", 200.0)
    assert out is not None
    assert out["mbid_recording"] == "aaa-first"


# ---------------------------------------------------------------------------
# 18. test_cached_response_written_on_stripped_path (R3 Finding 3D)
# ---------------------------------------------------------------------------


def test_cached_response_written_on_stripped_path(
    monkeypatch, tmp_path, silent_detect_long,
):
    """The .acoustid_raw.json sidecar must be written even when the
    stripped fingerprint produces the match. R3 Finding 3D — the
    integration would silently drop the raw payload from the stripped
    path without this."""
    cache_dir = tmp_path / "slug"
    cache_dir.mkdir()
    _install_fake_fpcalc_binary(monkeypatch, tmp_path)

    fpcalc_responses = [
        _ok_fpcalc_subprocess(fingerprint="RAW", duration=344.0),
        _ok_fpcalc_subprocess(fingerprint="STRIPPED", duration=338.0),
    ]

    def _route(cmd, *args, **kwargs):
        prog = str(cmd[0])
        if prog == "ffmpeg":
            if "silencedetect" in " ".join(cmd):
                return silent_detect_long
            Path(cmd[-1]).write_bytes(b"\x00")
            return _fake_completed()
        return fpcalc_responses.pop(0)

    monkeypatch.setattr(identify_stage.subprocess, "run", _route)

    stripped_raw = {
        "status": "ok",
        "results": [{
            "id": "ac-2", "score": 0.91,
            "recordings": [{"id": "rec-strip", "duration": 338}],
        }],
    }

    def _lookup(fp, dur, **kw):
        if fp == "RAW":
            return None
        return {
            "mbid_recording": "rec-strip",
            "acoustid_score": 0.91,
            "acoustid_id": "ac-2",
            "raw_response": stripped_raw,
        }

    monkeypatch.setattr(acoustid_client, "lookup", _lookup)
    monkeypatch.setattr(
        identify_stage.musicbrainz_client, "recording_lookup",
        lambda mbid, **kw: {
            "mbid_recording": mbid, "title": "T", "artist": "A",
            "mbid_artist": "a-1", "release": None,
            "mbid_release_group": None, "year": 2020, "isrc": None,
        },
    )

    identify_stage.run(tmp_path / "fake.mp3", cache_dir)

    raw_path = cache_dir / ".acoustid_raw.json"
    assert raw_path.exists(), "stripped path must persist .acoustid_raw.json"
    cached = json.loads(raw_path.read_text())
    assert cached["response"] == stripped_raw

    # The raw payload must not leak into identify.json.
    main = json.loads((cache_dir / "identify.json").read_text())
    assert "raw_response" not in main
    assert "_fingerprint_source" not in main


# ===========================================================================
# Integration tests — real ffmpeg + fpcalc against the corpus
# ===========================================================================


_CORPUS_ROOT = Path(__file__).resolve().parents[2] / "cache"

_CHARLIE_MP3 = (
    _CORPUS_ROOT / "charlie_puth_attention" / "charlie_puth_attention.mp3"
)
_REN_MP3 = (
    _CORPUS_ROOT
    / "ren_x_chinchilla_chalk_outlines"
    / "ren_x_chinchilla_chalk_outlines.mp3"
)
_BALTHAZAR_MP3 = (
    _CORPUS_ROOT
    / "balthazar-changes_official_video-p3jb998acqo"
    / "balthazar-changes_official_video-p3jb998acqo.mp3"
)


@pytest.mark.skipif(not _CHARLIE_MP3.exists(), reason="corpus MP3 not present")
def test_integration_charlie_puth_silence_strip():
    """Real silenceremove on charlie_puth: 0.45s leading silence -> output
    duration ~ (150 - 0.45) ≈ 149.55s. We assert the output is between
    140s and 150s (well below the raw 301.7s of the full MP3 — the -t 150
    cap dominates here)."""
    out = identify_stage._strip_leading_silence(
        _CHARLIE_MP3, threshold_db=-50, min_duration_sec=0.3,
    )
    try:
        # Probe duration via ffprobe.
        result = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        duration = float(result.stdout.strip())
        # 150s cap minus 0.45s strip ≈ 149.55s. Be lenient — ±1s.
        assert 140.0 < duration < 150.0, f"got {duration}"
    finally:
        out.unlink(missing_ok=True)


@pytest.mark.skipif(not _REN_MP3.exists(), reason="corpus MP3 not present")
def test_integration_ren_x_chinchilla_silence_strip():
    """ren_x_chinchilla: 6.47s leading silence; -t 150 caps the output
    at (150 - 6.47) ≈ 143.5s."""
    out = identify_stage._strip_leading_silence(
        _REN_MP3, threshold_db=-50, min_duration_sec=0.3,
    )
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        duration = float(result.stdout.strip())
        # Expected ~143.5s; allow ±1.5s.
        assert 141.0 < duration < 145.0, f"got {duration}"
    finally:
        out.unlink(missing_ok=True)


@pytest.mark.skipif(
    not _BALTHAZAR_MP3.exists(), reason="corpus MP3 not present"
)
def test_integration_balthazar_no_strip():
    """balthazar has 0.00s leading silence per R1; the probe should return
    0.0 (no silence_end event) and the gate would not cross."""
    leading = identify_stage._detect_leading_silence(
        _BALTHAZAR_MP3, threshold_db=-50, min_duration_sec=0.3,
    )
    assert leading == 0.0
