import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient


def _client(synthetic_cache):
    from webui.server import app
    return TestClient(app)


def test_root_serves_index_html(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/")
    assert r.status_code == 200
    assert "MusIQ-Lab" in r.text


def test_origin_guard_rejects_non_loopback_and_malformed_hosts(synthetic_cache):
    c = _client(synthetic_cache)

    assert c.get("/", headers={"host": "localhost:8765"}).status_code == 200
    assert c.get("/", headers={"host": "evil.example"}).status_code == 403
    assert c.get("/", headers={"host": "localhost:8765/poison"}).status_code == 403
    assert c.get("/", headers={"host": "localhost:notaport"}).status_code == 403


def test_origin_guard_rejects_non_loopback_and_malformed_origins(synthetic_cache):
    c = _client(synthetic_cache)

    assert c.get("/", headers={"origin": "http://localhost:8765"}).status_code == 200
    assert c.get("/", headers={"origin": "https://127.0.0.1:8765"}).status_code == 200
    assert c.get("/", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.get("/", headers={"origin": "http://localhost:8765/poison"}).status_code == 403
    assert c.get("/", headers={"origin": "http://localhost:notaport"}).status_code == 403


def test_api_tracks_returns_list(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["slug"] == "gorillaz_silent_running"
    assert data[0]["key"] == "F minor"
    assert data[0]["has_vocals"] is True
    # New column: staleness probe runs alongside the basic listing.
    assert "stale_stages" in data[0]
    assert isinstance(data[0]["stale_stages"], list)


def test_api_tracks_marks_legacy_cache_stale(synthetic_cache):
    """Synthetic cache has summary.json but no per-stage sidecars or
    canonical outputs → every required stage is stale (legacy pre-sidecar
    cache profile). The UI uses this list to wire the ⟳ button."""
    # Reset the staleness module's memo so a previous test's probe doesn't
    # bleed through (the in-memory cache is keyed by slug + mtime tuple).
    from webui import staleness
    staleness._cache.clear()
    c = _client(synthetic_cache)
    r = c.get("/api/tracks")
    data = r.json()
    stale = set(data[0]["stale_stages"])
    # All five required stages should show up since the fixture only writes
    # summary.json — no per-stage canonicals.
    assert {"stems", "beats", "key", "chords", "transcription"}.issubset(stale)


def test_api_track_summary_returns_full_object(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running")
    assert r.status_code == 200
    data = r.json()
    assert data["track"]["tempo_bpm"] == 107.14
    assert len(data["chords"]) == 2


def test_api_track_summary_unknown_slug_returns_404(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/does_not_exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "unknown_slug"
    assert "gorillaz_silent_running" in body["available"]


def test_api_f0_decodes_and_returns_json(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    fcpe = np.array([0.0, 220.0, 440.0], dtype=np.float32)
    pesto = np.array([110.0, 220.0, 330.0], dtype=np.float32)
    np.savez(track_dir / "vocal_f0.npz", fcpe=fcpe, pesto=pesto)

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/f0")
    assert r.status_code == 200
    body = r.json()
    assert body["n_frames"] == 3
    assert body["hop_sec"] == 0.01
    assert len(body["fcpe"]) == 3


def test_api_f0_missing_returns_404(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/f0")
    assert r.status_code == 404


def test_api_f0_includes_consensus_when_available(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    fcpe = np.array([0.0, 220.0, 440.0], dtype=np.float32)
    pesto = np.array([110.0, 220.0, 440.0], dtype=np.float32)
    np.savez(track_dir / "vocal_f0.npz", fcpe=fcpe, pesto=pesto)
    # Consensus stage outputs
    np.savez(
        track_dir / "vocal_consensus.npz",
        fcpe_corrected=fcpe,
        pesto_corrected=pesto,
        consensus_f0=np.array([np.nan, 220.0, 440.0], dtype=np.float32),
        agreement_strength=np.array([0.0, 0.85, 1.0], dtype=np.float32),
        vote_count=np.array([0, 3, 3], dtype=np.int8),
        octave_corrections=np.zeros((3, 2), dtype=np.int8),
    )

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/f0")
    assert r.status_code == 200
    body = r.json()
    assert body["consensus"] is not None
    cs = body["consensus"]
    assert cs["consensus_f0"][0] is None       # NaN serialized as null
    assert cs["consensus_f0"][1] == 220.0
    assert cs["vote_count"] == [0, 3, 3]
    assert cs["agreement_strength"] == [0.0, pytest.approx(0.85), 1.0]


def test_api_f0_returns_null_consensus_when_stage_not_run(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    fcpe = np.array([220.0, 440.0], dtype=np.float32)
    pesto = np.array([220.0, 440.0], dtype=np.float32)
    np.savez(track_dir / "vocal_f0.npz", fcpe=fcpe, pesto=pesto)
    # No vocal_consensus.npz written

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/f0")
    assert r.status_code == 200
    assert r.json()["consensus"] is None


def test_api_vocal_consensus_returns_summary(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    summary = {
        "schema_version": 1,
        "fps": 100.0,
        "n_frames": 200,
        "consensus_summary": {
            "frames_vote_3": 40,
            "frames_vote_2": 0,
            "frames_vote_1": 0,
            "frames_vote_0": 160,
            "frames_with_consensus_f0": 40,
            "octave_corrections_fcpe": 0,
            "octave_corrections_pesto": 0,
        },
        "n_notes": 1,
        "notes": [{
            "t_start": 0.5, "t_end": 0.9, "midi": 69,
            "intonation_cents": 18.3, "stability_cents": 4.2,
            "confidence": 0.92, "n_frames_used": 24,
        }],
    }
    (track_dir / "vocal_consensus.json").write_text(json.dumps(summary))

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/vocal_consensus")
    assert r.status_code == 200
    body = r.json()
    assert body["n_notes"] == 1
    assert body["notes"][0]["intonation_cents"] == 18.3


def test_api_vocal_consensus_missing_returns_404(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/vocal_consensus")
    assert r.status_code == 404


def test_api_audio_source_serves_full_when_no_range(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = track_dir / "gorillaz_silent_running.mp3"
    payload = b"\xff\xfb" + (b"\x00" * 1022)  # 1024 bytes of pseudo-mp3
    mp3.write_bytes(payload)

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/audio/source")
    assert r.status_code == 200
    assert r.content == payload
    assert r.headers["accept-ranges"] == "bytes"


def test_api_audio_source_honors_range(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = track_dir / "gorillaz_silent_running.mp3"
    payload = bytes(range(256)) * 4  # 1024 bytes, distinct values
    mp3.write_bytes(payload)

    c = _client(synthetic_cache)
    r = c.get(
        "/api/tracks/gorillaz_silent_running/audio/source",
        headers={"Range": "bytes=100-199"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 100-199/1024"
    assert r.content == payload[100:200]


def test_api_audio_source_416_when_out_of_bounds(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = track_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\x00" * 100)

    c = _client(synthetic_cache)
    r = c.get(
        "/api/tracks/gorillaz_silent_running/audio/source",
        headers={"Range": "bytes=500-1000"},
    )
    assert r.status_code == 416
    assert r.headers["content-range"] == "bytes */100"


def test_api_audio_stem_serves_wav(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    stems_dir = track_dir / "stems_6s"
    stems_dir.mkdir()
    wav = stems_dir / "anything_(Vocals)_htdemucs_6s.wav"
    sf.write(wav, np.zeros((100, 2), dtype=np.float32), 44100)

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/audio/stem/vocals")
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF"


def test_api_audio_stem_drums_served_when_wav_present(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    stems_dir = track_dir / "stems_6s"
    stems_dir.mkdir()
    wav = stems_dir / "anything_(Drums)_htdemucs_6s.wav"
    sf.write(wav, np.zeros((100, 2), dtype=np.float32), 44100)

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/audio/stem/drums")
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF"


def test_api_audio_stem_missing_returns_404_with_reason(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/audio/stem/drums")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "missing_stem"
    assert body["name"] == "drums"


def test_api_midi_endpoint(synthetic_cache):
    track_dir = synthetic_cache / "gorillaz_silent_running"
    midi_dir = track_dir / "midi"
    midi_dir.mkdir()
    (midi_dir / "vocals.mid").write_bytes(b"MThd\x00\x00\x00\x06fake")

    c = _client(synthetic_cache)
    r = c.get("/api/tracks/gorillaz_silent_running/midi/vocals")
    assert r.status_code == 200
    assert r.content[:4] == b"MThd"


def test_tool_endpoints_registered(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post("/api/tools/open-midi/gorillaz_silent_running/vocals")
    # 404 because no midi file in fixture; we only assert the route exists
    assert r.status_code in (200, 404)


def test_api_reanalyze_unknown_slug_emits_error_event(synthetic_cache):
    c = _client(synthetic_cache)
    # Slug must match the safe alphabet (post-2026-05-24 hardening) — use a
    # plausible-but-absent slug rather than the old `__no_such_slug__` literal.
    r = c.post("/api/tools/reanalyze/no-such-slug-zzz")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    import json as _json
    events = [_json.loads(ln) for ln in lines]
    assert any(e["type"] == "error" and "unknown slug" in e["message"] for e in events)


def test_api_reanalyze_no_source_emits_error_event(synthetic_cache):
    # The fixture's track.windows_path points at C:\fake\path.mp3 (doesn't
    # exist) and there is no cache mirror, so the route should bail before
    # attempting a WSL invocation. Guards us against accidentally shelling
    # out from a CI run.
    c = _client(synthetic_cache)
    r = c.post("/api/tools/reanalyze/gorillaz_silent_running")
    assert r.status_code == 200
    import json as _json
    events = [_json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    assert any(e["type"] == "error" and "no source MP3" in e["message"] for e in events)


def test_api_reanalyze_recovers_when_summary_missing_but_mp3_present(synthetic_cache, monkeypatch):
    # Recovery path: a prior reanalyze got killed mid-pipeline (e.g. the user
    # closed the modal, ASGI client-disconnect fired the finally that kills
    # the WSL subprocess), leaving the cache without summary.json but WITH
    # the source mp3 (the mirror is preserved across clears). Reanalyze must
    # still drive the pipeline against the cache mirror instead of bailing
    # with "unknown slug" — otherwise the track is permanently stranded.
    cache_dir = synthetic_cache / "halfcleared_track"
    cache_dir.mkdir()
    mp3 = cache_dir / "halfcleared_track.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")
    # Deliberately NO summary.json — that's the simulated post-disconnect state.

    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["slug"] = slug
        captured["source"] = Path(source)
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    c = _client(synthetic_cache)
    r = c.post("/api/tools/reanalyze/halfcleared_track")
    assert r.status_code == 200
    events = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    # No "unknown slug" error must be emitted; the stub-emitted done event
    # must reach the client.
    assert not any(e.get("type") == "error" for e in events), events
    assert any(e.get("type") == "done" for e in events), events
    # The runner was invoked with a path under the cache dir, which means the
    # tempfile was copied from cache_mp3 (the recovery branch).
    assert captured["slug"] == "halfcleared_track"
    assert captured["source"].name == "halfcleared_track.mp3"


def test_analyze_lock_released_after_unknown_slug_error(synthetic_cache):
    # Regression for the lock-leak fix: an early-error response must release
    # the lock so a follow-up request can acquire it. The previous code path
    # also did this for explicit early errors, but the orphan-subprocess case
    # (covered by killing on stream exit) needs the same guarantee.
    from webui.analyze_runner import _analyze_lock
    c = _client(synthetic_cache)
    r = c.post("/api/tools/reanalyze/no-such-slug-zzz")
    assert r.status_code == 200
    # Drain the body so the streaming response generator runs to completion.
    _ = r.text
    assert not _analyze_lock.locked()


def test_slug_for_no_collision(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "Brand_New.mp3"})
    assert r.status_code == 200
    j = r.json()
    assert j == {"slug": "brand_new", "exists": False, "suggested_new_slug": "brand_new-2"}


def test_slug_for_existing_track_collides(synthetic_cache):
    # Match the synthetic_cache slug exactly: gorillaz_silent_running
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "gorillaz_silent_running.mp3"})
    assert r.status_code == 200
    j = r.json()
    assert j["slug"] == "gorillaz_silent_running"
    assert j["exists"] is True
    assert j["suggested_new_slug"] == "gorillaz_silent_running-2"


def test_slug_for_unsupported_extension(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "song.m4a"})
    assert r.status_code == 415
    j = r.json()
    assert j["error"] == "unsupported_type"
    assert j["extension"] == ".m4a"


def test_slug_for_no_extension(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "noext"})
    assert r.status_code == 415
    assert r.json()["extension"] == ""


def test_analyze_upload_rejects_unsupported_extension(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/upload",
        files={"file": ("song.m4a", b"\x00\x00\x00", "audio/mp4")},
        data={"quality": "best", "mode": "new", "slug": "song"},
    )
    assert r.status_code == 415


def test_analyze_upload_rejects_invalid_slug(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/upload",
        files={"file": ("brand_new.mp3", b"\xff\xfb", "audio/mpeg")},
        data={"quality": "best", "mode": "new", "slug": "../etc/passwd"},
    )
    assert r.status_code == 400


def test_analyze_upload_rejects_collision_when_mode_new(synthetic_cache):
    """Filename slugs to an existing entry but mode=new + slug=existing.
    Server must reject with 409."""
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/upload",
        files={"file": ("gorillaz_silent_running.mp3", b"\xff\xfb", "audio/mpeg")},
        data={"quality": "best", "mode": "new", "slug": "gorillaz_silent_running"},
    )
    assert r.status_code == 409


def test_analyze_upload_invalid_quality_rejected(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/upload",
        files={"file": ("brand_new.mp3", b"\xff\xfb", "audio/mpeg")},
        data={"quality": "ludicrous", "mode": "new", "slug": "brand_new"},
    )
    assert r.status_code == 400


def test_analyze_upload_absolute_filename_stays_in_tempdir(synthetic_cache, monkeypatch):
    """Fix 2 regression: Content-Disposition filename with an absolute path
    must NOT escape the tempdir.  The server must use basename only when
    constructing tmp_path, so the written file still lives under the
    mkdtemp directory.
    """
    import tempfile as _tempfile

    captured = {}

    async def _fake_stream(slug, mp3_path, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["mp3_path"] = mp3_path
        # Yield a minimal valid ndjson so the streaming response completes.
        import json as _json
        yield (_json.dumps({"type": "done"}) + "\n").encode()

    monkeypatch.setattr("webui.analyze_runner.run_analyze_stream", _fake_stream)

    # Supply a filename that looks like an absolute path on Linux/Windows.
    # The slug for "/tmp/escape.mp3" is "escape" (Path stem normalised).
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/upload",
        files={"file": ("/tmp/escape.mp3", b"\xff\xfb", "audio/mpeg")},
        data={"quality": "best", "mode": "new", "slug": "escape"},
    )
    # The streaming endpoint returns 200 (even for errors it streams ndjson).
    assert r.status_code == 200

    # The path passed to run_analyze_stream must live inside a tempdir, not
    # at an absolute path derived from the raw filename.
    assert "mp3_path" in captured, "run_analyze_stream was never called"
    mp3_path = captured["mp3_path"]
    # Basename must be just the filename component, not a full path.
    assert mp3_path.name == "escape.mp3", f"unexpected name: {mp3_path.name}"
    # The file's parent must be the mkdtemp-created directory (starts with
    # the OS tempdir prefix, not e.g. /tmp directly from the client filename).
    assert mp3_path.parent != _tempfile.gettempdir(), (
        "tmp_path escaped to system tempdir root — basename not applied"
    )
    # Crucially: the parent directory must exist and be under the system temp
    # root as a sub-directory (the mkdtemp dir), not be the raw /tmp itself.
    assert mp3_path.parent.name.startswith("musiq_upload_"), (
        f"parent dir doesn't look like a musiq_upload_ tempdir: {mp3_path.parent}"
    )


def test_analyze_youtube_dry_run_happy_path(synthetic_cache, monkeypatch):
    from webui import analyze_runner

    async def fake_meta(url, *, update_first=False):
        return {"ok": True, "predicted_slug": "fresh_slug-vidid12345"}

    monkeypatch.setattr(analyze_runner, "youtube_metadata_slug", fake_meta)
    c = _client(synthetic_cache)
    r = c.post("/api/tools/analyze/youtube", json={"url": "https://x", "dry_run": True})
    assert r.status_code == 200
    j = r.json()
    assert j["predicted_slug"] == "fresh_slug-vidid12345"
    assert j["exists"] is False
    assert j["suggested_new_slug"] == "fresh_slug-vidid12345-2"


def test_analyze_youtube_dry_run_stale(synthetic_cache, monkeypatch):
    from webui import analyze_runner

    async def fake_meta(url, *, update_first=False):
        return {"ok": False, "kind": "ytdlp_stale", "stderr": "HTTP Error 403"}

    monkeypatch.setattr(analyze_runner, "youtube_metadata_slug", fake_meta)
    c = _client(synthetic_cache)
    r = c.post("/api/tools/analyze/youtube", json={"url": "https://x", "dry_run": True})
    assert r.status_code == 503
    assert r.json()["error"] == "ytdlp_stale"


def test_analyze_youtube_invalid_body(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post("/api/tools/analyze/youtube", json={})
    assert r.status_code == 400
    r = c.post("/api/tools/analyze/youtube", json={"url": ""})
    assert r.status_code == 400
    r = c.post(
        "/api/tools/analyze/youtube",
        content="{",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_analyze_youtube_reanalyze_missing_source_emits_error(synthetic_cache, monkeypatch):
    """Reanalyze branch: when neither windows_path nor cached MP3 exists,
    the stream must emit a source_not_found error event instead of letting
    shutil.copy2 raise FileNotFoundError mid-stream (which Starlette would
    silently swallow as an abrupt connection close)."""
    from webui import analyze_runner

    # synthetic_cache creates gorillaz_silent_running with:
    #   - windows_path = C:\fake\path.mp3  (does not exist)
    #   - no gorillaz_silent_running.mp3 in cache
    # So the missing-source branch fires without any extra setup.

    async def fake_meta(url, *, update_first=False):
        return {"ok": True, "predicted_slug": "gorillaz_silent_running"}

    monkeypatch.setattr(analyze_runner, "youtube_metadata_slug", fake_meta)
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tools/analyze/youtube",
        json={"url": "https://x", "mode": "reanalyze", "slug": "gorillaz_silent_running"},
    )
    assert r.status_code == 200  # streaming endpoint always returns 200
    import json as _json
    events = [_json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    assert any(
        e.get("type") == "error" and e.get("kind") == "source_not_found"
        for e in events
    ), f"expected source_not_found error event, got: {events}"


from unittest.mock import patch


def test_lyrics_get_404_when_uncached(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/tracks/demo/lyrics")
    assert r.status_code == 404


def test_lyrics_paste_then_get(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post("/api/tracks/demo/lyrics/paste", json={"text": "[00:01.00]hello\n[00:05.00]world\n"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_sync"] is True
    g = c.get("/api/tracks/demo/lyrics")
    assert g.status_code == 200
    assert g.json()["lines"][0]["text"] == "hello"


def test_lyrics_paste_invalid_json_returns_400(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.post(
        "/api/tracks/demo/lyrics/paste",
        content="{",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_lyrics_fetch_falls_back_to_user_meta_when_lyrics_meta_missing(synthetic_cache):
    """Regression: after Refetch deletes the lyrics directory, the fetch must
    still respect the rename — user_meta.json's display_name (the rename's
    canonical home) is consulted before falling through to identify_track."""
    captured = {}
    async def fake_lookup(*, artist, title, duration_sec, album="", _transport=None):
        captured["artist"] = artist
        captured["title"] = title
        return {
            "source": "lrclib", "has_sync": False, "synced_lrc": None,
            "plain_text": None, "lrclib_id": None, "error": "not_found",
        }

    import json as _json
    # Seed user_meta.json with a rename, leave lyrics/meta.json absent.
    (synthetic_cache / "gorillaz_silent_running" / "user_meta.json").write_text(
        _json.dumps({"display_name": "Gorillaz - Silent Running"}),
        encoding="utf-8",
    )

    c = _client(synthetic_cache)
    with patch("webui.lyrics.lrclib_lookup", fake_lookup):
        r = c.post("/api/tracks/gorillaz_silent_running/lyrics/fetch", json={})
    assert r.status_code == 200
    assert captured == {"artist": "Gorillaz", "title": "Silent Running"}
    assert r.json()["meta"]["artist"] == "Gorillaz"
    assert r.json()["meta"]["title"] == "Silent Running"


def test_lyrics_paste_preserves_existing_artist_title(synthetic_cache):
    """Regression: pasting lyrics must not clobber a prior rename's artist/title.
    save_synced/save_plain overwrites meta.json wholesale, so the route has to
    merge any existing values before saving."""
    import json as _json
    lyr = synthetic_cache / "demo" / "lyrics"
    lyr.mkdir(parents=True, exist_ok=True)
    (lyr / "meta.json").write_text(_json.dumps({
        "source": "user_rename", "lrclib_id": None,
        "artist": "Balthazar", "title": "Changes",
        "album": "", "duration_sec": 0,
    }), encoding="utf-8")

    c = _client(synthetic_cache)
    r = c.post("/api/tracks/demo/lyrics/paste", json={"text": "[00:01.00]hello\n"})
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["artist"] == "Balthazar"
    assert body["meta"]["title"] == "Changes"


def test_lyrics_fetch_calls_lrclib(synthetic_cache):
    async def fake_lookup(*, artist, title, duration_sec, album="", _transport=None):
        return {
            "source": "lrclib", "has_sync": True,
            "synced_lrc": "[00:01.00]hello\n", "plain_text": "hello",
            "lrclib_id": 42,
        }

    c = _client(synthetic_cache)
    with patch("webui.lyrics.lrclib_lookup", fake_lookup):
        # NOTE: using gorillaz_silent_running (not "demo") because the fetch
        # route calls tracks.get_summary(slug); only that slug exists in the
        # synthetic_cache fixture.
        r = c.post("/api/tracks/gorillaz_silent_running/lyrics/fetch", json={"artist": "A", "title": "T"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_sync"] is True
    assert body["meta"]["lrclib_id"] == 42


def test_lyrics_fetch_empty_body_prefers_cached_meta_over_identify_track(synthetic_cache):
    """Regression: a rename writes lyrics/meta.json with smart-split artist/title.
    A subsequent empty-body fetch (e.g. lyrics-tab _lazyLoad after refresh hook)
    must use those values rather than re-deriving from the filename and clobbering
    the rename's good data."""
    captured = {}
    async def fake_lookup(*, artist, title, duration_sec, album="", _transport=None):
        captured["artist"] = artist
        captured["title"] = title
        return {
            "source": "lrclib", "has_sync": False, "synced_lrc": None,
            "plain_text": None, "lrclib_id": None, "error": "not_found",
        }

    # Seed lyrics/meta.json with rename-style values (simulating a prior PATCH).
    import json as _json
    lyr = synthetic_cache / "gorillaz_silent_running" / "lyrics"
    lyr.mkdir(parents=True, exist_ok=True)
    (lyr / "meta.json").write_text(_json.dumps({
        "source": "user_rename", "lrclib_id": None,
        "artist": "Gorillaz", "title": "Silent Running",
        "album": "", "duration_sec": 215.0,
    }), encoding="utf-8")

    c = _client(synthetic_cache)
    with patch("webui.lyrics.lrclib_lookup", fake_lookup):
        r = c.post("/api/tracks/gorillaz_silent_running/lyrics/fetch", json={})
    assert r.status_code == 200
    # LRCLIB was called with the cached meta values, not the filename-derived ones.
    assert captured == {"artist": "Gorillaz", "title": "Silent Running"}
    # Returned meta also reflects the cached values.
    assert r.json()["meta"]["artist"] == "Gorillaz"
    assert r.json()["meta"]["title"] == "Silent Running"


def test_lyrics_delete(synthetic_cache):
    c = _client(synthetic_cache)
    c.post("/api/tracks/demo/lyrics/paste", json={"text": "hello"})
    r = c.delete("/api/tracks/demo/lyrics")
    assert r.status_code == 200
    g = c.get("/api/tracks/demo/lyrics")
    assert g.status_code == 404


def test_chat_history_initially_empty(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/chat/demo")
    assert r.status_code == 200
    assert r.json() == {"messages": []}


def test_chat_clear(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.delete("/api/chat/demo")
    assert r.status_code == 200


def _install_fake_claude_client(monkeypatch, *, scripts=None, query_raises=None):
    """Replace ClaudeSDKClient with a fake so chat actor tests don't spawn
    the real claude.exe. Returns the captured FakeClient list."""
    from unittest.mock import MagicMock
    from webui import chat_actor as actor_mod

    captured = []

    class FakeClient:
        def __init__(self, options=None):
            self.options = options
            self._scripts = list(scripts or [])
            self._query_raises = query_raises
            self.aexit_calls = 0
            self.queries = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self.aexit_calls += 1

        async def query(self, text):
            self.queries.append(text)
            if self._query_raises is not None:
                raise self._query_raises

        async def receive_response(self):
            script = self._scripts.pop(0) if self._scripts else []
            for m in script:
                yield m

    def _ctor(options=None):
        c = FakeClient(options=options)
        captured.append(c)
        return c

    monkeypatch.setattr(actor_mod, "ClaudeSDKClient", _ctor)
    return captured


def _mk_text_block(text):
    from unittest.mock import MagicMock
    b = MagicMock(spec=["text"])
    b.text = text
    return b


def _mk_result_msg(session_id="sid"):
    from unittest.mock import MagicMock
    m = MagicMock(spec=["session_id", "usage", "duration_ms"])
    m.session_id = session_id
    m.usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0}
    m.duration_ms = 100
    return m


def _mk_assistant_msg(blocks):
    from unittest.mock import MagicMock
    m = MagicMock(spec=["content"])
    m.content = blocks
    return m


def _ctx_client(synthetic_cache):
    """Use TestClient as a context manager so all requests in a test share
    one event loop. Required for chat actor tests because the actor's worker
    task is bound to whichever loop is active at start() — without `with`,
    each TestClient call may run in a fresh loop and the worker task ends
    up cancelled."""
    from webui.server import app
    return TestClient(app)


def test_chat_turn_streams_with_mocked_sdk(synthetic_cache, monkeypatch):
    script = [_mk_assistant_msg([_mk_text_block("hi"), _mk_text_block(" there")]),
              _mk_result_msg(session_id="sid")]
    _install_fake_claude_client(monkeypatch, scripts=[script])
    with _ctx_client(synthetic_cache) as c:
        payload = {"text": "hello", "view_state": {"playhead_sec": 1.0}}
        r = c.post("/api/chat/gorillaz_silent_running/turn", json=payload)
        assert r.status_code == 200
        body = r.text.strip().splitlines()
        parsed = [json.loads(line) for line in body]
        assert parsed[0]["type"] == "text"
        assert parsed[0]["delta"] == "hi"
        assert parsed[-1]["type"] == "done"
        assert parsed[-1]["session_id"] == "sid"


def test_chat_turn_invalid_json_returns_400_before_actor_creation(synthetic_cache, monkeypatch):
    captured = _install_fake_claude_client(monkeypatch)
    with _ctx_client(synthetic_cache) as c:
        r = c.post(
            "/api/chat/gorillaz_silent_running/turn",
            content="{",
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 400
    assert captured == []


def test_chat_turn_busy_returns_409(synthetic_cache, monkeypatch):
    # Simulate a chat already in flight by forcing actor.is_busy() True for
    # any actor the registry hands out.
    from webui import chat_actor as actor_mod
    _install_fake_claude_client(monkeypatch)
    monkeypatch.setattr(actor_mod.ChatActor, "is_busy", lambda self: True)
    with _ctx_client(synthetic_cache) as c:
        r = c.post("/api/chat/gorillaz_silent_running/turn", json={"text": "hi"})
        assert r.status_code == 409


def test_chat_clear_kills_actor(synthetic_cache, monkeypatch):
    script = [_mk_assistant_msg([_mk_text_block("ok")]), _mk_result_msg()]
    _install_fake_claude_client(monkeypatch, scripts=[script])
    with _ctx_client(synthetic_cache) as c:
        # First, run one turn so an actor exists and chat.json is written.
        r = c.post("/api/chat/gorillaz_silent_running/turn", json={"text": "hi"})
        assert r.status_code == 200
        chat_path = synthetic_cache / "gorillaz_silent_running" / "chat.json"
        assert chat_path.exists()
        # DELETE should kill the actor and remove chat.json.
        r = c.delete("/api/chat/gorillaz_silent_running")
        assert r.status_code == 200
        assert not chat_path.exists()


def test_chat_turn_persists_interleaved_blocks_in_original_order(synthetic_cache, monkeypatch):
    """Regression: gen() previously concatenated all text into one leading
    block and put tool blocks after. That broke _restoreHistory rendering —
    prose at the top, chips at the bottom. Now blocks must be preserved in
    original interleaved order."""
    from unittest.mock import MagicMock

    text1 = _mk_text_block("Looking now. ")
    tu = MagicMock(spec=["id", "name", "input"])
    tu.id = "tu1"
    tu.name = "mcp__musiq-tools__get_chord_at"
    tu.input = {"time_sec": 3.0, "current_slug": "gorillaz_silent_running"}
    text2 = _mk_text_block("It's a G major.")
    tr = MagicMock(spec=["tool_use_id", "content", "is_error"])
    tr.tool_use_id = "tu1"
    tr.content = [{"type": "text", "text": "G:maj"}]
    tr.is_error = False

    # SDK yields: assistant(text1+toolcall) → user(toolresult) → assistant(text2) → done
    script = [
        _mk_assistant_msg([text1, tu]),
        _mk_assistant_msg([tr]),  # tool result message
        _mk_assistant_msg([text2]),
        _mk_result_msg(),
    ]
    _install_fake_claude_client(monkeypatch, scripts=[script])
    with _ctx_client(synthetic_cache) as c:
        r = c.post("/api/chat/gorillaz_silent_running/turn", json={"text": "what chord?"})
        assert r.status_code == 200
    chat_json = json.loads((synthetic_cache / "gorillaz_silent_running" / "chat.json").read_text(encoding="utf-8"))
    # Two messages persisted: user, then assistant.
    msgs = chat_json["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assistant_blocks = msgs[1]["blocks"]
    types = [b["type"] for b in assistant_blocks]
    # The bug would produce ["text", "tool_use", "tool_result"] (all text
    # concatenated up front, tools after). The fix interleaves naturally.
    assert types == ["text", "tool_use", "tool_result", "text"]
    assert assistant_blocks[0]["text"].startswith("Looking now")
    assert assistant_blocks[1]["name"].endswith("get_chord_at")
    assert assistant_blocks[3]["text"] == "It's a G major."


def test_chat_stop_returns_false_when_no_actor(synthetic_cache):
    """No actor for this slug → interrupted:false, no error. The detailed
    forwarding path (ChatActor.interrupt → client.interrupt) is covered as a
    unit test in test_chat_actor.py."""
    c = _client(synthetic_cache)
    r = c.post("/api/chat/gorillaz_silent_running/stop")
    assert r.status_code == 200
    assert r.json() == {"interrupted": False}


def test_chat_stop_forwards_to_registry(synthetic_cache, monkeypatch):
    """Endpoint must call ChatRegistry.interrupt(slug) and return its bool."""
    from webui import server as srv_mod

    seen = {}
    async def fake_interrupt(self, slug):
        seen["slug"] = slug
        return True

    monkeypatch.setattr(srv_mod._chat_registry.__class__, "interrupt", fake_interrupt)
    c = _client(synthetic_cache)
    r = c.post("/api/chat/some-slug/stop")
    assert r.status_code == 200
    assert r.json() == {"interrupted": True}
    assert seen["slug"] == "some-slug"


def test_clear_cache_dir_preserves_chat_lyrics_and_user_meta(synthetic_cache):
    # _clear_cache_dir lives in analyze_runner now (server.py was refactored).
    from webui.analyze_runner import _clear_cache_dir
    cache = synthetic_cache / "demo"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "chat.json").write_text('{"schema_version":1,"messages":[]}', encoding="utf-8")
    lyr = cache / "lyrics"
    lyr.mkdir(parents=True, exist_ok=True)
    (lyr / "synced.lrc").write_text("[00:01.00]hello\n", encoding="utf-8")
    (cache / "user_meta.json").write_text('{"display_name": "Keep Me"}', encoding="utf-8")
    # Source mp3 mirror — the cache copy of the original file. analyze never
    # rewrites it, and reanalyze must not delete it (it's the source).
    (cache / "demo.mp3").write_bytes(b"\xff\xfb\x90")
    (cache / "summary.json").write_text("{}", encoding="utf-8")
    (cache / "stems_6s").mkdir(exist_ok=True)
    (cache / "stems_6s" / "x.wav").write_bytes(b"")
    _clear_cache_dir(cache)
    assert (cache / "chat.json").is_file()
    assert (cache / "lyrics" / "synced.lrc").is_file()
    assert (cache / "user_meta.json").is_file()
    assert (cache / "demo.mp3").is_file()
    assert not (cache / "summary.json").exists()
    assert not (cache / "stems_6s").exists()


def test_clear_cache_dir_raises_typed_error_on_locked_file(synthetic_cache, monkeypatch):
    """Regression: a locked non-preserved file (e.g. an antivirus holding
    summary.json) must surface as CacheLockedError carrying the offending
    path, rather than a raw PermissionError. The reanalyze streaming wrapper
    depends on this typed error to render an actionable message instead of a
    Python traceback. (Uses summary.json since demo.mp3 is in PRESERVE.)"""
    from webui.analyze_runner import _clear_cache_dir, CacheLockedError

    cache = synthetic_cache / "demo"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "summary.json").write_text("{}", encoding="utf-8")

    real_unlink = Path.unlink

    def fake_unlink(self, *args, **kwargs):
        if self.name == "summary.json":
            raise PermissionError(32, "in use")
        return real_unlink(self, *args, **kwargs)

    # Speed up the test — no need to wait the real backoff schedule.
    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr(Path, "unlink", fake_unlink)

    import pytest
    with pytest.raises(CacheLockedError) as exc_info:
        _clear_cache_dir(cache)
    assert exc_info.value.path.name == "summary.json"


def test_rename_happy_path(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch(
        "/api/tracks/gorillaz_silent_running",
        json={"display_name": "Gorillaz - Silent Running"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "display_name": "Gorillaz - Silent Running",
        "artist": "Gorillaz",
        "title": "Silent Running",
    }
    # user_meta.json was written
    import json as _json
    um = _json.loads((synthetic_cache / "gorillaz_silent_running" / "user_meta.json").read_text(encoding="utf-8"))
    assert um["display_name"] == "Gorillaz - Silent Running"
    # GET /api/tracks/<slug> reflects the merge
    g = c.get("/api/tracks/gorillaz_silent_running")
    assert g.json()["track"]["display_name"] == "Gorillaz - Silent Running"


def test_rename_smart_split_no_dash(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch(
        "/api/tracks/gorillaz_silent_running",
        json={"display_name": "Track 03 fragment"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "display_name": "Track 03 fragment",
        "artist": "",
        "title": "Track 03 fragment",
    }


def test_rename_smart_split_partition_first(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch(
        "/api/tracks/gorillaz_silent_running",
        json={"display_name": "A - B - C"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["artist"] == "A"
    assert body["title"] == "B - C"


def test_rename_updates_existing_lyrics_meta(synthetic_cache):
    """When lyrics meta.json already exists, the rename rewrites artist/title
    but preserves other fields (source, lrclib_id, duration_sec)."""
    c = _client(synthetic_cache)
    # Seed lyrics meta with a real LRCLIB record
    lyr = synthetic_cache / "gorillaz_silent_running" / "lyrics"
    lyr.mkdir(parents=True, exist_ok=True)
    import json as _json
    (lyr / "meta.json").write_text(_json.dumps({
        "source": "lrclib", "lrclib_id": 999,
        "artist": "wrong", "title": "wrong",
        "album": "Plastic Beach", "duration_sec": 180.0,
        "fetched_at": "2025-01-01T00:00:00Z", "has_sync": True,
    }), encoding="utf-8")
    r = c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "Gorillaz - Silent Running"})
    assert r.status_code == 200
    meta = _json.loads((lyr / "meta.json").read_text(encoding="utf-8"))
    assert meta["artist"] == "Gorillaz"
    assert meta["title"] == "Silent Running"
    assert meta["lrclib_id"] == 999  # preserved
    assert meta["album"] == "Plastic Beach"  # preserved


def test_rename_creates_lyrics_meta_when_missing(synthetic_cache):
    """No lyrics dir yet -> create it and seed a meta.json with source=user_rename."""
    c = _client(synthetic_cache)
    lyr = synthetic_cache / "gorillaz_silent_running" / "lyrics"
    assert not lyr.exists()
    r = c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "Gorillaz - Silent Running"})
    assert r.status_code == 200
    import json as _json
    meta = _json.loads((lyr / "meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "user_rename"
    assert meta["lrclib_id"] is None
    assert meta["artist"] == "Gorillaz"
    assert meta["title"] == "Silent Running"


def test_rename_validation_empty(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "   "})
    assert r.status_code == 400
    assert "empty" in r.json()["detail"]


def test_rename_validation_too_long(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "x" * 201})
    assert r.status_code == 400
    assert "too long" in r.json()["detail"]


def test_rename_validation_path_chars(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "foo/bar"})
    assert r.status_code == 400
    assert "invalid character" in r.json()["detail"]


def test_rename_unknown_slug(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.patch("/api/tracks/no_such_slug", json={"display_name": "Anything"})
    assert r.status_code == 404


def test_rename_invalidates_list_cache(synthetic_cache):
    c = _client(synthetic_cache)
    # Prime the cache via /api/tracks
    before = c.get("/api/tracks").json()
    assert any(t["slug"] == "gorillaz_silent_running" for t in before)
    c.patch("/api/tracks/gorillaz_silent_running", json={"display_name": "Renamed"})
    after = c.get("/api/tracks").json()
    [entry] = [t for t in after if t["slug"] == "gorillaz_silent_running"]
    assert entry["title"] == "Renamed"


# ---------------------------------------------------------------------------
# WI-11: stages + params payload tests for reanalyze endpoint
# ---------------------------------------------------------------------------

def test_reanalyze_accepts_stages_payload(synthetic_cache, monkeypatch):
    """POST /api/tools/reanalyze/{slug} with {stages: [...]} forwards stages_only."""
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["stages_only"] = stages_only
        captured["params"] = params
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    # Make the source mp3 available so _reanalyze_stream doesn't bail early.
    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/reanalyze/gorillaz_silent_running",
        json={"quality": "fast", "stages": ["transcription"]},
    )
    assert resp.status_code == 200
    # Drain the streaming response so the generator runs.
    _ = resp.text
    assert captured.get("stages_only") == {"transcription"}


def test_reanalyze_accepts_params_payload(synthetic_cache, monkeypatch):
    """POST /api/tools/reanalyze/{slug} with {params: {...}} forwards params."""
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["params"] = params
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/reanalyze/gorillaz_silent_running",
        json={"quality": "fast", "params": {"transcription_vocals": {"agreement_cents": 30}}},
    )
    assert resp.status_code == 200
    _ = resp.text
    assert captured.get("params") == {"transcription_vocals": {"agreement_cents": 30}}


def test_reanalyze_rejects_invalid_stages(synthetic_cache):
    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/reanalyze/gorillaz_silent_running",
        json={"stages": "not-a-list"},
    )
    assert resp.status_code == 400


def test_reanalyze_rejects_invalid_params(synthetic_cache):
    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/reanalyze/gorillaz_silent_running",
        json={"params": "not-an-object"},
    )
    assert resp.status_code == 400


def test_reanalyze_backward_compat_no_body(synthetic_cache, monkeypatch):
    """Empty body still works — stages_only=None, params=None."""
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["quality"] = quality
        captured["stages_only"] = stages_only
        captured["params"] = params
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post("/api/tools/reanalyze/gorillaz_silent_running")
    assert resp.status_code == 200
    _ = resp.text
    assert captured.get("stages_only") is None
    assert captured.get("params") is None


# ---------------------------------------------------------------------------
# /api/tools/analyze-stale/{slug} — non-destructive rerun (no cache clear)
# ---------------------------------------------------------------------------


def test_analyze_stale_endpoint_streams_ndjson_and_skips_cache_clear(
    synthetic_cache, monkeypatch,
):
    """POST /api/tools/analyze-stale/{slug} must:
      1. exist + return a streaming NDJSON body
      2. forward clear_cache=False to run_analyze_stream
    """
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["slug"] = slug
        captured["clear_cache"] = clear_cache
        captured["stages_only"] = stages_only
        captured["params"] = params
        captured["quality"] = quality
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post("/api/tools/analyze-stale/gorillaz_silent_running")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    _ = resp.text  # drain
    assert captured["clear_cache"] is False
    assert captured["slug"] == "gorillaz_silent_running"
    assert captured["stages_only"] is None
    assert captured["params"] is None


def test_analyze_stale_does_not_call_clear_cache_dir(synthetic_cache, monkeypatch):
    """Behavior assertion: with clear_cache=False the runner must NOT call
    _clear_cache_dir even if the cache is non-empty. Spy on the function and
    assert zero calls."""
    from webui import analyze_runner

    calls: list = []
    real_clear = analyze_runner._clear_cache_dir

    def spy_clear(*args, **kwargs):
        calls.append((args, kwargs))
        return real_clear(*args, **kwargs)

    monkeypatch.setattr(analyze_runner, "_clear_cache_dir", spy_clear)

    # Stub out the WSL spawn so we don't actually run analyze; we only need
    # the runner to reach (and skip) the cache-clear branch.
    async def stub_spawn(*args, **kwargs):
        class _P:
            stdout = None
            returncode = 0
            async def wait(self_inner):
                return 0
        # Use a tiny in-memory "stdout" that yields no lines.
        import asyncio as _asyncio
        class _R:
            async def readline(self_inner):
                return b""
        p = _P()
        p.stdout = _R()
        return p

    monkeypatch.setattr(analyze_runner, "_async_spawn", stub_spawn)
    # Stub tracks.get_summary so the success path can find the new summary.
    from webui import tracks
    monkeypatch.setattr(tracks, "get_summary", lambda slug: {"track": {}, "analysis": {}, "provenance": {}, "chords": [], "downbeats": [], "stems": {}})

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")
    # Make the cache non-empty so the would-be clear branch is reachable.
    (cache_dir / "stems_6s").mkdir(exist_ok=True)
    (cache_dir / "stems_6s" / "x.wav").write_bytes(b"\x00")

    c = _client(synthetic_cache)
    resp = c.post("/api/tools/analyze-stale/gorillaz_silent_running")
    assert resp.status_code == 200
    body = resp.text
    # Sanity: the stale-mode log line should appear.
    assert "rerun-stale: skipping cache clear" in body
    # The cache-clear function was never invoked.
    assert calls == [], f"_clear_cache_dir called unexpectedly: {calls}"
    # And the stems directory survived.
    assert (cache_dir / "stems_6s").is_dir()


def test_analyze_stale_accepts_quality_body(synthetic_cache, monkeypatch):
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["quality"] = quality
        captured["clear_cache"] = clear_cache
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/analyze-stale/gorillaz_silent_running",
        json={"quality": "fast"},
    )
    assert resp.status_code == 200
    _ = resp.text
    assert captured["quality"] == "fast"
    assert captured["clear_cache"] is False


def test_analyze_stale_rejects_invalid_quality(synthetic_cache):
    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/analyze-stale/gorillaz_silent_running",
        json={"quality": "ludicrous"},
    )
    assert resp.status_code == 400


def test_analyze_stale_empty_body_uses_defaults(synthetic_cache, monkeypatch):
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["quality"] = quality
        captured["stages_only"] = stages_only
        captured["params"] = params
        captured["clear_cache"] = clear_cache
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post("/api/tools/analyze-stale/gorillaz_silent_running")
    assert resp.status_code == 200
    _ = resp.text
    assert captured["clear_cache"] is False
    assert captured["stages_only"] is None
    assert captured["params"] is None
    # default quality = "best"
    assert captured["quality"] == "best"


def test_reanalyze_stages_and_params_combined(synthetic_cache, monkeypatch):
    """Both stages and params in the same payload are forwarded together."""
    captured: dict = {}

    async def stub_run(slug, source, quality, *, stages_only=None, params=None, clear_cache=True):
        captured["stages_only"] = stages_only
        captured["params"] = params
        yield b'{"type":"done"}\n'

    from webui import analyze_runner
    monkeypatch.setattr(analyze_runner, "run_analyze_stream", stub_run)

    cache_dir = synthetic_cache / "gorillaz_silent_running"
    mp3 = cache_dir / "gorillaz_silent_running.mp3"
    mp3.write_bytes(b"\xff\xfb\x90")

    c = _client(synthetic_cache)
    resp = c.post(
        "/api/tools/reanalyze/gorillaz_silent_running",
        json={
            "quality": "best",
            "stages": ["transcription", "chords"],
            "params": {"chords": {"n_chord_change_smoothing": 3}},
        },
    )
    assert resp.status_code == 200
    _ = resp.text
    assert captured.get("stages_only") == {"transcription", "chords"}
    assert captured.get("params") == {"chords": {"n_chord_change_smoothing": 3}}
