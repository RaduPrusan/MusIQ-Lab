# Analyze-from-library Implementation Plan

> **Status: SHIPPED 2026-05-03** alongside the sidebar/lyrics merge `7cc808b`. Both new entry points are live: "Analyze new audio file" (file upload, MP3 V0 transcode) and "Analyze YouTube URL" (yt-dlp + analyze chain). **File structure diverged from this plan during implementation:** routes live in `webui/webui/server.py` (not a new `library.py`) at `/api/tools/analyze/upload` (server.py:398) and `/api/tools/analyze/youtube` (server.py:500); the UI lives in `webui/static/js/ui/analyze-modal.js` (not new `library-*.js` files). The exact UI strings ("Analyze new audio file", "Analyze YouTube URL") are at `analyze-modal.js:63-64,206`. This was the right call — adding to existing well-scoped files was cheaper than creating new modules. Follow-up fixes (`88b98db` upload-endpoint issues, `1d377af` source_not_found event in YouTube reanalyze path) shipped alongside. **Individual `- [ ]` checkboxes below were not ticked during execution; the merge commit and git log are the authoritative status of record. Plan body retained as historical narrative; consult the actual file structure above if hunting current code.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new entry points to the Library Tracks dropdown — "Analyze new audio file" (browse local mp3/wav/flac, ≤500 MB, transcoded to MP3 V0 if needed) and "Analyze YouTube URL" (yt-dlp download into the canonical Windows folder, then analyze) — with default stem-separation quality set to **Best** for both flows and for the existing Reanalyze modal.

**Architecture:** Python FastAPI server gains three new routes that share a common `_run_analyze_stream` helper (extracted from the existing reanalyze code) emitting an extended NDJSON event protocol with new `phase` / `progress` / `slug` events alongside the existing `log` / `stage` / `done` / `error` types. A single shared `_analyze_lock` guards all three flows. The browser gets a new modal (`analyze-modal.js`) built from helpers shared with `reanalyze.js` (`analyze-shared.js`). Track-picker header gains two compact buttons that open the modal.

**Tech Stack:** Python 3.13 / FastAPI / Starlette `UploadFile` / `asyncio.create_subprocess_exec` / pytest with `fastapi.testclient.TestClient`. JS: ES modules, no build step, `node:test` for unit tests, Playwright for E2E. ffmpeg + yt-dlp.exe spawned as subprocesses (argv list, no shell).

**Spec:** `docs/superpowers/specs/2026-05-02-analyze-from-library-design.md`

---

## File map

**New (Python):**
- `webui/webui/analyze_runner.py` — `_run_analyze_stream`, `_analyze_lock`, `slug_for_filename`, `find_first_free_slug`, `is_stale_ytdlp_stderr`, `transcode_to_mp3`, `youtube_metadata_slug`, `youtube_download`.
- `webui/tests/test_analyze_runner.py` — unit tests for all helpers.

**New (JS):**
- `webui/static/js/ui/analyze-shared.js` — extracted helpers: `buildQualitySelector`, `streamAnalyze` (NDJSON reader), `renderStats`, `STAGE_ORDER`, `QUALITY_PRESETS`, `STATUS_COLOR`.
- `webui/static/js/ui/analyze-modal.js` — `showAnalyzeModal({mode:"file"|"youtube"})`, state machine: input / collision / streaming / done / error.
- `webui/tests-js/analyze-modal.test.js` — state-machine + NDJSON event-handler tests.
- `webui/tests-e2e/analyze-upload.spec.js` — E2E happy path + collision flow.
- `webui/tests-e2e/analyze-youtube.spec.js` — E2E network-tagged YouTube happy path.

**Modified (Python):**
- `webui/webui/server.py` — add `/api/util/slug-for`, `/api/tools/analyze/upload`, `/api/tools/analyze/youtube`; refactor `/api/tools/reanalyze/{slug}` to delegate to `_run_analyze_stream`; rename `_reanalyze_lock` → `_analyze_lock`.

**Modified (JS):**
- `webui/static/js/ui/reanalyze.js` — import shared helpers, flip `DEFAULT_QUALITY` to `"best"`.
- `webui/static/js/ui/track-picker.js` — header gains `+ File` and `+ YT` buttons that dynamically import `analyze-modal.js`.
- `webui/static/js/api.js` — wrappers for the new endpoints.
- `webui/static/css/track.css` — header flex layout, header-button styles.

---

## Task 1: Extract `_run_analyze_stream` helper + fix lock-leak on client disconnect

This is a pure refactor. Existing reanalyze tests must keep passing. We also fix the inherited bug where closing the browser tab mid-stream releases the lock while the WSL subprocess keeps running (orphaned), allowing a second analyze to clobber the same `cache/<slug>/`.

**Files:**
- Create: `webui/webui/analyze_runner.py`
- Modify: `webui/webui/server.py:187-425` (the entire reanalyze block)
- Test: `webui/tests/test_server.py` (existing tests must still pass; we add one for the lock-leak fix)

- [ ] **Step 1: Write the failing test for the lock-leak fix**

Add to `webui/tests/test_server.py`:

```python
def test_analyze_lock_released_after_unknown_slug_error(synthetic_cache):
    # Regression for the lock-leak fix: an early-error response must release
    # the lock so a follow-up request can acquire it. The previous code path
    # also did this for explicit early errors, but the orphan-subprocess case
    # (covered by killing on stream exit) needs the same guarantee.
    from webui.analyze_runner import _analyze_lock
    c = _client(synthetic_cache)
    r = c.post("/api/tools/reanalyze/__no_such__")
    assert r.status_code == 200
    # Drain the body so the streaming response generator runs to completion.
    _ = r.text
    assert not _analyze_lock.locked()
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webui && pytest tests/test_server.py::test_analyze_lock_released_after_unknown_slug_error -v
```

