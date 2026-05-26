"""Runtime defenses for the locally-bound webui.

The app binds 127.0.0.1:8765 with no authentication. That model only holds
if we also enforce that (a) requests actually came from the user's own
browser pointed at localhost and (b) every path-segment parameter that
becomes a filesystem path is constrained to a known-safe alphabet.

This module ships three pieces:

* ``OriginGuard`` — ASGI middleware that rejects HTTP/WS scopes whose
  ``Host`` isn't ``127.0.0.1:<port>`` / ``localhost:<port>`` or whose
  ``Origin`` (when present) isn't one of the same. Closes the
  cross-origin-localhost + DNS-rebinding attack class.

* ``SecurityHeaders`` — adds ``X-Frame-Options``, ``X-Content-Type-Options``
  and ``Referrer-Policy`` to every HTML/JSON response. Cheap belt-and-braces
  against an embedded malicious page driving the UI via postMessage.

* ``validate_slug`` / ``validate_stem`` — string validators raising
  ``HTTPException(400)``. Apply to every ``{slug}`` / ``{stem}`` path
  parameter that becomes a filesystem path. The slug alphabet matches what
  ``analyze_runner.slug_for_filename`` produces, so any legitimate slug
  passes; ``..``, ``%2E%2E``, slashes, and NULs are rejected.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException


# --- Slug / stem validation -------------------------------------------------

# Matches what analyze_runner.slug_for_filename (and analyze.cache.slug_for)
# produce: lowercase alnum + `_` + `-`, first char alnum, max 128 chars.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")

# Stems known to the audio engine and the analyze pipeline. Kept here (not
# imported from server.py) so this module has no inbound dependencies on
# the rest of webui — easier to test, and avoids import cycles.
_STEM_ALLOW = frozenset({
    "vocals", "bass", "guitar", "piano", "other", "drums", "instrumental",
})


def is_safe_slug(slug: Any) -> bool:
    return isinstance(slug, str) and bool(_SLUG_RE.fullmatch(slug))


def is_safe_stem(stem: Any, *, allow: Iterable[str] | None = None) -> bool:
    choices = frozenset(allow) if allow is not None else _STEM_ALLOW
    return isinstance(stem, str) and stem in choices


def validate_slug(slug: str) -> str:
    """Return slug unchanged if it matches the safe alphabet; else 400."""
    if not is_safe_slug(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    return slug


def validate_stem(stem: str, *, allow: Iterable[str] | None = None) -> str:
    """Return stem unchanged if it's in the allow-list; else 400.

    ``allow`` defaults to the canonical stem set. Callers with their own
    smaller set (e.g. only the htdemucs_6s names, no instrumental) can pass
    it explicitly.
    """
    choices = frozenset(allow) if allow is not None else _STEM_ALLOW
    if not isinstance(stem, str) or stem not in choices:
        raise HTTPException(status_code=400, detail=f"invalid stem: {stem!r}")
    return stem


# --- Middleware -------------------------------------------------------------

# Only allow the loopback hostnames the user can legitimately type into a
# browser. Even if --host is later changed to 0.0.0.0, the Origin/Host check
# keeps the app reachable only via these two names — a deliberate guard
# rail, paired with the startup banner in __main__.
#
# `testserver` is Starlette TestClient's hardcoded default Host header. It's
# not a routable name (no DNS, no link-local fallback), so allowing it here
# only matters inside pytest's in-process ASGI transport — production
# browsers will never legitimately send it.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}


def _split_host_port(host_header: str) -> tuple[str, str | None]:
    """Split a Host header into (host, port). Handles IPv6 brackets.

    Returns ("", None) for malformed values. In particular, reject path,
    query, fragment, userinfo, empty-host, and non-numeric port forms so
    headers like ``localhost:8765/abc`` cannot be treated as loopback.
    """
    if not host_header:
        return "", None
    if any(ch in host_header for ch in "/?#@"):
        return "", None
    if host_header.startswith("["):
        # [::1]:8765 → host="[::1]", port="8765"
        end = host_header.find("]")
        if end == -1:
            return "", None
        host = host_header[: end + 1]
        rest = host_header[end + 1 :]
        if rest.startswith(":"):
            port = rest[1:]
            if not port.isdigit():
                return "", None
            return host, port
        if rest:
            return "", None
        return host, None
    if host_header == "::1":
        return host_header, None
    if ":" in host_header:
        h, _, p = host_header.rpartition(":")
        if not h or not p.isdigit():
            return "", None
        return h, p
    return host_header, None


def _origin_host(origin: str) -> str:
    """Return validated host from an Origin header, or "" when invalid."""
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    try:
        _ = parsed.port
    except ValueError:
        return ""
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        return ""
    if ":" in parsed.hostname and not parsed.hostname.startswith("["):
        return f"[{parsed.hostname}]"
    return parsed.hostname


class OriginGuard:
    """Reject scopes that don't carry a loopback Host (and a loopback Origin if any).

    Designed for an app deliberately bound to ``127.0.0.1`` with no auth.
    The check runs for both HTTP and WebSocket scopes:

    * ``Host`` must resolve to ``127.0.0.1`` / ``localhost`` (any port). This
      defeats DNS rebinding: even if a malicious domain's DNS flips to
      127.0.0.1 mid-session, the browser will keep sending the original
      Host header.
    * ``Origin``, when present, must be ``http(s)://<loopback>[:port]``. This
      blocks a cross-origin page from POSTing into our app via simple-CORS
      requests.

    Non-browser callers (curl, native apps) typically don't send Origin —
    that's fine; only Host is mandatory.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host_raw = headers.get(b"host", b"").decode("latin-1")
        host, _port = _split_host_port(host_raw)
        if host not in _LOOPBACK_HOSTS:
            await self._reject(scope, send, "host not loopback")
            return

        origin = headers.get(b"origin", b"").decode("latin-1")
        if origin:
            origin_host = _origin_host(origin)
            if origin_host not in _LOOPBACK_HOSTS:
                await self._reject(scope, send, "origin not loopback")
                return

        await self._app(scope, receive, send)

    @staticmethod
    async def _reject(scope: dict, send: Any, reason: str) -> None:
        if scope["type"] == "websocket":
            # ASGI websocket reject: send a close before accept.
            await send({"type": "websocket.close", "code": 4403})
            return
        body = f'{{"detail":"forbidden: {reason}"}}'.encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


class SecurityHeaders:
    """Inject X-Frame-Options + X-Content-Type-Options + Referrer-Policy.

    Implemented as raw ASGI middleware (not BaseHTTPMiddleware) for the
    same reason as _NoCacheDevMiddleware — buffer-free pass-through so
    streaming endpoints stay streamed.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def patched_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                _ensure_header(headers, b"x-frame-options", b"DENY")
                _ensure_header(headers, b"x-content-type-options", b"nosniff")
                _ensure_header(headers, b"referrer-policy", b"no-referrer")
                message["headers"] = headers
            await send(message)

        await self._app(scope, receive, patched_send)


def _ensure_header(headers: list, key: bytes, value: bytes) -> None:
    """Append (key, value) only if no header with that name is already set."""
    if not any(k.lower() == key for k, _ in headers):
        headers.append((key, value))
