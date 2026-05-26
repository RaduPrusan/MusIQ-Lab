import json
import subprocess
from pathlib import Path

import pytest

from analyze.stages import identify


def _fake_fpcalc_output(fp="FAKE_FP", duration=240.5):
    return (
        f"FILE=/tmp/fake.mp3\n"
        f"DURATION={duration}\n"
        f"FINGERPRINT={fp}\n"
    )


def test_run_writes_identify_json(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"not really audio")

    monkeypatch.setattr(
        identify, "_run_fpcalc",
        lambda p: {"fingerprint": "FP", "duration": 240.5},
    )
    monkeypatch.setattr(
        identify.acoustid_client, "lookup",
        lambda fp, dur, **kw: {
            "mbid_recording": "rec-mbid",
            "acoustid_score": 0.94,
            "acoustid_id": "aid",
        },
    )
    monkeypatch.setattr(
        identify.musicbrainz_client, "recording_lookup",
        lambda mbid: {
            "mbid_recording": mbid, "title": "Track", "artist": "Artist",
            "mbid_artist": "art-mbid", "release": "Album",
            "mbid_release_group": "rg-mbid", "year": 2001, "isrc": "GB000001",
        },
    )

    out = identify.run(mp3, tmp_path)
    assert out["identified"] is True
    assert out["title"] == "Track"
    assert out["acoustid_score"] == 0.94

    on_disk = json.loads((tmp_path / "identify.json").read_text())
    assert on_disk == out


def test_run_soft_fails_below_score_threshold(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    monkeypatch.setattr(
        identify, "_run_fpcalc",
        lambda p: {"fingerprint": "FP", "duration": 100.0},
    )
    monkeypatch.setattr(identify.acoustid_client, "lookup", lambda fp, dur, **kw: None)

    out = identify.run(mp3, tmp_path)
    assert out == {"identified": False, "reason": "no AcoustID match above threshold"}
    assert (tmp_path / "identify.json").exists()


def test_run_soft_fails_when_fpcalc_missing(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")

    def explode(_p):
        raise FileNotFoundError("fpcalc not vendored")
    monkeypatch.setattr(identify, "_run_fpcalc", explode)

    out = identify.run(mp3, tmp_path)
    assert out["identified"] is False
    assert "fpcalc" in out["reason"]


def test_run_soft_fails_on_acoustid_error(monkeypatch, tmp_path):
    from analyze.clients.acoustid import AcoustIDError
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    monkeypatch.setattr(
        identify, "_run_fpcalc",
        lambda p: {"fingerprint": "FP", "duration": 100.0},
    )

    def boom(fp, dur, **kw):
        raise AcoustIDError("no api key")
    monkeypatch.setattr(identify.acoustid_client, "lookup", boom)

    out = identify.run(mp3, tmp_path)
    assert out["identified"] is False
    assert "AcoustID" in out["reason"] or "api key" in out["reason"]


def test_cached_returns_true_after_run(monkeypatch, tmp_path):
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    monkeypatch.setattr(
        identify, "_run_fpcalc",
        lambda p: {"fingerprint": "FP", "duration": 100.0},
    )
    monkeypatch.setattr(identify.acoustid_client, "lookup", lambda fp, dur, **kw: None)
    identify.run(mp3, tmp_path)
    assert identify.cached(tmp_path) is True


def _good_payload(mbid="rec-mbid", title="Track", artist="Artist"):
    return {
        "identified": True,
        "mbid_recording": mbid,
        "acoustid_score": 0.94,
        "acoustid_id": "aid",
        "title": title,
        "artist": artist,
        "mbid_artist": "art-mbid",
        "release": "Album",
        "mbid_release_group": "rg-mbid",
        "year": 2001,
        "isrc": "GB000001",
    }


def test_run_does_not_demote_cached_identified_on_mb_error(monkeypatch, tmp_path):
    """A subsequent run that hits a transient MusicBrainz outage must keep
    the previously-good identification rather than overwrite it with a stub."""
    from analyze.clients.musicbrainz import MusicBrainzError
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    # Seed cache with a known-good identification.
    good = _good_payload()
    identify._write(tmp_path, good, {})

    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: {"fingerprint": "FP", "duration": 240.0})
    monkeypatch.setattr(
        identify.acoustid_client, "lookup",
        lambda fp, dur, **kw: {"mbid_recording": "rec-mbid", "acoustid_score": 0.9, "acoustid_id": "aid"},
    )

    def mb_outage(_mbid):
        raise MusicBrainzError("HTTP 503: service unavailable")
    monkeypatch.setattr(identify.musicbrainz_client, "recording_lookup", mb_outage)

    out = identify.run(mp3, tmp_path)
    assert out == good
    on_disk = json.loads((tmp_path / "identify.json").read_text())
    assert on_disk == good


def test_run_does_not_demote_cached_identified_on_acoustid_error(monkeypatch, tmp_path):
    """Same protection when AcoustID itself errors out."""
    from analyze.clients.acoustid import AcoustIDError
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    good = _good_payload()
    identify._write(tmp_path, good, {})

    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: {"fingerprint": "FP", "duration": 240.0})

    def acoustid_outage(_fp, _dur, **_kw):
        raise AcoustIDError("HTTP 503: service unavailable")
    monkeypatch.setattr(identify.acoustid_client, "lookup", acoustid_outage)

    out = identify.run(mp3, tmp_path)
    assert out == good


def test_run_does_not_demote_cached_identified_on_no_match(monkeypatch, tmp_path):
    """Even a non-transient 'no match above threshold' outcome shouldn't
    overwrite a known-good identification. --force is the explicit reset."""
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    good = _good_payload()
    identify._write(tmp_path, good, {})

    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: {"fingerprint": "FP", "duration": 240.0})
    monkeypatch.setattr(identify.acoustid_client, "lookup", lambda fp, dur, **kw: None)

    out = identify.run(mp3, tmp_path)
    assert out == good


def test_run_overwrites_cached_identified_with_new_identified(monkeypatch, tmp_path):
    """A successful re-run that finds a different MBID should still update
    the cache — preservation only protects against demotion to identified=False."""
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    identify._write(tmp_path, _good_payload(title="Old Title"), {})

    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: {"fingerprint": "FP", "duration": 240.0})
    monkeypatch.setattr(
        identify.acoustid_client, "lookup",
        lambda fp, dur, **kw: {"mbid_recording": "new-mbid", "acoustid_score": 0.99, "acoustid_id": "aid2"},
    )
    monkeypatch.setattr(
        identify.musicbrainz_client, "recording_lookup",
        lambda mbid: {
            "mbid_recording": mbid, "title": "New Title", "artist": "A",
            "mbid_artist": "art", "release": "R", "mbid_release_group": "rg",
            "year": 2020, "isrc": "X",
        },
    )

    out = identify.run(mp3, tmp_path)
    assert out["title"] == "New Title"
    assert out["mbid_recording"] == "new-mbid"


def test_run_overwrites_cached_unidentified_with_new_unidentified(monkeypatch, tmp_path):
    """A stuck transient-error stub can be replaced by a fresh transient-error
    stub — preservation only protects identified=True payloads."""
    mp3 = tmp_path / "fake.mp3"
    mp3.write_bytes(b"x")
    identify._write(tmp_path, {"identified": False, "reason": "old stub"}, {})

    monkeypatch.setattr(identify, "_run_fpcalc", lambda p: {"fingerprint": "FP", "duration": 240.0})
    monkeypatch.setattr(identify.acoustid_client, "lookup", lambda fp, dur, **kw: None)

    out = identify.run(mp3, tmp_path)
    assert out["reason"] == "no AcoustID match above threshold"