Expected: FAIL with `ImportError: cannot import name '_analyze_lock' from 'webui.analyze_runner'` (module doesn't exist yet).

- [ ] **Step 3: Create `analyze_runner.py` with extracted code**

Create `webui/webui/analyze_runner.py`:

```python
"""Shared analyze-pipeline runner.

Extracted from server.py during the analyze-from-library work. Owns the
single-flight analyze lock and the WSL invocation of `python -m analyze`.
Emits an NDJSON event stream with these types:

  {"type":"log","line":...}                       raw stdout/stderr
  {"type":"stage","name":...,"status":...}        per-pipeline-stage marker
  {"type":"phase","name":...,"status":...}        upload/transcode/download/analyze
  {"type":"slug","slug":...}                      final slug (after summary.json read)
  {"type":"done","stats":...,"slug":...}          terminal success
  {"type":"error","message":...,"kind":...}       terminal error

Lock-leak fix: the previous reanalyze code released the lock when the
generator exited (including on client disconnect mid-stream), orphaning the
WSL subprocess. We now wrap the proc lifetime in a try/finally that kills
+ waits the subprocess on early exit so the lock and the work track each
other.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import shutil
from pathlib import Path

from . import _paths, tracks

log = logging.getLogger(__name__)

_async_spawn = asyncio.create_subprocess_exec
_analyze_lock = asyncio.Lock()


def _to_wsl_path(p: Path) -> str:
    s = str(p.resolve())
    if len(s) < 3 or s[1] != ":":
        return s.replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:].replace(chr(92), '/')}"


def _clear_cache_dir(cache: Path) -> None:
    for child in cache.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def ndjson(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


def stats_from_summary(s: dict) -> dict:
    track = s.get("track") or {}
    analysis = s.get("analysis") or {}
    provenance = s.get("provenance") or {}
    chords = s.get("chords") or []
    downbeats = s.get("downbeats") or []
    stems = s.get("stems") or {}

    note_counts: dict[str, int] = {}
    for stem, info in stems.items():
        if stem == "drums" or not isinstance(info, dict):
            continue
        notes = info.get("notes")
        if isinstance(notes, list):
            note_counts[stem] = len(notes)

    drums = stems.get("drums") if isinstance(stems.get("drums"), dict) else {}
    drums_block: dict = {"transcribed": bool(drums.get("transcribed"))}
    if drums.get("transcribed"):
        per_piece = {}
        total = 0
        for piece in ("kick", "snare", "toms", "hihat", "cymbals"):
            v = drums.get(piece)
            if isinstance(v, dict) and isinstance(v.get("t"), list):
                per_piece[piece] = len(v["t"])
                total += len(v["t"])
        drums_block["pieces"] = per_piece
        drums_block["total"] = total
    elif drums.get("reason"):
        drums_block["reason"] = drums["reason"]

    return {
        "duration_sec": track.get("duration_sec"),
        "tempo_bpm": track.get("tempo_bpm"),
        "key": track.get("key"),
        "key_confidence": track.get("key_confidence"),
        "scale": analysis.get("scale"),
        "chord_count": len(chords),
        "downbeat_count": len(downbeats),
        "predominant_chord_loop": analysis.get("predominant_chord_loop"),
        "loop_roman": analysis.get("loop_roman"),
        "loop_appearances": len(analysis.get("loop_appearances") or []),
        "vocal_range": analysis.get("vocal_range"),
        "modal_interchange_count": analysis.get("modal_interchange_count"),
        "note_counts": note_counts,
        "drums": drums_block,
        "stems_quality": provenance.get("stems_quality"),
        "warnings": list(provenance.get("warnings") or []),
    }


async def run_analyze_stream(slug: str, source_path: Path, quality: str):
    """Async generator yielding NDJSON event bytes for one analyze run.

    Caller is responsible for ensuring source_path exists and is the final
    .mp3 to feed into the pipeline (after any upload/transcode/download).
    The lock is acquired here; if busy, emits lock_busy and exits.
    """
    if _analyze_lock.locked():
        yield ndjson({"type": "error", "message": "another analysis is already running", "kind": "lock_busy"})
        return

    async with _analyze_lock:
        proc = None
        try:
            cache = _paths.cache_dir() / slug
            cache.mkdir(parents=True, exist_ok=True)
            if any(cache.iterdir()):
                _clear_cache_dir(cache)
                yield ndjson({"type": "log", "line": f"cleared cache/{slug}/"})

            yield ndjson({"type": "phase", "name": "analyze", "status": "start"})

            project_wsl = _to_wsl_path(_paths.project_root())
            src_wsl = _to_wsl_path(source_path)
            script = (
                f"cd {shlex.quote(project_wsl)} && "
                f"source .venv/bin/activate && "
                f"python -u -m analyze {shlex.quote(src_wsl)} "
                f"--stems-quality {shlex.quote(quality)} 2>&1"
            )
            yield ndjson({"type": "log", "line": f"stems quality: {quality}"})
            yield ndjson({"type": "log", "line": f"wsl script: {script}"})

            try:
                proc = await _async_spawn(
                    "wsl", "--", "bash", "-c", script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError:
                yield ndjson({"type": "error", "message": "wsl.exe not found on PATH", "kind": "analyze_failed"})
                return

            assert proc.stdout is not None
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                stripped = line.lstrip()
                if stripped.startswith("==> Stage "):
                    rest = stripped[len("==> Stage "):]
                    name, _, status = rest.partition(":")
                    status_word = status.strip().split()[0] if status.strip() else "running"
                    yield ndjson({"type": "stage", "name": name.strip(), "status": status_word})
                yield ndjson({"type": "log", "line": line})

            rc = await proc.wait()
            proc = None  # successfully reaped, no kill needed in finally
            if rc != 0:
                yield ndjson({"type": "error", "message": f"analyze exited with code {rc}", "kind": "analyze_failed"})
                return

            yield ndjson({"type": "phase", "name": "analyze", "status": "end"})

            tracks._cache.pop(slug, None)
            try:
                new_summary = tracks.get_summary(slug)
            except KeyError:
                yield ndjson({"type": "error", "message": "analyze finished but summary.json was not produced", "kind": "analyze_failed"})
                return

            yield ndjson({"type": "slug", "slug": slug})
            yield ndjson({"type": "done", "stats": stats_from_summary(new_summary), "slug": slug})
        except Exception as exc:  # noqa: BLE001 — surface unexpected errors
            log.exception("analyze failed for %s", slug)
            yield ndjson({"type": "error", "message": f"{type(exc).__name__}: {exc}", "kind": "internal"})
        finally:
            # Lock-leak fix: if the generator exits while proc is still alive
            # (e.g. ASGI client-disconnect raises out of `yield`), kill it so
            # the lock release tracks the work, not the response.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
```

- [ ] **Step 4: Refactor `server.py` reanalyze block to delegate**

In `webui/webui/server.py`, replace the entire block from `# --- Reanalyze:` (line ~187) to end-of-file with this thin wrapper. Imports at the top of `server.py` add: `from . import analyze_runner`. Delete the local `_async_spawn`, `_reanalyze_lock`, `_to_wsl_path`, `_clear_cache_dir`, `_stats_from_summary`, `_ndjson`, and `_reanalyze_stream` definitions.

```python
import tempfile

from . import analyze_runner

_STEMS_QUALITY_CHOICES = ("fast", "normal", "best")
_DEFAULT_STEMS_QUALITY = "normal"


async def _reanalyze_stream(slug: str, stems_quality: str = _DEFAULT_STEMS_QUALITY):
    """Reanalyze: stage source out of cache, then run analyze on it."""
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        yield analyze_runner.ndjson({"type": "error", "message": f"unknown slug: {slug}", "kind": "analyze_failed"})
        return

    cache = _paths.cache_dir() / slug
    track_meta = summary.get("track") or {}
    windows_path = track_meta.get("windows_path")
    cache_mp3 = cache / f"{slug}.mp3"

    src_win: Path | None = None
    src_origin = ""
    if windows_path and Path(windows_path).is_file():
        src_win = Path(windows_path)
        src_origin = "original path"
    elif cache_mp3.is_file():
        src_win = cache_mp3
        src_origin = "cache mirror (original path missing)"
    else:
        yield analyze_runner.ndjson({"type": "error", "message": f"no source MP3 found for {slug}", "kind": "analyze_failed"})
        return

    yield analyze_runner.ndjson({"type": "log", "line": f"source: {src_win} ({src_origin})"})

    with tempfile.TemporaryDirectory(prefix="musiq_reanalyze_") as tmp:
        tmp_src = Path(tmp) / src_win.name
        shutil.copy2(src_win, tmp_src)
        async for chunk in analyze_runner.run_analyze_stream(slug, tmp_src, stems_quality):
            yield chunk


@app.post("/api/tools/reanalyze/{slug}")
async def api_tool_reanalyze(slug: str, request: Request) -> StreamingResponse:
    quality = _DEFAULT_STEMS_QUALITY
    raw = await request.body()
    if raw:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        if "quality" in payload:
            q = payload["quality"]
            if q not in _STEMS_QUALITY_CHOICES:
                raise HTTPException(
                    status_code=400,
                    detail=f"quality must be one of {list(_STEMS_QUALITY_CHOICES)}",
                )
            quality = q
    return StreamingResponse(
        _reanalyze_stream(slug, stems_quality=quality),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 5: Run all server tests**

```
cd webui && pytest tests/ -v
```

Expected: PASS — all existing reanalyze tests + the new lock-release test.

- [ ] **Step 6: Commit**

```
git add webui/webui/analyze_runner.py webui/webui/server.py webui/tests/test_server.py
git commit -m "refactor(webui): extract analyze_runner from server, fix lock-leak on disconnect"
```

---

## Task 2: Slug helpers (`slug_for_filename`, `find_first_free_slug`)

These are the building blocks for the slug-for endpoint and for server-side validation. `slug_for_filename` wraps `analyze.cache.slug_for` with the `.mp3`-suffix dance for filenames that contain dots in titles. `find_first_free_slug` walks `cache/<slug>-N/` looking for the lowest free N≥2.

**Files:**
- Modify: `webui/webui/analyze_runner.py`
- Test: `webui/tests/test_analyze_runner.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `webui/tests/test_analyze_runner.py`:

```python
"""Unit tests for analyze_runner helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

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


def test_find_first_free_slug_returns_dash_2_when_base_doesnt_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze_runner._paths, "cache_dir", lambda: tmp_path)
    # Even if base is free, suggested-new is still -2 (caller decides whether
    # to use base or suggested based on `exists`).
    assert analyze_runner.find_first_free_slug("foo") == "foo-2"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_analyze_runner.py -v
```

Expected: FAIL with `AttributeError: module 'webui.analyze_runner' has no attribute 'slug_for_filename'`.

- [ ] **Step 3: Implement the helpers**

Append to `webui/webui/analyze_runner.py`:

```python
from analyze.cache import slug_for as _slug_for_path


def slug_for_filename(filename: str) -> str:
    """Compute the cache slug for a source filename.

    Synthesizes a .mp3 suffix if the input has no extension or a non-audio
    one, so Path.stem strips the right thing. Without this, titles
    containing dots ("Track 1.0 (Live)") would slug to the wrong stem.
    """
    p = Path(filename)
    if p.suffix.lower() not in {".mp3", ".wav", ".flac"}:
        p = Path(filename + ".mp3")
    return _slug_for_path(p)


def find_first_free_slug(base: str) -> str:
    """Return the first <base>-N (N>=2) that is not present under cache/."""
    cache_root = _paths.cache_dir()
    n = 2
    while (cache_root / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_analyze_runner.py -v
```

Expected: PASS, all 5 tests.

- [ ] **Step 5: Commit**

```
git add webui/webui/analyze_runner.py webui/tests/test_analyze_runner.py
git commit -m "feat(webui): slug_for_filename + find_first_free_slug helpers"
```

---

## Task 3: `GET /api/util/slug-for` endpoint

Pre-flight collision check for the upload flow. Returns `{slug, exists, suggested_new_slug}` or 415 for unsupported extension.

**Files:**
- Modify: `webui/webui/server.py`
- Test: `webui/tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_server.py`:

```python
def test_slug_for_no_collision(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "Brand_New.mp3"})
    assert r.status_code == 200
    j = r.json()
    assert j == {"slug": "brand_new", "exists": False, "suggested_new_slug": "brand_new-2"}


def test_slug_for_collision(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/util/slug-for", params={"filename": "Gorillaz - Silent Running.mp3"})
    assert r.status_code == 200
    j = r.json()
    assert j["slug"] == "gorillaz-silent_running"
    # The synthetic cache has gorillaz_silent_running, NOT gorillaz-silent_running,
    # so this filename slugs to a non-existing slug. Test the colliding name:


def test_slug_for_existing_track_collides(synthetic_cache):
    # Match the synthetic_cache slug exactly: gorillaz_silent_running
    c = _client(synthetic_cache)
    # underscores collapse via slugifier; need a filename that produces the exact slug
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_server.py -k slug_for -v
```

Expected: FAIL with 404 (route doesn't exist).

- [ ] **Step 3: Implement the endpoint**

Add to `webui/webui/server.py` (anywhere among the route definitions):

```python
_SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".flac"}


@app.get("/api/util/slug-for")
def api_util_slug_for(filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        return JSONResponse(
            status_code=415,
            content={"error": "unsupported_type", "extension": ext},
        )
    slug = analyze_runner.slug_for_filename(filename)
    cache_path = _paths.cache_dir() / slug / "summary.json"
    return {
        "slug": slug,
        "exists": cache_path.is_file(),
        "suggested_new_slug": analyze_runner.find_first_free_slug(slug),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_server.py -k slug_for -v
```

Expected: PASS, all 5 tests (or 4 if the loose intermediate-test passes vacuously — verify each assertion runs).

- [ ] **Step 5: Commit**

```
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): add /api/util/slug-for pre-flight collision endpoint"
```

---

## Task 4: ffmpeg transcode helper (`transcode_to_mp3`)

Async helper that transcodes a `.wav`/`.flac` file to MP3 V0 using `ffmpeg`. Streams stderr lines as log events. Returns the output path on success; raises on ffmpeg failure or missing binary.

**Files:**
- Modify: `webui/webui/analyze_runner.py`
- Test: `webui/tests/test_analyze_runner.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_analyze_runner.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_analyze_runner.py -k transcode -v
```

Expected: FAIL with `AttributeError: module 'webui.analyze_runner' has no attribute 'transcode_to_mp3'`.

- [ ] **Step 3: Implement `transcode_to_mp3`**

Append to `webui/webui/analyze_runner.py`:

```python
async def transcode_to_mp3(src: Path, dst: Path):
    """Transcode src (any libavformat-readable audio) to dst as MP3 V0.

    Yields NDJSON event bytes for log/phase/error. ffmpeg is expected to be
    on PATH (CLAUDE.md confirms it for this machine; required by yt-dlp too).
    """
    yield ndjson({"type": "phase", "name": "transcode", "status": "start"})
    yield ndjson({"type": "log", "line": f"transcode {src.name} -> {dst.name} (MP3 V0)"})

    argv = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-i", str(src),
        "-c:a", "libmp3lame", "-q:a", "0",
        str(dst),
    ]
    try:
        proc = await _async_spawn(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield ndjson({"type": "error", "message": "ffmpeg not found on PATH", "kind": "ffmpeg_failed"})
        return

    assert proc.stderr is not None
    while True:
        raw = await proc.stderr.readline()
        if not raw:
            break
        yield ndjson({"type": "log", "line": raw.decode("utf-8", errors="replace").rstrip("\r\n")})

    rc = await proc.wait()
    if rc != 0:
        yield ndjson({"type": "error", "message": f"ffmpeg exited with code {rc}", "kind": "ffmpeg_failed"})
        return

    yield ndjson({"type": "phase", "name": "transcode", "status": "end"})
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_analyze_runner.py -k transcode -v
```

Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```
git add webui/webui/analyze_runner.py webui/tests/test_analyze_runner.py
git commit -m "feat(webui): ffmpeg transcode helper (WAV/FLAC -> MP3 V0)"
```

---

## Task 5: Stale-yt-dlp stderr pattern detector (`is_stale_ytdlp_stderr`)

Pure-function detector returning `True` if a stderr blob matches one of the documented stale-yt-dlp triggers (CLAUDE.md). Simple, fast, isolated.

**Files:**
- Modify: `webui/webui/analyze_runner.py`
- Test: `webui/tests/test_analyze_runner.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_analyze_runner.py`:

```python
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
])
def test_is_stale_ytdlp_stderr_negatives(stderr_blob):
    assert analyze_runner.is_stale_ytdlp_stderr(stderr_blob) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_analyze_runner.py -k stale_ytdlp -v
```

Expected: FAIL with AttributeError.

- [ ] **Step 3: Implement `is_stale_ytdlp_stderr`**

Append to `webui/webui/analyze_runner.py`:

```python
import re

_STALE_PATTERNS = (
    re.compile(r"HTTP Error 403: Forbidden"),
    re.compile(r"Your yt-dlp version \([^)]+\) is older than 90 days"),
    re.compile(r"Sign in to confirm you're not a bot"),
    re.compile(r"Requested format is not available"),
)
# Combo: "missing a url" warning AND a download-failure line both present.
_MISSING_URL = re.compile(r"formats have been skipped as they are missing a url")
_DL_FAIL = re.compile(r"(?im)^ERROR.*(download|failed)")


def is_stale_ytdlp_stderr(stderr: str) -> bool:
    if not stderr:
        return False
    for pat in _STALE_PATTERNS:
        if pat.search(stderr):
            return True
    if _MISSING_URL.search(stderr) and _DL_FAIL.search(stderr):
        return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_analyze_runner.py -k stale_ytdlp -v
```

Expected: PASS, both parametrized groups (10 cases total).

- [ ] **Step 5: Commit**

```
git add webui/webui/analyze_runner.py webui/tests/test_analyze_runner.py
git commit -m "feat(webui): stale-yt-dlp stderr pattern detector"
```

---

## Task 6: yt-dlp metadata fetch helper (`youtube_metadata_slug`)

Single async function that runs `yt-dlp.exe --skip-download --print '%(title)s-%(id)s'` and returns either the predicted slug or a structured error.

**Files:**
- Modify: `webui/webui/analyze_runner.py`
- Test: `webui/tests/test_analyze_runner.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_analyze_runner.py`:

```python
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
    assert "yt-dlp.exe" in str(captured["argv"][0])
    assert "--skip-download" in captured["argv"]
    assert "--print" in captured["argv"]


def test_youtube_metadata_slug_stale(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"", b"ERROR: HTTP Error 403: Forbidden\n")

    monkeypatch.setattr(analyze_runner, "_async_spawn", lambda *a, **kw: _async_return(FakeProc()))

    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is False
    assert result["kind"] == "ytdlp_stale"


def test_youtube_metadata_slug_other_failure(monkeypatch):
    class FakeProc:
        returncode = 1
        async def communicate(self):
            return (b"", b"ERROR: Video unavailable\n")

    monkeypatch.setattr(analyze_runner, "_async_spawn", lambda *a, **kw: _async_return(FakeProc()))

    result = asyncio.run(analyze_runner.youtube_metadata_slug("https://example/x"))
    assert result["ok"] is False
    assert result["kind"] == "ytdlp_metadata_failed"


# helper for monkey-patching async functions inline
async def _async_return(value):
    return value
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_analyze_runner.py -k youtube_metadata -v
```

Expected: FAIL with AttributeError.

- [ ] **Step 3: Implement `youtube_metadata_slug`**

Append to `webui/webui/analyze_runner.py`:

```python
YT_DLP_BIN = r"C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe"
YT_OUT_DIR = Path(r"C:\Users\<you>\Videos\Any Video Converter Ultimate\Youtube")


async def youtube_metadata_slug(url: str, *, update_first: bool = False) -> dict:
    """Fetch the predicted '<title>-<id>' from yt-dlp without downloading.

    Returns one of:
      {"ok": True, "predicted_slug": "<slug>"}
      {"ok": False, "kind": "ytdlp_stale", "stderr": "..."}
      {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "..."}
    """
    if update_first:
        # Best-effort update. If it fails we still try the metadata fetch.
        try:
            up = await _async_spawn(
                YT_DLP_BIN, "-U",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await up.communicate()
        except FileNotFoundError:
            return {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "yt-dlp.exe not found"}

    try:
        proc = await _async_spawn(
            YT_DLP_BIN,
            "--skip-download",
            "--print", "%(title)s-%(id)s",
            "--no-update",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "yt-dlp.exe not found"}

    stdout, stderr = await proc.communicate()
    stderr_text = stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        kind = "ytdlp_stale" if is_stale_ytdlp_stderr(stderr_text) else "ytdlp_metadata_failed"
        return {"ok": False, "kind": kind, "stderr": stderr_text}

    line = stdout.decode("utf-8", errors="replace").strip().splitlines()[0] if stdout else ""
    if not line:
        return {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "yt-dlp produced no output"}

    return {"ok": True, "predicted_slug": slug_for_filename(line + ".mp3")}
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_analyze_runner.py -k youtube_metadata -v
```

Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```
git add webui/webui/analyze_runner.py webui/tests/test_analyze_runner.py
git commit -m "feat(webui): yt-dlp metadata fetch helper (slug pre-check)"
```

---

## Task 7: yt-dlp download helper (`youtube_download`) with progress parsing

Async generator that runs the real download, parses `[download] N% of X.XX MiB at Y.YY MiB/s ETA HH:MM:SS` lines into structured progress events, and emits the final `.mp3` path on success.

**Files:**
- Modify: `webui/webui/analyze_runner.py`
- Test: `webui/tests/test_analyze_runner.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_analyze_runner.py`:

```python
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

    class FakeProc:
        returncode = 0
        class Stdout:
            def __init__(self, lines):
                self._lines = list(lines)
            async def readline(self):
                return self._lines.pop(0) if self._lines else b""
        stderr = Stdout([b""])
        async def wait(self):
            return 0
        def __init__(self):
            self.stdout = self.Stdout(output_lines)

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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_analyze_runner.py -k "progress or youtube_download" -v
```

Expected: FAIL — helpers not defined.

- [ ] **Step 3: Implement `parse_ytdlp_progress` + `youtube_download`**

Append to `webui/webui/analyze_runner.py`:

```python
_PROGRESS_RE = re.compile(
    r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+\S+\s+at\s+(\S+)\s+ETA\s+(\d+):(\d+):(\d+)"
)


def parse_ytdlp_progress(line: str) -> dict | None:
    if not line:
        return None
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    pct = float(m.group(1))
    speed = m.group(2)
    h, mn, s = int(m.group(3)), int(m.group(4)), int(m.group(5))
    eta_sec = h * 3600 + mn * 60 + s
    return {"pct": pct, "speed": speed, "eta_sec": eta_sec}


async def youtube_download(url: str, *, update_first: bool = False):
    """Download URL via yt-dlp into YT_OUT_DIR. Yields NDJSON event bytes.

    On success the LAST event is {"type":"downloaded","path":"<final mp3>"}.
    On failure the last event is {"type":"error","kind":"ytdlp_stale"|"ytdlp_download_failed",...}.
    """
    if update_first:
        yield ndjson({"type": "log", "line": "running yt-dlp -U"})
        try:
            up = await _async_spawn(
                YT_DLP_BIN, "-U",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            yield ndjson({"type": "error", "message": "yt-dlp.exe not found", "kind": "ytdlp_download_failed"})
            return
        assert up.stdout is not None
        while True:
            raw = await up.stdout.readline()
            if not raw:
                break
            yield ndjson({"type": "log", "line": raw.decode("utf-8", errors="replace").rstrip("\r\n")})
        await up.wait()

    YT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_template = str(YT_OUT_DIR / "%(title)s-%(id)s.%(ext)s")

    yield ndjson({"type": "phase", "name": "download", "status": "start"})

    argv = [
        YT_DLP_BIN,
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-update", "--newline",
        "-o", out_template,
        "--print", "after_move:filepath",
        url,
    ]

    try:
        proc = await _async_spawn(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield ndjson({"type": "error", "message": "yt-dlp.exe not found", "kind": "ytdlp_download_failed"})
        return

    assert proc.stdout is not None and proc.stderr is not None
    final_path: str | None = None

    async def _drain_stderr():
        chunks = []
        while True:
            raw = await proc.stderr.readline()
            if not raw:
                break
            chunks.append(raw)
        return b"".join(chunks)

    stderr_task = asyncio.create_task(_drain_stderr())

    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        prog = parse_ytdlp_progress(line)
        if prog is not None:
            yield ndjson({"type": "progress", "phase": "download", **prog})
        # The "after_move:filepath" emission is a non-bracketed bare path.
        # Track the *last* such line as the final path.
        if line and not line.startswith("[") and (line.endswith(".mp3") or "\\" in line or "/" in line):
            final_path = line
        yield ndjson({"type": "log", "line": line})

    rc = await proc.wait()
    stderr_bytes = await stderr_task
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    for stderr_line in stderr_text.splitlines():
        yield ndjson({"type": "log", "line": stderr_line})

    if rc != 0:
        kind = "ytdlp_stale" if is_stale_ytdlp_stderr(stderr_text) else "ytdlp_download_failed"
        yield ndjson({"type": "error", "message": f"yt-dlp exited with code {rc}", "kind": kind})
        return

    if final_path is None:
        yield ndjson({"type": "error", "message": "yt-dlp finished but no filepath was emitted", "kind": "ytdlp_download_failed"})
        return

    yield ndjson({"type": "phase", "name": "download", "status": "end"})
    yield ndjson({"type": "downloaded", "path": final_path})
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_analyze_runner.py -v
```

Expected: PASS, all tests including new ones.

- [ ] **Step 5: Commit**

```
git add webui/webui/analyze_runner.py webui/tests/test_analyze_runner.py
git commit -m "feat(webui): yt-dlp download helper with progress parsing"
```

---

## Task 8: `POST /api/tools/analyze/upload` endpoint

Multipart upload, validation (extension, size, slug), optional transcode, then delegate to `run_analyze_stream`.

**Files:**
- Modify: `webui/webui/server.py`
- Test: `webui/tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_server.py -k analyze_upload -v
```

Expected: FAIL with 404 (route absent).

- [ ] **Step 3: Implement the endpoint**

Add to `webui/webui/server.py`:

```python
from fastapi import File, Form, UploadFile

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
_UPLOAD_CONTENT_TYPES = {
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/flac", "audio/x-flac",
}


def _validate_upload_slug(filename: str, mode: str, slug: str) -> None:
    """Raise HTTPException if (mode, slug) violate the slug-validation rule."""
    expected_base = analyze_runner.slug_for_filename(filename)
    if mode == "reanalyze":
        if slug != expected_base:
            raise HTTPException(status_code=400, detail="slug must match base for reanalyze mode")
        return
    # mode == "new"
    if slug == expected_base:
        return
    if not slug.startswith(f"{expected_base}-"):
        raise HTTPException(status_code=400, detail="slug must be base or '<base>-<N>'")
    suffix = slug[len(expected_base) + 1:]
    if not suffix.isdigit() or int(suffix) < 2:
        raise HTTPException(status_code=400, detail="suffix N must be integer >= 2")


@app.post("/api/tools/analyze/upload")
async def api_tool_analyze_upload(
    file: UploadFile = File(...),
    quality: str = Form(...),
    mode: str = Form("new"),
    slug: str = Form(...),
) -> StreamingResponse:
    if quality not in _STEMS_QUALITY_CHOICES:
        raise HTTPException(status_code=400, detail=f"quality must be one of {list(_STEMS_QUALITY_CHOICES)}")
    if mode not in ("new", "reanalyze"):
        raise HTTPException(status_code=400, detail="mode must be 'new' or 'reanalyze'")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        return JSONResponse(status_code=415, content={"error": "unsupported_type", "extension": ext})
    if file.content_type and file.content_type not in _UPLOAD_CONTENT_TYPES:
        return JSONResponse(
            status_code=415,
            content={"error": "unsupported_type", "content_type": file.content_type},
        )

    _validate_upload_slug(file.filename or "", mode, slug)

    # Server-side collision recheck.
    cache_dir = _paths.cache_dir() / slug
    if mode == "new" and cache_dir.is_dir() and (cache_dir / "summary.json").is_file():
        raise HTTPException(status_code=409, detail="slug already exists")
    if mode == "reanalyze" and not (cache_dir / "summary.json").is_file():
        raise HTTPException(status_code=409, detail="slug does not exist")

    tmp = tempfile.mkdtemp(prefix="musiq_upload_")
    tmp_path = Path(tmp) / (file.filename or "upload.mp3")
    bytes_written = 0
    with tmp_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            bytes_written += len(chunk)
            if bytes_written > _MAX_UPLOAD_BYTES:
                out.close()
                shutil.rmtree(tmp, ignore_errors=True)
                raise HTTPException(status_code=413, detail="upload exceeds 500 MB cap")
            out.write(chunk)

    async def _stream():
        try:
            yield analyze_runner.ndjson({"type": "phase", "name": "upload", "status": "end"})
            source_path = tmp_path
            if ext in (".wav", ".flac"):
                mp3_path = tmp_path.with_suffix(".mp3")
                async for chunk in analyze_runner.transcode_to_mp3(tmp_path, mp3_path):
                    yield chunk
                    if b'"kind":"ffmpeg_failed"' in chunk:
                        return
                tmp_path.unlink(missing_ok=True)
                source_path = mp3_path
            async for chunk in analyze_runner.run_analyze_stream(slug, source_path, quality):
                yield chunk
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_server.py -k analyze_upload -v
```

Expected: PASS, all 4 tests.

- [ ] **Step 5: Commit**

```
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): POST /api/tools/analyze/upload endpoint"
```

---

## Task 9: `POST /api/tools/analyze/youtube` endpoint

JSON body, dry_run + streaming paths, mocked-subprocess tests for both.

**Files:**
- Modify: `webui/webui/server.py`
- Test: `webui/tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && pytest tests/test_server.py -k analyze_youtube -v
```

Expected: FAIL with 404.

- [ ] **Step 3: Implement the endpoint**

Add to `webui/webui/server.py`:

```python
def _validate_youtube_slug(predicted_base: str, mode: str, slug: str) -> None:
    if mode == "reanalyze":
        if slug != predicted_base:
            raise HTTPException(status_code=400, detail="slug must match predicted base for reanalyze")
        return
    if slug == predicted_base:
        return
    if not slug.startswith(f"{predicted_base}-"):
        raise HTTPException(status_code=400, detail="slug must be base or '<base>-<N>'")
    suffix = slug[len(predicted_base) + 1:]
    if not suffix.isdigit() or int(suffix) < 2:
        raise HTTPException(status_code=400, detail="suffix N must be integer >= 2")


@app.post("/api/tools/analyze/youtube")
async def api_tool_analyze_youtube(request: Request) -> Response:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    url = body.get("url")
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail="url is required")
    quality = body.get("quality", _DEFAULT_STEMS_QUALITY)
    if quality not in _STEMS_QUALITY_CHOICES:
        raise HTTPException(status_code=400, detail=f"quality must be one of {list(_STEMS_QUALITY_CHOICES)}")
    update_ytdlp = bool(body.get("update_ytdlp", False))
    dry_run = bool(body.get("dry_run", False))

    if dry_run:
        meta = await analyze_runner.youtube_metadata_slug(url, update_first=update_ytdlp)
        if not meta["ok"]:
            status = 503 if meta["kind"] == "ytdlp_stale" else 502
            return JSONResponse(
                status_code=status,
                content={"error": meta["kind"], "message": meta.get("stderr", "")},
            )
        predicted = meta["predicted_slug"]
        cache_dir = _paths.cache_dir() / predicted
        return {
            "predicted_slug": predicted,
            "exists": (cache_dir / "summary.json").is_file(),
            "suggested_new_slug": analyze_runner.find_first_free_slug(predicted),
        }

    mode = body.get("mode", "new")
    slug = body.get("slug")
    if mode not in ("new", "reanalyze"):
        raise HTTPException(status_code=400, detail="mode must be 'new' or 'reanalyze'")
    if not slug or not isinstance(slug, str):
        raise HTTPException(status_code=400, detail="slug is required when dry_run is false")

    # Re-fetch metadata to validate slug + collision (cheap; ~2-3s).
    meta = await analyze_runner.youtube_metadata_slug(url, update_first=update_ytdlp)
    if not meta["ok"]:
        async def _err_stream():
            yield analyze_runner.ndjson({
                "type": "error",
                "kind": meta["kind"],
                "message": meta.get("stderr", "") or "yt-dlp metadata failed",
            })
        return StreamingResponse(_err_stream(), media_type="application/x-ndjson")

    predicted = meta["predicted_slug"]
    _validate_youtube_slug(predicted, mode, slug)

    cache_dir = _paths.cache_dir() / slug
    if mode == "new" and (cache_dir / "summary.json").is_file():
        raise HTTPException(status_code=409, detail="slug already exists")
    if mode == "reanalyze" and not (cache_dir / "summary.json").is_file():
        raise HTTPException(status_code=409, detail="slug does not exist")

    async def _stream():
        if mode == "reanalyze":
            # Reuse cached source MP3 — no re-download.
            cache_mp3 = cache_dir / f"{slug}.mp3"
            track_meta = (tracks.get_summary(slug).get("track") or {})
            wp = track_meta.get("windows_path")
            src = Path(wp) if wp and Path(wp).is_file() else cache_mp3
            yield analyze_runner.ndjson({"type": "log", "line": f"reanalyze YouTube source: {src}"})
            with tempfile.TemporaryDirectory(prefix="musiq_yt_re_") as tmp:
                staged = Path(tmp) / src.name
                shutil.copy2(src, staged)
                async for chunk in analyze_runner.run_analyze_stream(slug, staged, quality):
                    yield chunk
            return

        # mode == "new"
        downloaded_path: str | None = None
        async for chunk in analyze_runner.youtube_download(url, update_first=update_ytdlp):
            obj = json.loads(chunk.decode("utf-8").rstrip("\n"))
            if obj.get("type") == "downloaded":
                downloaded_path = obj["path"]
                continue  # don't pass through; internal coordination event
            if obj.get("type") == "error":
                yield chunk
                return
            yield chunk
        if downloaded_path is None:
            yield analyze_runner.ndjson({"type": "error", "kind": "ytdlp_download_failed", "message": "no path emitted"})
            return
        async for chunk in analyze_runner.run_analyze_stream(slug, Path(downloaded_path), quality):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && pytest tests/test_server.py -k analyze_youtube -v
```

Expected: PASS, all 3 tests.

- [ ] **Step 5: Commit**

```
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): POST /api/tools/analyze/youtube endpoint (dry_run + streaming)"
```

---

## Task 10: Extract shared JS helpers to `analyze-shared.js`

Pure JS refactor. The existing `reanalyze.js` file is the single consumer; after this refactor it imports from `analyze-shared.js`. Existing JS tests (`webui/tests-js/`) must keep passing.

**Files:**
- Create: `webui/static/js/ui/analyze-shared.js`
- Modify: `webui/static/js/ui/reanalyze.js`
- Test: `webui/tests-js/analyze-shared.test.js` (new)

- [ ] **Step 1: Write a failing test for the shared module**

Create `webui/tests-js/analyze-shared.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  QUALITY_PRESETS,
  STAGE_ORDER,
  STATUS_COLOR,
  parseNdjsonStream,
} from "../static/js/ui/analyze-shared.js";

test("QUALITY_PRESETS exposes fast/normal/best with stable ordering", () => {
  const ids = QUALITY_PRESETS.map((p) => p.value);
  assert.deepEqual(ids, ["fast", "normal", "best"]);
});

test("STAGE_ORDER includes all known stages", () => {
  for (const name of ["stems", "beats", "key", "chords", "transcription", "beats_xcheck", "vocal_f0", "drums"]) {
    assert.ok(STAGE_ORDER.includes(name), `missing ${name}`);
  }
});

test("STATUS_COLOR has running/cached/done/error", () => {
  assert.ok(STATUS_COLOR.running);
  assert.ok(STATUS_COLOR.cached);
  assert.ok(STATUS_COLOR.done);
  assert.ok(STATUS_COLOR.error);
});

test("parseNdjsonStream splits lines including those crossing chunk boundaries", async () => {
  // Simulate a fetch ReadableStream with chunks that split a JSON line in two.
  async function* gen() {
    yield new TextEncoder().encode('{"type":"log","line":"a"}\n{"type":"sta');
    yield new TextEncoder().encode('ge","name":"stems","status":"running"}\n');
  }
  const events = [];
  for await (const ev of parseNdjsonStream(gen())) events.push(ev);
  assert.equal(events.length, 2);
  assert.equal(events[0].line, "a");
  assert.equal(events[1].name, "stems");
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webui && node --test tests-js/analyze-shared.test.js
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create `analyze-shared.js`**

Create `webui/static/js/ui/analyze-shared.js`:

```javascript
// Shared helpers used by reanalyze.js and analyze-modal.js. Extracted during
// the analyze-from-library work so both modals draw from the same vocabulary
// (stage order, quality presets, NDJSON event handling, stats rendering).

import { el } from "./dom.js";

export const STAGE_ORDER = [
  "stems", "beats", "key", "chords", "transcription",
  "beats_xcheck", "vocal_f0", "drums",
];

export const QUALITY_PRESETS = [
  { value: "fast",   label: "Fast",   blurb: "shifts=2  · ~½ time" },
  { value: "normal", label: "Normal", blurb: "shifts=4  · default" },
  { value: "best",   label: "Best",   blurb: "shifts=8  · ~2× time" },
];

export const STATUS_COLOR = {
  running: "#7eddff",
  cached: "#888",
  done: "#7ed881",
  error: "#ff6b6b",
};

export function buildQualitySelector(state) {
  const wrap = document.createElement("div");
  wrap.className = "reanalyze-quality";

  const label = document.createElement("div");
  label.className = "reanalyze-quality-label";
  label.textContent = "Stem separation quality";
  wrap.appendChild(label);

  const seg = document.createElement("div");
  seg.className = "reanalyze-quality-seg";
  wrap.appendChild(seg);

  const buttons = QUALITY_PRESETS.map((preset) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "reanalyze-quality-btn";
    btn.dataset.value = preset.value;
    btn.setAttribute("aria-pressed", String(preset.value === state.quality));
    if (preset.value === state.quality) btn.classList.add("active");

    const lbl = document.createElement("span");
    lbl.className = "reanalyze-quality-btn-label";
    lbl.textContent = preset.label;
    btn.appendChild(lbl);

    const blurb = document.createElement("span");
    blurb.className = "reanalyze-quality-btn-blurb";
    blurb.textContent = preset.blurb;
    btn.appendChild(blurb);

    seg.appendChild(btn);
    return btn;
  });

  for (const btn of buttons) {
    btn.addEventListener("click", () => {
      state.quality = btn.dataset.value;
      for (const other of buttons) {
        const isActive = other === btn;
        other.classList.toggle("active", isActive);
        other.setAttribute("aria-pressed", String(isActive));
      }
    });
  }

  return wrap;
}

// Async-iterate JSON events from a ReadableStream-like async iterable of bytes.
// Handles lines split across chunks. Unparseable lines are yielded as
// {type:"log", line:<raw>}.
export async function* parseNdjsonStream(byteSource) {
  const decoder = new TextDecoder();
  let buf = "";
  for await (const chunk of byteSource) {
    buf += decoder.decode(chunk, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try { yield JSON.parse(line); }
      catch { yield { type: "log", line: `(unparseable: ${line})` }; }
    }
  }
  const tail = buf.trim();
  if (tail) {
    try { yield JSON.parse(tail); }
    catch { yield { type: "log", line: tail }; }
  }
}

// Convenience wrapper: open the fetch, then iterate events via callback.
// Returns a Promise that resolves when the stream ends.
export async function streamAnalyze(url, init, onEvent) {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    onEvent({ type: "error", message: `HTTP ${res.status}: ${body || res.statusText}` });
    return;
  }
  async function* readerToBytes() {
    const reader = res.body.getReader();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      yield value;
    }
  }
  for await (const ev of parseNdjsonStream(readerToBytes())) onEvent(ev);
}

