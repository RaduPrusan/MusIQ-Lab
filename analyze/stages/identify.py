"""Stage: AcoustID/MusicBrainz identification of the source MP3.

Output: cache_dir/identify.json with either
    {"identified": true, "mbid_recording": "...", "title": "...",
     "artist": "...", "release": "...", "year": 2001, "isrc": "...",
     "mbid_artist": "...", "mbid_release_group": "...",
     "acoustid_score": 0.94, "acoustid_id": "..."}
or
    {"identified": false, "reason": "..."}

The stage is OPTIONAL. Any failure (binary missing, API down, no API
key, low score, MB 404) writes the {identified: false, reason} variant
rather than raising — same pattern as analyze/stages/drums.py.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from analyze import sidecar
from analyze.clients import acoustid as acoustid_client
from analyze.clients import musicbrainz as musicbrainz_client
from analyze.text import slug_parser

CANONICAL = "identify.json"
SCHEMA_VERSION = 5
DEFAULT_PARAMS: dict = {
    "silence_strip_enabled": True,
    "silence_strip_threshold_db": -50,
    "silence_strip_min_duration_sec": 0.3,
    "silence_strip_gate_sec": 0.3,
    "fallback_enabled": True,
    # Round 5: lowered from 0.85 → 0.75 to recover commercial tracks where
    # the title carries minor capitalization / wording deltas vs MB
    # ("Original Mix", "(Single Version)"). The 0.03 duration-variance
    # tightening (from 0.05) acts as a compensating guard.
    "fallback_min_title_similarity": 0.75,
    "fallback_max_duration_variance": 0.03,
    # Round 5 (Item 1) — artist-plausibility gate on the canonical
    # AcoustID path. Catches AcoustID DB integrity errors where the
    # wrong MBID is linked to a fingerprint (e.g., the gorillaz silent-
    # running track being identified as DJ Allan McLoud).
    "artist_plausibility_min_similarity": 0.30,
    "artist_plausibility_title_fallback_threshold": 0.30,
}

_FPCALC = Path(__file__).resolve().parents[1] / "vendor" / "chromaprint" / "fpcalc"

log = logging.getLogger(__name__)


class FpcalcError(RuntimeError):
    """Raised when fpcalc output is malformed (missing keys / not JSON)."""


def cached(cache_dir: Path, **params) -> bool:
    if not (cache_dir / CANONICAL).exists():
        return False
    p = {**DEFAULT_PARAMS, **params}
    # Legacy bridge: if identify.json exists with identified=true but there is
    # no sidecar (pre-sidecar caches), synthesize one at the current schema
    # version so we don't re-query AcoustID on every analyze run. This is
    # safe because identified=true caches are protected by _preserve_or_write
    # from being demoted — synthesizing the sidecar simply records "we accept
    # this prior identification under the current params".
    if not sidecar.matches(cache_dir, "identify", p, expected_schema_version=SCHEMA_VERSION):
        try:
            existing = json.loads((cache_dir / CANONICAL).read_text())
        except (json.JSONDecodeError, OSError):
            existing = None
        if existing and existing.get("identified"):
            sidecar.write(cache_dir, "identify", p, schema_version=SCHEMA_VERSION)
            return True
        return False
    return True


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)")


def _detect_leading_silence(
    mp3: Path, threshold_db: int, min_duration_sec: float
) -> float:
    """Probe the head of ``mp3`` with ``ffmpeg silencedetect`` and return
    the first ``silence_end`` timestamp if it falls inside the first 30s
    (i.e. is a leading-silence event, not an internal gap). Returns 0.0
    when no event is reported or the event is past the 30s anchor.

    Any subprocess failure (FileNotFoundError, nonzero exit, timeout) is
    re-raised; the caller in ``run()`` catches via a broad ``except`` and
    falls back to the raw MP3.

    The ``-t 30`` input-duration limit is load-bearing: silencedetect does
    NOT exit on the first event, so without ``-t`` ffmpeg reads the whole
    file (~12-20s wall time per track). With ``-t 30`` the probe is ~0.3s.
    """
    cmd = [
        "ffmpeg",
        "-t", "30",
        "-i", str(mp3),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration_sec}",
        "-f", "null", "-",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=10, check=False,
    )
    # ffmpeg returns 0 even with "silence_end" events; only check for genuine
    # failures (nonzero exit). Bytes vs str: text=True gives str.
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr,
        )
    m = _SILENCE_END_RE.search(result.stderr or "")
    if not m:
        return 0.0
    try:
        val = float(m.group(1))
    except (TypeError, ValueError):
        return 0.0
    if val > 30.0:
        return 0.0
    return val


def _strip_leading_silence(
    mp3: Path, threshold_db: int, min_duration_sec: float
) -> Path:
    """Write a temp WAV with leading silence stripped via
    ``ffmpeg silenceremove`` and return its path. Caller owns deletion.

    Temp file is placed in the same directory as ``mp3`` (avoids NTFS
    cross-volume issues for subsequent rename/replace operations, though
    we only consume the file here). The ``-t 150`` input-duration limit
    caps decode at 150s — fpcalc only reads 120s; 30s strip headroom +
    120s for the fingerprint = 150s. Without it, we'd decode and re-encode
    the entire (potentially 5+ minute) MP3 for no benefit.
    """
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".wav", dir=str(mp3.parent))
    os.close(tmp_fd)
    tmp = Path(tmp_name)
    cmd = [
        "ffmpeg",
        "-t", "150",
        "-y",
        "-i", str(mp3),
        "-af",
        f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:"
        f"start_duration={min_duration_sec}:detection=peak",
        "-ar", "44100",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(tmp),
    ]
    try:
        subprocess.run(
            cmd, capture_output=True, check=True, timeout=30,
        )
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _run_fpcalc(mp3: Path) -> dict:
    """Shell out to the vendored fpcalc binary; return {fingerprint, duration}.

    Raises:
      - FileNotFoundError: vendored binary missing
      - subprocess.CalledProcessError / TimeoutExpired: fpcalc nonzero / hang
      - FpcalcError: stdout is not JSON, or missing required keys
    """
    if not _FPCALC.exists():
        raise FileNotFoundError(
            f"fpcalc not vendored at {_FPCALC} — run scripts/install-chromaprint.sh"
        )
    result = subprocess.run(
        [str(_FPCALC), "-json", str(mp3)],
        capture_output=True, text=True, check=True, timeout=60,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise FpcalcError(
            f"fpcalc stdout is not JSON: {e}; first 200 chars: {result.stdout[:200]!r}"
        ) from e
    if "fingerprint" not in data or "duration" not in data:
        raise FpcalcError(
            f"fpcalc JSON missing required keys; got keys={sorted(data.keys())}"
        )
    return {"fingerprint": data["fingerprint"], "duration": float(data["duration"])}


def _artist_plausibility_check(
    mp3: Path,
    fp_duration_sec: float,
    identified_artist: str | None,
    identified_title: str | None,
    *,
    min_similarity: float,
    title_fallback_threshold: float,
) -> tuple[bool, dict]:
    """Round 5 (Item 1): compare slug-derived artist vs the AcoustID-
    identified artist. Returns ``(passed, diag)``.

    ``diag`` is always populated (used to write diagnostic fields into
    identify.json when we demote a canonical match). Keys:
      ``acoustid_proposed_artist`` — identified_artist (None-safe)
      ``slug_derived_artist`` — what the slug parser produced (may be "")
      ``acoustid_artist_similarity`` — float in [0, 1]
      ``mode`` — ``"artist"`` (had a slug-derived artist) or
                  ``"title_fallback"`` (no slug artist; compared title forms)

    Two modes:
      1. **Artist mode** — when slug-derived artist is non-empty: compare
         normalized slug artist vs normalized identified artist directly.
         Pass if ratio ≥ ``min_similarity`` (default 0.50).
      2. **Title-fallback mode** — when slug-derived artist is empty (e.g.
         the ``charlie_puth_attention`` slug with no `-` separator): compare
         the slug-derived title vs "<identified artist> <identified title>".
         Pass if ratio ≥ ``title_fallback_threshold`` (default 0.30). This
         catches the gorillaz-style case where the slug carries the artist
         in the title field but the identified artist is wholly unrelated.

    Any exception is caught and treated as PASS (fail-open) — the gate is
    a quality guard, not a hard requirement, and we never want a slug-
    parse hiccup to drop an otherwise-valid identification.
    """
    diag: dict = {
        "acoustid_proposed_artist": identified_artist,
        "slug_derived_artist": "",
        "acoustid_artist_similarity": None,
        "mode": "artist",
    }
    if not identified_artist:
        # Nothing to compare; pass (cannot judge).
        return True, diag
    try:
        ident = slug_parser.identify_track_from_slug(
            mp3, duration_sec=fp_duration_sec,
        )
        slug_artist = (ident.get("artist") or "").strip()
        slug_title = (ident.get("title") or "").strip()
        diag["slug_derived_artist"] = slug_artist

        norm_id_artist = musicbrainz_client._normalize_for_search(
            identified_artist
        ).lower()

        if slug_artist:
            norm_slug_artist = musicbrainz_client._normalize_for_search(
                slug_artist
            ).lower()
            sim = difflib.SequenceMatcher(
                None, norm_slug_artist, norm_id_artist,
            ).ratio()
            diag["acoustid_artist_similarity"] = round(sim, 4)
            diag["mode"] = "artist"
            if sim >= min_similarity:
                return True, diag
            # Substring rescue: the slug parser may have mis-split a
            # compilation prefix as the artist (e.g. `buddha-bar-ali_kuru_...`
            # → artist="Buddha", but the actual artist "Ali Kuru" is in the
            # title portion). If the AcoustID-proposed artist appears as a
            # substring of the full slug stem, the slug DOES support that
            # artist — pass. Require length ≥ 4 to avoid short-name false
            # rescues (a slug containing "Dj" wouldn't rescue every artist
            # named "DJ Anything").
            norm_id_artist_stripped = norm_id_artist.strip()
            if len(norm_id_artist_stripped) >= 4:
                full_slug_norm = musicbrainz_client._normalize_for_search(
                    f"{slug_artist} {slug_title}".strip()
                ).lower()
                if norm_id_artist_stripped in full_slug_norm:
                    diag["mode"] = "artist_substring_rescue"
                    return True, diag
            return False, diag

        # Title-fallback mode: no slug-derived artist available.
        if not slug_title:
            return True, diag  # nothing to compare against — pass
        slug_title_clean = slug_parser.clean_title(slug_title) or slug_title
        norm_slug_title = musicbrainz_client._normalize_for_search(
            slug_title_clean
        ).lower()
        norm_id_title = musicbrainz_client._normalize_for_search(
            identified_title or ""
        ).lower()
        target_combined = (
            f"{norm_id_artist} {norm_id_title}".strip()
        )
        sim = difflib.SequenceMatcher(
            None, norm_slug_title, target_combined,
        ).ratio()
        diag["acoustid_artist_similarity"] = round(sim, 4)
        diag["mode"] = "title_fallback"
        return sim >= title_fallback_threshold, diag
    except Exception as exc:  # noqa: BLE001 — gate must never crash run()
        log.warning(
            "artist-plausibility check raised: %s — treating as pass", exc,
        )
        return True, diag


def _log_outcome(slug: str, *, source: str, score, mbid, reason) -> None:
    """Emit the per-spec §4.1 structured one-liner.

    Valid ``source`` values:
      - ``acoustid``             — raw fingerprint produced the match
      - ``acoustid_stripped``    — leading-silence-stripped fingerprint
                                    produced the match (Round 3 fallback)
      - ``acoustid_unenriched``  — AcoustID matched but MusicBrainz failed
                                    so the on-disk payload is identified=false
                                    while AcoustID itself had a result
      - ``fallback``             — MB text-search produced the match after
                                    AcoustID returned no usable result
                                    (Round 4 fallback)
      - ``none``                 — neither path produced an identification
                                    (fpcalc failed, AcoustID error, or both
                                    raw + stripped lookups returned None)

    Format: ``identify: slug=<slug> source=<one-of-above> score=<float|—> mbid=<mbid|—> reason=<string|->``.
    """
    def _fmt(v):
        return "—" if v is None or v == "" else v
    log.info(
        "identify: slug=%s source=%s score=%s mbid=%s reason=%s",
        slug, source, _fmt(score), _fmt(mbid), _fmt(reason),
    )


def _cache_raw_acoustid(cache_dir: Path, fingerprint: str, raw: dict) -> None:
    """Best-effort write of <cache_dir>/.acoustid_raw.json for offline replay."""
    try:
        fp_hash = hashlib.sha1(
            fingerprint.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()[:12]
        payload = {
            "queried_at": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "fingerprint_hash": fp_hash,
            "response": raw,
        }
        path = cache_dir / ".acoustid_raw.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, path)
    except Exception as e:  # pragma: no cover — best-effort, never fail identify
        log.debug("failed to cache raw acoustid response: %s", e)


def _try_mb_recording_lookup_with_retry(mbid: str) -> dict | None:
    """Call ``musicbrainz_client.recording_lookup`` with one retry after a
    1s wait on transient MusicBrainz failures. Returns the metadata dict
    on success or None after both attempts failed.

    Used by both the AcoustID-canonical path and the
    ``acoustid_unenriched`` retry per D1 §7.
    """
    try:
        return musicbrainz_client.recording_lookup(mbid)
    except musicbrainz_client.MusicBrainzError as e:
        log.warning(
            "musicbrainz recording_lookup failed for %s: %s — retrying once after 1s",
            mbid, e,
        )
        time.sleep(1.0)
        try:
            return musicbrainz_client.recording_lookup(mbid)
        except musicbrainz_client.MusicBrainzError as e2:
            log.warning(
                "musicbrainz recording_lookup retry also failed for %s: %s",
                mbid, e2,
            )
            return None


def _attempt_mb_text_search_fallback(
    mp3: Path,
    fp_duration_sec: float,
    params: dict,
    slug: str,
) -> tuple[dict | None, str | None]:
    """Seed MB text-search from the slug / ID3 and return a payload dict
    on success or ``(None, reason)`` on rejection.

    The payload, when non-None, is ready to merge into ``identify.json``:
      ``{identified=True, source=fallback, match_method=mb_text_search,
         mbid_recording, title, artist, album, year, duration_variance_pct,
         title_similarity}``

    Soft-fail: ANY exception inside this function is caught and returned
    as ``(None, "fallback_error: ...")``. Identify.run() must never crash
    because the fallback misbehaved.
    """
    try:
        ident = slug_parser.identify_track_from_slug(mp3, duration_sec=fp_duration_sec)
        artist = ident.get("artist", "") or ""
        title = ident.get("title", "") or ""
        title_seed = slug_parser.clean_title(title) if title else ""
        if not title_seed:
            return None, "fallback_no_match"

        candidates = musicbrainz_client.search_recording(
            artist=artist,
            title=title_seed,
            duration_sec=fp_duration_sec,
        )

        scored, reject_reason = musicbrainz_client.score_candidates(
            candidates,
            fp_duration_sec=fp_duration_sec,
            target_title=title_seed,
            max_duration_variance=params.get("fallback_max_duration_variance", 0.05),
            min_title_similarity=params.get("fallback_min_title_similarity", 0.85),
        )
        if scored is None:
            return None, reject_reason or "fallback_no_match"

        chosen = scored.recording
        chosen_mbid = chosen.get("id")
        if not chosen_mbid:
            return None, "fallback_no_match"

        # Enrich with release metadata (album + year). Soft-fail: if the
        # detail lookup fails we keep the candidate's own data.
        try:
            release_meta = musicbrainz_client.lookup_release_metadata(chosen_mbid)
        except musicbrainz_client.MusicBrainzError as e:
            log.warning(
                "fallback: lookup_release_metadata failed for %s: %s "
                "— using search-result fields",
                chosen_mbid, e,
            )
            release_meta = None

        cand_artist_credit = chosen.get("artist-credit") or []
        cand_artist = (
            cand_artist_credit[0].get("name")
            if cand_artist_credit and isinstance(cand_artist_credit[0], dict)
            else None
        )
        payload: dict = {
            "identified": True,
            "source": "fallback",
            "match_method": "mb_text_search",
            "mbid_recording": chosen_mbid,
            "title": chosen.get("title"),
            "artist": cand_artist,
            "album": None,
            "year": None,
            "duration_variance_pct": round(scored.dur_variance, 4),
            "title_similarity": round(scored.title_sim, 4),
        }
        if release_meta:
            # release_meta carries title/artist too, but the search hit's
            # title is the one we similarity-scored against — preserve it.
            payload["album"] = release_meta.get("release")
            payload["year"] = release_meta.get("year")
            payload["mbid_artist"] = release_meta.get("mbid_artist")
            payload["mbid_release_group"] = release_meta.get("mbid_release_group")
            payload["isrc"] = release_meta.get("isrc")
            if not payload["artist"] and release_meta.get("artist"):
                payload["artist"] = release_meta["artist"]
        return payload, None
    except Exception as exc:  # noqa: BLE001 — fallback must never crash run()
        log.warning(
            "fallback: MB text-search raised for %s: %s", slug, exc,
        )
        return None, f"fallback_error: {type(exc).__name__}: {exc}"


def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    slug = cache_dir.name

    # 1. Preprocessing (silence-strip). Soft-fails into strip_tmp=None so
    # downstream code falls back to the raw MP3 unconditionally.
    strip_tmp: Path | None = None
    if p.get("silence_strip_enabled", True):
        try:
            leading_sec = _detect_leading_silence(
                mp3,
                threshold_db=p.get("silence_strip_threshold_db", -50),
                min_duration_sec=p.get("silence_strip_min_duration_sec", 0.3),
            )
            if leading_sec > p.get("silence_strip_gate_sec", 0.3):
                strip_tmp = _strip_leading_silence(
                    mp3,
                    threshold_db=p.get("silence_strip_threshold_db", -50),
                    min_duration_sec=p.get("silence_strip_min_duration_sec", 0.3),
                )
                log.debug(
                    "silence-strip: %s stripped %.2fs", slug, leading_sec,
                )
        except Exception as exc:  # noqa: BLE001 — preprocessing is an enhancement
            log.warning(
                "silence-strip preprocessing failed for %s, using raw: %s",
                slug, exc,
            )
            strip_tmp = None

    # 2. Outer try/finally guarantees strip_tmp is removed regardless of
    # which inner branch returns early or raises.
    try:
        # 2a. fpcalc on raw MP3.
        try:
            fp_raw = _run_fpcalc(mp3)
        except (FileNotFoundError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired, FpcalcError) as e:
            stderr_tail = ""
            raw_stderr = getattr(e, "stderr", None)
            if raw_stderr:
                if isinstance(raw_stderr, bytes):
                    stderr_tail = raw_stderr.decode("utf-8", "replace")[-200:]
                else:
                    stderr_tail = str(raw_stderr)[-200:]
            reason = f"fpcalc failed: {type(e).__name__}: {e}"
            if stderr_tail:
                reason = f"{reason} | stderr_tail={stderr_tail!r}"
            result = _preserve_or_write(
                cache_dir, {"identified": False, "source": "none", "reason": reason}, p
            )
            _log_outcome(slug, source="none", score=None, mbid=None, reason=result.get("reason"))
            return result

        # 2b. AcoustID lookup on raw fingerprint — use the reason-aware
        # variant so we can drive the R4 fallback trigger off the
        # discriminator (no_results vs all_unlinked vs below_threshold).
        try:
            raw_match, raw_reason = acoustid_client.lookup_with_reason(
                fp_raw["fingerprint"], fp_raw["duration"],
            )
        except acoustid_client.AcoustIDError as e:
            result = _preserve_or_write(
                cache_dir, {
                    "identified": False,
                    "source": "none",
                    "reason": f"AcoustID error: {e}",
                    "match_method": None,
                }, p,
            )
            _log_outcome(
                slug, source="none", score=None, mbid=None,
                reason=result.get("reason"),
            )
            return result

        # Always cache the raw AcoustID JSON for forensics — even on
        # empty / below-threshold / unlinked outcomes (R3 inherited debt).
        if raw_match is not None and raw_match.get("raw_response") is not None:
            _cache_raw_acoustid(
                cache_dir, fp_raw["fingerprint"], raw_match["raw_response"],
            )
        # Strip internal fields before downstream use; ``_empty`` is only a
        # signal carrier from acoustid_client.
        if raw_match is not None and raw_match.get("_empty"):
            match = None
        else:
            match = raw_match
            if match is not None:
                match = {k: v for k, v in match.items() if k != "raw_response"}

        last_acoustid_reason = raw_reason

        # 2c. Stripped fingerprint fallback — only fires when raw returned
        # None AND preprocessing actually produced a temp WAV. Guard against
        # short post-strip durations; fpcalc accuracy + AcoustID DB rejects
        # fingerprints under ~30s.
        if match is None and strip_tmp is not None:
            try:
                fp_stripped = _run_fpcalc(strip_tmp)
                if fp_stripped["duration"] >= 30.0:
                    stripped_match, stripped_reason = acoustid_client.lookup_with_reason(
                        fp_stripped["fingerprint"], fp_stripped["duration"],
                    )
                    if stripped_match is not None and stripped_match.get("raw_response") is not None:
                        _cache_raw_acoustid(
                            cache_dir,
                            fp_stripped["fingerprint"],
                            stripped_match["raw_response"],
                        )
                    if stripped_match is not None and not stripped_match.get("_empty"):
                        match = {
                            k: v for k, v in stripped_match.items()
                            if k != "raw_response"
                        }
                        # Internal flag: surfaces to _log_outcome below as
                        # source="acoustid_stripped" so operators can see
                        # which path produced the identification. Stripped
                        # before write so it doesn't leak into identify.json.
                        match["_fingerprint_source"] = "stripped"
                    else:
                        # The stripped probe gives us a fresher reason than
                        # the raw one (which we'd have to fall back to MB
                        # text-search regardless).
                        last_acoustid_reason = stripped_reason or last_acoustid_reason
                else:
                    log.warning(
                        "silence-strip fallback: post-strip duration %.2fs "
                        "below 30s for %s; skipping stripped AcoustID lookup",
                        fp_stripped["duration"], slug,
                    )
            except Exception as exc:  # noqa: BLE001 — fallback is best-effort
                log.warning(
                    "silence-strip AcoustID fallback failed for %s: %s",
                    slug, exc,
                )
                match = None

        # 2d. AcoustID returned a usable match — proceed to MB enrichment.
        if match is not None:
            # Extract the internal fingerprint-source flag before MB lookup so
            # nothing downstream sees it (it must not appear in identify.json).
            fingerprint_source = match.pop("_fingerprint_source", "raw")
            acoustid_source = (
                "acoustid_stripped" if fingerprint_source == "stripped" else "acoustid"
            )

            mb = _try_mb_recording_lookup_with_retry(match["mbid_recording"])
            if mb is None:
                # MB lookup (incl. retry) failed — persist as
                # acoustid_unenriched. Do NOT fall through to text-search:
                # we already have a confidence-validated MBID.
                result = _preserve_or_write(
                    cache_dir, {
                        "identified": False,
                        "source": "acoustid_unenriched",
                        "match_method": "mb_direct",
                        "reason": "MusicBrainz error after retry",
                        "mbid_recording": match.get("mbid_recording"),
                        "acoustid_score": match.get("acoustid_score"),
                        "acoustid_id": match.get("acoustid_id"),
                    }, p,
                )
                _log_outcome(
                    slug, source="acoustid_unenriched",
                    score=match.get("acoustid_score"),
                    mbid=match.get("mbid_recording"),
                    reason=result.get("reason"),
                )
                return result

            # Round 5 (Item 1): artist-plausibility sanity check on the
            # CANONICAL AcoustID path (raw fingerprint only — stripped
            # fingerprints are rare in practice and have additional silence-
            # strip provenance, skip per R5 spec). When the slug-derived
            # artist diverges sharply from the identified artist, the
            # AcoustID DB likely has the wrong MBID linked to this
            # fingerprint (e.g., gorillaz silent-running → DJ Allan McLoud).
            # Demote to identified=false rather than silently swapping to
            # fallback — fallback could just as easily be wrong.
            if fingerprint_source == "raw":
                passed, diag = _artist_plausibility_check(
                    mp3,
                    fp_raw["duration"],
                    identified_artist=mb.get("artist"),
                    identified_title=mb.get("title"),
                    min_similarity=p.get(
                        "artist_plausibility_min_similarity", 0.50,
                    ),
                    title_fallback_threshold=p.get(
                        "artist_plausibility_title_fallback_threshold", 0.30,
                    ),
                )
                if not passed:
                    log.warning(
                        "artist-plausibility gate REJECTED canonical match "
                        "for %s: identified=%r vs slug=%r sim=%s (mode=%s)",
                        slug, diag.get("acoustid_proposed_artist"),
                        diag.get("slug_derived_artist"),
                        diag.get("acoustid_artist_similarity"),
                        diag.get("mode"),
                    )
                    reject_payload = {
                        "identified": False,
                        "source": "none",
                        "match_method": None,
                        "reason": "acoustid_artist_mismatch",
                        "acoustid_proposed_artist": diag.get(
                            "acoustid_proposed_artist"
                        ),
                        "slug_derived_artist": diag.get(
                            "slug_derived_artist"
                        ),
                        "acoustid_artist_similarity": diag.get(
                            "acoustid_artist_similarity"
                        ),
                    }
                    # IMPORTANT: bypass _preserve_or_write here. The R5
                    # artist-plausibility rejection is NOT a transient error
                    # (which is what _preserve_or_write guards against — it
                    # exists to stop AcoustID/MB 5xx outages from demoting a
                    # cached identification). This rejection is a deliberate
                    # integrity decision: the AcoustID database has the wrong
                    # MBID linked to this fingerprint, and the prior cached
                    # "identified=true" was wrong. Use the direct _write so
                    # the existing wrong payload is overwritten.
                    _write(cache_dir, reject_payload, p)
                    _log_outcome(
                        slug, source="none",
                        score=match.get("acoustid_score"),
                        mbid=match.get("mbid_recording"),
                        reason=reject_payload["reason"],
                    )
                    return reject_payload

            payload = {
                "identified": True,
                "source": acoustid_source,
                "match_method": (
                    "chromaprint_stripped" if fingerprint_source == "stripped"
                    else "chromaprint"
                ),
                **match,
                **mb,
            }
            result = _preserve_or_write(cache_dir, payload, p)
            _log_outcome(
                slug,
                source=acoustid_source if result.get("identified") else "none",
                score=result.get("acoustid_score"),
                mbid=result.get("mbid_recording"),
                reason=result.get("reason"),
            )
            return result

        # 2e. AcoustID produced nothing. Decide whether to fire the MB
        # text-search fallback (R4). Trigger ONLY on no_results /
        # all_unlinked per Blocker B. The below_threshold band is
        # empirically empty on this corpus (Blocker B §3) — defer.
        fallback_trigger = last_acoustid_reason in (
            acoustid_client.REASON_NO_RESULTS,
            acoustid_client.REASON_ALL_UNLINKED,
        )

        if p.get("fallback_enabled", True) and fallback_trigger:
            fb_payload, fb_reason = _attempt_mb_text_search_fallback(
                mp3, fp_raw["duration"], p, slug,
            )
            if fb_payload is not None:
                result = _preserve_or_write(cache_dir, fb_payload, p)
                _log_outcome(
                    slug, source="fallback",
                    score=None,
                    mbid=result.get("mbid_recording"),
                    reason=result.get("reason"),
                )
                return result
            # Fallback failed — persist with the fallback-specific reason
            # so the operator can see why (no_match / ambiguous / error).
            result = _preserve_or_write(
                cache_dir, {
                    "identified": False,
                    "source": "none",
                    "match_method": None,
                    "reason": fb_reason or "fallback_no_match",
                }, p,
            )
            _log_outcome(
                slug, source="none", score=None, mbid=None,
                reason=result.get("reason"),
            )
            return result

        # No fallback (disabled, or AcoustID returned below_threshold which
        # is out-of-scope for v1). Persist the disambiguated AcoustID reason.
        result = _preserve_or_write(
            cache_dir, {
                "identified": False,
                "source": "none",
                "match_method": None,
                "reason": last_acoustid_reason or "acoustid_no_results",
            }, p,
        )
        _log_outcome(
            slug, source="none", score=None, mbid=None,
            reason=result.get("reason"),
        )
        return result
    finally:
        if strip_tmp is not None:
            try:
                strip_tmp.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover — best-effort cleanup
                log.debug("failed to unlink strip_tmp %s: %s", strip_tmp, exc)


def _atomic_write_text(path: Path, text: str) -> None:
    """Same-dir tmp + ``os.replace`` for atomic crash-safe writes.

    Same-directory placement is REQUIRED on NTFS: ``os.replace`` across
    volumes raises ``OSError: [WinError 17]``.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _preserve_or_write(cache_dir: Path, new_payload: dict, params: dict) -> dict:
    """Write new_payload to identify.json, but never demote a cached
    identified=True to identified=False. Refreshes the sidecar either way
    so cached() reports valid. Returns whichever payload is now on disk.

    Why: AcoustID/MusicBrainz outages serve transient HTTP 5xx responses
    that would otherwise overwrite a previously-good identification with
    a {identified: false, reason: "HTTP 503"} stub. Even non-transient
    "no match above threshold" outcomes shouldn't silently demote a known
    canonical title — if the user really wants to reset, --force does it.

    Writes are atomic (same-dir tmp + os.replace) so a crash mid-write
    cannot leave identify.json half-written.
    """
    path = cache_dir / CANONICAL
    if not new_payload.get("identified") and path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = None
        if existing and existing.get("identified"):
            sidecar.write(cache_dir, "identify", params, schema_version=SCHEMA_VERSION)
            return existing
    _atomic_write_text(path, json.dumps(new_payload, indent=2))
    sidecar.write(cache_dir, "identify", params, schema_version=SCHEMA_VERSION)
    return new_payload


def _write(cache_dir: Path, payload: dict, params: dict) -> None:
    """Direct write — bypasses preservation. Kept for callers that need
    to force a payload regardless of existing state (e.g. tests, --force
    flows that already cleared the cache)."""
    _atomic_write_text(cache_dir / CANONICAL, json.dumps(payload, indent=2))
    sidecar.write(cache_dir, "identify", params, schema_version=SCHEMA_VERSION)
