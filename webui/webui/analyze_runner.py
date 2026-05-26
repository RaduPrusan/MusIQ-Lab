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
import os
import re
import shlex
import shutil
from pathlib import Path

from . import _paths, tracks

log = logging.getLogger(__name__)

_async_spawn = asyncio.create_subprocess_exec
_analyze_lock = asyncio.Lock()

# Per-stage produced artifacts. When _clear_cache_dir is called with
# only_stages={"transcription"}, only the artifacts listed under each
# named stage are deleted; everything else is preserved (matching the
# spirit of the existing PRESERVE list, just inverted).
#
# Globs are relative to the cache_dir root. Use Path.glob() — these are
# real on-disk path patterns, not regexes.
STAGE_ARTIFACTS: dict[str, list[str]] = {
    "stems": [
        "stems_6s",
        "stems_htdemucs_ft",
        "stems_bsroformer",
        "stems_routing.json",
        ".params_stems.json",  # in case sidecar moves out of stems_6s/ later
    ],
    "beats": [
        "madmom_downbeats.json",
        ".params_beats.json",
    ],
    "key": [
        "skey.json",
        ".params_key.json",
    ],
    "chords": [
        "chords.json",
        ".params_chords.json",
    ],
    "transcription": [
        "midi",
        "transcription_summary.json",
        "transcription_piano.json",
        ".params_transcription.json",
        ".params_transcription_piano.json",
        # transcription_vocals.json removed 2026-05-04 with the homegrown
        # F0→notes revert; vocals now go through basic-pitch.
    ],
    "beats_xcheck": [
        "beat_this.json",
        ".params_beats_xcheck.json",
    ],
    "vocal_f0": [
        "vocal_f0.npz",
        "vocal_f0_summary.json",
        ".params_vocal_f0.json",
    ],
    "drums": [
        "stems_drums",
        "drums_summary.json",
    ],
    "stems_dynamics": [
        "dynamics",
        ".params_stems_dynamics.json",
    ],
    "vocal_consensus_contour": [
        "vocal_consensus.npz",
        "vocal_consensus.json",
        ".params_vocal_consensus_contour.json",
    ],
}


def _to_wsl_path(p: Path) -> str:
    s = str(p.resolve())
    if len(s) < 3 or s[1] != ":":
        return s.replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:].replace(chr(92), '/')}"


class CacheLockedError(Exception):
    """Raised when _clear_cache_dir can't delete a cache child because the
    file is held open by another process. Carries the offending path so the
    streaming wrapper can show the user where to look (the source mp3 is
    the usual suspect — held open by a player or a streaming response)."""

    def __init__(self, path: Path, original: BaseException):
        super().__init__(f"file in use: {path} ({original})")
        self.path = path
        self.original = original


def _clear_cache_dir(cache: Path, *, only_stages: set[str] | None = None) -> None:
    """Clear cache contents, preserving the user-authored artifacts.

    When only_stages is None (default), behaves exactly as before — full clear
    minus the PRESERVE set. When only_stages is given, deletes only the
    artifacts each named stage produces (per STAGE_ARTIFACTS), leaving every
    other stage's output intact.

    Selective mode raises ValueError if an unknown stage name is passed —
    silently ignoring would mask UI bugs.

    Preserve list: chat history (chat.json), cached lyrics (lyrics/),
    user-authored display name (user_meta.json), and the source mp3 mirror
    (cache/<slug>/<slug>.mp3). The analyze pipeline never rewrites the mp3
    (analyze/pipeline.py:274 only copies when missing); keeping it here is
    the source of truth for any future reanalyze. NTFS handle-release lag can
    also hold a transient lock on it; the retry loop below handles that for
    other files, but we simply don't touch the mp3.
    """
    PRESERVE = {"chat.json", "lyrics", "user_meta.json", f"{cache.name}.mp3"}

    if only_stages is None:
        # ---- Full-clear path (existing behavior) ----
        # Defense-in-depth: even with the .mp3 preserved, NTFS handle release can
        # lag socket close by a few hundred ms for any cache file the server has
        # served. Retry briefly before giving up so the user doesn't see a
        # transient race as a hard failure.
        import time as _time
        for child in cache.iterdir():
            if child.name in PRESERVE:
                continue
            last_err: BaseException | None = None
            for attempt in range(4):
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    last_err = None
                    break
                except PermissionError as e:
                    last_err = e
                    _time.sleep(0.3 * (attempt + 1))
            if last_err is not None:
                raise CacheLockedError(child, last_err)
        return

    # ---- Selective-clear path (new) ----
    unknown = only_stages - set(STAGE_ARTIFACTS)
    if unknown:
        raise ValueError(
            f"unknown stages {sorted(unknown)}; expected one of {sorted(STAGE_ARTIFACTS)}"
        )

    import time as _time
    targets: list[Path] = []
    for stage in only_stages:
        for artifact_glob in STAGE_ARTIFACTS[stage]:
            for path in cache.glob(artifact_glob):
                if path.name in PRESERVE:
                    continue
                targets.append(path)

    for path in targets:
        last_err: BaseException | None = None
        for attempt in range(4):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():  # may have been deleted as a child of a dir target
                    path.unlink()
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                _time.sleep(0.3 * (attempt + 1))
            except FileNotFoundError:
                # Already gone — fine.
                last_err = None
                break
        if last_err is not None:
            raise CacheLockedError(path, last_err)


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