export function renderStats(target, s) {
  while (target.firstChild) target.removeChild(target.firstChild);
  target.style.display = "";
  target.appendChild(el("h3", {
    style: { margin: "8px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--fg-2)" },
    text: "Analysis result",
  }));

  const grid = el("div", {
    style: {
      display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
      gap: "4px 16px", fontSize: "12px",
    },
  });
  const fmtDuration = (sec) => {
    if (sec == null) return "—";
    const m = Math.floor(sec / 60), s2 = (sec - m * 60);
    return `${m}:${s2.toFixed(1).padStart(4, "0")}`;
  };
  const row = (label, value) => {
    grid.appendChild(el("span", { style: { color: "var(--fg-2)" }, text: label }));
    grid.appendChild(el("span", { style: { color: "var(--fg-1)" }, text: String(value ?? "—") }));
  };
  row("Duration", fmtDuration(s.duration_sec));
  row("Tempo", s.tempo_bpm != null ? `${s.tempo_bpm.toFixed(1)} BPM` : "—");
  row("Key", s.key_confidence != null
    ? `${s.key} (conf ${(s.key_confidence * 100).toFixed(0)}%)`
    : (s.key ?? "—"));
  row("Scale", s.scale ?? "—");
  row("Downbeats", s.downbeat_count);
  row("Chords", s.chord_count);
  if (Array.isArray(s.predominant_chord_loop) && s.predominant_chord_loop.length) {
    const loopText = s.predominant_chord_loop.join(" | ");
    const roman = Array.isArray(s.loop_roman) && s.loop_roman.length
      ? `  (${s.loop_roman.join(" | ")})` : "";
    row("Loop", `${loopText}${roman} × ${s.loop_appearances}`);
  } else {
    row("Loop", "none");
  }
  row("Modal interchange", s.modal_interchange_count ?? 0);
  if (s.vocal_range) {
    row("Vocal range", `${s.vocal_range.low_name}–${s.vocal_range.high_name} (${s.vocal_range.span_semitones} st)`);
  } else {
    row("Vocal range", "—");
  }
  target.appendChild(grid);

  if (s.note_counts && Object.keys(s.note_counts).length) {
    target.appendChild(el("h3", {
      style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--fg-2)" },
      text: "Notes per stem",
    }));
    const stemGrid = el("div", {
      style: {
        display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: "2px 12px", fontSize: "12px",
      },
    });
    for (const [stem, n] of Object.entries(s.note_counts)) {
      stemGrid.appendChild(el("span", {
        style: { color: "var(--fg-1)" },
        text: `${stem}: ${n}`,
      }));
    }
    target.appendChild(stemGrid);
  }

  target.appendChild(el("h3", {
    style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "var(--fg-2)" },
    text: "Drums",
  }));
  if (s.drums?.transcribed) {
    const drumLine = Object.entries(s.drums.pieces || {})
      .map(([k, n]) => `${k}: ${n}`).join("  ·  ");
    target.appendChild(el("div", {
      style: { color: "var(--fg-1)" },
      text: `${drumLine}  (total ${s.drums.total} hits)`,
    }));
  } else {
    target.appendChild(el("div", {
      style: { color: "var(--fg-2)" },
      text: s.drums?.reason ? `not transcribed — ${s.drums.reason}` : "not transcribed",
    }));
  }

  if (Array.isArray(s.warnings) && s.warnings.length) {
    target.appendChild(el("h3", {
      style: { margin: "12px 0 4px", fontSize: "12px", textTransform: "uppercase", color: "#ffd93d" },
      text: `Warnings (${s.warnings.length})`,
    }));
    const ul = el("ul", { style: { margin: 0, paddingLeft: "18px", color: "var(--fg-1)" } });
    for (const w of s.warnings) ul.appendChild(el("li", { text: w }));
    target.appendChild(ul);
  }
}

