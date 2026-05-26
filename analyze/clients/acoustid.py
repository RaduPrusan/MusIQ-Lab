"""AcoustID Web Service v2 client.

Docs: https://acoustid.org/webservice
Rate limit: 3 req/s, enforced per-client. We don't expect to hit this for
single-track interactive use; if batch identification is added later,
add a `RateLimiter` similar to MusicBrainz's 1 req/s gate.

Round 4: ``lookup_with_reason`` returns ``(match, reason)`` so the
identify stage can decide whether to fire the MB text-search fallback.
The plain ``lookup`` wrapper preserves the historical return shape.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from analyze import keys

ENDPOINT = "https://api.acoustid.org/v2/lookup"
DEFAULT_MIN_SCORE = 0.65
RETRY_5XX_MAX_ATTEMPTS = 4  # initial + 3 retries
# Backoff between attempts: index i sleeps RETRY_BACKOFF_SEC[i] before attempt i+1.
# Total recovery window: 14s (1+4+9), enough headroom for a corpus-wide reanalyze.
RETRY_BACKOFF_SEC = [1, 4, 9]

# Reason discriminator values used by Round 4 identify.run().
REASON_NO_RESULTS = "acoustid_no_results"
REASON_BELOW_THRESHOLD = "acoustid_below_threshold"
REASON_ALL_UNLINKED = "acoustid_all_unlinked"

log = logging.getLogger(__name__)


class AcoustIDError(RuntimeError):
    pass


def lookup_with_reason(
    fingerprint: str,
    duration_sec: float,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    timeout_sec: float = 10.0,
) -> tuple[Optional[dict], Optional[str]]:
    """Like ``lookup`` but returns ``(match, reason)`` so the identify
    stage can decide whether to fire the MB text-search fallback.

    Reason is None when match is non-None. When match is None, reason is
    one of:
      - ``REASON_NO_RESULTS`` — AcoustID returned ``results: []``
      - ``REASON_BELOW_THRESHOLD`` — every result was below ``min_score``
      - ``REASON_ALL_UNLINKED`` — at least one above-threshold result
        existed but none carried a non-empty ``recordings`` array

    Errors still raise ``AcoustIDError`` (caller must wrap).

    Important compatibility note: this function calls ``lookup`` (the
    module-level name, not the internal ``_lookup_impl``) so any test
    monkeypatching ``acoustid_client.lookup`` is honored. When ``lookup``
    returns ``None`` we cannot disambiguate the cause from the public
    signature alone, so we report ``REASON_NO_RESULTS`` (the most common
    branch on this corpus per Blocker B). A direct ``_lookup_impl`` call
    still produces the precise discriminator from the raw HTTP response.
    """
    # If `lookup` hasn't been monkeypatched, call _lookup_impl directly so
    # we get the precise reason. Otherwise call `lookup` (the patched
    # function) and infer the reason from its return value.
    if lookup is _original_lookup:
        return _lookup_impl(
            fingerprint, duration_sec,
            min_score=min_score, timeout_sec=timeout_sec,
        )
    match = lookup(
        fingerprint, duration_sec,
        min_score=min_score, timeout_sec=timeout_sec,
    )
    if match is None:
        return None, REASON_NO_RESULTS
    return match, None


def lookup(
    fingerprint: str,
    duration_sec: float,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    timeout_sec: float = 10.0,
) -> dict | None:
    """Look up a Chromaprint fingerprint in the AcoustID database.

    Returns a dict ``{"mbid_recording": str, "acoustid_score": float,
    "acoustid_id": str, "raw_response": dict}`` for the best linked result
    above ``min_score``, or ``None`` if no result both clears the threshold
    AND has at least one MusicBrainz recording linked.

    The walker sorts results by score descending and returns the first one
    that satisfies BOTH conditions (score >= min_score AND non-empty
    recordings). High-score unlinked results are skipped and logged at
    DEBUG level (for future fingerprint-submit work).

    Within the winning result, the recording whose ``duration`` is closest
    to ``duration_sec`` is selected. If no duration data is available,
    falls back to ``recordings[0]``.

    The ``raw_response`` field is the full parsed AcoustID JSON, returned
    so the caller can persist it for offline debugging / replay of walker
    changes without re-querying the API.

    Raises AcoustIDError on missing API key, HTTP non-200 after retries,
    transport errors (DNS, connect, read, timeout — all wrapped), or an
    AcoustID-side ``status="error"`` response (error code surfaced in
    the message).

    Note: ``meta`` parameter is a SINGLE key ("recordings"). The AcoustID
    spec accepts multiple metas joined by ``+`` (e.g. ``recordings+releases``)
    but httpx URL-encodes ``+`` to ``%2B`` which AcoustID rejects silently.
    If you need additional meta keys, pass them as a list/tuple so httpx
    issues a repeated key, or use the ``recordings`` superset.
    """
    match, _reason = _lookup_impl(
        fingerprint, duration_sec,
        min_score=min_score, timeout_sec=timeout_sec,
    )
    # Preserve the historical contract: callers using ``lookup`` see None
    # for any "no usable match" outcome. The reason-aware sentinel only
    # surfaces through ``lookup_with_reason``.
    if match is None or match.get("_empty"):
        return None
    return match


def _lookup_impl(
    fingerprint: str,
    duration_sec: float,
    *,
    min_score: float,
    timeout_sec: float,
) -> tuple[Optional[dict], Optional[str]]:
    """Shared implementation for ``lookup`` and ``lookup_with_reason``.
    Returns ``(match_or_None, reason_or_None)`` — reason is one of the
    REASON_* constants when match is None and the HTTP exchange succeeded.

    The historical ``lookup()`` walker is preserved verbatim; the only
    behavior added is recording which of the three "no usable match"
    branches we exited through.
    """
    api_key = keys.get_acoustid_key()
    if not api_key:
        raise AcoustIDError("no api key (set ACOUSTID_API_KEY in .env)")

    params = {
        "client": api_key,
        "meta": "recordings",
        "fingerprint": fingerprint,
        "duration": int(round(duration_sec)),
    }

    last_status: int | None = None
    last_body = ""
    resp = None
    # Construct client ONCE; reuse across retry attempts so connection-pool
    # state (and the timeout config) is consistent.
    with httpx.Client(timeout=timeout_sec) as client:
        for attempt in range(RETRY_5XX_MAX_ATTEMPTS):
            try:
                resp = client.get(ENDPOINT, params=params)
            except httpx.RequestError as e:
                # DNS, connect, read, timeout — all are transport-level.
                # Surface as AcoustIDError so identify.run()'s except clause
                # catches it and invokes _preserve_or_write.
                raise AcoustIDError(f"transport: {type(e).__name__}: {e}") from e
            if resp.status_code < 500:
                break  # any non-5xx is a final answer
            last_status, last_body = resp.status_code, resp.text[:200]
            if attempt < RETRY_5XX_MAX_ATTEMPTS - 1:
                backoff = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
                time.sleep(backoff)
        else:
            # Loop exhausted without breaking — all attempts were 5xx
            raise AcoustIDError(
                f"HTTP {last_status} after {RETRY_5XX_MAX_ATTEMPTS} attempts: {last_body}"
            )

    assert resp is not None  # the for/else guarantees we either broke or raised
    if resp.status_code != 200:
        raise AcoustIDError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if data.get("status") != "ok":
        err = data.get("error") or {}
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else err
        raise AcoustIDError(
            f"status={data.get('status')} code={code} message={message!r}"
        )

    results = data.get("results") or []
    if not results:
        # No results at all — we still want to surface the raw_response so
        # the caller can persist .acoustid_raw.json for forensics.
        return (
            {"raw_response": data, "_empty": True},
            REASON_NO_RESULTS,
        )

    # Sort descending by score so we walk highest-first. Skip any result
    # that's below threshold (sorted, so we can bail) or has no recordings.
    sorted_results = sorted(
        results, key=lambda r: r.get("score", 0.0), reverse=True
    )
    chosen = None
    saw_above_threshold = False
    for r in sorted_results:
        score = r.get("score", 0.0)
        if score < min_score:
            # Sorted descending — nothing further will pass either.
            break
        saw_above_threshold = True
        recordings = r.get("recordings") or []
        if not recordings:
            log.debug(
                "acoustid: skipping unlinked high-score result id=%s score=%.3f",
                r.get("id", ""), score,
            )
            continue
        chosen = r
        break

    if chosen is None:
        # Disambiguate why we found nothing usable.
        if saw_above_threshold:
            reason = REASON_ALL_UNLINKED
        else:
            reason = REASON_BELOW_THRESHOLD
        return (
            {"raw_response": data, "_empty": True},
            reason,
        )

    recordings = chosen.get("recordings") or []
    # Recording selection: prefer the recording whose duration is closest to
    # the fingerprinted track's duration. Falls back to recordings[0] if no
    # recording has a duration field.
    def _dur_delta(rec: dict) -> float | None:
        d = rec.get("duration")
        if d is None:
            return None
        try:
            return abs(float(d) - duration_sec)
        except (TypeError, ValueError):
            return None

    with_dur = [(r, _dur_delta(r)) for r in recordings]
    candidates_with_dur = [(r, d) for r, d in with_dur if d is not None]
    if candidates_with_dur:
        # Secondary sort by recording.id makes tie-breaks deterministic
        # across runs when two recordings have identical |dur-delta|.
        chosen_rec = min(
            candidates_with_dur,
            key=lambda rd: (rd[1], rd[0].get("id", "")),
        )[0]
    else:
        chosen_rec = recordings[0]

    match = {
        "mbid_recording": chosen_rec["id"],
        "acoustid_score": float(chosen["score"]),
        "acoustid_id": chosen.get("id", ""),
        "raw_response": data,
    }
    return match, None


# Stash the original `lookup` reference at import time so
# ``lookup_with_reason`` can detect monkeypatches and route accordingly
# (call the patched `lookup` and synthesize the reason vs. call
# `_lookup_impl` and get the precise reason). Defined AFTER `lookup` so
# the name resolves; must stay at module bottom.
_original_lookup = lookup