async def run_analyze_stream(
    slug: str,
    source_path: Path,
    quality: str,
    *,
    stages_only: set[str] | None = None,
    params: dict | None = None,
    clear_cache: bool = True,
):
    """Async generator yielding NDJSON event bytes for one analyze run.

    Caller is responsible for ensuring source_path exists and is the final
    .mp3 to feed into the pipeline (after any upload/transcode/download).
    The lock is acquired here; if busy, emits lock_busy and exits.

    `stages_only` and `params` are optional. When `stages_only` is provided,
    the cache is cleared only for those stages (selective re-run); the WSL
    command line forwards `--stages-only`. When `params` is provided, it's
    serialized to a temp JSON file under the cache dir and `--params-json
    <path>` is passed to the CLI.

    `clear_cache` (default True) preserves all current behavior. Set False
    for the "rerun stale stages only" path: the cache is left untouched and
    the per-stage cached() check inside `python -m analyze` decides which
    work is actually stale (schema bump, params drift). Cheap when the cache
    is fully fresh; targeted when one stage's sidecar predates a bump.
    """
    # TOCTOU safety: the cooperative scheduler can't switch coroutines
    # between this check and the async-with below because there is no
    # `await` in between. Do NOT introduce one.
    if _analyze_lock.locked():
        yield ndjson({"type": "error", "message": "another analysis is already running", "kind": "lock_busy"})
        return

    async with _analyze_lock:
        proc = None
        params_tmp: Path | None = None
        try:
            cache = _paths.cache_dir() / slug
            cache.mkdir(parents=True, exist_ok=True)
            if clear_cache:
                if any(cache.iterdir()):
                    try:
                        _clear_cache_dir(cache, only_stages=stages_only)
                    except CacheLockedError as e:
                        # Friendly, actionable error — no raw Windows traceback.
                        # Most common cause is the audio source FileResponse not
                        # yet released by the OS, or another app holding the mp3.
                        yield ndjson({
                            "type": "error",
                            "kind": "cache_locked",
                            "message": (
                                f"Couldn't clear the cache: {e.path.name} is in use by another "
                                "process. Pause playback (or close any external player), wait a "
                                "few seconds, and try Reanalyze again."
                            ),
                            "path": str(e.path),
                        })
                        return
                    except ValueError as e:
                        # Unknown stage name — surface as a friendly error
                        yield ndjson({
                            "type": "error",
                            "kind": "invalid_request",
                            "message": str(e),
                        })
                        return
                    yield ndjson({"type": "log", "line": f"cleared cache/{slug}/"})
            else:
                yield ndjson({"type": "log", "line": "rerun-stale: skipping cache clear; pipeline cached() gates per stage"})

            yield ndjson({"type": "phase", "name": "analyze", "status": "start"})

            project_wsl = _to_wsl_path(_paths.project_root())
            src_wsl = _to_wsl_path(source_path)

            extra_args = ""
            if stages_only:
                extra_args += f" --stages-only {shlex.quote(','.join(sorted(stages_only)))}"
            if params is not None:
                # Stage params JSON to a temp file inside the cache dir so it's
                # available to the WSL-side process via the cache mount. Using
                # cache dir (rather than Windows tempfile + WSL path translation)
                # keeps the path inside the project mount and cleanup is easy.
                params_tmp = cache / ".webui_params.json"
                params_tmp.write_text(json.dumps(params))
                params_tmp_wsl = _to_wsl_path(params_tmp)
                extra_args += f" --params-json {shlex.quote(params_tmp_wsl)}"

            script = (
                f"cd {shlex.quote(project_wsl)} && "
                f"source .venv/bin/activate && "
                f"python -u -m analyze {shlex.quote(src_wsl)} "
                f"--stems-quality {shlex.quote(quality)}{extra_args} 2>&1"
            )
            yield ndjson({"type": "log", "line": f"stems quality: {quality}"})
            if stages_only:
                yield ndjson({"type": "log", "line": f"stages-only: {','.join(sorted(stages_only))}"})
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
            # Clean up the params temp file if it was written.
            if params_tmp is not None and params_tmp.exists():
                try:
                    params_tmp.unlink()
                except (PermissionError, FileNotFoundError):
                    pass
            # Lock-leak fix: if the generator exits while proc is still alive
            # (e.g. ASGI client-disconnect raises out of `yield`), kill it so
            # the lock release tracks the work, not the response.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except (ProcessLookupError, PermissionError):
                    pass