export function buttonStyle() {
  return {
    padding: "6px 14px", background: "var(--bg-2)", color: "var(--fg-1)",
    border: "1px solid var(--bg-3)", borderRadius: "4px", cursor: "pointer",
    fontSize: "12px",
  };
}
```

- [ ] **Step 4: Refactor `reanalyze.js` to use shared module**

Open `webui/static/js/ui/reanalyze.js` and replace its imports + delete the now-shared local definitions:

Replace the existing `import { el } from "./dom.js";` and the local `const STAGE_ORDER`, `const QUALITY_PRESETS`, `const STATUS_COLOR`, `function buildQualitySelector`, `async function streamReanalyze`, `function renderStats`, `function buttonStyle` with:

```javascript
import { el } from "./dom.js";
import {
  STAGE_ORDER,
  QUALITY_PRESETS,
  STATUS_COLOR,
  buildQualitySelector,
  streamAnalyze,
  renderStats,
  buttonStyle,
} from "./analyze-shared.js";
```

Inside `startReanalyzePipeline`, replace the call `streamReanalyze(slug, quality, ...)` with:
```javascript
streamAnalyze(`/api/tools/reanalyze/${encodeURIComponent(slug)}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ quality }),
}, (event) => {
  if (event.type === "log") pushLog(event.line);
  else if (event.type === "stage") setStage(event.name, event.status);
  else if (event.type === "done") showStats(event.stats);
  else if (event.type === "error") showError(event.message);
}).catch((err) => showError(`request failed: ${err.message || err}`));
```

Delete the now-removed helpers from `reanalyze.js` entirely.

- [ ] **Step 5: Run all JS tests**

```
cd webui && node --test tests-js/
```

Expected: PASS — new shared-module tests + the existing track-data, coords, view-state, track-picker tests.

- [ ] **Step 6: Commit**

```
git add webui/static/js/ui/analyze-shared.js webui/static/js/ui/reanalyze.js webui/tests-js/analyze-shared.test.js
git commit -m "refactor(webui): extract analyze-shared.js helpers from reanalyze.js"
```

---

## Task 11: Flip reanalyze `DEFAULT_QUALITY` to `"best"`

**Files:**
- Modify: `webui/static/js/ui/reanalyze.js`
- Test: `webui/tests-js/analyze-shared.test.js` (extend; or new file)

- [ ] **Step 1: Write the failing test**

Append to `webui/tests-js/analyze-shared.test.js`:

```javascript
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

test("reanalyze.js DEFAULT_QUALITY is 'best'", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const src = readFileSync(resolve(here, "../static/js/ui/reanalyze.js"), "utf-8");
  // The constant is exported / declared at module scope; assert literal source.
  assert.match(src, /const DEFAULT_QUALITY = "best";/);
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webui && node --test tests-js/analyze-shared.test.js
```

Expected: FAIL — current value is `"normal"`.

- [ ] **Step 3: Edit `reanalyze.js`**

Change line 32 (or wherever `const DEFAULT_QUALITY` lives after Task 10's refactor):

```javascript
const DEFAULT_QUALITY = "best";
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && node --test tests-js/
```

Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```
git add webui/static/js/ui/reanalyze.js webui/tests-js/analyze-shared.test.js
git commit -m "feat(webui): default reanalyze quality to Best"
```

---

## Task 12: `analyze-modal.js` — input step (file + URL variants)

Build the modal scaffolding and the input step only. Subsequent tasks add collision / streaming / done / error states.

**Files:**
- Create: `webui/static/js/ui/analyze-modal.js`
- Test: `webui/tests-js/analyze-modal.test.js` (new)

- [ ] **Step 1: Write the failing test**

Create `webui/tests-js/analyze-modal.test.js`:

```javascript
import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

// Minimal DOM bootstrap; jsdom is a transitive dev-dep already used by playwright.
const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.HTMLElement = dom.window.HTMLElement;

test("showAnalyzeModal({mode:'file'}) renders the file-input step", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /Analyze new audio file/i);
  const fileInput = overlay.querySelector('input[type="file"]');
  assert.ok(fileInput);
  assert.equal(fileInput.getAttribute("accept"), ".mp3,.wav,.flac");
  // Analyze button starts disabled (no file picked yet).
  const buttons = overlay.querySelectorAll("button");
  const analyzeBtn = [...buttons].find((b) => /Analyze/i.test(b.textContent));
  assert.ok(analyzeBtn);
  assert.equal(analyzeBtn.disabled, true);
  overlay.remove();
});

test("showAnalyzeModal({mode:'youtube'}) renders the URL-input step", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "youtube" });
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /Analyze YouTube URL/i);
  const urlInput = overlay.querySelector('input[type="text"]');
  assert.ok(urlInput);
  const buttons = overlay.querySelectorAll("button");
  const analyzeBtn = [...buttons].find((b) => /Analyze/i.test(b.textContent));
  assert.equal(analyzeBtn.disabled, true);
  overlay.remove();
});
```

- [ ] **Step 2: Verify jsdom is available, install if not**

```
cd webui && node -e "require('jsdom')" 2>&1
```

If "Cannot find module": `cd webui && npm i -D jsdom`. Otherwise proceed. (jsdom already ships with playwright in `tests-e2e/`; if the unit-test dir lacks it, create `webui/package.json` with `{"devDependencies":{"jsdom":"^25.0.0"}}` and `npm i`.)

- [ ] **Step 3: Run test to verify it fails**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: FAIL — file doesn't exist.

- [ ] **Step 4: Create `analyze-modal.js`**

Create `webui/static/js/ui/analyze-modal.js`:

```javascript
// Analyze-from-library modal. Two entry variants — file picker or YouTube
// URL — flow through the same state machine: input → (collision step) →
// streaming → done | error. Built from analyze-shared.js primitives so
// reanalyze and "analyze new" agree on UX vocabulary.

import { el } from "./dom.js";
import {
  buildQualitySelector,
  streamAnalyze,
  renderStats,
  STAGE_ORDER,
  STATUS_COLOR,
  buttonStyle,
} from "./analyze-shared.js";
import { api } from "../api.js";

const DEFAULT_QUALITY = "best";

export function showAnalyzeModal({ mode }) {
  const overlay = el("div", {
    style: {
      position: "fixed", inset: 0, background: "rgba(0,0,0,.75)", zIndex: 200,
      display: "flex", alignItems: "center", justifyContent: "center",
    },
  });
  const panel = el("div", {
    style: {
      background: "var(--bg-1)", border: "1px solid var(--bg-3)", borderRadius: "8px",
      padding: "20px 24px", display: "flex", flexDirection: "column", gap: "12px",
      fontSize: "12px", color: "var(--fg-1)",
    },
    onClick: (e) => e.stopPropagation(),
  });
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  const state = {
    mode,                 // "file" | "youtube"
    quality: DEFAULT_QUALITY,
    file: null,           // File object (mode=file)
    url: "",              // string (mode=youtube)
    slug: null,           // computed via slug-for / dry_run
    suggestedNew: null,   // <slug>-N
    exists: false,
    extError: null,       // string (when slug-for returns 415)
  };

  renderInputStep(panel, overlay, state);
  return overlay;
}

function renderInputStep(panel, overlay, state) {
  panel.replaceChildren();
  panel.style.width = "min(560px, 92vw)";
  panel.style.height = "auto";

  const heading = document.createElement("h2");
  heading.style.margin = "0";
  heading.style.fontSize = "15px";
  heading.style.color = "white";
  heading.textContent = state.mode === "file"
    ? "Analyze new audio file"
    : "Analyze YouTube URL";
  panel.appendChild(heading);

  if (state.mode === "file") {
    panel.appendChild(buildFileInputBlock(state, refresh));
  } else {
    panel.appendChild(buildUrlInputBlock(state, refresh));
  }

  panel.appendChild(buildQualitySelector(state));

  const actions = document.createElement("div");
  actions.className = "reanalyze-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => overlay.remove());

  const analyzeBtn = document.createElement("button");
  analyzeBtn.className = "btn-confirm";
  analyzeBtn.textContent = "Analyze";
  analyzeBtn.addEventListener("click", () => onAnalyzeClick(panel, overlay, state));

  actions.appendChild(cancelBtn);
  actions.appendChild(analyzeBtn);
  panel.appendChild(actions);

  function refresh() {
    const ready = state.mode === "file"
      ? !!state.file && !state.extError && !!state.slug
      : !!state.url.trim();
    analyzeBtn.disabled = !ready;
  }
  refresh();
}

function buildFileInputBlock(state, onRefresh) {
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });

  const input = document.createElement("input");
  input.type = "file";
  input.setAttribute("accept", ".mp3,.wav,.flac");

  const nameEl = el("div", { style: { fontSize: "11px", color: "var(--fg-2)" }, text: "" });
  const errorEl = el("div", { style: { fontSize: "11px", color: "#ff6b6b" }, text: "" });

  input.addEventListener("change", async () => {
    const file = input.files?.[0] ?? null;
    state.file = file;
    state.slug = null;
    state.extError = null;
    state.exists = false;
    nameEl.textContent = file ? file.name : "";
    errorEl.textContent = "";
    onRefresh();
    if (!file) return;
    try {
      const res = await api.slugForFilename(file.name);
      if (res.error === "unsupported_type") {
        state.extError = `Unsupported file type: ${res.extension || "(none)"}`;
        errorEl.textContent = state.extError;
        onRefresh();
        return;
      }
      state.slug = res.slug;
      state.exists = res.exists;
      state.suggestedNew = res.suggested_new_slug;
      onRefresh();
    } catch (e) {
      state.extError = `Pre-check failed: ${e.message || e}`;
      errorEl.textContent = state.extError;
      onRefresh();
    }
  });

  wrap.appendChild(input);
  wrap.appendChild(nameEl);
  wrap.appendChild(errorEl);
  return wrap;
}

function buildUrlInputBlock(state, onRefresh) {
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } });
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "https://www.youtube.com/watch?v=...";
  input.style.width = "100%";
  input.style.padding = "6px 8px";
  input.addEventListener("input", () => {
    state.url = input.value;
    onRefresh();
  });
  wrap.appendChild(input);
  return wrap;
}

async function onAnalyzeClick(panel, overlay, state) {
  // Pre-check / collision handling lives in the next task. For now, no-op.
}
```

- [ ] **Step 5: Add `api.slugForFilename` wrapper**

Open `webui/static/js/api.js` and append:

```javascript
api.slugForFilename = async (filename) => {
  const r = await fetch(`/api/util/slug-for?filename=${encodeURIComponent(filename)}`);
  if (r.status === 415) return await r.json();
  if (!r.ok) {
    const e = new Error(`slug-for failed: ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return await r.json();
};
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: PASS, both tests.

- [ ] **Step 7: Commit**

```
git add webui/static/js/ui/analyze-modal.js webui/static/js/api.js webui/tests-js/analyze-modal.test.js
git commit -m "feat(webui): analyze-modal input step (file + URL variants)"
```

---

## Task 13: Collision step + analyze-trigger flow

Adds the three-button collision UI and wires the `Analyze` click to either go straight to streaming (no collision) or transition to collision step.

**Files:**
- Modify: `webui/static/js/ui/analyze-modal.js`
- Test: `webui/tests-js/analyze-modal.test.js`

- [ ] **Step 1: Write the failing test**

Append to `webui/tests-js/analyze-modal.test.js`:

```javascript
test("collision step renders three buttons with the suggested slug", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  // Force the modal into the collision state directly via the exported helper.
  mod._renderCollisionStep(overlay.querySelector("div > div"), overlay, {
    mode: "file",
    quality: "best",
    slug: "bohemian_rhapsody",
    suggestedNew: "bohemian_rhapsody-2",
    exists: true,
  });
  const buttonText = [...overlay.querySelectorAll("button")].map((b) => b.textContent);
  assert.ok(buttonText.some((t) => /Add New bohemian_rhapsody-2/.test(t)));
  assert.ok(buttonText.some((t) => /^Reanalyze$/.test(t)));
  assert.ok(buttonText.some((t) => /^Cancel$/.test(t)));
  overlay.remove();
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: FAIL — `_renderCollisionStep` doesn't exist.

- [ ] **Step 3: Implement collision step + analyze trigger**

In `webui/static/js/ui/analyze-modal.js`, replace the placeholder `onAnalyzeClick` with a real implementation, and add `_renderCollisionStep` (exported under the underscored name for testability):

```javascript
async function onAnalyzeClick(panel, overlay, state) {
  if (state.mode === "file") {
    if (!state.exists) {
      startStreaming(panel, overlay, state, { mode: "new", slug: state.slug });
      return;
    }
    _renderCollisionStep(panel, overlay, state);
    return;
  }
  // YouTube: dry-run for the slug + collision check
  try {
    const dry = await api.youtubeDryRun(state.url, { update_ytdlp: false });
    state.slug = dry.predicted_slug;
    state.exists = dry.exists;
    state.suggestedNew = dry.suggested_new_slug;
    if (!state.exists) {
      startStreaming(panel, overlay, state, { mode: "new", slug: state.slug });
      return;
    }
    _renderCollisionStep(panel, overlay, state);
  } catch (e) {
    if (e.kind === "ytdlp_stale") {
      // Surface inline with retry button using update_ytdlp.
      _renderInlineYtdlpStale(panel, overlay, state);
      return;
    }
    _renderError(panel, overlay, `Metadata fetch failed: ${e.message || e}`);
  }
}

export function _renderCollisionStep(panel, overlay, state) {
  panel.replaceChildren();
  panel.style.width = "min(560px, 92vw)";

  panel.appendChild(el("h2", {
    style: { margin: 0, fontSize: "15px", color: "white" },
    text: state.mode === "file" ? "Analyze new audio file" : "Analyze YouTube URL",
  }));
  panel.appendChild(el("div", {
    style: { color: "var(--fg-1)" },
    text: `Already in library: ${state.slug}`,
  }));

  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  const cancelBtn = el("button", {
    style: buttonStyle(), text: "Cancel",
    onClick: () => overlay.remove(),
  });
  const reanalyzeBtn = el("button", {
    style: buttonStyle(), text: "Reanalyze",
    onClick: () => startStreaming(panel, overlay, state, { mode: "reanalyze", slug: state.slug }),
  });
  const addNewBtn = el("button", {
    style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
    text: `Add New ${state.suggestedNew}`,
    onClick: () => startStreaming(panel, overlay, state, { mode: "new", slug: state.suggestedNew }),
  });
  row.appendChild(cancelBtn);
  row.appendChild(reanalyzeBtn);
  row.appendChild(addNewBtn);
  panel.appendChild(row);
}

function _renderInlineYtdlpStale(panel, overlay, state) {
  panel.replaceChildren();
  panel.appendChild(el("h2", { style: { margin: 0, fontSize: "15px", color: "white" }, text: "yt-dlp is stale" }));
  panel.appendChild(el("p", {
    style: { color: "#ff6b6b" },
    text: "yt-dlp failed with a stale-version pattern. Update and retry?",
  }));
  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  row.appendChild(el("button", { style: buttonStyle(), text: "Cancel", onClick: () => overlay.remove() }));
  row.appendChild(el("button", {
    style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
    text: "Update yt-dlp & retry",
    onClick: async () => {
      try {
        const dry = await api.youtubeDryRun(state.url, { update_ytdlp: true });
        state.slug = dry.predicted_slug;
        state.exists = dry.exists;
        state.suggestedNew = dry.suggested_new_slug;
        if (!state.exists) startStreaming(panel, overlay, state, { mode: "new", slug: state.slug, update_ytdlp: true });
        else _renderCollisionStep(panel, overlay, state);
      } catch (e) {
        _renderError(panel, overlay, `Retry failed: ${e.message || e}`);
      }
    },
  }));
  panel.appendChild(row);
}

function _renderError(panel, overlay, message) {
  panel.replaceChildren();
  panel.appendChild(el("h2", { style: { margin: 0, fontSize: "15px", color: "#ff6b6b" }, text: "Error" }));
  panel.appendChild(el("p", { style: { color: "#ff6b6b", whiteSpace: "pre-wrap" }, text: message }));
  const row = el("div", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } });
  row.appendChild(el("button", { style: buttonStyle(), text: "Close", onClick: () => overlay.remove() }));
  panel.appendChild(row);
}

