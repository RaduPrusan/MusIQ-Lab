import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import _paths, _security, analyze_runner, audio, f0, lastfm, tracks, user_meta
from . import lyrics as _lyrics
from ._security import validate_slug, validate_stem
from .identify import read_identify

log = logging.getLogger(__name__)
app = FastAPI(title="MusIQ-Lab webui")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


class _NoCacheDevMiddleware:
    """Dev server: tell browsers to revalidate JS/CSS and audio on every
    request so a re-analysis (which rewrites the cached MP3/WAV) shows up
    without manual cache clearing.

    Implemented as raw ASGI middleware (not @app.middleware("http")) because
    Starlette's BaseHTTPMiddleware buffers streaming response bodies through
    an internal queue, which deadlocks with our long-running SSE/NDJSON
    endpoints (analyze, chat, lyrics fetch). Raw ASGI middleware passes
    `send` through unchanged, so streamed bodies reach the wire as they're
    yielded.
    """
    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = scope.get("path", "")
        nocache = path.startswith("/static/") or "/audio/" in path
        if not nocache:
            await self._app(scope, receive, send)
            return
        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for (k, v) in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache, must-revalidate"))
                message["headers"] = headers
            await send(message)
        await self._app(scope, receive, patched_send)


app.add_middleware(_NoCacheDevMiddleware)
# Loopback-only Origin/Host enforcement + standard security headers.
# Mounted AFTER _NoCacheDevMiddleware so the guard runs first (Starlette
# middleware is LIFO at request time). Both pieces are raw ASGI so they
# pass-through streaming bodies without buffering.
app.add_middleware(_security.SecurityHeaders)
app.add_middleware(_security.OriginGuard)

# WASAPI audio engine v1 — Phase 1 (device-picker scaffold). The router
# exposes a single WebSocket at /api/audio/control. _NoCacheDevMiddleware
# only intercepts scope["type"] == "http", so WS frames pass through
# unchanged.
from .audio_backend.ws import router as audio_router, shutdown_all_sessions  # noqa: E402
app.include_router(audio_router)


@app.on_event("shutdown")
async def _close_audio_sessions() -> None:
    """Force-close any live AudioSession on app exit.

    The per-WS handler also closes its session in a finally block; this
    second path guards against the case where FastAPI tears down before
    the WS disconnect handler runs (e.g. SIGINT mid-stream). atexit can't
    do this — the asyncio loop is already closed by the time atexit fires
    and any pending WS sends would race.
    """
    await shutdown_all_sessions()

_STEM_GLOBS = {
    "vocals":       ["stems_6s/*(Vocals)*.wav"],
    "bass":         ["stems_6s/*(Bass)*.wav"],
    "guitar":       ["stems_6s/*(Guitar)*.wav"],
    "piano":        ["stems_6s/*(Piano)*.wav"],
    "other":        ["stems_6s/*(Other)*.wav"],
    "drums":        ["stems_6s/*(Drums)*.wav"],
    "instrumental": ["stems_bsroformer/*(Instrumental)*.wav"],
}

# Mirror of analyze.stages.stems.STEMS_QUALITY_PARAMS keys. Hard-coded here so
# the webui process (which runs on Windows and doesn't import the analyze
# package) can validate the value before shelling into WSL.
_STEMS_QUALITY_CHOICES = ("fast", "normal", "best")
_DEFAULT_STEMS_QUALITY = "best"

_SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".flac"}


async def _read_json_object(request: Request, *, empty: dict | None = None) -> dict:
    """Read a request body as a JSON object, returning 400 for bad input."""
    raw = await request.body()
    if not raw and empty is not None:
        return dict(empty)
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/tracks")
def api_tracks() -> list[dict]:
    from . import staleness as _staleness
    cache = _paths.cache_dir()
    out: list[dict] = []
    for t in tracks.list_tracks():
        row = asdict(t)
        row["stale_stages"] = _staleness.stale_stages(cache / t.slug)
        out.append(row)
    return out


@app.get("/api/tracks/{slug}")
def api_track(slug: str) -> dict:
    validate_slug(slug)
    try:
        return tracks.get_summary(slug)
    except KeyError:
        available = [t.slug for t in tracks.list_tracks()][:10]
        return JSONResponse(
            status_code=404,
            content={"error": "unknown_slug", "slug": slug, "available": available},
        )


