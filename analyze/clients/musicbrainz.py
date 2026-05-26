"""MusicBrainz Web Service v2 client (read-only recording lookups).

Docs: https://musicbrainz.org/doc/MusicBrainz_API
Rate limit: 1 req/s with a meaningful User-Agent. We respect both; the
1 req/s gate is enforced via a module-level last-call timestamp so the
caller doesn't have to think about it.

Round 4 added:
  - ``search_recording(artist, title, duration_sec)`` — MB Lucene query
    used by the identify stage's text-search fallback when AcoustID
    fails. Returns up to ``limit`` candidate dicts.
  - ``score_candidates(...)`` — scores candidates by title similarity +
    duration variance; rejects below-threshold and ambiguous top-2.
  - ``lookup_release_metadata(mbid)`` — fetches album/year for a known
    recording MBID, picking the earliest release.

All three share the same 1 req/s gate.
"""
from __future__ import annotations

import difflib
import threading
import time
import unicodedata
from typing import Optional

import httpx

from analyze import keys

ENDPOINT = "https://musicbrainz.org/ws/2/recording"
SEARCH_ENDPOINT = "https://musicbrainz.org/ws/2/recording/"
MIN_INTERVAL_SEC = 1.0
_last_call: float = 0.0
_lock = threading.Lock()


class MusicBrainzError(RuntimeError):
    pass


def _gate() -> None:
    global _last_call
    with _lock:
        now = time.monotonic()
        wait = MIN_INTERVAL_SEC - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def recording_lookup(mbid: str, *, timeout_sec: float = 10.0) -> dict:
    """Look up a recording by MBID and extract the fields we care about.

    Returns: ``{"mbid_recording", "title", "artist", "mbid_artist",
    "release", "mbid_release_group", "year", "isrc"}``. Missing optional
    fields are None.

    Raises MusicBrainzError on non-200.
    """
    _gate()
    params = {"inc": "artist-credits+releases+release-groups+isrcs", "fmt": "json"}
    headers = {"User-Agent": keys.get_user_agent()}
    url = f"{ENDPOINT}/{mbid}"
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        raise MusicBrainzError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()

    credits = data.get("artist-credit") or []
    first_artist = credits[0]["artist"] if credits else None
    releases = data.get("releases") or []
    first_release = releases[0] if releases else None
    rg = (first_release or {}).get("release-group") or {}
    isrcs = data.get("isrcs") or []
    first_release_date = data.get("first-release-date") or rg.get("first-release-date") or ""
    year = int(first_release_date[:4]) if first_release_date[:4].isdigit() else None

    return {
        "mbid_recording": data.get("id", mbid),
        "title": data.get("title"),
        "artist": first_artist["name"] if first_artist else None,
        "mbid_artist": first_artist["id"] if first_artist else None,
        "release": first_release["title"] if first_release else None,
        "mbid_release_group": rg.get("id"),
        "year": year,
        "isrc": isrcs[0] if isrcs else None,
    }


# ---------------------------------------------------------------------------
# Round 4: MB text-search fallback
# ---------------------------------------------------------------------------