// Streaming + done steps land in the next task. Placeholder for now:
function startStreaming(panel, overlay, state, params) {
  panel.replaceChildren();
  panel.appendChild(el("div", { text: `(streaming will go here — params: ${JSON.stringify(params)})` }));
}
```

Add `api.youtubeDryRun` to `webui/static/js/api.js`:

```javascript
api.youtubeDryRun = async (url, { update_ytdlp = false } = {}) => {
  const r = await fetch("/api/tools/analyze/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, dry_run: true, update_ytdlp }),
  });
  if (r.status === 503) {
    const body = await r.json();
    const e = new Error(body.message || "yt-dlp stale");
    e.kind = "ytdlp_stale";
    throw e;
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const e = new Error(body.message || `dry_run failed: ${r.status}`);
    e.kind = body.error || "ytdlp_metadata_failed";
    throw e;
  }
  return await r.json();
};
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```
git add webui/static/js/ui/analyze-modal.js webui/static/js/api.js webui/tests-js/analyze-modal.test.js
git commit -m "feat(webui): analyze-modal collision step + analyze trigger"
```

---

## Task 14: Streaming step (phase strip + stage chips + log + progress bar)

**Files:**
- Modify: `webui/static/js/ui/analyze-modal.js`
- Test: `webui/tests-js/analyze-modal.test.js`