@app.patch("/api/tracks/{slug}")
async def api_track_rename(slug: str, request: Request) -> dict:
    """Update user-authored track metadata. Today: just display_name.

    Side effect: writes lyrics/meta.json with smart-split artist/title so the
    lyrics-tab header reflects the rename without a separate edit.
    """
    validate_slug(slug)
    # 404 first if slug is unknown — surface validation error from a known track.
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")

    body = await _read_json_object(request, empty={})

    try:
        display_name = user_meta.validate_display_name(body.get("display_name"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    artist, title = user_meta.split_artist_title(display_name)

    slug_cache = _paths.cache_dir() / slug
    user_meta.write(slug_cache, {"display_name": display_name})

    # Update (or create) lyrics/meta.json so the lyrics-tab header reflects
    # the rename. Preserve other meta fields if a previous fetch populated them.
    lyr = _lyrics.cache_dir_for(slug_cache)
    lyr.mkdir(parents=True, exist_ok=True)
    meta_path = lyr / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    else:
        meta = {
            "source": "user_rename",
            "lrclib_id": None,
            "album": "",
            "duration_sec": float((summary.get("track") or {}).get("duration_sec") or 0.0),
        }
    meta["artist"] = artist
    meta["title"] = title
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Invalidate the list-tracks memoization for this slug so the next
    # /api/tracks GET reflects the new title.
    tracks._cache.pop(slug, None)

    return {"display_name": display_name, "artist": artist, "title": title}


@app.get("/api/tracks/{slug}/f0")
def api_f0(slug: str) -> dict:
    validate_slug(slug)
    cache = _paths.cache_dir() / slug
    npz = cache / "vocal_f0.npz"
    if not npz.is_file():
        raise HTTPException(status_code=404, detail="vocal_f0.npz not found")
    consensus_npz = cache / "vocal_consensus.npz"
    vocals_dyn_npz = cache / "dynamics" / "vocals.npz"
    return f0.decode_f0(
        npz,
        consensus_npz if consensus_npz.is_file() else None,
        vocals_dyn_npz if vocals_dyn_npz.is_file() else None,
    )


@app.get("/api/tracks/{slug}/vocal_consensus")
def api_vocal_consensus(slug: str) -> dict:
    """Per-note intonation summary from the vocal_consensus_contour stage."""
    validate_slug(slug)
    json_path = _paths.cache_dir() / slug / "vocal_consensus.json"
    if not json_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="vocal_consensus.json not found (stage may not have run)",
        )
    return json.loads(json_path.read_text())


@app.get("/api/track/{slug}/lastfm")
def api_lastfm(slug: str) -> dict:
    """Last.fm tags + similar artists for a track.

    Returns {available: bool, tags?, similar_artists?, reason?}. Reads the
    on-disk cache (cache/<slug>/lastfm.json) first; on miss, fetches from
    Last.fm and writes the cache. Soft-fails to available=false when no MBID
    is on disk or Last.fm errors (e.g. missing API key, network) — only
    404s for an unknown slug.
    """
    validate_slug(slug)
    cache = _paths.cache_dir() / slug
    if not cache.exists():
        raise HTTPException(status_code=404, detail="track not found")

    identified = read_identify(cache)
    if not identified or not identified.get("identified"):
        return {"available": False, "reason": "no MBID (track not identified)"}

    mbid_rec = identified.get("mbid_recording")
    mbid_art = identified.get("mbid_artist")
    if not mbid_rec and not mbid_art:
        return {"available": False, "reason": "identify.json missing both MBIDs"}

    cached = lastfm.load_cache(cache)
    if cached is not None:
        return {"available": True, **cached}

    try:
        tags = lastfm.fetch_track_info(mbid_recording=mbid_rec)["tags"] if mbid_rec else []
        similar = lastfm.fetch_similar_artists(mbid_artist=mbid_art) if mbid_art else []
    except lastfm.LastFmError as e:
        return {"available": False, "reason": str(e)}

    payload = {"tags": tags, "similar_artists": similar}
    lastfm.write_cache(cache, payload)
    return {"available": True, **payload}


@app.get("/api/tracks/{slug}/audio/source")
def api_audio_source(slug: str, request: Request) -> Response:
    validate_slug(slug)
    cache = _paths.cache_dir() / slug
    candidates = list(cache.glob("*.mp3"))
    if candidates:
        return _serve_with_range(candidates[0], request, "audio/mpeg")
    # Fallback to summary.json windows_path — the analyze pipeline records the
    # original MP3 location outside cache/, and we honor it for playback.
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="source mp3 not found")
    win = (summary.get("track") or {}).get("windows_path")
    if win:
        p = Path(win)
        if p.is_file():
            return _serve_with_range(p, request, "audio/mpeg")
    raise HTTPException(status_code=404, detail="source mp3 not found")