# Slug algorithm — mirrors analyze.cache.slug_for exactly so the webui can
# compute slugs without importing the analyze package (which drags in ML
# dependencies unavailable in the Windows webui environment).
_SEP_RUN = re.compile(r"[^a-z0-9]+")


def _slug_for_stem(stem: str) -> str:
    """Convert a bare filename stem to a cache slug (same as analyze.cache.slug_for)."""
    s = stem.lower()
    out: list[str] = []
    last = 0
    for m in _SEP_RUN.finditer(s):
        out.append(s[last : m.start()])
        out.append("-" if "-" in m.group() else "_")
        last = m.end()
    out.append(s[last:])
    return "".join(out).strip("-_")


def slug_for_filename(filename: str) -> str:
    """Compute the cache slug for a source filename.

    Synthesizes a .mp3 suffix if the input has no extension or a non-audio
    one, so Path.stem strips the right thing. Without this, titles
    containing dots ("Track 1.0 (Live)") would slug to the wrong stem.
    """
    p = Path(filename)
    if p.suffix.lower() not in {".mp3", ".wav", ".flac"}:
        # Strip the non-audio suffix and synthesize .mp3 so .stem captures
        # the full intended title without the original extension leaking in.
        p = Path(p.stem + ".mp3")
    return _slug_for_stem(p.stem)