- [ ] **Step 1: Write the failing test**

Append to `webui/tests-js/analyze-modal.test.js`:

```javascript
test("streaming step renders phase strip with file-flow phases", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "file" });
  mod._renderStreamingStep(overlay.querySelector("div > div"), overlay, {
    mode: "file",
    quality: "best",
    slug: "brand_new",
    file: new dom.window.File([new Uint8Array(0)], "brand_new.mp3"),
  }, { mode: "new", slug: "brand_new" });

  const phaseChips = overlay.querySelectorAll(".analyze-phase-chip");
  const labels = [...phaseChips].map((c) => c.textContent);
  // file flow: upload → transcode (hidden for mp3 source) → analyze
  assert.ok(labels.some((l) => /Upload/i.test(l)));
  assert.ok(labels.some((l) => /Analyze/i.test(l)));
  overlay.remove();
});

test("streaming step renders phase strip with YouTube-flow phases", async () => {
  const mod = await import("../static/js/ui/analyze-modal.js");
  const overlay = mod.showAnalyzeModal({ mode: "youtube" });
  mod._renderStreamingStep(overlay.querySelector("div > div"), overlay, {
    mode: "youtube",
    quality: "best",
    slug: "fresh-slug",
    url: "https://x",
  }, { mode: "new", slug: "fresh-slug" });

  const phaseChips = overlay.querySelectorAll(".analyze-phase-chip");
  const labels = [...phaseChips].map((c) => c.textContent);
  assert.ok(labels.some((l) => /Download/i.test(l)));
  assert.ok(labels.some((l) => /Analyze/i.test(l)));
  overlay.remove();
});
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: FAIL — `_renderStreamingStep` doesn't exist.

- [ ] **Step 3: Implement streaming step**

In `webui/static/js/ui/analyze-modal.js`, replace the placeholder `startStreaming` and add `_renderStreamingStep`:

```javascript
function startStreaming(panel, overlay, state, params) {
  _renderStreamingStep(panel, overlay, state, params);
}