@app.get("/api/tracks/{slug}/audio/stem/{name}")
def api_audio_stem(slug: str, name: str, request: Request) -> Response:
    validate_slug(slug)
    cache = _paths.cache_dir() / slug
    if name not in _STEM_GLOBS:
        raise HTTPException(status_code=400, detail=f"unknown stem: {name}")
    for pattern in _STEM_GLOBS[name]:
        for path in cache.glob(pattern):
            return _serve_with_range(path, request, "audio/wav")
    return JSONResponse(
        status_code=404,
        content={
            "error": "missing_stem",
            "name": name,
            "reason": f"no stem WAV matched any of {_STEM_GLOBS[name]}",
        },
    )


@app.get("/api/tracks/{slug}/midi/{stem}")
def api_midi(slug: str, stem: str) -> FileResponse:
    validate_slug(slug)
    validate_stem(stem)
    cache = _paths.cache_dir() / slug
    mid = cache / "midi" / f"{stem}.mid"
    if not mid.is_file():
        raise HTTPException(status_code=404, detail=f"{stem}.mid not found")
    return FileResponse(
        mid,
        media_type="audio/midi",
        filename=f"{slug}_{stem}.mid",
    )


@app.get("/api/util/slug-for")
def api_util_slug_for(filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        return JSONResponse(
            status_code=415,
            content={"error": "unsupported_type", "extension": ext},
        )
    slug = analyze_runner.slug_for_filename(filename)
    cache_path = _paths.cache_dir() / slug / f"{slug}.summary.json"
    return {
        "slug": slug,
        "exists": cache_path.is_file(),
        "suggested_new_slug": analyze_runner.find_first_free_slug(slug),
    }


def _serve_with_range(path: Path, request: Request, media_type: str) -> Response:
    size = path.stat().st_size
    rng = audio.parse_range(request.headers.get("range"), size)
    if request.headers.get("range") and rng is None:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}"},
        )
    if rng is None:
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes"},
        )
    start, end = rng
    chunk_len = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(chunk_len)
    return Response(
        content=chunk,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_len),
        },
    )


@app.post("/api/tools/open-midi/{slug}/{stem}")
def api_tool_open_midi(slug: str, stem: str) -> dict:
    validate_slug(slug)
    validate_stem(stem)
    cache = _paths.cache_dir() / slug
    mid = cache / "midi" / f"{stem}.mid"
    if not mid.is_file():
        raise HTTPException(status_code=404, detail=f"{stem}.mid not found")
    os.startfile(mid)  # Windows-only; opens in user's default .mid handler
    return {"opened": str(mid)}


@app.post("/api/tools/reveal-cache/{slug}")
def api_tool_reveal_cache(slug: str) -> dict:
    validate_slug(slug)
    target = _paths.cache_dir() / slug
    # Defence in depth on top of validate_slug: the resolved path must stay
    # inside the cache dir. Cheap and traps symlink shenanigans + future
    # validate_slug regressions.
    cache_root = _paths.cache_dir().resolve()
    if not target.resolve().is_relative_to(cache_root):
        raise HTTPException(status_code=400, detail="slug escapes cache root")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"cache/{slug} not found")
    subprocess.Popen(["explorer", str(target)])
    return {"opened": str(target)}


# --- Reanalyze: clear cache and re-run the analyze pipeline in WSL --------
#
# Streams stage/log lines back as NDJSON. Only one reanalysis runs at a time
# across the process — concurrent requests get a single error event instead
# of trampling each other.
#
# The WSL subprocess management, lock, and NDJSON helpers all live in
# analyze_runner. This file only handles source-resolution (finding the
# original MP3 path or falling back to the cache mirror) and staging it into
# a tempdir before delegating to analyze_runner.run_analyze_stream().