def _escape_lucene(text: str) -> str:
    """Escape Lucene reserved characters that confuse MB's parser when they
    appear inside a quoted phrase. MB still accepts most punctuation
    literally, but ``"`` and ``\\`` MUST be escaped. We keep the list
    minimal to avoid over-escaping legitimate apostrophes etc."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _normalize_for_search(s: str) -> str:
    """Round 5: Unicode + smart-quote normalization for MB search + similarity.

    Smart quotes (U+2018/U+2019/U+201C/U+201D) and accented characters
    differ from MB's canonical Lucene-indexed forms. Without normalization,
    a slug-derived title with a curly apostrophe against an MB record with
    a straight apostrophe scores below the title-similarity gate even
    though the underlying strings are semantically identical.

    Pipeline:
      1. NFKD decompose so combining-diacritic codepoints are separable.
      2. Strip combining-mark codepoints (so ``é`` becomes ``e``).
      3. Flatten Unicode quotes / dashes to ASCII equivalents.

    Returned text is suitable as input to both ``_escape_lucene`` (for the
    Lucene query) and ``difflib.SequenceMatcher`` (for similarity scoring).
    """
    if not s:
        return s
    n = unicodedata.normalize("NFKD", s)
    n = "".join(c for c in n if not unicodedata.combining(c))
    # Single quotes / apostrophes
    n = n.replace("‘", "'").replace("’", "'")
    n = n.replace("ʼ", "'")  # modifier letter apostrophe
    # Double quotes
    n = n.replace("“", '"').replace("”", '"')
    # En / em dashes → ASCII hyphen
    n = n.replace("–", "-").replace("—", "-")
    return n


def search_recording(
    artist: Optional[str],
    title: str,
    duration_sec: float,  # noqa: ARG001 — kept for parity / future scoring
    *,
    limit: int = 10,
    timeout_sec: float = 10.0,
) -> list[dict]:
    """Query MB's recording search endpoint with a Lucene phrase query.

    Behavior:
      - If artist is non-empty: ``artist:"<artist>" AND recording:"<title>"``
      - Else (None or empty): ``recording:"<title>"`` — let MB's
        artist-credit matching handle artist extraction at the search
        side. The Round 5 artist-plausibility gate in identify.py is then
        responsible for rejecting wrong-artist matches downstream.
      - GET https://musicbrainz.org/ws/2/recording/?query=...&limit=<N>&fmt=json
      - Honors the 1 req/s gate.
      - Retries once on HTTP 429 (rate-limited) after a 2s sleep.
      - Retries once on HTTP 503 (transient overload) after a 1s sleep.
      - Raises ``MusicBrainzError`` on other non-200 responses.

    Returns the ``recordings`` array (possibly empty). Each entry has
    ``id``, ``score`` (0-100), ``title``, optional ``length`` (ms),
    optional ``artist-credit`` list, optional ``releases``.

    Round 5: ``_normalize_for_search`` is applied to BOTH the artist and
    title strings BEFORE Lucene-escaping so smart quotes / NFKD-decomposable
    accents don't break the index lookup.
    """
    title = _normalize_for_search((title or "").strip())
    if not title:
        return []
    artist = _normalize_for_search((artist or "").strip())

    if artist:
        query = f'artist:"{_escape_lucene(artist)}" AND recording:"{_escape_lucene(title)}"'
    else:
        query = f'recording:"{_escape_lucene(title)}"'

    params = {"query": query, "limit": int(limit), "fmt": "json"}
    headers = {"User-Agent": keys.get_user_agent()}

    def _do_request() -> httpx.Response:
        _gate()
        with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
            return client.get(SEARCH_ENDPOINT, params=params, headers=headers)

    resp = _do_request()
    if resp.status_code == 429:
        # Backoff once; MB doesn't always emit Retry-After, so use a flat 2s.
        time.sleep(2.0)
        resp = _do_request()
    elif resp.status_code == 503:
        time.sleep(1.0)
        resp = _do_request()

    if resp.status_code != 200:
        raise MusicBrainzError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return list(data.get("recordings") or [])


class ScoredCandidate:
    """Return shape for ``score_candidates`` — keeps the chosen recording
    plus the metrics the caller wants to persist (duration variance, title
    similarity). Defined as a small object so callers can dot-access
    without re-deriving them.
    """

    __slots__ = ("recording", "dur_variance", "title_sim")

    def __init__(self, recording: dict, dur_variance: float, title_sim: float):
        self.recording = recording
        self.dur_variance = dur_variance
        self.title_sim = title_sim

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"ScoredCandidate(id={self.recording.get('id')!r}, "
            f"dur_variance={self.dur_variance:.4f}, "
            f"title_sim={self.title_sim:.4f})"
        )


def _candidate_artist_name(rec: dict) -> str:
    """Pluck the first artist-credit name (string) from an MB record, or
    return empty string. Used for fallback similarity scoring when our
    seed title may carry the artist as a prefix (no `-` separator)."""
    credits = rec.get("artist-credit") or []
    if not credits:
        return ""
    first = credits[0]
    if isinstance(first, dict):
        # Two shapes occur: {"name": "..."} OR {"artist": {"name": ...}}
        if isinstance(first.get("name"), str):
            return first["name"]
        artist = first.get("artist")
        if isinstance(artist, dict) and isinstance(artist.get("name"), str):
            return artist["name"]
    return ""


def score_candidates(
    candidates: list[dict],
    fp_duration_sec: float,
    target_title: str,
    *,
    max_duration_variance: float = 0.05,
    min_title_similarity: float = 0.85,
    ambiguity_epsilon: float = 0.02,
) -> tuple[Optional[ScoredCandidate], Optional[str]]:
    """Score MB search candidates and return ``(best, reason)``.

    On a clean win, ``reason`` is None. On rejection, ``best`` is None and
    ``reason`` is one of:
      - ``fallback_no_match`` — no candidate cleared the gates.
      - ``fallback_ambiguous`` — top 2 candidates score within
        ``ambiguity_epsilon`` of each other on the combined
        ``(dur_variance, -title_sim)`` tuple → false-positive risk.

    Scoring (per D1 §3):
      - Reject any candidate with no usable ``length`` (MB hasn't recorded
        a duration — we can't confirm).
      - Reject if ``|cand_dur - fp_dur| / fp_dur > max_duration_variance``.
      - Reject if title similarity < ``min_title_similarity``.
      - Sort the remainder by ``(dur_variance, -title_sim)`` ascending —
        i.e. smallest variance + highest similarity wins.

    Title similarity uses the **maximum** of three comparisons:
      1. target vs rec.title
      2. target vs (artist-credit + " " + rec.title)
      3. target with the artist-prefix stripped vs rec.title
    This handles the Charlie-Puth-style slug where ``_parse_filename``
    returns ``("", "Charlie Puth Attention")`` but MB matches with
    ``title="Attention", artist="Charlie Puth"``.
    """
    if not candidates:
        return None, "fallback_no_match"
    if fp_duration_sec <= 0:
        return None, "fallback_no_match"

    # Round 5: normalize the target title once. Per-rec normalization happens
    # in the loop. SequenceMatcher is sensitive to Unicode form + apostrophe
    # shape, so both sides must be folded identically before comparison.
    target_lc = _normalize_for_search((target_title or "")).lower()
    scored: list[ScoredCandidate] = []
    for rec in candidates:
        length_ms = rec.get("length")
        if not length_ms:
            continue
        try:
            rec_dur = float(length_ms) / 1000.0
        except (TypeError, ValueError):
            continue
        if rec_dur < 1.0:
            continue
        dur_variance = abs(rec_dur - fp_duration_sec) / fp_duration_sec
        if dur_variance > max_duration_variance:
            continue
        rec_title = (rec.get("title") or "").strip()
        if not rec_title:
            continue
        rec_title_lc = _normalize_for_search(rec_title).lower()
        cand_artist_lc = _normalize_for_search(
            _candidate_artist_name(rec)
        ).lower()

        # (1) direct title comparison
        sim_direct = difflib.SequenceMatcher(
            None, target_lc, rec_title_lc,
        ).ratio()
        # (2) "artist title" combined comparison — handles slug forms with
        # no artist/title separator where target carries both.
        sim_combined = 0.0
        if cand_artist_lc:
            combined = f"{cand_artist_lc} {rec_title_lc}"
            sim_combined = difflib.SequenceMatcher(
                None, target_lc, combined,
            ).ratio()
        # (3) target-with-artist-prefix-stripped vs rec.title — also helps
        # the slug case from the opposite direction.
        sim_stripped = 0.0
        if cand_artist_lc and target_lc.startswith(cand_artist_lc):
            stripped = target_lc[len(cand_artist_lc):].strip()
            if stripped:
                sim_stripped = difflib.SequenceMatcher(
                    None, stripped, rec_title_lc,
                ).ratio()
        title_sim = max(sim_direct, sim_combined, sim_stripped)
        if title_sim < min_title_similarity:
            continue
        scored.append(ScoredCandidate(rec, dur_variance, title_sim))

    if not scored:
        return None, "fallback_no_match"

    scored.sort(key=lambda s: (s.dur_variance, -s.title_sim))
    if len(scored) >= 2:
        # Compare combined score magnitudes; "within epsilon" on EITHER axis
        # (dur OR sim) is enough to flag as ambiguous since both gate the
        # match independently.
        top, runner = scored[0], scored[1]
        if (
            abs(top.dur_variance - runner.dur_variance) < ambiguity_epsilon
            and abs(top.title_sim - runner.title_sim) < ambiguity_epsilon
        ):
            return None, "fallback_ambiguous"
    return scored[0], None


def lookup_release_metadata(mbid: str, *, timeout_sec: float = 10.0) -> dict:
    """Look up release metadata (album, year, artist) for a recording MBID
    obtained from MB search. Picks the EARLIEST release per release-events
    or first-release-date (addresses R1 F8 debt vs ``releases[0]``).

    Returns the same shape as ``recording_lookup`` so callers can blend
    the result into the identify payload. Raises ``MusicBrainzError`` on
    non-200.
    """
    _gate()
    params = {"inc": "artist-credits+releases+release-groups+isrcs", "fmt": "json"}
    headers = {"User-Agent": keys.get_user_agent()}
    url = f"{ENDPOINT}/{mbid}"
    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        raise MusicBrainzError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()

    credits = data.get("artist-credit") or []
    first_artist = credits[0]["artist"] if credits else None

    # Pick the earliest release by date (release.date YYYY-MM-DD). Fall back
    # to releases[0] if none of them carry a date.
    releases = data.get("releases") or []

    def _release_date_key(rel: dict) -> str:
        # Empty string sorts last under ascending sort, but we want missing
        # dates to lose to any present date, so map "" -> "9999-12-31".
        d = rel.get("date") or ""
        return d if d else "9999-12-31"

    if releases:
        sorted_releases = sorted(releases, key=_release_date_key)
        first_release = sorted_releases[0]
    else:
        first_release = None

    rg = (first_release or {}).get("release-group") or {}
    isrcs = data.get("isrcs") or []
    # Year priority: chosen release's date → recording's first-release-date → release-group's first-release-date
    candidate_dates = []
    if first_release and first_release.get("date"):
        candidate_dates.append(first_release["date"])
    if data.get("first-release-date"):
        candidate_dates.append(data["first-release-date"])
    if rg.get("first-release-date"):
        candidate_dates.append(rg["first-release-date"])
    year = None
    for d in candidate_dates:
        head = d[:4]
        if head.isdigit():
            year = int(head)
            break

    return {
        "mbid_recording": data.get("id", mbid),
        "title": data.get("title"),
        "artist": first_artist["name"] if first_artist else None,
        "mbid_artist": first_artist["id"] if first_artist else None,
        "release": first_release["title"] if first_release else None,
        "mbid_release_group": rg.get("id"),
        "year": year,
        "isrc": isrcs[0] if isrcs else None,
    }