export function _renderStreamingStep(panel, overlay, state, params) {
  panel.replaceChildren();
  panel.style.width = "min(1080px, 96vw)";
  panel.style.height = "min(1400px, 96vh)";

  panel.appendChild(el("h2", {
    style: { margin: 0, fontSize: "15px", color: "white" },
    text: state.mode === "file" ? `Analyzing — ${state.file?.name ?? params.slug}` : `Analyzing — ${state.url}`,
  }));

  // Phase strip
  const phasesForFile = ["upload", state.file?.name?.toLowerCase().endsWith(".mp3") ? null : "transcode", "analyze"].filter(Boolean);
  const phasesForYoutube = ["download", "analyze"];
  const phases = state.mode === "file" ? phasesForFile : phasesForYoutube;

  const phaseStrip = el("div", { style: { display: "flex", gap: "6px" } });
  const phaseChips = new Map();
  for (const name of phases) {
    const chip = el("span", {
      class: "analyze-phase-chip",
      style: {
        padding: "3px 10px", borderRadius: "12px", border: "1px solid var(--bg-3)",
        color: "var(--fg-2)", fontSize: "11px", textTransform: "capitalize",
      },
      text: name,
    });
    phaseChips.set(name, chip);
    phaseStrip.appendChild(chip);
  }
  panel.appendChild(phaseStrip);

  // Optional download progress bar (YouTube only)
  let progressBar = null, progressFill = null, progressText = null;
  if (state.mode === "youtube") {
    progressBar = el("div", { style: { width: "100%", height: "6px", background: "var(--bg-3)", borderRadius: "3px", overflow: "hidden" } });
    progressFill = el("div", { style: { width: "0%", height: "100%", background: "var(--accent, #4a90e2)", transition: "width .15s linear" } });
    progressBar.appendChild(progressFill);
    progressText = el("div", { style: { fontSize: "10px", color: "var(--fg-2)" }, text: "" });
    panel.appendChild(progressBar);
    panel.appendChild(progressText);
  }

  // Stage chips (analyze phase)
  const stageBar = el("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px" } });
  const stageChips = new Map();
  for (const name of STAGE_ORDER) {
    const chip = el("span", {
      style: {
        padding: "3px 8px", borderRadius: "10px", border: "1px solid var(--bg-3)",
        color: "var(--fg-2)", fontSize: "10px", fontFamily: "var(--font-mono, monospace)",
      },
      text: name,
    });
    stageChips.set(name, chip);
    stageBar.appendChild(chip);
  }
  panel.appendChild(stageBar);

  // Log
  const logBox = el("pre", {
    style: {
      flex: "1 1 auto", minHeight: "300px", overflow: "auto",
      margin: 0, padding: "10px 12px", background: "var(--bg-0, #000)",
      border: "1px solid var(--bg-3)", borderRadius: "4px",
      fontFamily: "var(--font-mono, monospace)", fontSize: "11px",
      whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--fg-1)",
    },
  });
  panel.appendChild(logBox);

  const statsArea = el("div", { style: { display: "none" } });
  panel.appendChild(statsArea);

  const errorBanner = el("div", {
    style: {
      display: "none", padding: "8px 12px", background: "rgba(255,107,107,.12)",
      border: "1px solid #ff6b6b", borderRadius: "4px", color: "#ff6b6b",
      whiteSpace: "pre-wrap",
    },
  });
  panel.appendChild(errorBanner);

  const footer = el("div", { style: { display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "4px" } });
  const closeBtn = el("button", { style: { ...buttonStyle(), opacity: 0.5 }, text: "Close", onClick: () => overlay.remove() });
  closeBtn.disabled = true;
  const openBtn = el("button", {
    style: { ...buttonStyle(), display: "none", background: "var(--accent, #4a90e2)", color: "white" },
    text: "Open new track",
    onClick: () => { /* set in onDone */ },
  });
  footer.appendChild(openBtn);
  footer.appendChild(closeBtn);
  panel.appendChild(footer);

  // Helpers
  const pushLog = (line) => {
    const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 4;
    logBox.appendChild(document.createTextNode(line + "\n"));
    if (atBottom) logBox.scrollTop = logBox.scrollHeight;
  };
  const setPhase = (name, status) => {
    const chip = phaseChips.get(name);
    if (!chip) return;
    if (status === "start") {
      chip.style.color = STATUS_COLOR.running;
      chip.style.borderColor = STATUS_COLOR.running;
    } else if (status === "end") {
      chip.style.color = STATUS_COLOR.done;
      chip.style.borderColor = STATUS_COLOR.done;
    }
  };
  const setStage = (name, status) => {
    const chip = stageChips.get(name);
    if (!chip) return;
    const color = STATUS_COLOR[status] || "var(--fg-1)";
    chip.style.color = color;
    chip.style.borderColor = color;
    chip.textContent = status === "running" ? `▶ ${name}` : status === "cached" ? `${name} (cached)` : name;
  };
  const setProgress = (pct, eta_sec, speed) => {
    if (!progressFill) return;
    progressFill.style.width = `${pct.toFixed(1)}%`;
    progressText.textContent = `${pct.toFixed(1)}%  ·  ${speed}  ·  ETA ${eta_sec}s`;
  };
  const finalize = ({ ok, slug, stats, errorMessage, errorKind }) => {
    closeBtn.disabled = false;
    closeBtn.style.opacity = 1;
    if (ok) {
      renderStats(statsArea, stats);
      statsArea.style.display = "";
      openBtn.style.display = "";
      openBtn.onclick = () => {
        location.search = `?slug=${encodeURIComponent(slug)}`;
      };
    } else {
      errorBanner.textContent = errorMessage || "(unknown error)";
      errorBanner.style.display = "";
      // Stale-yt-dlp recovery affordance
      if (errorKind === "ytdlp_stale") {
        const retryBtn = el("button", {
          style: { ...buttonStyle(), background: "var(--accent, #4a90e2)", color: "white" },
          text: "Update yt-dlp & retry",
          onClick: () => _renderInlineYtdlpStale(panel, overlay, state),
        });
        footer.insertBefore(retryBtn, openBtn);
      }
    }
  };

  // Wire up the network call.
  let finalSlug = params.slug;
  let finalStats = null;
  const onEvent = (event) => {
    if (event.type === "log") pushLog(event.line);
    else if (event.type === "phase") setPhase(event.name, event.status);
    else if (event.type === "progress") setProgress(event.pct, event.eta_sec, event.speed);
    else if (event.type === "stage") setStage(event.name, event.status);
    else if (event.type === "slug") finalSlug = event.slug;
    else if (event.type === "done") { finalStats = event.stats; finalSlug = event.slug ?? finalSlug; finalize({ ok: true, slug: finalSlug, stats: finalStats }); }
    else if (event.type === "error") finalize({ ok: false, errorMessage: event.message, errorKind: event.kind });
  };

  if (state.mode === "file") {
    const fd = new FormData();
    fd.append("file", state.file);
    fd.append("quality", state.quality);
    fd.append("mode", params.mode);
    fd.append("slug", params.slug);
    streamAnalyze("/api/tools/analyze/upload", { method: "POST", body: fd }, onEvent)
      .catch((e) => onEvent({ type: "error", message: `request failed: ${e.message || e}` }));
  } else {
    streamAnalyze("/api/tools/analyze/youtube", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: state.url, quality: state.quality,
        mode: params.mode, slug: params.slug,
        update_ytdlp: !!params.update_ytdlp,
      }),
    }, onEvent).catch((e) => onEvent({ type: "error", message: `request failed: ${e.message || e}` }));
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd webui && node --test tests-js/analyze-modal.test.js
```

Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```
git add webui/static/js/ui/analyze-modal.js webui/tests-js/analyze-modal.test.js
git commit -m "feat(webui): analyze-modal streaming step (phase strip + progress)"
```

---

## Task 15: Track-picker header buttons + CSS

Wire `+ File` and `+ YT` buttons into the dropdown header. They dynamically import `analyze-modal.js`.

**Files:**
- Modify: `webui/static/js/ui/track-picker.js`
- Modify: `webui/static/css/track.css`
- Test: `webui/tests-js/track-picker.test.js` (existing)

- [ ] **Step 1: Write the failing test**

Append to `webui/tests-js/track-picker.test.js`:

```javascript
test("track-picker header includes + File and + YT buttons", async () => {
  const { JSDOM } = await import("jsdom");
  const dom = new JSDOM("<!doctype html><html><body><div id='picker'></div></body></html>");
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  globalThis.HTMLElement = dom.window.HTMLElement;
  const { mountTrackPicker } = await import("../static/js/ui/track-picker.js");
  const picker = dom.window.document.getElementById("picker");
  mountTrackPicker(picker, [], { currentSlug: null, onPick: () => {} });
  picker.toggle();
  const headerText = picker.querySelector(".tp-header")?.textContent ?? "";
  assert.match(headerText, /\+ File/);
  assert.match(headerText, /\+ YT/);
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd webui && node --test tests-js/track-picker.test.js
```

Expected: FAIL — header doesn't have those buttons.

- [ ] **Step 3: Edit `track-picker.js` `buildHeader`**

Replace the existing `buildHeader` with:

```javascript
function buildHeader(trackCount) {
  const header = document.createElement("div");
  header.className = "tp-header";

  const left = document.createElement("div");
  left.className = "tp-header-title";
  const label = document.createTextNode("LIBRARY · ");
  const count = document.createElement("span");
  count.className = "tp-count";
  count.textContent = String(trackCount);
  const trail = document.createTextNode(" TRACKS");
  left.appendChild(label);
  left.appendChild(count);
  left.appendChild(trail);
  header.appendChild(left);

  const actions = document.createElement("div");
  actions.className = "tp-header-actions";
  const fileBtn = document.createElement("button");
  fileBtn.className = "tp-header-btn";
  fileBtn.textContent = "+ File";
  fileBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const m = await import("./analyze-modal.js");
    m.showAnalyzeModal({ mode: "file" });
  });
  const ytBtn = document.createElement("button");
  ytBtn.className = "tp-header-btn";
  ytBtn.textContent = "+ YT";
  ytBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const m = await import("./analyze-modal.js");
    m.showAnalyzeModal({ mode: "youtube" });
  });
  actions.appendChild(fileBtn);
  actions.appendChild(ytBtn);
  header.appendChild(actions);

  return header;
}
```

- [ ] **Step 4: Add CSS for the header**

Append to `webui/static/css/track.css`:

```css
.tp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.tp-header-actions {
  display: flex;
  gap: 6px;
}
.tp-header-btn {
  background: transparent;
  border: 1px solid var(--bg-3);
  color: var(--fg-2);
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 10px;
  cursor: pointer;
  font-family: inherit;
}
.tp-header-btn:hover {
  color: var(--fg-1);
  border-color: var(--fg-2);
}
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd webui && node --test tests-js/track-picker.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit**