async def _reanalyze_stream(
    slug: str,
    stems_quality: str = _DEFAULT_STEMS_QUALITY,
    *,
    stages_only: set[str] | None = None,
    params: dict | None = None,
    clear_cache: bool = True,
):
    """Reanalyze: stage source out of cache, then run analyze on it.

    When `clear_cache=False`, the cache is preserved and the analyze pipeline's
    per-stage cached() check decides what to re-run (used by the
    "Analyze (rerun stale)" Tools entry).
    """
    cache = _paths.cache_dir() / slug
    cache_mp3 = cache / f"{slug}.mp3"

    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        # summary.json missing typically means a previous reanalyze was killed
        # mid-pipeline (client disconnect kills the WSL subprocess via the
        # finally block in run_analyze_stream) before it could write a fresh
        # summary, leaving the cache half-cleared. The .mp3 mirror is preserved
        # across cache clears, so we can still drive a recovery reanalyze from
        # it. If even the mp3 is gone, the slug is genuinely unknown.
        if not cache_mp3.is_file():
            yield analyze_runner.ndjson({"type": "error", "message": f"unknown slug: {slug}", "kind": "analyze_failed"})
            return
        summary = {}

    track_meta = summary.get("track") or {}
    windows_path = track_meta.get("windows_path")

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
        async for chunk in analyze_runner.run_analyze_stream(
            slug, tmp_src, stems_quality,
            stages_only=stages_only, params=params, clear_cache=clear_cache,
        ):
            yield chunk


_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
_UPLOAD_CONTENT_TYPES = {
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/flac", "audio/x-flac",
}