def find_first_free_slug(base: str) -> str:
    """Return the first <base>-N (N>=2) that is not present under cache/."""
    cache_root = _paths.cache_dir()
    n = 2
    while (cache_root / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


_STALE_PATTERNS = (
    re.compile(r"HTTP Error 403: Forbidden"),
    re.compile(r"Your yt-dlp version \([^)]+\) is older than 90 days"),
    re.compile(r"Sign in to confirm you're not a bot"),
    re.compile(r"Requested format is not available"),
)
# Combo trigger: "missing a url" warning AND a download-failure line both present.
_MISSING_URL = re.compile(r"formats have been skipped as they are missing a url")
# Tightened: must explicitly mention a download failure (in either order),
# not just any ERROR line containing "failed". Otherwise unrelated errors
# like "ERROR: Failed to extract any player response" would combine with
# the SABR missing-url warning to falsely flag staleness.
_DL_FAIL = re.compile(r"(?im)^ERROR.*(download.*fail|fail.*download)")

# YouTube/yt-dlp configuration. Both consumed by youtube_metadata_slug + the
# upcoming youtube_download helper.
#
#   MUSIQ_YTDLP_BIN  — full path to yt-dlp.exe (default: "yt-dlp" on PATH).
#   MUSIQ_YT_OUT_DIR — directory for downloaded source MP3s (default:
#                      ~/Videos/musiq-lab on Windows, ~/Music/musiq-lab elsewhere).
#
# Both default to portable values; override via env when the user has a
# canonical local layout. Raw-string env values are accepted verbatim, so
# Windows paths with backslashes and `$` chars pass through unmodified —
# argv-list spawn (no shell) keeps `$` literal.
def _default_yt_out_dir() -> Path:
    home = Path.home()
    base = home / "Videos" if (home / "Videos").is_dir() else home / "Music"
    return base / "musiq-lab"


YT_DLP_BIN = os.environ.get("MUSIQ_YTDLP_BIN", "yt-dlp")
YT_OUT_DIR = Path(os.environ.get("MUSIQ_YT_OUT_DIR") or _default_yt_out_dir())


def is_stale_ytdlp_stderr(stderr: str) -> bool:
    """Return True iff `stderr` matches a documented stale-yt-dlp trigger.

    Triggers are sourced from CLAUDE.md "Auto-update on the spot" section:
      - HTTP 403
      - "older than 90 days" version banner
      - "Sign in to confirm" bot challenge
      - "Requested format is not available"
      - "missing a url" SABR warning + a download-failure line both present
    """
    if not stderr:
        return False
    for pat in _STALE_PATTERNS:
        if pat.search(stderr):
            return True
    if _MISSING_URL.search(stderr) and _DL_FAIL.search(stderr):
        return True
    return False


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
            stdout=asyncio.subprocess.DEVNULL,
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


async def youtube_metadata_slug(url: str, *, update_first: bool = False) -> dict:
    """Fetch the predicted '<title>-<id>' from yt-dlp without downloading.

    Returns one of:
      {"ok": True, "predicted_slug": "<slug>"}
      {"ok": False, "kind": "ytdlp_stale", "stderr": "..."}
      {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "..."}

    `update_first=True` runs `yt-dlp -U` before the metadata fetch (used when
    the modal retries after a previous stale-yt-dlp surface).
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

    stripped = stdout.decode("utf-8", errors="replace").strip()
    line = stripped.splitlines()[0] if stripped else ""
    if not line:
        return {"ok": False, "kind": "ytdlp_metadata_failed", "stderr": "yt-dlp produced no output"}

    return {"ok": True, "predicted_slug": slug_for_filename(line + ".mp3")}


_PROGRESS_RE = re.compile(
    r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+\S+\s+at\s+(\S+)\s+ETA\s+(\d+):(\d+):(\d+)"
)

# YouTube video IDs are 11 chars from the base64-url-safe alphabet. We pull
# them from the URL so we can locate the actual on-disk file after download —
# yt-dlp's printed `after_move:filepath` mangles characters its console
# encoding can't represent (e.g. fullwidth pipe ｜ U+FF5C, used as the NTFS
# substitute for "|", prints as a regular space) so the printed path can
# differ from the on-disk path. The 11-char ID is the stable suffix in our
# `%(title)s-%(id)s.%(ext)s` template, so we glob by it after success.
_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})(?:[?&#]|$)")


def _extract_youtube_id(url: str) -> str | None:
    """Return the 11-char YouTube video ID from common URL forms, or None."""
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def parse_ytdlp_progress(line: str) -> dict | None:
    """Parse a yt-dlp progress line into structured fields.

    Returns {pct: float, speed: str, eta_sec: int} for matching lines,
    None otherwise (including empty input). Format is stable when
    yt-dlp is invoked with --newline (one update per line, no \\r overwrite).
    """
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

    Phase + log + progress events stream throughout. On success the LAST
    event is {"type":"downloaded","path":"<final mp3>"}. On failure the
    last event is {"type":"error","kind":"ytdlp_stale"|"ytdlp_download_failed",...}.
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
        await up.wait()  # best-effort: ignore rc — download attempt below will surface any real failure

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
        # Tightened detection: filter out WARNING/ERROR prefixes and URL-bearing
        # lines so a stray non-bracketed warning containing https://... cannot
        # clobber final_path. The after_move:filepath emission is always a bare
        # absolute filesystem path, so excluding "://" is safe.
        if (
            line
            and not line.startswith("[")
            and not line.startswith("WARNING")
            and not line.startswith("ERROR")
            and "://" not in line
            and (line.endswith(".mp3") or "\\" in line or "/" in line)
        ):
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

    # yt-dlp's printed `after_move:filepath` is unreliable when the title
    # contains chars its console encoding can't represent (e.g. ｜ U+FF5C,
    # the NTFS substitute for the forbidden "|", prints as a regular space).
    # The on-disk filename uses the substitute char; the printed path does
    # not. Glob by the 11-char YouTube ID (stable suffix in our output
    # template) to recover the actual file.
    yt_id = _extract_youtube_id(url)
    if yt_id:
        ext = Path(final_path).suffix or ".mp3"
        candidates = sorted(
            YT_OUT_DIR.glob(f"*-{yt_id}{ext}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            actual = str(candidates[0])
            if actual != final_path:
                yield ndjson({"type": "log", "line": f"resolved on-disk path via id glob: {actual}"})
                final_path = actual

    yield ndjson({"type": "phase", "name": "download", "status": "end"})
    yield ndjson({"type": "downloaded", "path": final_path})