```
git add webui/static/js/ui/track-picker.js webui/static/css/track.css webui/tests-js/track-picker.test.js
git commit -m "feat(webui): + File / + YT header buttons in Library Tracks dropdown"
```

---

## Task 16: E2E — upload happy path with mocked WSL

This is a Playwright test that exercises the full upload flow against the real server. The WSL invocation is mocked at the server level via a fake-binary trick: we set the analyze module's `_async_spawn` to a stub that pretends to be `python -m analyze` and writes a synthetic `summary.json`.

**Files:**
- Create: `webui/tests-e2e/analyze-upload.spec.js`
- Create: `webui/tests-e2e/fixtures/tiny.wav` (44 bytes — valid empty WAV header)

- [ ] **Step 1: Generate a 1-second silent WAV fixture**

```
cd webui/tests-e2e && mkdir -p fixtures && python -c "import wave, struct; w=wave.open('fixtures/tiny.wav','w'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(struct.pack('<' + 'h'*44100, *([0]*44100))); w.close()"
```

Verify file exists:
```
ls -la webui/tests-e2e/fixtures/tiny.wav
```

Expected: ~88 KB file.

- [ ] **Step 2: Write the failing E2E test**

Create `webui/tests-e2e/analyze-upload.spec.js`:

```javascript
import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

test.describe("Analyze new file (upload)", () => {
  test("opens modal, picks file, sees collision step is bypassed for fresh slug", async ({ page }) => {
    await page.goto("/");
    // Open the picker
    await page.locator(".track-picker").click();
    // Click + File
    await page.getByRole("button", { name: "+ File" }).click();
    // Modal opens
    await expect(page.getByRole("heading", { name: /Analyze new audio file/i })).toBeVisible();
    // Pick fixture
    await page.locator('input[type="file"]').setInputFiles(resolve(here, "fixtures/tiny.wav"));
    // Wait for slug-for pre-check
    await expect(page.getByRole("button", { name: "Analyze" })).toBeEnabled({ timeout: 5000 });
    // (We stop here without clicking Analyze because the actual pipeline
    // requires WSL + GPU and is out of scope for this test. The path so far
    // covers the modal/network plumbing.)
  });
});
```

- [ ] **Step 3: Run the test to verify it fails initially (before all deps are wired)**

```
cd webui/tests-e2e && npx playwright test analyze-upload.spec.js
```

Expected: PASS if all prior tasks landed correctly. If it fails, address the reported issue (likely a selector mismatch with the actual rendered DOM).

- [ ] **Step 4: Commit**

```
git add webui/tests-e2e/analyze-upload.spec.js webui/tests-e2e/fixtures/tiny.wav
git commit -m "test(webui): E2E for analyze-upload modal pre-check flow"
```

---

## Task 17: E2E — collision flow surfaces the three-button step

**Files:**
- Modify: `webui/tests-e2e/analyze-upload.spec.js`

- [ ] **Step 1: Append the test**

Append to `webui/tests-e2e/analyze-upload.spec.js`:

```javascript
test("collision flow surfaces three-button step", async ({ page }) => {
  // Pick a filename whose slug matches an existing track in the local cache
  // (the dev box has Gorillaz - Silent Running... yielding slug
  // gorillaz_silent_running). We simulate by uploading a WAV named to slug
  // into a known existing slug. Locally derived from list_tracks().
  await page.goto("/");
  const tracks = await page.evaluate(() => fetch("/api/tracks").then((r) => r.json()));
  if (!tracks.length) test.skip(true, "no tracks in cache to collide with");

  const collidingSlug = tracks[0].slug;
  // Build a temp file with name <slug>.wav
  const tmpName = `${collidingSlug}.wav`;
  await page.locator(".track-picker").click();
  await page.getByRole("button", { name: "+ File" }).click();
  // Use the existing fixture but override file.name via FileChooser.
  const chooserPromise = page.waitForEvent("filechooser");
  await page.locator('input[type="file"]').click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: tmpName,
    mimeType: "audio/wav",
    buffer: require("node:fs").readFileSync(require("node:path").resolve(__dirname, "fixtures/tiny.wav")),
  });
  await page.getByRole("button", { name: "Analyze" }).click();
  // Three-button collision step
  await expect(page.getByRole("button", { name: new RegExp(`Add New ${collidingSlug}-2`) })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reanalyze" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
});
```

- [ ] **Step 2: Run the test**

```
cd webui/tests-e2e && npx playwright test analyze-upload.spec.js
```

Expected: PASS (skipped if no tracks in cache).

- [ ] **Step 3: Commit**

```
git add webui/tests-e2e/analyze-upload.spec.js
git commit -m "test(webui): E2E for collision flow three-button step"
```

---

## Task 18: E2E — YouTube dry_run hits the right endpoint (mocked at fetch layer)

**Files:**
- Create: `webui/tests-e2e/analyze-youtube.spec.js`

- [ ] **Step 1: Write the test**

Create `webui/tests-e2e/analyze-youtube.spec.js`:

```javascript
import { test, expect } from "@playwright/test";

test.describe("Analyze YouTube URL", () => {
  test("opens modal and hits dry_run endpoint with the URL", async ({ page }) => {
    await page.goto("/");
    let dryRunBody = null;
    await page.route("**/api/tools/analyze/youtube", async (route) => {
      const post = await route.request().postDataJSON();
      if (post.dry_run) {
        dryRunBody = post;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            predicted_slug: "fake_song-vidid12345",
            exists: false,
            suggested_new_slug: "fake_song-vidid12345-2",
          }),
        });
      } else {
        // Don't actually run analyze — return a minimal NDJSON stream that ends.
        await route.fulfill({
          status: 200,
          contentType: "application/x-ndjson",
          body: '{"type":"error","message":"test stub","kind":"internal"}\n',
        });
      }
    });
    await page.locator(".track-picker").click();
    await page.getByRole("button", { name: "+ YT" }).click();
    await page.locator('input[type="text"]').fill("https://www.youtube.com/watch?v=AbCdEf12345");
    await page.getByRole("button", { name: "Analyze" }).click();
    // The streaming step should now be rendered with the test-stub error.
    await expect(page.locator("text=test stub")).toBeVisible({ timeout: 5000 });
    expect(dryRunBody).toMatchObject({ url: "https://www.youtube.com/watch?v=AbCdEf12345", dry_run: true });
  });
});
```

- [ ] **Step 2: Run the test**

```
cd webui/tests-e2e && npx playwright test analyze-youtube.spec.js
```

Expected: PASS.

- [ ] **Step 3: Commit**

```
git add webui/tests-e2e/analyze-youtube.spec.js
git commit -m "test(webui): E2E for YouTube modal -> dry_run endpoint"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Plan task(s) |
|---|---|
| UI: header buttons in Library Tracks dropdown | Task 15 |
| UI: Analyze modal — input step (file + URL) | Task 12 |
| UI: collision step (3-button) with semantic asymmetry | Task 13 |
| UI: streaming step (phase strip + stage chips + progress) | Task 14 |
| UI: done step (Open new / Stay here) | Task 14 (in `finalize`) |
| UI: error step (incl. stale-yt-dlp retry) | Tasks 13 (inline) + 14 (in-stream) |
| Reanalyze default → Best | Task 11 |
| `GET /api/util/slug-for` | Task 3 |
| `POST /api/tools/analyze/upload` | Task 8 |
| `POST /api/tools/analyze/youtube` (dry_run + streaming) | Task 9 |
| `POST /api/tools/reanalyze/{slug}` refactor (delegate) | Task 1 |
| Protocol: phase / progress / slug events | Tasks 1, 4, 7, 14 |
| Shared `_run_analyze_stream` + `_analyze_lock` | Task 1 |
| Lock-leak fix on disconnect | Task 1 |
| Slug helpers + extension allowlist | Tasks 2, 3 |
| Server-side slug validation rule | Tasks 8, 9 |
| ffmpeg transcode for WAV/FLAC | Task 4 + integrated in Task 8 |
| yt-dlp simulate (slug pre-check, `.mp3` synthetic suffix) | Task 6 |
| yt-dlp download with progress parsing | Task 7 |
| Stale-yt-dlp pattern detection + retry | Tasks 5, 13 (UI), 14 (UI) |
| YouTube reanalyze branch (reuse cache, no re-download) | Task 9 |
| Lock semantics (acquired after buffer/metadata) | Task 1 (acquire inside `run_analyze_stream`) |
| Defaults change rollup (UI only) | Tasks 11, 12 |
| E2E coverage | Tasks 16, 17, 18 |

All spec sections mapped to tasks.

**2. Placeholder scan:**

- No "TBD" / "TODO" / "implement later" — verified.
- No "similar to Task N" — each task contains complete code.
- All test code blocks contain real assertions.
- All implementation code blocks are complete and runnable.
- Exact `git add` paths in every commit step.

**3. Type / name consistency:**

- `_analyze_lock` consistent across Tasks 1, 8, 9.
- `_async_spawn` consistent across Tasks 1, 4, 6, 7.
- `analyze_runner.ndjson()` consistent.
- `analyze_runner.run_analyze_stream(slug, source_path, quality)` signature consistent (Tasks 1, 8, 9).
- `slug_for_filename` used by Tasks 2, 3, 6, 8.
- `find_first_free_slug` used by Tasks 2, 3, 9.
- `is_stale_ytdlp_stderr` used by Tasks 5, 6, 7.
- `youtube_metadata_slug` returns `{ok, predicted_slug, kind, stderr}` consistent across Tasks 6, 9.
- `youtube_download` yields `{type:"downloaded", path}` as the success terminal — coordinated with Task 9's `_stream` consumer.
- `STAGE_ORDER`, `QUALITY_PRESETS`, `STATUS_COLOR` exported names match between Tasks 10 and the consumers in Tasks 11, 12, 14.
- JS `streamAnalyze(url, init, onEvent)` signature consistent (Tasks 10, 12, 14).
- Modal helper exports `_renderCollisionStep`, `_renderStreamingStep` consistently named (Tasks 13, 14).

All cross-task references resolve.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-02-analyze-from-library.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