def _validate_upload_slug(filename: str, mode: str, slug: str) -> None:
    """Raise HTTPException if (mode, slug) violate the slug-validation rule.

    Forecloses path-traversal (../, /etc/...) and contract violations
    (client sending an arbitrary slug instead of the slug-for-derived one).
    """
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
    stages: str = Form("[]"),   # JSON-encoded list of stage names
    params: str = Form("{}"),   # JSON-encoded object of per-stage params
) -> StreamingResponse:
    if quality not in _STEMS_QUALITY_CHOICES:
        raise HTTPException(status_code=400, detail=f"quality must be one of {list(_STEMS_QUALITY_CHOICES)}")
    if mode not in ("new", "reanalyze"):
        raise HTTPException(status_code=400, detail="mode must be 'new' or 'reanalyze'")

    try:
        stages_list = json.loads(stages)
        params_dict = json.loads(params)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="stages/params must be valid JSON")
    if not isinstance(stages_list, list) or not all(isinstance(s, str) for s in stages_list):
        raise HTTPException(status_code=400, detail="stages must be a list of strings")
    if not isinstance(params_dict, dict):
        raise HTTPException(status_code=400, detail="params must be a JSON object")
    stages_only = set(stages_list) if stages_list else None
    params_or_none: dict | None = params_dict if params_dict else None

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        return JSONResponse(status_code=415, content={"error": "unsupported_type", "extension": ext})
    if file.content_type and file.content_type not in _UPLOAD_CONTENT_TYPES:
        return JSONResponse(
            status_code=415,
            content={"error": "unsupported_type", "content_type": file.content_type},
        )

    _validate_upload_slug(file.filename or "", mode, slug)

    # Server-side collision recheck. Use the canonical {slug}.summary.json
    # path (matches tracks._summary_path) — NOT bare summary.json.
    cache_dir = _paths.cache_dir() / slug
    summary_file = cache_dir / f"{slug}.summary.json"
    if mode == "new" and cache_dir.is_dir() and summary_file.is_file():
        raise HTTPException(status_code=409, detail="slug already exists")
    if mode == "reanalyze" and not summary_file.is_file():
        raise HTTPException(status_code=409, detail="slug does not exist")

    tmp = tempfile.mkdtemp(prefix="musiq_upload_")
    safe_name = Path(file.filename or "upload.mp3").name or "upload.mp3"
    tmp_path = Path(tmp) / safe_name
    bytes_written = 0
    try:
        with tmp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="upload exceeds 500 MB cap")
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    async def _stream():
        try:
            yield analyze_runner.ndjson({"type": "phase", "name": "upload", "status": "end"})
            source_path = tmp_path
            if ext in (".wav", ".flac"):
                mp3_path = tmp_path.with_suffix(".mp3")
                async for chunk in analyze_runner.transcode_to_mp3(tmp_path, mp3_path):
                    yield chunk
                    if b'"ffmpeg_failed"' in chunk:
                        return
                tmp_path.unlink(missing_ok=True)
                source_path = mp3_path
            async for chunk in analyze_runner.run_analyze_stream(
                slug, source_path, quality,
                stages_only=stages_only, params=params_or_none,
            ):
                yield chunk
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    body = await _read_json_object(request, empty={})
    url = body.get("url")
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail="url is required")
    quality = body.get("quality", _DEFAULT_STEMS_QUALITY)
    if quality not in _STEMS_QUALITY_CHOICES:
        raise HTTPException(status_code=400, detail=f"quality must be one of {list(_STEMS_QUALITY_CHOICES)}")
    update_ytdlp = bool(body.get("update_ytdlp", False))
    dry_run = bool(body.get("dry_run", False))

    # Optional selective-run fields — same contract as /api/tools/reanalyze/{slug}.
    stages_only: set[str] | None = None
    yt_params: dict | None = None
    if "stages" in body:
        stages_raw = body["stages"]
        if not isinstance(stages_raw, list) or not all(isinstance(s, str) for s in stages_raw):
            raise HTTPException(status_code=400, detail="stages must be a list of strings")
        stages_only = set(stages_raw) if stages_raw else None
    if "params" in body:
        params_raw = body["params"]
        if not isinstance(params_raw, dict):
            raise HTTPException(status_code=400, detail="params must be a JSON object")
        yt_params = params_raw if params_raw else None

    if dry_run:
        meta = await analyze_runner.youtube_metadata_slug(url, update_first=update_ytdlp)
        if not meta["ok"]:
            kind = meta.get("kind", "ytdlp_failed")
            status = 503 if kind == "ytdlp_stale" else 502
            return JSONResponse(
                status_code=status,
                content={"error": kind, "message": meta.get("stderr", "")},
            )
        predicted = meta["predicted_slug"]
        cache_dir = _paths.cache_dir() / predicted
        return JSONResponse(content={
            "predicted_slug": predicted,
            "exists": (cache_dir / f"{predicted}.summary.json").is_file(),
            "suggested_new_slug": analyze_runner.find_first_free_slug(predicted),
        })

    mode = body.get("mode", "new")
    slug = body.get("slug")
    if mode not in ("new", "reanalyze"):
        raise HTTPException(status_code=400, detail="mode must be 'new' or 'reanalyze'")
    if not slug or not isinstance(slug, str):
        raise HTTPException(status_code=400, detail="slug is required when dry_run is false")

    async def _stream():
        # Metadata re-fetch + slug/collision validation moved inside the
        # generator so the streaming response opens FIRST. The yt-dlp call
        # below is 1–5 s; without an early log line the modal sat blank
        # while the user wondered if anything was happening.
        yield analyze_runner.ndjson({"type": "log", "line": "validating slug via yt-dlp..."})
        meta = await analyze_runner.youtube_metadata_slug(url, update_first=update_ytdlp)
        if not meta["ok"]:
            yield analyze_runner.ndjson({
                "type": "error",
                "kind": meta.get("kind", "ytdlp_failed"),
                "message": meta.get("stderr", "") or "yt-dlp metadata failed",
            })
            return

        predicted = meta["predicted_slug"]
        try:
            _validate_youtube_slug(predicted, mode, slug)
        except HTTPException as e:
            yield analyze_runner.ndjson({
                "type": "error",
                "kind": "slug_invalid",
                "message": str(e.detail),
            })
            return

        cache_dir = _paths.cache_dir() / slug
        summary_file = cache_dir / f"{slug}.summary.json"
        if mode == "new" and summary_file.is_file():
            yield analyze_runner.ndjson({
                "type": "error",
                "kind": "slug_collision",
                "message": "slug already exists",
            })
            return
        if mode == "reanalyze" and not summary_file.is_file():
            yield analyze_runner.ndjson({
                "type": "error",
                "kind": "slug_missing",
                "message": "slug does not exist",
            })
            return

        if mode == "reanalyze":
            # Reuse cached source MP3 — no re-download.
            cache_mp3 = cache_dir / f"{slug}.mp3"
            try:
                track_meta = (tracks.get_summary(slug).get("track") or {})
            except KeyError:
                track_meta = {}
            wp = track_meta.get("windows_path")
            src = Path(wp) if wp and Path(wp).is_file() else cache_mp3
            yield analyze_runner.ndjson({"type": "log", "line": f"reanalyze YouTube source: {src}"})
            if not src.is_file():
                yield analyze_runner.ndjson({
                    "type": "error",
                    "kind": "source_not_found",
                    "message": f"no source MP3 found for {slug}",
                })
                return
            with tempfile.TemporaryDirectory(prefix="musiq_yt_re_") as tmp:
                staged = Path(tmp) / src.name
                shutil.copy2(src, staged)
                async for chunk in analyze_runner.run_analyze_stream(
                    slug, staged, quality,
                    stages_only=stages_only, params=yt_params,
                ):
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
        async for chunk in analyze_runner.run_analyze_stream(
            slug, Path(downloaded_path), quality,
            stages_only=stages_only, params=yt_params,
        ):
            yield chunk

    return StreamingResponse(
        _stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _parse_reanalyze_body(request: Request) -> tuple[str, set[str] | None, dict | None]:
    """Parse the optional JSON body shared by /reanalyze and /analyze-stale.

    Empty body is fine; returns (default_quality, None, None). Otherwise
    body must be a JSON object with optional "quality", "stages", "params".
    Raises HTTPException on validation failure.
    """
    quality = _DEFAULT_STEMS_QUALITY
    stages_only: set[str] | None = None
    params: dict | None = None
    raw = await request.body()
    if not raw:
        return quality, stages_only, params
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
    if "stages" in payload:
        stages_raw = payload["stages"]
        if not isinstance(stages_raw, list) or not all(isinstance(s, str) for s in stages_raw):
            raise HTTPException(status_code=400, detail="stages must be a list of strings")
        stages_only = set(stages_raw) if stages_raw else None
    if "params" in payload:
        params_raw = payload["params"]
        if not isinstance(params_raw, dict):
            raise HTTPException(status_code=400, detail="params must be a JSON object")
        params = params_raw if params_raw else None
    return quality, stages_only, params


@app.post("/api/tools/reanalyze/{slug}")
async def api_tool_reanalyze(slug: str, request: Request) -> StreamingResponse:
    # Body is optional; if present, must be JSON with optional "quality",
    # "stages", and "params" keys. We parse leniently — empty body / missing
    # key fall back to defaults so the endpoint stays compatible with the
    # no-body POST the modal used before this option existed.
    validate_slug(slug)
    quality, stages_only, params = await _parse_reanalyze_body(request)
    return StreamingResponse(
        _reanalyze_stream(slug, stems_quality=quality, stages_only=stages_only, params=params),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/tools/analyze-stale/{slug}")
async def api_tool_analyze_stale(slug: str, request: Request) -> StreamingResponse:
    """Re-run analyze without clearing the cache.

    The pipeline's per-stage cached() check decides which work is genuinely
    stale (e.g. a beats sidecar predating SCHEMA_VERSION=2 triggers a madmom
    re-run plus a fresh summary.json). Cheap: minutes vs the 5-15 min full
    reanalyze, and a no-op when every stage's cache is fresh. Same body
    contract as /reanalyze; only the cache-clear step is suppressed.
    """
    validate_slug(slug)
    quality, stages_only, params = await _parse_reanalyze_body(request)
    return StreamingResponse(
        _reanalyze_stream(
            slug, stems_quality=quality, stages_only=stages_only, params=params,
            clear_cache=False,
        ),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Lyrics ----------------------------------------------------------------


def _lyrics_cache(slug: str) -> Path:
    return _lyrics.cache_dir_for(_paths.cache_dir() / slug)


@app.get("/api/tracks/{slug}/lyrics")
def api_lyrics_get(slug: str) -> dict:
    validate_slug(slug)
    cache = _lyrics_cache(slug)
    cached = _lyrics.load_cached(cache)
    if not cached:
        raise HTTPException(status_code=404, detail="no lyrics cached")
    return cached


@app.delete("/api/tracks/{slug}/lyrics")
def api_lyrics_delete(slug: str) -> dict:
    validate_slug(slug)
    _lyrics.clear_cache(_lyrics_cache(slug))
    return {"cleared": slug}


@app.post("/api/tracks/{slug}/lyrics/fetch")
async def api_lyrics_fetch(slug: str, request: Request) -> dict:
    validate_slug(slug)
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")
    duration = (summary.get("track") or {}).get("duration_sec") or 0
    overrides = await _read_json_object(request, empty={})
    artist = overrides.get("artist") or ""
    title = overrides.get("title") or ""
    # Source-of-truth chain for artist/title: explicit overrides → cached
    # lyrics meta (e.g. from a prior fetch) → user-authored display_name in
    # user_meta.json (the canonical rename) → filename heuristic. The
    # user_meta.json step is what makes Refetch survive deleteLyrics: the
    # rename writes both lyrics/meta.json AND user_meta.json, but DELETE
    # only wipes the former.
    if not artist or not title:
        existing_meta_path = _lyrics_cache(slug) / "meta.json"
        if existing_meta_path.is_file():
            try:
                em = json.loads(existing_meta_path.read_text(encoding="utf-8"))
                artist = artist or (em.get("artist") or "")
                title = title or (em.get("title") or "")
            except json.JSONDecodeError:
                pass
    if not artist or not title:
        display = (user_meta.read(_paths.cache_dir() / slug).get("display_name") or "").strip()
        if display:
            ua, ut = user_meta.split_artist_title(display)
            artist = artist or ua
            title = title or ut
    if not artist or not title:
        windows_path = ((summary.get("track") or {}).get("windows_path")) or ""
        if windows_path:
            ident = _lyrics.identify_track(Path(windows_path), duration_sec=duration)
            artist = artist or ident["artist"]
            title = title or ident["title"]
    result = await _lyrics.lrclib_lookup(artist=artist, title=title, duration_sec=duration)
    cache = _lyrics_cache(slug)
    meta = {
        "source": "lrclib",
        "lrclib_id": result.get("lrclib_id"),
        "artist": artist, "title": title, "album": "", "duration_sec": duration,
    }
    if result.get("has_sync") and result.get("synced_lrc"):
        _lyrics.save_synced(cache, result["synced_lrc"], meta)
    elif result.get("plain_text"):
        _lyrics.save_plain(cache, result["plain_text"], meta)
    else:
        return {"has_sync": False, "lines": [], "plain_text": None, "meta": meta, "error": result.get("error")}
    cached = _lyrics.load_cached(cache)
    return cached


@app.post("/api/tracks/{slug}/lyrics/paste")
async def api_lyrics_paste(slug: str, request: Request) -> dict:
    validate_slug(slug)
    payload = await _read_json_object(request, empty={})
    text = (payload or {}).get("text") or ""
    if not text:
        raise HTTPException(status_code=400, detail="empty paste")
    cache = _lyrics_cache(slug)
    # Preserve artist/title across the wholesale meta.json rewrite that
    # save_synced/save_plain performs. Same source-of-truth chain as
    # api_lyrics_fetch: cached lyrics meta → user_meta.json display_name.
    artist, title = "", ""
    existing_meta_path = cache / "meta.json"
    if existing_meta_path.is_file():
        try:
            em = json.loads(existing_meta_path.read_text(encoding="utf-8"))
            artist = em.get("artist") or ""
            title = em.get("title") or ""
        except json.JSONDecodeError:
            pass
    if not artist or not title:
        display = (user_meta.read(_paths.cache_dir() / slug).get("display_name") or "").strip()
        if display:
            ua, ut = user_meta.split_artist_title(display)
            artist = artist or ua
            title = title or ut
    meta = {
        "source": "user_paste",
        "lrclib_id": None,
        "artist": artist, "title": title, "album": "", "duration_sec": 0,
    }
    _lyrics.save_paste(cache, text, meta)
    return _lyrics.load_cached(cache)


# --- Chat ------------------------------------------------------------------
from . import chat as _chat
from . import chat_actor as _chat_actor


# One ChatRegistry per process. Each slug gets a long-lived ChatActor with
# its own ClaudeSDKClient — see chat_actor.py for the lifecycle and why
# we don't open/close per HTTP turn.
_chat_registry = _chat_actor.ChatRegistry()


@app.on_event("startup")
async def _start_chat_registry() -> None:
    _chat_registry.start_sweeper()


@app.on_event("shutdown")
async def _stop_chat_registry() -> None:
    await _chat_registry.close_all()


def _chat_path(slug: str) -> Path:
    return _paths.cache_dir() / slug / "chat.json"


@app.get("/api/chat/{slug}")
def api_chat_history(slug: str) -> dict:
    validate_slug(slug)
    return {"messages": _chat.load_history(_chat_path(slug))}


@app.post("/api/chat/{slug}/stop")
async def api_chat_stop(slug: str) -> dict:
    validate_slug(slug)
    """Best-effort cancel of an in-flight turn on `slug`.

    Returns `{interrupted: bool}` — false means no actor exists or no turn is
    in flight. The browser hits this *before* aborting its fetch so the SDK
    actually stops; otherwise the abort only closes the HTTP stream and the
    actor keeps generating until the model finishes.
    """
    interrupted = await _chat_registry.interrupt(slug)
    return {"interrupted": interrupted}


@app.delete("/api/chat/{slug}")
async def api_chat_clear(slug: str) -> dict:
    validate_slug(slug)
    # Kill the actor first so its in-flight write to chat.json (if any)
    # can't resurrect the file after we delete it.
    await _chat_registry.kill(slug)
    _chat.clear_history(_chat_path(slug))
    return {"cleared": slug}


@app.post("/api/chat/{slug}/turn")
async def api_chat_turn(slug: str, request: Request) -> StreamingResponse:
    validate_slug(slug)
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")
    payload = await _read_json_object(request)
    user_text = payload.get("text") or ""
    view_state = payload.get("view_state")
    chat_path = _chat_path(slug)
    user_message = _chat.build_user_message(user_text, view_state)

    # Build options lazily so the actor sees the resume_session_id captured
    # right before creation. After the actor exists, build_options is not
    # called again — subsequent turns reuse the already-open client.
    resume_id = _chat.load_last_session_id(chat_path)
    def _make_options():
        return _chat.build_actor_options(
            system_prompt=_chat.build_system_prompt(summary),
            mcp_server=_chat.make_mcp_server(),
            allowed_tools=_chat.ALLOWED_TOOLS,
            resume_session_id=resume_id,
        )

    actor = await _chat_registry.get_or_create(slug, build_options=_make_options)
    if actor.is_busy():
        log.warning("chat: turn rejected for slug=%s — actor busy", slug)
        raise HTTPException(status_code=409, detail="chat_busy")

    _chat.append_user_message(chat_path, user_message)
    stream = await actor.submit_turn(user_message)

    async def gen():
        # Preserve original interleave: each event appends a block (text
        # events extend the trailing text block; tool events always open a
        # fresh one). Previous version concatenated all text first, then all
        # tool blocks — so after _restoreHistory the transcript showed prose
        # at the top and tool chips at the bottom regardless of original
        # order. See claude-tab.js _renderMessage.
        assistant_blocks: list[dict] = []
        session_id_seen: str | None = None
        try:
            async for ev in stream:
                t = ev["type"]
                if t == "text":
                    if assistant_blocks and assistant_blocks[-1].get("type") == "text":
                        assistant_blocks[-1]["text"] += ev["delta"]
                    else:
                        assistant_blocks.append({"type": "text", "text": ev["delta"]})
                elif t == "tool_use":
                    assistant_blocks.append({"type": "tool_use", "id": ev["id"], "name": ev["name"], "input": ev["input"]})
                elif t == "tool_result":
                    assistant_blocks.append({"type": "tool_result", "id": ev["id"], "ok": ev["ok"], "summary": ev["summary"]})
                elif t == "done":
                    session_id_seen = ev.get("session_id") or session_id_seen
                yield (json.dumps(ev) + "\n").encode("utf-8")
        finally:
            if assistant_blocks:
                _chat.append_assistant_message(
                    chat_path,
                    blocks=assistant_blocks,
                    session_id=session_id_seen or actor.current_session_id,
                )

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
