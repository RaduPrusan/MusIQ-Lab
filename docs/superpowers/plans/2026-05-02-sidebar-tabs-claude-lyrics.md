# Sidebar tabs + Claude + Lyrics Implementation Plan

> **Status: SHIPPED 2026-05-03** via merge `7cc808b` ("merge: sidebar tabs + Claude + Lyrics + loop region"; 22-commit feature branch). All target artifacts exist on `main`: `webui/webui/chat.py`, `webui/webui/lyrics.py`, `webui/static/js/ui/{tabs,tabbed-sidebar,claude-tab,lyrics-tab}.js`, plus the chat + lyrics REST routes and the view-state loop region honored by the audio engine, piano-roll, minimap, and transport. Follow-up polish (rename modal, paste dialog, identify_track slug prettifier, persistence-across-reanalyze, claude-agent-sdk 0.1.72→0.1.77 bump) shipped between 2026-05-04 and 2026-05-09 — see git log for `webui/webui/lyrics*` and `webui/webui/chat*`. **Individual `- [ ]` checkboxes below were not ticked during execution (worktree-driven merge); the merge commit and git log are the authoritative status of record. Plan body retained as historical narrative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a multi-tab sidebar to the webui — Tab 1 (existing Track content, unchanged), Tab 2 (Claude assistant via `claude-agent-sdk` with OAuth/subscription auth and a tool surface that can read pipeline artifacts and dispatch UI commands), Tab 3 (karaoke-style synced lyrics from LRCLIB with per-line click-to-seek and auto-scroll).

**Architecture:** Backend additions are two Python modules (`chat.py`, `lyrics.py`) and ~7 new FastAPI routes; backend talks to Claude via `claude-agent-sdk.query()` (stateless per turn, history serialized to `cache/<slug>/chat.json`) and exposes in-process MCP tools whose return dicts carry a private `_ui_action` key extracted by a streaming wrapper that emits NDJSON events to the browser. Frontend gains a tab shell (`tabs.js` + `tabbed-sidebar.js`), a Claude chat panel (`claude-tab.js`), a karaoke lyrics panel (`lyrics-tab.js`), and a cross-cutting view-state loop region honored by the audio engine, piano-roll, minimap, and transport.

**Tech Stack:** Python 3.11+ / FastAPI / `claude-agent-sdk` (bundles Claude Code CLI, uses `~/.claude/` OAuth credentials) / `mutagen` (ID3 tag reader) / `httpx` (already a transitive dep — used to call LRCLIB) / pytest with `fastapi.testclient.TestClient` and a `respx`/monkey-patch HTTPX mock. Frontend: ES modules, no build step, manual-smoke verification via `webui/run.bat` and screenshots under `tests/screenshots/sidebar-tabs/`.

**Spec:** [`docs/superpowers/specs/2026-05-02-sidebar-tabs-claude-lyrics-design.md`](../specs/2026-05-02-sidebar-tabs-claude-lyrics-design.md)

**Coordination:** A parallel work-stream ([`docs/superpowers/plans/2026-05-02-analyze-from-library.md`](2026-05-02-analyze-from-library.md)) is adding analyze-from-file and analyze-from-YouTube flows. Their changes touch the topbar/track-picker and add new analyze routes; ours touch the sidebar and add chat/lyrics routes. The only shared file is `webui/webui/server.py` and `webui/static/css/track.css` — both additive on disjoint regions. Implementation runs in a worktree branched from `main`. If the parallel work has merged by start time, branch from current `main`. If it merges *after* this plan starts, rebase the worktree onto the new `main` after the parallel work lands; route additions and CSS additions don't conflict textually.

---

## File map

**New (Python):**
- `webui/webui/chat.py` — system prompt template, MCP tools (UI-action + server-only + lyrics), message assembly, NDJSON streaming wrapper around `claude_agent_sdk.query`, conversation persistence.
- `webui/webui/lyrics.py` — ID3 reader (`mutagen`), LRCLIB client (`/api/get` + `/api/search` fallback), LRC parser, cache I/O, paste handling.
- `webui/tests/test_chat.py` — unit tests for tools, message assembly, streaming wrapper (mock SDK), persistence.
- `webui/tests/test_lyrics.py` — unit tests for LRC parser, ID3 reader, LRCLIB client (mock HTTP), cache I/O.

**New (JS):**
- `webui/static/js/ui/tabs.js` — `TabBar` component (host, tabs, active, persistence).
- `webui/static/js/ui/tabbed-sidebar.js` — orchestrates the three tab panels; preserves `Sidebar`'s external surface.
- `webui/static/js/ui/claude-tab.js` — chat UI: composer, transcript, NDJSON stream reader, tool-chip rendering, UI-action dispatcher, stop/clear/restore.
- `webui/static/js/ui/lyrics-tab.js` — karaoke UI: editable header, refresh menu, scroll container, active-line highlight, click-to-seek, auto-scroll suspend.

**Modified (Python):**
- `webui/webui/server.py` — `/api/chat/{slug}/turn`, `/api/chat/{slug}` (GET + DELETE), `/api/tracks/{slug}/lyrics` (GET + DELETE), `/api/tracks/{slug}/lyrics/fetch` (POST), `/api/tracks/{slug}/lyrics/paste` (POST); `_clear_cache_dir` preserves `chat.json` + `lyrics/`.
- `webui/tests/test_server.py` — new cases for chat + lyrics routes; `_clear_cache_dir` preservation regression.
- `webui/requirements.txt` — `+ claude-agent-sdk`, `+ mutagen`.
- `webui/requirements.lock` — regenerated.

**Modified (JS):**
- `webui/static/js/main.js` — swap `Sidebar` → `TabbedSidebar` at the mount site (~5 lines).
- `webui/static/js/api.js` — fetch wrappers for chat + lyrics endpoints.
- `webui/static/js/view/view-state.js` — `loopStart`, `loopEnd`, `setLoop`, `clearLoop`.
- `webui/static/js/audio/web-audio-engine.js` — playback loop honors `[loopStart, loopEnd]`.
- `webui/static/js/render/pianoroll.js` — translucent loop band overlay on canvas.
- `webui/static/js/ui/minimap.js` — translucent loop band overlay.
- `webui/static/js/ui/transport.js` — `Loop: 1:23–2:14 ✕` chip when active.

**Modified (CSS):**
- `webui/static/css/track.css` — tab strip, claude tab (header, transcript, composer, tool chips), lyrics tab (header, scroll container, active line), loop chip.

---

## Phase 1 — Setup

### Task 1: Create the worktree and install dependencies

**Files:**
- Modify: `webui/requirements.txt`
- Regenerate: `webui/requirements.lock`

- [ ] **Step 1: Create the worktree from `main`**

```bash
cd '<PROJECT_PATH>'
git worktree add .claude/worktrees/sidebar-tabs -b feat/sidebar-tabs-claude-lyrics main
cd .claude/worktrees/sidebar-tabs
```

If the analyze-from-library plan has merged by now, `main` already includes those changes — we branch on top. If it hasn't, we'll rebase later. Either way, work proceeds in this worktree from this point forward.

- [ ] **Step 2: Add the two new Python deps to `webui/requirements.txt`**

Append to `webui/requirements.txt`:

```
claude-agent-sdk>=0.0.16
mutagen>=1.47
```

- [ ] **Step 3: Recreate the venv and regenerate the lockfile**

```bash
cd webui
rm -rf .venv requirements.lock
uv venv
uv pip install -r requirements.txt
uv pip freeze > requirements.lock
```

Expected: `claude-agent-sdk` and `mutagen` appear in `requirements.lock`.

- [ ] **Step 4: Smoke-test the SDK can import and the CLI is bundled**

```bash
.venv/Scripts/python -c "from claude_agent_sdk import query, ClaudeAgentOptions, tool, create_sdk_mcp_server; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Verify Claude is logged in**

Run `claude /login` separately if needed. Then verify auth works through the SDK by running a one-shot query:

```bash
.venv/Scripts/python -c "
import asyncio
from claude_agent_sdk import query, AssistantMessage, TextBlock
async def go():
    async for m in query(prompt='Reply with the single word: ok'):
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, TextBlock):
                    print(b.text.strip())
                    return
asyncio.run(go())
"
```

Expected output: a one-word answer like `ok` (case-insensitive match acceptable). If this errors with auth-related text, the executor must run `claude /login` and re-try before continuing.

- [ ] **Step 6: Run the existing test suite to confirm nothing regressed**

```bash
cd webui && .venv/Scripts/python -m pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add webui/requirements.txt webui/requirements.lock
git commit -m "chore(webui): add claude-agent-sdk + mutagen deps"
```

---

## Phase 2 — Lyrics backend (TDD)

### Task 2: LRC parser

**Files:**
- Create: `webui/webui/lyrics.py`
- Test: `webui/tests/test_lyrics.py`

- [ ] **Step 1: Write failing tests for the LRC parser**

Create `webui/tests/test_lyrics.py`:

```python
from webui.lyrics import parse_lrc


def test_parse_lrc_simple_two_lines():
    text = "[00:01.50]first line\n[00:04.20]second line\n"
    result = parse_lrc(text)
    assert result["has_sync"] is True
    assert result["lines"] == [
        {"time_sec": 1.5, "text": "first line"},
        {"time_sec": 4.2, "text": "second line"},
    ]
    assert result["plain_text"] == "first line\nsecond line"


def test_parse_lrc_with_minutes():
    text = "[02:13.99]a verse line\n"
    result = parse_lrc(text)
    assert result["lines"][0]["time_sec"] == 2 * 60 + 13.99


def test_parse_lrc_section_marker_kept_in_text():
    text = "[00:00.00]\n[00:01.00][Verse 1]\n[00:05.00]She walked\n"
    result = parse_lrc(text)
    assert result["lines"][0]["text"] == "[Verse 1]"
    assert result["lines"][1]["text"] == "She walked"


def test_parse_lrc_metadata_lines_dropped():
    text = "[ar:Some Artist]\n[ti:Some Title]\n[00:01.00]hello\n"
    result = parse_lrc(text)
    assert len(result["lines"]) == 1
    assert result["lines"][0]["text"] == "hello"


def test_parse_lrc_blank_text_kept_with_empty_string():
    text = "[00:01.00]\n[00:05.00]first\n"
    result = parse_lrc(text)
    assert result["lines"][0] == {"time_sec": 1.0, "text": ""}


def test_parse_lrc_plain_text_no_brackets():
    text = "first line\nsecond line\n"
    result = parse_lrc(text)
    assert result["has_sync"] is False
    assert result["lines"] == []
    assert result["plain_text"] == "first line\nsecond line"


def test_parse_lrc_mixed_synced_and_plain_treated_as_synced():
    # Real LRCLIB files sometimes have header notes interleaved.
    # Any timestamped line makes the file synced; non-timestamped lines drop.
    text = "Lyrics by Someone\n[00:01.00]first\n[00:05.00]second\n"
    result = parse_lrc(text)
    assert result["has_sync"] is True
    assert len(result["lines"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'webui.lyrics'`.

- [ ] **Step 3: Create `webui/webui/lyrics.py` with the parser**

Create `webui/webui/lyrics.py`:

```python
"""Lyrics fetching, parsing, and cache I/O for the webui."""
from __future__ import annotations

import re
from typing import TypedDict


class LrcLine(TypedDict):
    time_sec: float
    text: str


class ParsedLyrics(TypedDict):
    has_sync: bool
    lines: list[LrcLine]
    plain_text: str


_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_METADATA_TAG_RE = re.compile(r"^\[(ar|ti|al|au|by|offset|re|ve|length):.*\]\s*$", re.IGNORECASE)


def parse_lrc(text: str) -> ParsedLyrics:
    """Parse an LRC-format string into a structured form.

    Lines beginning with metadata tags ([ar:...], [ti:...], etc.) are dropped.
    Lines with one or more `[mm:ss.xx]` timestamps become synced entries.
    Lines with neither timestamps nor metadata tags are dropped from `lines`
    but still contribute to `plain_text`.
    """
    synced_lines: list[LrcLine] = []
    plain_lines: list[str] = []
    has_any_timestamp = False

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if _METADATA_TAG_RE.match(line):
            continue
        timestamps = list(_TIMESTAMP_RE.finditer(line))
        if not timestamps:
            plain_lines.append(line)
            continue
        has_any_timestamp = True
        # Strip all timestamps from the line; the residue is the lyric text.
        # Multiple-timestamp lines (rare) emit one entry per timestamp with
        # the same text — useful for repeated choruses.
        residue = _TIMESTAMP_RE.sub("", line).lstrip()
        for m in timestamps:
            mm = int(m.group(1))
            ss = int(m.group(2))
            cs = m.group(3) or "0"
            frac = float("0." + cs)
            t = mm * 60 + ss + frac
            synced_lines.append({"time_sec": t, "text": residue})
        plain_lines.append(residue)

    synced_lines.sort(key=lambda x: x["time_sec"])
    return {
        "has_sync": has_any_timestamp,
        "lines": synced_lines,
        "plain_text": "\n".join(plain_lines),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lyrics.py webui/tests/test_lyrics.py
git commit -m "feat(webui): add LRC parser for lyrics tab"
```

---

### Task 3: ID3 tag reader with filename fallback

**Files:**
- Modify: `webui/webui/lyrics.py` (append)
- Modify: `webui/tests/test_lyrics.py` (append)

- [ ] **Step 1: Write failing tests for the tag reader**

Append to `webui/tests/test_lyrics.py`:

```python
from pathlib import Path

from webui.lyrics import identify_track


def test_identify_from_id3_tags(tmp_path, monkeypatch):
    fake_path = tmp_path / "track.mp3"
    fake_path.write_bytes(b"")  # mutagen.File on empty returns None — we monkeypatch instead

    class FakeTags(dict):
        pass

    fake_tags = FakeTags({"artist": ["Some Artist"], "title": ["Some Title"], "album": ["Some Album"]})

    def fake_mutagen_file(path, easy=True):
        return fake_tags

    monkeypatch.setattr("webui.lyrics._mutagen_file", fake_mutagen_file)
    result = identify_track(fake_path, duration_sec=212.0)
    assert result == {"artist": "Some Artist", "title": "Some Title", "album": "Some Album", "duration_sec": 212.0}


def test_identify_filename_fallback_with_dash(tmp_path, monkeypatch):
    fake_path = tmp_path / "Gorillaz - Silent Running.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=180.0)
    assert result["artist"] == "Gorillaz"
    assert result["title"] == "Silent Running"


def test_identify_filename_fallback_underscore(tmp_path, monkeypatch):
    fake_path = tmp_path / "olivia_dean_dive.mp3"
    fake_path.write_bytes(b"")
    monkeypatch.setattr("webui.lyrics._mutagen_file", lambda p, easy=True: None)
    result = identify_track(fake_path, duration_sec=180.0)
    # No clear artist/title separator — drop into title-only fallback
    assert result["artist"] == ""
    assert result["title"] == "olivia_dean_dive"


def test_identify_partial_id3_uses_filename_for_missing(tmp_path, monkeypatch):
    fake_path = tmp_path / "Gorillaz - Silent Running.mp3"
    fake_path.write_bytes(b"")

    class FakeTags(dict):
        pass

    monkeypatch.setattr(
        "webui.lyrics._mutagen_file",
        lambda p, easy=True: FakeTags({"title": ["Silent Running"]}),  # artist missing
    )
    result = identify_track(fake_path, duration_sec=180.0)
    assert result["artist"] == "Gorillaz"  # filled from filename
    assert result["title"] == "Silent Running"  # from id3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v -k identify
```

Expected: FAIL with `ImportError: cannot import name 'identify_track'`.

- [ ] **Step 3: Append the implementation to `webui/webui/lyrics.py`**

```python
from pathlib import Path

import mutagen


class TrackIdentity(TypedDict):
    artist: str
    title: str
    album: str
    duration_sec: float


def _mutagen_file(path: Path, easy: bool = True):
    """Wrapper for mutagen.File so tests can monkeypatch it."""
    return mutagen.File(str(path), easy=easy)


def _parse_filename(stem: str) -> tuple[str, str]:
    """Heuristic: split on ` - ` (dash with spaces). Other forms fall back to title-only."""
    if " - " in stem:
        artist, _, title = stem.partition(" - ")
        return artist.strip(), title.strip()
    return "", stem


def identify_track(mp3_path: Path, duration_sec: float) -> TrackIdentity:
    """Return artist/title/album for an MP3, preferring ID3 tags and falling
    back to filename parsing for any missing field."""
    artist = title = album = ""
    try:
        tags = _mutagen_file(mp3_path, easy=True)
    except Exception:
        tags = None
    if tags:
        artist = (tags.get("artist") or [""])[0] or ""
        title = (tags.get("title") or [""])[0] or ""
        album = (tags.get("album") or [""])[0] or ""
    if not artist or not title:
        fb_artist, fb_title = _parse_filename(mp3_path.stem)
        if not artist:
            artist = fb_artist
        if not title:
            title = fb_title
    return {"artist": artist, "title": title, "album": album, "duration_sec": duration_sec}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lyrics.py webui/tests/test_lyrics.py
git commit -m "feat(webui): add ID3-with-filename-fallback track identification"
```

---

### Task 4: LRCLIB HTTP client

**Files:**
- Modify: `webui/webui/lyrics.py` (append)
- Modify: `webui/tests/test_lyrics.py` (append)

- [ ] **Step 1: Write failing tests for the LRCLIB client**

Append to `webui/tests/test_lyrics.py`:

```python
import httpx
import pytest

from webui.lyrics import lrclib_lookup


class _FakeTransport(httpx.MockTransport):
    pass


@pytest.mark.asyncio
async def test_lrclib_get_returns_synced(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/get"
        params = dict(request.url.params)
        assert params["artist_name"] == "Gorillaz"
        assert params["track_name"] == "Silent Running"
        return httpx.Response(
            200,
            json={
                "id": 12345,
                "syncedLyrics": "[00:01.00]first\n[00:05.00]second\n",
                "plainLyrics": "first\nsecond",
                "duration": 180,
            },
        )

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="Gorillaz", title="Silent Running", duration_sec=180.0, _transport=transport
    )
    assert result["source"] == "lrclib"
    assert result["has_sync"] is True
    assert result["lrclib_id"] == 12345
    assert "[00:01.00]first" in result["synced_lrc"]


@pytest.mark.asyncio
async def test_lrclib_get_404_falls_back_to_search(monkeypatch):
    calls: list[str] = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/get":
            return httpx.Response(404)
        if request.url.path == "/api/search":
            return httpx.Response(
                200,
                json=[
                    {"id": 1, "duration": 100, "syncedLyrics": None, "plainLyrics": "wrong song"},
                    {"id": 2, "duration": 181, "syncedLyrics": "[00:01.00]right\n", "plainLyrics": "right"},
                ],
            )
        return httpx.Response(500)

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert calls == ["/api/get", "/api/search"]
    assert result["lrclib_id"] == 2  # closest duration to 180
    assert result["has_sync"] is True


@pytest.mark.asyncio
async def test_lrclib_no_match_returns_not_found(monkeypatch):
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(200, json=[])

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert result == {"source": "lrclib", "has_sync": False, "synced_lrc": None, "plain_text": None, "lrclib_id": None, "error": "not_found"}


@pytest.mark.asyncio
async def test_lrclib_network_error_propagates_as_error_dict(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("simulated network failure")

    transport = _FakeTransport(handler)
    result = await lrclib_lookup(
        artist="X", title="Y", duration_sec=180.0, _transport=transport
    )
    assert result["error"] == "network"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v -k lrclib
```

Expected: FAIL with `ImportError: cannot import name 'lrclib_lookup'`.

- [ ] **Step 3: Append the LRCLIB client to `webui/webui/lyrics.py`**

```python
import httpx

LRCLIB_BASE = "https://lrclib.net"
LRCLIB_USER_AGENT = "MusIQ-Lab/0.1 (local single-user music analysis app)"


class LrclibResult(TypedDict, total=False):
    source: str
    has_sync: bool
    synced_lrc: str | None
    plain_text: str | None
    lrclib_id: int | None
    error: str  # "not_found" | "network" | "http_<status>"


async def lrclib_lookup(
    *, artist: str, title: str, duration_sec: float, album: str = "", _transport=None
) -> LrclibResult:
    """Query LRCLIB for lyrics. Tries /api/get first; on 404, falls back to
    /api/search and picks the result with the closest duration. Returns a
    structured dict regardless of outcome — never raises for network/4xx/5xx."""
    headers = {"User-Agent": LRCLIB_USER_AGENT}
    timeout = httpx.Timeout(8.0, connect=4.0)
    client_args = {"base_url": LRCLIB_BASE, "headers": headers, "timeout": timeout}
    if _transport is not None:
        client_args["transport"] = _transport

    try:
        async with httpx.AsyncClient(**client_args) as client:
            params = {
                "artist_name": artist,
                "track_name": title,
                "duration": int(round(duration_sec)),
            }
            if album:
                params["album_name"] = album
            r = await client.get("/api/get", params=params)
            if r.status_code == 200:
                data = r.json()
                return _shape_lrclib_record(data)
            if r.status_code != 404:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": f"http_{r.status_code}",
                }
            # 404 → search fallback
            sr = await client.get(
                "/api/search", params={"artist_name": artist, "track_name": title}
            )
            if sr.status_code != 200:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": f"http_{sr.status_code}",
                }
            results = sr.json() or []
            if not results:
                return {
                    "source": "lrclib", "has_sync": False, "synced_lrc": None,
                    "plain_text": None, "lrclib_id": None, "error": "not_found",
                }
            best = min(
                results,
                key=lambda x: abs(int(x.get("duration", 0)) - int(round(duration_sec))),
            )
            return _shape_lrclib_record(best)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
        return {
            "source": "lrclib", "has_sync": False, "synced_lrc": None,
            "plain_text": None, "lrclib_id": None, "error": "network",
        }


def _shape_lrclib_record(data: dict) -> LrclibResult:
    synced = data.get("syncedLyrics")
    plain = data.get("plainLyrics")
    return {
        "source": "lrclib",
        "has_sync": bool(synced),
        "synced_lrc": synced,
        "plain_text": plain,
        "lrclib_id": data.get("id"),
    }
```

Also add `pytest-asyncio` to `webui/requirements.txt` if it isn't present (check first):

```bash
cd webui && grep -E '^pytest-asyncio' requirements.txt || echo "pytest-asyncio>=0.23" >> requirements.txt
```

If it was added, regenerate the lock and reinstall:

```bash
cd webui && uv pip install -r requirements.txt && uv pip freeze > requirements.lock
```

Add `asyncio_mode = "auto"` to `webui/pyproject.toml` under a `[tool.pytest.ini_options]` section if not present. Verify with:

```bash
cd webui && grep -A2 'tool.pytest' pyproject.toml || echo "[tool.pytest.ini_options]\nasyncio_mode = \"auto\"" >> pyproject.toml
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lyrics.py webui/tests/test_lyrics.py webui/requirements.txt webui/requirements.lock webui/pyproject.toml
git commit -m "feat(webui): add LRCLIB HTTP client (get + search fallback)"
```

---

### Task 5: Lyrics cache I/O + service orchestration

**Files:**
- Modify: `webui/webui/lyrics.py` (append)
- Modify: `webui/tests/test_lyrics.py` (append)

- [ ] **Step 1: Write failing tests for the service layer**

Append to `webui/tests/test_lyrics.py`:

```python
from webui.lyrics import (
    cache_dir_for, load_cached, save_synced, save_plain, save_paste, clear_cache,
    detect_paste_format,
)


def test_save_and_load_synced(tmp_path):
    cache = tmp_path / "lyrics"
    save_synced(cache, lrc_text="[00:01.00]hello\n", meta={"source": "lrclib", "lrclib_id": 1, "artist": "A", "title": "T", "album": "", "duration_sec": 180})
    loaded = load_cached(cache)
    assert loaded["has_sync"] is True
    assert loaded["meta"]["source"] == "lrclib"


def test_save_and_load_plain(tmp_path):
    cache = tmp_path / "lyrics"
    save_plain(cache, plain_text="line one\nline two", meta={"source": "claude_web", "artist": "A", "title": "T", "album": "", "duration_sec": 180})
    loaded = load_cached(cache)
    assert loaded["has_sync"] is False
    assert loaded["plain_text"] == "line one\nline two"


def test_load_cached_missing_returns_none(tmp_path):
    assert load_cached(tmp_path / "lyrics") is None


def test_detect_paste_lrc_with_timestamps():
    assert detect_paste_format("[00:01.00]hello") == "lrc"


def test_detect_paste_plain_text():
    assert detect_paste_format("just plain words\nno timestamps") == "plain"


def test_save_paste_routes_to_lrc(tmp_path):
    cache = tmp_path / "lyrics"
    save_paste(cache, "[00:01.00]hello\n", meta={"source": "user_paste", "artist": "", "title": "", "album": "", "duration_sec": 0})
    assert (cache / "synced.lrc").is_file()
    assert not (cache / "plain.txt").is_file()


def test_save_paste_routes_to_plain(tmp_path):
    cache = tmp_path / "lyrics"
    save_paste(cache, "no timestamps here", meta={"source": "user_paste", "artist": "", "title": "", "album": "", "duration_sec": 0})
    assert (cache / "plain.txt").is_file()
    assert not (cache / "synced.lrc").is_file()


def test_clear_cache_removes_directory(tmp_path):
    cache = tmp_path / "lyrics"
    save_synced(cache, "[00:01.00]hello\n", meta={"source": "lrclib", "artist": "", "title": "", "album": "", "duration_sec": 0})
    clear_cache(cache)
    assert not cache.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v -k "save_ or load_ or detect_ or clear_cache"
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Append the cache I/O layer to `webui/webui/lyrics.py`**

```python
import json
import shutil


def cache_dir_for(slug_cache_root: Path) -> Path:
    """Given a cache/<slug>/ path, return the lyrics subdirectory path."""
    return slug_cache_root / "lyrics"


def save_synced(cache: Path, lrc_text: str, meta: dict) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "synced.lrc").write_text(lrc_text, encoding="utf-8")
    plain = parse_lrc(lrc_text)["plain_text"]
    if plain:
        (cache / "plain.txt").write_text(plain, encoding="utf-8")
    meta_with_ts = {**meta, "fetched_at": _utc_now_iso(), "has_sync": True}
    (cache / "meta.json").write_text(json.dumps(meta_with_ts, indent=2), encoding="utf-8")


def save_plain(cache: Path, plain_text: str, meta: dict) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "plain.txt").write_text(plain_text, encoding="utf-8")
    meta_with_ts = {**meta, "fetched_at": _utc_now_iso(), "has_sync": False}
    (cache / "meta.json").write_text(json.dumps(meta_with_ts, indent=2), encoding="utf-8")


def detect_paste_format(text: str) -> str:
    """Return 'lrc' if any line carries a [mm:ss(.cs)?] timestamp, else 'plain'."""
    return "lrc" if _TIMESTAMP_RE.search(text) else "plain"


def save_paste(cache: Path, text: str, meta: dict) -> None:
    if detect_paste_format(text) == "lrc":
        save_synced(cache, text, meta)
    else:
        save_plain(cache, text, meta)


def load_cached(cache: Path) -> dict | None:
    """Return parsed lyrics from the cache, or None if no cache."""
    meta_path = cache / "meta.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    synced_path = cache / "synced.lrc"
    plain_path = cache / "plain.txt"
    if synced_path.is_file():
        parsed = parse_lrc(synced_path.read_text(encoding="utf-8"))
        return {
            "has_sync": True,
            "lines": parsed["lines"],
            "plain_text": parsed["plain_text"],
            "meta": meta,
        }
    if plain_path.is_file():
        return {
            "has_sync": False,
            "lines": [],
            "plain_text": plain_path.read_text(encoding="utf-8"),
            "meta": meta,
        }
    return None


def clear_cache(cache: Path) -> None:
    if cache.is_dir():
        shutil.rmtree(cache)


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_lyrics.py -v
```

Expected: all 22 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lyrics.py webui/tests/test_lyrics.py
git commit -m "feat(webui): add lyrics cache I/O + paste-format detection"
```

---

## Phase 3 — Chat backend (TDD)

### Task 6: System prompt + message assembly

**Files:**
- Create: `webui/webui/chat.py`
- Create: `webui/tests/test_chat.py`

- [ ] **Step 1: Write failing tests for the message-assembly pipeline**

Create `webui/tests/test_chat.py`:

```python
import json
from webui.chat import build_system_prompt, build_user_message, MAX_HISTORY_TOKENS_HEURISTIC


def test_build_system_prompt_includes_track_summary():
    summary = {
        "track": {"slug": "demo", "key": "C major", "tempo_bpm": 120, "duration_sec": 180},
        "chords": [], "downbeats": [], "stems": {}, "analysis": {},
    }
    prompt = build_system_prompt(summary)
    assert "music tutor" in prompt.lower()
    assert "C major" in prompt
    assert json.dumps(summary) in prompt or "120" in prompt  # summary embedded somehow


def test_build_user_message_prepends_view_state():
    snapshot = {"playhead_sec": 83.5, "current_chord": "C:maj", "highlighted_stem": "piano"}
    msg = build_user_message("what's the chord?", snapshot)
    assert msg.startswith("<view_state>")
    assert "</view_state>" in msg
    assert "what's the chord?" in msg
    assert "83.5" in msg


def test_build_user_message_no_snapshot_omits_block():
    msg = build_user_message("hello", None)
    assert "<view_state>" not in msg
    assert msg == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: FAIL — `webui.chat` doesn't exist yet.

- [ ] **Step 3: Create `webui/webui/chat.py` with the assembly helpers**

```python
"""Claude assistant: system prompt, message assembly, tools, streaming wrapper, persistence."""
from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT_TEMPLATE = """You are MusIQ-Lab's in-app music tutor. The user is studying a single
track in a piano-roll viewer. You have access to the pipeline's full analysis (chords with Roman
numerals, function tags, modal-interchange flags, stems, loop, key, scale, vocal range, downbeats),
the current view state, and — when present — the synced lyrics.

Roles you fill, in order of frequency:
- Tutor: explain harmony, chord function, modal interchange, why a progression works.
- Guide: suggest practice approaches, transposition for instrument or vocal range.
- Operator: when the user asks to *do* something, use tools to seek, mute/solo, set a loop region,
  or highlight a stem or lyric line.
- Lyricist: interpret lyrics, identify rhyme schemes and themes, translate.
- Librarian: search across other analyzed tracks for similar harmonic features.

Default to text answers. Reach for tools only when an action is the cleanest answer (e.g. "show me
the modulation" → seek + highlight). Do not narrate every tool you intend to use; just use it.

Track summary follows. Each user message is prefixed with a <view_state>...</view_state> block
describing the playhead, current chord, mute/solo state, and active tab at message time — read it
but do not mention it unless the user asks about the current moment.

<track_summary>
{summary_json}
</track_summary>
"""

MAX_HISTORY_TOKENS_HEURISTIC = 150_000  # conservative cutoff before truncating oldest turns


def build_system_prompt(summary: dict) -> str:
    """Render the system prompt with the track summary embedded."""
    return SYSTEM_PROMPT_TEMPLATE.format(summary_json=json.dumps(summary, ensure_ascii=False))


def build_user_message(text: str, view_state: dict | None) -> str:
    """Prepend a <view_state> block to the user's text. Returns text unchanged
    if view_state is None (used for the very first turn or stateless tests)."""
    if view_state is None:
        return text
    snapshot = json.dumps(view_state, ensure_ascii=False)
    return f"<view_state>{snapshot}</view_state>\n{text}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/chat.py webui/tests/test_chat.py
git commit -m "feat(webui): chat system prompt + message assembly"
```

---

### Task 7: Tool definitions (server-only, UI-action, lyrics)

**Files:**
- Modify: `webui/webui/chat.py` (append)
- Modify: `webui/tests/test_chat.py` (append)

- [ ] **Step 1: Write failing tests for tool functions**

Append to `webui/tests/test_chat.py`:

```python
import asyncio
from webui.chat import (
    seek_to, set_loop_region, set_stem_state, highlight_stem, open_midi_tool,
    switch_tab, highlight_lyric_line,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_seek_to_returns_ui_action():
    out = _run(seek_to({"time_sec": 12.34}))
    assert out["_ui_action"] == {"action": "seek_to", "args": {"time_sec": 12.34}}
    assert "Queued seek" in out["content"][0]["text"]


def test_set_loop_region_validates_ordering():
    out = _run(set_loop_region({"start_sec": 5.0, "end_sec": 12.0}))
    assert out["_ui_action"]["args"] == {"start_sec": 5.0, "end_sec": 12.0}


def test_set_loop_region_rejects_inverted():
    out = _run(set_loop_region({"start_sec": 12.0, "end_sec": 5.0}))
    assert out.get("is_error") is True
    assert "_ui_action" not in out


def test_set_stem_state_partial_args():
    out = _run(set_stem_state({"stem": "vocals", "mute": True}))
    assert out["_ui_action"]["args"] == {"stem": "vocals", "mute": True}


def test_switch_tab_validates_choice():
    out = _run(switch_tab({"tab": "lyrics"}))
    assert out["_ui_action"]["args"] == {"tab": "lyrics"}
    bad = _run(switch_tab({"tab": "wat"}))
    assert bad.get("is_error") is True


def test_highlight_lyric_line_passes_through_index():
    out = _run(highlight_lyric_line({"index": 7}))
    assert out["_ui_action"]["args"] == {"index": 7}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: FAIL — tool functions don't exist.

- [ ] **Step 3: Append the tool definitions to `webui/webui/chat.py`**

```python
from claude_agent_sdk import tool, create_sdk_mcp_server


# UI-action tools — every return dict carries a `_ui_action` key extracted by the streaming wrapper.
# The `content` list is what Claude sees; `_ui_action` is private to our process.

@tool("seek_to", "Move the audio playhead to a specific time in the track.", {"time_sec": float})
async def seek_to(args: dict[str, Any]) -> dict[str, Any]:
    t = float(args["time_sec"])
    return {
        "content": [{"type": "text", "text": f"Queued seek to {t:.2f}s"}],
        "_ui_action": {"action": "seek_to", "args": {"time_sec": t}},
    }


@tool(
    "set_loop_region",
    "Set a loop region. Audio loops between start_sec and end_sec until cleared.",
    {"start_sec": float, "end_sec": float},
)
async def set_loop_region(args: dict[str, Any]) -> dict[str, Any]:
    s, e = float(args["start_sec"]), float(args["end_sec"])
    if e <= s:
        return {"content": [{"type": "text", "text": "end_sec must be greater than start_sec"}], "is_error": True}
    return {
        "content": [{"type": "text", "text": f"Loop region: {s:.2f}s – {e:.2f}s"}],
        "_ui_action": {"action": "set_loop_region", "args": {"start_sec": s, "end_sec": e}},
    }


@tool(
    "set_stem_state",
    "Update mute/solo/volume for one stem. Any of mute (bool), solo (bool), volume (0..1) can be omitted.",
    {"stem": str, "mute": bool, "solo": bool, "volume": float},
)
async def set_stem_state(args: dict[str, Any]) -> dict[str, Any]:
    payload = {"stem": args["stem"]}
    for k in ("mute", "solo", "volume"):
        if k in args and args[k] is not None:
            payload[k] = args[k]
    return {
        "content": [{"type": "text", "text": f"Updated {args['stem']}: {payload}"}],
        "_ui_action": {"action": "set_stem_state", "args": payload},
    }


@tool("highlight_stem", "Switch which stem is highlighted on the piano roll.", {"stem": str})
async def highlight_stem(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"Highlighted: {args['stem']}"}],
        "_ui_action": {"action": "highlight_stem", "args": {"stem": args["stem"]}},
    }


@tool("open_midi", "Open the MIDI file for a stem in the user's default MIDI handler.", {"stem": str})
async def open_midi_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"Opening {args['stem']}.mid"}],
        "_ui_action": {"action": "open_midi", "args": {"stem": args["stem"]}},
    }


_TAB_CHOICES = {"track", "claude", "lyrics"}


@tool("switch_tab", "Switch the sidebar's active tab. tab must be 'track', 'claude', or 'lyrics'.", {"tab": str})
async def switch_tab(args: dict[str, Any]) -> dict[str, Any]:
    if args["tab"] not in _TAB_CHOICES:
        return {"content": [{"type": "text", "text": f"Unknown tab: {args['tab']}"}], "is_error": True}
    return {
        "content": [{"type": "text", "text": f"Switched to {args['tab']} tab"}],
        "_ui_action": {"action": "switch_tab", "args": {"tab": args["tab"]}},
    }


@tool(
    "highlight_lyric_line",
    "Highlight a specific lyric line by index in the lyrics tab and scroll it into focus.",
    {"index": int},
)
async def highlight_lyric_line(args: dict[str, Any]) -> dict[str, Any]:
    idx = int(args["index"])
    return {
        "content": [{"type": "text", "text": f"Highlighting lyric line #{idx}"}],
        "_ui_action": {"action": "highlight_lyric_line", "args": {"index": idx}},
    }


# Server-only tools — read pipeline artifacts. The chat module imports tracks lazily inside the
# function bodies to avoid a circular import at module load time.

@tool("list_tracks", "List all analyzed tracks in the local library.", {})
async def list_tracks_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    items = [{"slug": t.slug, "title": t.title, "duration_sec": t.duration_sec} for t in _tracks.list_tracks()]
    return {"content": [{"type": "text", "text": json.dumps(items, ensure_ascii=False)}]}


@tool("get_summary", "Return the full summary.json for any track in the library by slug.", {"slug": str})
async def get_summary_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    try:
        s = _tracks.get_summary(args["slug"])
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {args['slug']}"}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(s, ensure_ascii=False)}]}


@tool(
    "find_chord_occurrences",
    "Find all chord occurrences in the current track matching a query (label like 'F:maj' or roman like 'V').",
    {"query": str, "current_slug": str},
)
async def find_chord_occurrences(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    try:
        s = _tracks.get_summary(args["current_slug"])
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {args['current_slug']}"}], "is_error": True}
    q = args["query"].strip()
    hits = []
    for c in s.get("chords") or []:
        if q == c.get("label") or q == c.get("roman"):
            hits.append({"start": c["start"], "end": c["end"], "label": c.get("label"), "roman": c.get("roman")})
    return {"content": [{"type": "text", "text": json.dumps(hits, ensure_ascii=False)}]}


# Lyrics tool — wraps the lyrics module's fetch/cache; emits a UI action on success.

@tool(
    "fetch_lyrics",
    "Look up lyrics for the current track on LRCLIB. Optionally override artist/title for the search.",
    {"current_slug": str, "artist": str, "title": str},
)
async def fetch_lyrics_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import lyrics as _lyrics, tracks as _tracks, _paths
    slug = args["current_slug"]
    try:
        s = _tracks.get_summary(slug)
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {slug}"}], "is_error": True}
    duration = (s.get("track") or {}).get("duration_sec") or 0
    cache = _lyrics.cache_dir_for(_paths.cache_dir() / slug)
    cached = _lyrics.load_cached(cache)
    if cached:
        return {
            "content": [{"type": "text", "text": f"Lyrics already cached (synced={cached['has_sync']})."}],
            "_ui_action": {"action": "reload_lyrics", "args": {}},
        }
    artist = args.get("artist") or ""
    title = args.get("title") or ""
    if not artist or not title:
        windows_path = ((s.get("track") or {}).get("windows_path")) or ""
        if windows_path:
            from pathlib import Path
            ident = _lyrics.identify_track(Path(windows_path), duration_sec=duration)
            artist = artist or ident["artist"]
            title = title or ident["title"]
    result = await _lyrics.lrclib_lookup(artist=artist, title=title, duration_sec=duration)
    meta = {"source": "lrclib", "lrclib_id": result.get("lrclib_id"), "artist": artist, "title": title, "album": "", "duration_sec": duration}
    if result.get("has_sync") and result.get("synced_lrc"):
        _lyrics.save_synced(cache, result["synced_lrc"], meta)
        return {"content": [{"type": "text", "text": "Synced lyrics fetched."}], "_ui_action": {"action": "reload_lyrics", "args": {}}}
    if result.get("plain_text"):
        _lyrics.save_plain(cache, result["plain_text"], meta)
        return {"content": [{"type": "text", "text": "Plain lyrics fetched (no timing)."}], "_ui_action": {"action": "reload_lyrics", "args": {}}}
    return {"content": [{"type": "text", "text": f"No lyrics found ({result.get('error', 'unknown')})."}], "is_error": True}


# All tools wired into one in-process MCP server.
def make_mcp_server():
    return create_sdk_mcp_server(
        name="musiq-tools",
        version="1.0.0",
        tools=[
            seek_to, set_loop_region, set_stem_state, highlight_stem, open_midi_tool,
            switch_tab, highlight_lyric_line,
            list_tracks_tool, get_summary_tool, find_chord_occurrences,
            fetch_lyrics_tool,
        ],
    )


ALLOWED_TOOLS = [
    "mcp__musiq-tools__seek_to",
    "mcp__musiq-tools__set_loop_region",
    "mcp__musiq-tools__set_stem_state",
    "mcp__musiq-tools__highlight_stem",
    "mcp__musiq-tools__open_midi",
    "mcp__musiq-tools__switch_tab",
    "mcp__musiq-tools__highlight_lyric_line",
    "mcp__musiq-tools__list_tracks",
    "mcp__musiq-tools__get_summary",
    "mcp__musiq-tools__find_chord_occurrences",
    "mcp__musiq-tools__fetch_lyrics",
    "WebFetch",
    "WebSearch",
]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/chat.py webui/tests/test_chat.py
git commit -m "feat(webui): add chat tool surface (UI-action + server-only + lyrics)"
```

---

### Task 8: Streaming wrapper around `claude_agent_sdk.query`

**Files:**
- Modify: `webui/webui/chat.py` (append)
- Modify: `webui/tests/test_chat.py` (append)

- [ ] **Step 1: Write failing tests using a mocked SDK iterator**

Append to `webui/tests/test_chat.py`:

```python
import json as _json
from unittest.mock import MagicMock, patch
import pytest

from webui.chat import stream_turn


class _Block:
    pass


class _TextBlock(_Block):
    def __init__(self, text):
        self.text = text


class _ToolUseBlock(_Block):
    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


class _AssistantMessage:
    def __init__(self, content):
        self.content = content


class _ResultMessage:
    def __init__(self, total_cost_usd=0.0, session_id="sid", usage=None):
        self.total_cost_usd = total_cost_usd
        self.session_id = session_id
        self.usage = usage or {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 80}


@pytest.mark.asyncio
async def test_stream_turn_emits_text_and_done():
    async def fake_query(prompt, options=None):
        yield _AssistantMessage([_TextBlock("hello "), _TextBlock("world")])
        yield _ResultMessage()

    with patch("webui.chat.sdk_query", fake_query), \
         patch("webui.chat._isinstance_aware", _aware_for_test([_AssistantMessage, _TextBlock, _ToolUseBlock, _ResultMessage])):
        events = [e async for e in stream_turn(prompt="hi", system_prompt="sys", history=[], allowed_tools=[])]
    types = [e["type"] for e in events]
    assert "text" in types
    assert events[-1]["type"] == "done"
    assert events[-1]["tokens"]["input"] == 100


@pytest.mark.asyncio
async def test_stream_turn_extracts_ui_action_from_tool_result():
    # Simulate Claude calling seek_to: the SDK fires a ToolUseBlock; the SDK's
    # in-process MCP machinery executes the @tool function and feeds its
    # `content` back into Claude. Our wrapper must (a) emit a tool_use event
    # and (b) detect _ui_action from the tool's return dict and emit ui_action.
    # We simulate this by patching the runtime so stream_turn observes both
    # the ToolUseBlock and our injected tool-result via the wrapper hook.

    async def fake_query(prompt, options=None):
        yield _AssistantMessage([_ToolUseBlock(id="tu1", name="mcp__musiq-tools__seek_to", input={"time_sec": 12.0})])
        yield _ResultMessage()

    fake_tool_result = {
        "tu1": {"_ui_action": {"action": "seek_to", "args": {"time_sec": 12.0}}, "content": [{"type": "text", "text": "queued"}]}
    }
    with patch("webui.chat.sdk_query", fake_query), \
         patch("webui.chat._tool_result_capture", fake_tool_result), \
         patch("webui.chat._isinstance_aware", _aware_for_test([_AssistantMessage, _TextBlock, _ToolUseBlock, _ResultMessage])):
        events = [e async for e in stream_turn(prompt="seek please", system_prompt="sys", history=[], allowed_tools=["mcp__musiq-tools__seek_to"])]
    actions = [e for e in events if e["type"] == "ui_action"]
    assert len(actions) == 1
    assert actions[0]["action"] == "seek_to"
    assert actions[0]["args"]["time_sec"] == 12.0


def _aware_for_test(expected_types):
    """Helper: return an isinstance-aware predicate keyed off test stub class names.
    The wrapper imports SDK types lazily via a module-level _isinstance_aware
    callable that we override during tests."""
    def aware(obj, cls_name):
        return type(obj).__name__ == cls_name
    return aware
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v -k stream_turn
```

Expected: FAIL — `stream_turn` doesn't exist.

- [ ] **Step 3: Append the streaming wrapper to `webui/webui/chat.py`**

```python
from collections.abc import AsyncIterator
from claude_agent_sdk import query as sdk_query, ClaudeAgentOptions
from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, ResultMessage


# Module-level hooks for test injection.
def _isinstance_aware(obj, cls_name: str) -> bool:
    return isinstance(obj, {
        "AssistantMessage": AssistantMessage,
        "TextBlock": TextBlock,
        "ToolUseBlock": ToolUseBlock,
        "ResultMessage": ResultMessage,
    }[cls_name])


# Per-process tool-result capture: keyed by tool_use_id, holds the dict the
# tool function returned (including the private _ui_action). Populated by a
# wrapper layer set up in stream_turn before the SDK runs.
_tool_result_capture: dict[str, dict] = {}


async def stream_turn(
    *, prompt: str, system_prompt: str, history: list[dict], allowed_tools: list[str], cwd: str | None = None,
) -> AsyncIterator[dict]:
    """Run one Claude turn, yielding NDJSON events.

    Event shapes:
      {"type": "text", "delta": str}
      {"type": "tool_use", "id": str, "name": str, "input": dict}
      {"type": "ui_action", "id": str, "action": str, "args": dict}
      {"type": "tool_result", "id": str, "ok": bool, "summary": str}
      {"type": "done", "tokens": {"input": int, "output": int, "cache_read": int}, "session_id": str}
      {"type": "error", "message": str, "kind": str}
      {"type": "auth_required"}
    """
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"musiq-tools": make_mcp_server()},
        allowed_tools=allowed_tools,
        # Conversation history is replayed by the SDK via the prompt parameter; we use
        # message-list form when history is non-empty (see assemble_prompt below).
    )
    if cwd is not None:
        options = ClaudeAgentOptions(**{**options.__dict__, "cwd": cwd})  # SDK options are not frozen
    full_prompt = assemble_prompt(history, prompt)

    seen_tool_use_ids: set[str] = set()

    try:
        async for msg in sdk_query(prompt=full_prompt, options=options):
            if _isinstance_aware(msg, "AssistantMessage"):
                for block in msg.content:
                    if _isinstance_aware(block, "TextBlock"):
                        yield {"type": "text", "delta": block.text}
                    elif _isinstance_aware(block, "ToolUseBlock"):
                        seen_tool_use_ids.add(block.id)
                        yield {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input)}
                        # If the tool function has already populated _tool_result_capture,
                        # emit ui_action right here. Otherwise wait until the next message.
                        captured = _tool_result_capture.pop(block.id, None)
                        if captured and "_ui_action" in captured:
                            yield {
                                "type": "ui_action",
                                "id": block.id,
                                "action": captured["_ui_action"]["action"],
                                "args": captured["_ui_action"]["args"],
                            }
                            yield {"type": "tool_result", "id": block.id, "ok": not captured.get("is_error"), "summary": _summarize_tool_result(captured)}
            elif _isinstance_aware(msg, "ResultMessage"):
                # Drain any remaining captured tool results that arrived after their ToolUseBlock.
                for tu_id in list(_tool_result_capture.keys()):
                    captured = _tool_result_capture.pop(tu_id, None)
                    if captured and "_ui_action" in captured:
                        yield {
                            "type": "ui_action", "id": tu_id,
                            "action": captured["_ui_action"]["action"],
                            "args": captured["_ui_action"]["args"],
                        }
                usage = getattr(msg, "usage", None) or {}
                yield {
                    "type": "done",
                    "session_id": getattr(msg, "session_id", None),
                    "tokens": {
                        "input": usage.get("input_tokens", 0),
                        "output": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                    },
                }
    except Exception as e:  # noqa: BLE001
        kind, message = _classify_exception(e)
        if kind == "auth":
            yield {"type": "auth_required"}
        else:
            yield {"type": "error", "kind": kind, "message": message}


def assemble_prompt(history: list[dict], new_user_text: str) -> str | list[dict]:
    """If history is empty, send the user text as a string. Otherwise, send a
    list-of-messages so the SDK replays them. Each history entry is shaped
    {"role": "user"|"assistant", "blocks": [...]}; we flatten back to the
    SDK's accepted schema."""
    if not history:
        return new_user_text
    messages: list[dict] = []
    for h in history:
        # The SDK accepts {role, content} in stream-input mode; content is a string or block list.
        messages.append({"role": h["role"], "content": _flatten_blocks_for_sdk(h["blocks"])})
    messages.append({"role": "user", "content": new_user_text})
    return messages


def _flatten_blocks_for_sdk(blocks: list[dict]) -> str:
    # Concise text-only flattening — tool_use/tool_result blocks are stored for our
    # transcript display but are not replayed to the SDK as historical context;
    # text turns alone are enough for Claude to maintain conversational continuity
    # and avoids re-running tool effects.
    out = []
    for b in blocks:
        if b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out).strip()


def _summarize_tool_result(captured: dict) -> str:
    blocks = captured.get("content") or []
    for b in blocks:
        if b.get("type") == "text":
            t = b.get("text", "")
            return t[:200]
    return ""


def _classify_exception(e: Exception) -> tuple[str, str]:
    s = str(e).lower()
    if "login" in s or "credential" in s or "unauthor" in s or "auth" in s:
        return "auth", str(e)
    if "timeout" in s or "connect" in s:
        return "network", str(e)
    return "internal", str(e)
```

Note: `_tool_result_capture` is a simple module-level dict because `query()` is one-call-per-turn and the chat route uses a single-flight lock. Concurrent turns are rejected with 409, so there's no cross-turn contamination.

The capture mechanism: when an `@tool`-decorated coroutine is invoked by the SDK's MCP runtime, we wrap each tool function with a small adapter that stores its return dict by `tool_use_id`. That adapter registration happens in `make_mcp_server()` — modify it now:

```python
# Replace the existing make_mcp_server() body with this:
def make_mcp_server():
    base_tools = [
        seek_to, set_loop_region, set_stem_state, highlight_stem, open_midi_tool,
        switch_tab, highlight_lyric_line,
        list_tracks_tool, get_summary_tool, find_chord_occurrences,
        fetch_lyrics_tool,
    ]
    wrapped = [_wrap_for_capture(t) for t in base_tools]
    return create_sdk_mcp_server(name="musiq-tools", version="1.0.0", tools=wrapped)


def _wrap_for_capture(tool_fn):
    """Wrap an @tool-decorated coroutine so its return dict is captured for
    later UI-action extraction. The wrapper preserves the @tool metadata."""
    inner = tool_fn  # already decorated; inner takes (args, tool_use_id?) per SDK convention
    async def wrapped(args: dict[str, Any], _meta: dict | None = None):
        result = await inner(args) if not _meta else await inner(args, _meta)
        tu_id = (_meta or {}).get("tool_use_id")
        if tu_id:
            _tool_result_capture[tu_id] = result
        return result
    # Preserve the SDK's introspection metadata if present on the original.
    for attr in ("__tool_name__", "__tool_description__", "__tool_schema__", "__name__"):
        if hasattr(tool_fn, attr):
            setattr(wrapped, attr, getattr(tool_fn, attr))
    return wrapped
```

If the SDK version in use doesn't pass `_meta` with `tool_use_id` to MCP tool functions, the executor must verify with a one-line debug print in `_wrap_for_capture` and adjust. Document the actual signature found and proceed accordingly. The contract is: we need access to the `tool_use_id` at tool-execution time. If the SDK exposes it differently, route the same data through that channel.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/chat.py webui/tests/test_chat.py
git commit -m "feat(webui): NDJSON streaming wrapper around claude-agent-sdk.query"
```

---

### Task 9: Chat history persistence

**Files:**
- Modify: `webui/webui/chat.py` (append)
- Modify: `webui/tests/test_chat.py` (append)

- [ ] **Step 1: Write failing tests for chat persistence**

Append to `webui/tests/test_chat.py`:

```python
from webui.chat import load_history, append_user_message, append_assistant_message, clear_history


def test_load_history_missing_returns_empty(tmp_path):
    assert load_history(tmp_path / "chat.json") == []


def test_append_and_load_roundtrip(tmp_path):
    p = tmp_path / "chat.json"
    append_user_message(p, "hello")
    append_assistant_message(p, blocks=[{"type": "text", "text": "hi back"}])
    h = load_history(p)
    assert len(h) == 2
    assert h[0]["role"] == "user"
    assert h[0]["blocks"][0]["text"] == "hello"
    assert h[1]["role"] == "assistant"
    assert h[1]["blocks"][0]["text"] == "hi back"


def test_clear_history_removes_file(tmp_path):
    p = tmp_path / "chat.json"
    append_user_message(p, "hello")
    clear_history(p)
    assert not p.exists()


def test_corrupt_json_treated_as_empty_with_backup(tmp_path):
    p = tmp_path / "chat.json"
    p.write_text("not json", encoding="utf-8")
    h = load_history(p)
    assert h == []
    backups = list(tmp_path.glob("chat.json.bak.*"))
    assert len(backups) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v -k history
```

Expected: FAIL — persistence functions don't exist.

- [ ] **Step 3: Append persistence helpers to `webui/webui/chat.py`**

```python
from pathlib import Path
import os
import time


CHAT_SCHEMA_VERSION = 1


def load_history(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("messages", [])
    except (json.JSONDecodeError, OSError):
        ts = int(time.time())
        backup = path.with_suffix(path.suffix + f".bak.{ts}")
        try:
            path.rename(backup)
        except OSError:
            pass
        return []


def _save_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _save_history(path: Path, messages: list[dict], session_id: str | None = None) -> None:
    payload = {"schema_version": CHAT_SCHEMA_VERSION, "messages": messages}
    if session_id:
        payload["last_session_id"] = session_id
    _save_atomic(path, payload)


def append_user_message(path: Path, text: str) -> None:
    h = load_history(path)
    h.append({"role": "user", "blocks": [{"type": "text", "text": text}], "ts": _utc_now_iso_chat()})
    _save_history(path, h)


def append_assistant_message(path: Path, blocks: list[dict], session_id: str | None = None) -> None:
    h = load_history(path)
    h.append({"role": "assistant", "blocks": blocks, "ts": _utc_now_iso_chat()})
    _save_history(path, h, session_id=session_id)


def clear_history(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _utc_now_iso_chat() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/chat.py webui/tests/test_chat.py
git commit -m "feat(webui): chat history persistence with corrupt-file backup"
```

---

## Phase 4 — Server routes (TDD)

### Task 10: Lyrics routes

**Files:**
- Modify: `webui/webui/server.py`
- Modify: `webui/tests/test_server.py`

- [ ] **Step 1: Write failing tests for the lyrics routes**

Append to `webui/tests/test_server.py` (use the existing `_client` and `synthetic_cache` fixtures):

```python
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


def test_lyrics_fetch_calls_lrclib(synthetic_cache):
    async def fake_lookup(*, artist, title, duration_sec, album="", _transport=None):
        return {
            "source": "lrclib", "has_sync": True,
            "synced_lrc": "[00:01.00]hello\n", "plain_text": "hello",
            "lrclib_id": 42,
        }

    c = _client(synthetic_cache)
    with patch("webui.lyrics.lrclib_lookup", fake_lookup):
        r = c.post("/api/tracks/demo/lyrics/fetch", json={"artist": "A", "title": "T"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_sync"] is True
    assert body["meta"]["lrclib_id"] == 42


def test_lyrics_delete(synthetic_cache):
    c = _client(synthetic_cache)
    c.post("/api/tracks/demo/lyrics/paste", json={"text": "hello"})
    r = c.delete("/api/tracks/demo/lyrics")
    assert r.status_code == 200
    g = c.get("/api/tracks/demo/lyrics")
    assert g.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v -k lyrics
```

Expected: FAIL — routes don't exist.

- [ ] **Step 3: Add the lyrics routes to `webui/webui/server.py`**

Append (after the existing reanalyze block):

```python
# --- Lyrics ----------------------------------------------------------------
from . import lyrics as _lyrics


def _lyrics_cache(slug: str) -> Path:
    return _lyrics.cache_dir_for(_paths.cache_dir() / slug)


@app.get("/api/tracks/{slug}/lyrics")
def api_lyrics_get(slug: str) -> dict:
    cache = _lyrics_cache(slug)
    cached = _lyrics.load_cached(cache)
    if not cached:
        raise HTTPException(status_code=404, detail="no lyrics cached")
    return cached


@app.delete("/api/tracks/{slug}/lyrics")
def api_lyrics_delete(slug: str) -> dict:
    _lyrics.clear_cache(_lyrics_cache(slug))
    return {"cleared": slug}


@app.post("/api/tracks/{slug}/lyrics/fetch")
async def api_lyrics_fetch(slug: str, request: Request) -> dict:
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")
    duration = (summary.get("track") or {}).get("duration_sec") or 0
    raw = await request.body()
    overrides = json.loads(raw or b"{}") if raw else {}
    artist = overrides.get("artist") or ""
    title = overrides.get("title") or ""
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
    raw = await request.body()
    payload = json.loads(raw or b"{}")
    text = (payload or {}).get("text") or ""
    if not text:
        raise HTTPException(status_code=400, detail="empty paste")
    cache = _lyrics_cache(slug)
    meta = {
        "source": "user_paste",
        "lrclib_id": None,
        "artist": "", "title": "", "album": "", "duration_sec": 0,
    }
    _lyrics.save_paste(cache, text, meta)
    return _lyrics.load_cached(cache)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v
```

Expected: all existing + 4 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): add lyrics REST routes (get/fetch/paste/delete)"
```

---

### Task 11: Chat routes

**Files:**
- Modify: `webui/webui/server.py`
- Modify: `webui/tests/test_server.py`

- [ ] **Step 1: Write failing tests for the chat routes**

Append to `webui/tests/test_server.py`:

```python
import asyncio


def test_chat_history_initially_empty(synthetic_cache):
    c = _client(synthetic_cache)
    r = c.get("/api/chat/demo")
    assert r.status_code == 200
    assert r.json() == {"messages": []}


def test_chat_clear(synthetic_cache):
    c = _client(synthetic_cache)
    # Can't run a real chat turn here without the SDK; just verify clear returns 200.
    r = c.delete("/api/chat/demo")
    assert r.status_code == 200


def test_chat_turn_streams_with_mocked_sdk(synthetic_cache, monkeypatch):
    # Patch stream_turn to yield a scripted event sequence.
    async def fake_stream(**kwargs):
        yield {"type": "text", "delta": "hi"}
        yield {"type": "text", "delta": " there"}
        yield {"type": "done", "session_id": "sid", "tokens": {"input": 10, "output": 5, "cache_read": 0}}

    monkeypatch.setattr("webui.chat.stream_turn", fake_stream)
    c = _client(synthetic_cache)
    payload = {"text": "hello", "view_state": {"playhead_sec": 1.0}}
    r = c.post("/api/chat/demo/turn", json=payload)
    assert r.status_code == 200
    body = r.text.strip().splitlines()
    parsed = [json.loads(line) for line in body]
    assert parsed[0]["type"] == "text"
    assert parsed[-1]["type"] == "done"


def test_chat_turn_busy_returns_409(synthetic_cache, monkeypatch):
    # Force the lock to look held.
    from webui import chat as chat_mod
    monkeypatch.setattr(chat_mod, "_chat_lock_held", lambda: True)
    c = _client(synthetic_cache)
    r = c.post("/api/chat/demo/turn", json={"text": "hi"})
    assert r.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v -k chat
```

Expected: FAIL — routes don't exist.

- [ ] **Step 3: Add the chat routes to `webui/webui/server.py`**

Append:

```python
# --- Chat ------------------------------------------------------------------
import asyncio as _asyncio
from . import chat as _chat


_chat_lock = _asyncio.Lock()
# Function indirection so tests can monkeypatch lock state.
def _chat_lock_held() -> bool:
    return _chat_lock.locked()
_chat.__dict__["_chat_lock_held"] = _chat_lock_held


def _chat_path(slug: str) -> Path:
    return _paths.cache_dir() / slug / "chat.json"


@app.get("/api/chat/{slug}")
def api_chat_history(slug: str) -> dict:
    return {"messages": _chat.load_history(_chat_path(slug))}


@app.delete("/api/chat/{slug}")
def api_chat_clear(slug: str) -> dict:
    _chat.clear_history(_chat_path(slug))
    return {"cleared": slug}


@app.post("/api/chat/{slug}/turn")
async def api_chat_turn(slug: str, request: Request) -> StreamingResponse:
    if _chat_lock_held():
        raise HTTPException(status_code=409, detail="chat_busy")
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")
    payload = json.loads(await request.body())
    user_text = payload.get("text") or ""
    view_state = payload.get("view_state")

    chat_path = _chat_path(slug)
    history = _chat.load_history(chat_path)
    system_prompt = _chat.build_system_prompt(summary)
    user_message = _chat.build_user_message(user_text, view_state)

    async def gen():
        async with _chat_lock:
            _chat.append_user_message(chat_path, user_message)
            collected_text: list[str] = []
            collected_blocks: list[dict] = []
            session_id_seen: str | None = None
            async for ev in _chat.stream_turn(
                prompt=user_message,
                system_prompt=system_prompt,
                history=history,
                allowed_tools=_chat.ALLOWED_TOOLS,
            ):
                if ev["type"] == "text":
                    collected_text.append(ev["delta"])
                if ev["type"] == "tool_use":
                    collected_blocks.append({"type": "tool_use", "id": ev["id"], "name": ev["name"], "input": ev["input"]})
                if ev["type"] == "tool_result":
                    collected_blocks.append({"type": "tool_result", "id": ev["id"], "ok": ev["ok"], "summary": ev["summary"]})
                if ev["type"] == "done":
                    session_id_seen = ev.get("session_id")
                yield (json.dumps(ev) + "\n").encode("utf-8")
            assistant_blocks = (
                ([{"type": "text", "text": "".join(collected_text)}] if collected_text else [])
                + collected_blocks
            )
            if assistant_blocks:
                _chat.append_assistant_message(chat_path, blocks=assistant_blocks, session_id=session_id_seen)

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v
```

Expected: all existing + 4 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): chat REST routes — turn/history/clear with NDJSON streaming"
```

---

### Task 12: Preserve `chat.json` and `lyrics/` across reanalysis

**Files:**
- Modify: `webui/webui/server.py:213` (`_clear_cache_dir`)
- Modify: `webui/tests/test_server.py`

- [ ] **Step 1: Write a failing regression test**

Append to `webui/tests/test_server.py`:

```python
def test_clear_cache_dir_preserves_chat_and_lyrics(synthetic_cache):
    from webui.server import _clear_cache_dir
    cache = synthetic_cache / "demo"
    (cache / "chat.json").write_text('{"schema_version":1,"messages":[]}', encoding="utf-8")
    lyr = cache / "lyrics"
    lyr.mkdir(parents=True, exist_ok=True)
    (lyr / "synced.lrc").write_text("[00:01.00]hello\n", encoding="utf-8")
    # Simulate other artifacts that should be wiped:
    (cache / "summary.json").write_text("{}", encoding="utf-8")
    (cache / "stems_6s").mkdir(exist_ok=True)
    (cache / "stems_6s" / "x.wav").write_bytes(b"")
    _clear_cache_dir(cache)
    assert (cache / "chat.json").is_file()
    assert (cache / "lyrics" / "synced.lrc").is_file()
    assert not (cache / "summary.json").is_file()
    assert not (cache / "stems_6s").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v -k preserves_chat_and_lyrics
```

Expected: FAIL — current `_clear_cache_dir` wipes everything.

- [ ] **Step 3: Update `_clear_cache_dir` in `webui/webui/server.py`**

Replace the function body at line ~213:

```python
def _clear_cache_dir(cache: Path) -> None:
    PRESERVE = {"chat.json", "lyrics"}
    for child in cache.iterdir():
        if child.name in PRESERVE:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd webui && .venv/Scripts/python -m pytest tests/test_server.py -v
```

Expected: all tests PASS, including existing reanalyze tests (preserve set is additive — it only changes which items survive the clear).

- [ ] **Step 5: Commit**

```bash
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): preserve chat.json and lyrics/ across reanalysis"
```

---

## Phase 5 — Frontend tab shell

### Task 13: Tab strip CSS + `tabs.js` component

**Files:**
- Create: `webui/static/js/ui/tabs.js`
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Add tab-strip styles to `webui/static/css/track.css`**

Append to `webui/static/css/track.css`:

```css
/* ---- Sidebar tab strip ----------------------------------------------- */
.tab-strip {
  display: flex;
  border-bottom: 1px solid var(--bg-3);
  background: var(--bg-1);
}
.tab-strip .tab {
  flex: 1;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--ls-caps);
  color: var(--fg-2);
  font-weight: 600;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  text-align: center;
}
.tab-strip .tab:hover { color: var(--fg-1); }
.tab-strip .tab.active {
  color: var(--fg-1);
  border-bottom-color: var(--c-vocals);
}
.tab-panel { display: none; }
.tab-panel.active { display: block; }
```

- [ ] **Step 2: Create `webui/static/js/ui/tabs.js`**

```js
import { el } from "./dom.js";

/**
 * TabBar — manages a horizontal tab strip and a panel container that
 * shows one panel at a time. Each tab gets a host element (a div) that
 * persists across activations; consumers render into it.
 */
export class TabBar {
  constructor(host, tabs, opts = {}) {
    this.host = host;
    this.tabs = tabs; // [{ id, label, onActivate?, onDeactivate? }]
    this.opts = opts;
    this.panelHosts = new Map();
    this._currentId = null;
    this._build();
  }

  _build() {
    this.strip = el("div", { class: "tab-strip" });
    this.panels = el("div", { class: "tab-panels" });
    this.host.appendChild(this.strip);
    this.host.appendChild(this.panels);

    for (const t of this.tabs) {
      const btn = el("button", {
        class: "tab",
        text: t.label,
        attrs: { type: "button", "data-tab": t.id },
        onClick: () => this.activate(t.id),
      });
      this.strip.appendChild(btn);
      const panel = el("div", { class: "tab-panel", attrs: { "data-tab": t.id } });
      this.panels.appendChild(panel);
      this.panelHosts.set(t.id, panel);
    }
  }

  /** Returns the host element (div) for tab `id`, even when inactive. */
  panelFor(id) { return this.panelHosts.get(id); }

  current() { return this._currentId; }

  activate(id) {
    if (this._currentId === id) return;
    if (!this.panelHosts.has(id)) return;
    const prev = this.tabs.find((t) => t.id === this._currentId);
    if (prev?.onDeactivate) prev.onDeactivate();
    for (const btn of this.strip.querySelectorAll(".tab")) {
      btn.classList.toggle("active", btn.dataset.tab === id);
    }
    for (const p of this.panels.querySelectorAll(".tab-panel")) {
      p.classList.toggle("active", p.dataset.tab === id);
    }
    this._currentId = id;
    const next = this.tabs.find((t) => t.id === id);
    if (next?.onActivate) next.onActivate();
    if (this.opts.persist) {
      try { localStorage.setItem(this.opts.persist, id); } catch {}
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add webui/static/js/ui/tabs.js webui/static/css/track.css
git commit -m "feat(webui): TabBar component + tab-strip styles"
```

---

### Task 14: `tabbed-sidebar.js` orchestrator + swap into `main.js`

**Files:**
- Create: `webui/static/js/ui/tabbed-sidebar.js`
- Modify: `webui/static/js/main.js`
- Modify: `webui/static/js/ui/sidebar.js` (no source changes — just confirm it works as a panel renderer)

- [ ] **Step 1: Create `webui/static/js/ui/tabbed-sidebar.js`**

```js
import { TabBar } from "./tabs.js";
import { Sidebar } from "./sidebar.js";

const STORAGE_KEY = "musiq:activeTab";

/**
 * TabbedSidebar wraps the existing Sidebar (Tab 1) and stubs Tabs 2 + 3.
 * The Tab 2 (Claude) and Tab 3 (Lyrics) panels are populated by their
 * dedicated modules in later tasks.
 */
export class TabbedSidebar {
  constructor(host) {
    this.host = host;
    this.bar = null;
    this.trackSidebar = null;
    this.claudeTab = null;
    this.lyricsTab = null;
  }

  mount(trackData, viewState, engine) {
    this.host.replaceChildren();
    this.bar = new TabBar(this.host, [
      { id: "track", label: "Track" },
      { id: "claude", label: "Claude" },
      { id: "lyrics", label: "Lyrics" },
    ], { persist: STORAGE_KEY });

    // Tab 1 — existing sidebar
    this.trackSidebar = new Sidebar(this.bar.panelFor("track"));
    this.trackSidebar.mount(trackData, viewState, engine);

    // Tab 2 + 3 placeholders — replaced by claude-tab.js / lyrics-tab.js mounts later.
    this.bar.panelFor("claude").replaceChildren();
    this.bar.panelFor("lyrics").replaceChildren();

    // Restore last-used tab.
    let active = "track";
    try { active = localStorage.getItem(STORAGE_KEY) || "track"; } catch {}
    this.bar.activate(active);
  }

  // Pass-through methods the rest of main.js calls.
  setCurrentTime(t) {
    this.trackSidebar?.setCurrentTime(t);
    this.lyricsTab?.setCurrentTime?.(t);
  }
  setStemStatus(name, status, detail) {
    this.trackSidebar?.setStemStatus(name, status, detail);
  }
  get stemStatus() { return this.trackSidebar?.stemStatus ?? {}; }
}
```

- [ ] **Step 2: Update `main.js` to use TabbedSidebar**

In `webui/static/js/main.js`:

Replace the import (around line 9):

```js
import { Sidebar } from "./ui/sidebar.js";
```

With:

```js
import { TabbedSidebar } from "./ui/tabbed-sidebar.js";
```

And replace the mount line (around line 157):

```js
sidebar = new Sidebar(side);
sidebar.mount(trackData, viewState, engine);
```

With:

```js
sidebar = new TabbedSidebar(side);
sidebar.mount(trackData, viewState, engine);
```

(The variable name `sidebar` and its public interface remain identical, so all the `engine.on(...)` callbacks at lines 115-129 keep working.)

- [ ] **Step 3: Manual smoke**

```bash
cd webui && .venv/Scripts/python -m webui --port 8765
```

Open `http://127.0.0.1:8765/`. Expected:
- Sidebar shows three tabs: Track / Claude / Lyrics.
- Track tab is active by default and shows the existing sections (Now playing, Stems, Loop, Function, Harmony stats).
- Clicking Claude or Lyrics shows an empty panel (placeholder).
- Refreshing keeps the last-used tab.
- Take a screenshot and save under `tests/screenshots/sidebar-tabs/01-shell.png`.

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/ui/tabbed-sidebar.js webui/static/js/main.js tests/screenshots/sidebar-tabs/01-shell.png
git commit -m "feat(webui): tabbed sidebar shell — Track tab populated, Claude/Lyrics placeholders"
```

---

## Phase 6 — View-state loop region (cross-cutting)

### Task 15: View-state additions + engine playback honoring loop

**Files:**
- Modify: `webui/static/js/view/view-state.js`
- Modify: `webui/static/js/audio/web-audio-engine.js`

- [ ] **Step 1: Add loop fields and methods to view-state**

In `webui/static/js/view/view-state.js`, add these properties to the state object (within `createViewState` or its constructor):

```js
this.loopStart = null; // seconds | null
this.loopEnd = null;   // seconds | null

this.setLoop = function(start, end) {
  this.loopStart = start;
  this.loopEnd = end;
  this._emit("change");
}.bind(this);

this.clearLoop = function() {
  this.loopStart = null;
  this.loopEnd = null;
  this._emit("change");
}.bind(this);
```

(Adapt to the actual shape of `view-state.js`; the executor reads the existing module first to match its style.)

- [ ] **Step 2: Make the audio engine honor the loop region**

In `webui/static/js/audio/web-audio-engine.js`, add a `setLoop(start, end)` and `clearLoop()` method. In the per-frame `time` emitter, before emitting `time`, check:

```js
if (this._loopEnd != null && t >= this._loopEnd) {
  this.seek(this._loopStart);
  return; // skip emitting `time` for this frame; next tick will pick up the new position
}
```

Wire `view-state.on("change", ...)` from `main.js` to call `engine.setLoop(viewState.loopStart, viewState.loopEnd)` whenever the loop fields change.

- [ ] **Step 3: Manual smoke**

In the browser console:

```js
window.__currentSlug;  // confirm loaded
// (Open dev tools and use the live engine + viewState refs hung off the module.)
```

For an explicit smoke without a UI yet: temporarily add a button in `transport.js` that calls `viewState.setLoop(10, 20)` and play. Confirm playback wraps from 20→10. Remove the button after verification (or keep it as a placeholder for Task 17).

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/view/view-state.js webui/static/js/audio/web-audio-engine.js
git commit -m "feat(webui): view-state loop region + engine wraparound"
```

---

### Task 16: Loop band overlay on pianoroll + minimap

**Files:**
- Modify: `webui/static/js/render/pianoroll.js`
- Modify: `webui/static/js/ui/minimap.js`

- [ ] **Step 1: Add loop band rendering to `pianoroll.js`**

In the canvas draw loop, after rendering chord/notes and before the playhead, draw a translucent band when `viewState.loopStart != null`:

```js
if (viewState.loopStart != null && viewState.loopEnd != null) {
  const xs = timeToX(viewState.loopStart, viewState);
  const xe = timeToX(viewState.loopEnd, viewState);
  ctx.fillStyle = "rgba(255, 184, 107, 0.10)";
  ctx.fillRect(xs, 0, xe - xs, canvas.height);
  ctx.strokeStyle = "rgba(255, 184, 107, 0.40)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(xs + 0.5, 0); ctx.lineTo(xs + 0.5, canvas.height);
  ctx.moveTo(xe - 0.5, 0); ctx.lineTo(xe - 0.5, canvas.height);
  ctx.stroke();
}
```

Trigger a redraw when `view-state.on("change")` fires (existing wiring already does this for scroll/zoom changes).

- [ ] **Step 2: Add the same band to `minimap.js`**

In the minimap's draw routine, scaled to the minimap's coordinate system (full-track horizontal mapping):

```js
if (viewState.loopStart != null) {
  const xs = (viewState.loopStart / duration) * canvas.width;
  const xe = (viewState.loopEnd / duration) * canvas.width;
  ctx.fillStyle = "rgba(255, 184, 107, 0.18)";
  ctx.fillRect(xs, 0, xe - xs, canvas.height);
}
```

- [ ] **Step 3: Manual smoke**

Set `viewState.setLoop(10, 30)` in the console; confirm a translucent band appears over the canvas and minimap. Save screenshot to `tests/screenshots/sidebar-tabs/02-loop-band.png`.

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/render/pianoroll.js webui/static/js/ui/minimap.js tests/screenshots/sidebar-tabs/02-loop-band.png
git commit -m "feat(webui): loop band overlay on pianoroll + minimap"
```

---

### Task 17: Transport loop chip

**Files:**
- Modify: `webui/static/js/ui/transport.js`
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Add the loop chip to transport**

In `transport.js`, in the mount routine, append a span that's hidden by default. On `view-state.on("change")`, update its text and visibility:

```js
const loopChip = el("button", { class: "loop-chip", attrs: { type: "button", title: "Click to clear loop" } });
loopChip.style.display = "none";
loopChip.addEventListener("click", () => viewState.clearLoop());
host.appendChild(loopChip);

const refresh = () => {
  if (viewState.loopStart == null) {
    loopChip.style.display = "none";
    return;
  }
  loopChip.textContent = `Loop ${fmtTime(viewState.loopStart)}–${fmtTime(viewState.loopEnd)} ✕`;
  loopChip.style.display = "";
};
viewState.on("change", refresh);
refresh();
```

`fmtTime` already exists in `transport.js`; if not, define it as `(t) => { const m = Math.floor(t/60); const s = (t-m*60).toFixed(2).padStart(5,"0"); return `${m}:${s}`; }`.

- [ ] **Step 2: CSS for the chip**

Append to `webui/static/css/track.css`:

```css
.loop-chip {
  font-size: 11px;
  color: #ffb86b;
  background: rgba(255, 184, 107, 0.12);
  border: 1px solid rgba(255, 184, 107, 0.35);
  border-radius: 9999px;
  padding: 3px 9px;
  cursor: pointer;
  margin-left: 8px;
}
.loop-chip:hover { background: rgba(255, 184, 107, 0.22); }
```

- [ ] **Step 3: Manual smoke**

Set a loop region; verify the chip appears in the transport, shows correct times, clicking it clears the loop. Save `tests/screenshots/sidebar-tabs/03-loop-chip.png`.

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/ui/transport.js webui/static/css/track.css tests/screenshots/sidebar-tabs/03-loop-chip.png
git commit -m "feat(webui): transport loop chip with click-to-clear"
```

---

## Phase 7 — Lyrics tab (Tab 3)

### Task 18: Lyrics tab skeleton, lazy fetch, render

**Files:**
- Create: `webui/static/js/ui/lyrics-tab.js`
- Modify: `webui/static/js/api.js` (add lyrics wrappers)
- Modify: `webui/static/js/ui/tabbed-sidebar.js` (mount lyrics tab)

- [ ] **Step 1: Add lyrics API wrappers**

Append to `webui/static/js/api.js`:

```js
async function getLyrics(slug) {
  const r = await fetch(`/api/tracks/${encodeURIComponent(slug)}/lyrics`);
  if (r.status === 404) return null;
  if (!r.ok) throw httpError(r);
  return r.json();
}
async function fetchLyrics(slug, body = {}) {
  const r = await fetch(`/api/tracks/${encodeURIComponent(slug)}/lyrics/fetch`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw httpError(r);
  return r.json();
}
async function pasteLyrics(slug, text) {
  const r = await fetch(`/api/tracks/${encodeURIComponent(slug)}/lyrics/paste`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
  });
  if (!r.ok) throw httpError(r);
  return r.json();
}
async function deleteLyrics(slug) {
  const r = await fetch(`/api/tracks/${encodeURIComponent(slug)}/lyrics`, { method: "DELETE" });
  if (!r.ok) throw httpError(r);
  return r.json();
}
// add to the `api` export object:
//   getLyrics, fetchLyrics, pasteLyrics, deleteLyrics
```

- [ ] **Step 2: Create `webui/static/js/ui/lyrics-tab.js`**

```js
import { el, clear } from "./dom.js";
import { api } from "../api.js";

export class LyricsTab {
  constructor(host) {
    this.host = host;
    this.slug = null;
    this.engine = null;
    this.viewState = null;
    this.data = null;          // { has_sync, lines, plain_text, meta }
    this.activeIndex = -1;
    this._scrollSuspendedUntil = 0;
    this._fetchInFlight = false;
    this._mounted = false;
  }

  mount(trackData, viewState, engine) {
    this.slug = trackData.meta.slug;
    this.viewState = viewState;
    this.engine = engine;
    this._mounted = true;
    this._render();
    this._lazyLoad();
  }

  // Called when tab is activated.
  onActivate() {
    if (!this.data && !this._fetchInFlight) this._lazyLoad();
  }

  setCurrentTime(t) {
    if (!this.data?.has_sync) return;
    const lines = this.data.lines;
    if (!lines.length) return;
    // Binary search for the active line.
    let lo = 0, hi = lines.length - 1, idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].time_sec <= t) { idx = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    if (idx !== this.activeIndex) {
      this.activeIndex = idx;
      this._refreshActive();
    }
  }

  highlightLineByIndex(idx) {
    this.activeIndex = idx;
    this._refreshActive(true /* force scroll */);
  }

  async _lazyLoad() {
    this._fetchInFlight = true;
    try {
      const cached = await api.getLyrics(this.slug);
      if (cached) {
        this.data = cached;
        this._render();
        return;
      }
      // First-open fetch from LRCLIB.
      const fetched = await api.fetchLyrics(this.slug, {});
      this.data = fetched;
      this._render();
    } catch (e) {
      this._renderError(e.message || "fetch failed");
    } finally {
      this._fetchInFlight = false;
    }
  }

  _render() {
    clear(this.host);
    const header = this._buildHeader();
    const scroll = el("div", { class: "lyrics-scroll" });
    this.host.appendChild(header);
    this.host.appendChild(scroll);
    this._scrollEl = scroll;

    if (!this.data) {
      scroll.appendChild(el("div", { class: "lyrics-empty", text: "Loading lyrics…" }));
      return;
    }
    if (this.data.has_sync) {
      this.data.lines.forEach((line, i) => {
        const lineEl = el("div", {
          class: "lyric-line",
          text: line.text || "·",
          attrs: { "data-i": String(i) },
          onClick: () => this.engine?.seek(line.time_sec),
        });
        scroll.appendChild(lineEl);
      });
    } else if (this.data.plain_text) {
      const pre = el("pre", { class: "lyrics-plain", text: this.data.plain_text });
      scroll.appendChild(pre);
      scroll.appendChild(el("div", { class: "lyrics-banner", text: "No timing data — only plain text." }));
    } else {
      scroll.appendChild(el("div", { class: "lyrics-empty", text: "No lyrics found." }));
    }
    scroll.addEventListener("scroll", () => {
      this._scrollSuspendedUntil = performance.now() + 4000;
    }, { passive: true });
  }

  _renderError(msg) {
    clear(this.host);
    this.host.appendChild(this._buildHeader());
    this.host.appendChild(el("div", { class: "lyrics-empty lyrics-error", text: msg }));
  }

  _buildHeader() {
    const meta = this.data?.meta ?? {};
    const head = el("div", { class: "lyrics-header" });
    const title = el("div", { class: "lyrics-title", attrs: { contenteditable: "true" }, text: meta.title || "" });
    const sep = el("span", { class: "lyrics-sep", text: "·" });
    const artist = el("div", { class: "lyrics-artist", attrs: { contenteditable: "true" }, text: meta.artist || "" });
    const refresh = el("button", { class: "lyrics-refresh", text: "⟳", attrs: { type: "button", title: "Re-fetch from LRCLIB" } });
    refresh.addEventListener("click", async () => {
      this.data = null;
      this._render();
      try {
        await api.deleteLyrics(this.slug);
        const fetched = await api.fetchLyrics(this.slug, {
          artist: artist.textContent.trim(), title: title.textContent.trim(),
        });
        this.data = fetched;
        this._render();
      } catch (e) {
        this._renderError(e.message || "fetch failed");
      }
    });
    head.appendChild(artist);
    head.appendChild(sep);
    head.appendChild(title);
    head.appendChild(refresh);
    return head;
  }

  _refreshActive(forceScroll = false) {
    if (!this._scrollEl) return;
    for (const node of this._scrollEl.querySelectorAll(".lyric-line")) {
      const i = +node.dataset.i;
      node.classList.toggle("active", i === this.activeIndex);
    }
    if (this.activeIndex >= 0 && (forceScroll || performance.now() > this._scrollSuspendedUntil)) {
      const node = this._scrollEl.querySelector(`.lyric-line[data-i="${this.activeIndex}"]`);
      if (node) {
        const top = node.offsetTop - this._scrollEl.clientHeight * 0.33;
        this._scrollEl.scrollTo({ top, behavior: "smooth" });
      }
    }
  }
}
```

- [ ] **Step 3: Wire lyrics tab into TabbedSidebar**

Modify `tabbed-sidebar.js`:

```js
import { LyricsTab } from "./lyrics-tab.js";
// in mount():
this.lyricsTab = new LyricsTab(this.bar.panelFor("lyrics"));
this.lyricsTab.mount(trackData, viewState, engine);
// the tab's onActivate is wired through the TabBar tabs config:
this.bar.tabs.find((t) => t.id === "lyrics").onActivate = () => this.lyricsTab.onActivate();
```

(Adjust if `tabs` is not exposed as a property — alternatively pass an `onActivate` in the tabs array constructor up front and reference `this.lyricsTab` via closure.)

- [ ] **Step 4: CSS for the lyrics tab**

Append to `webui/static/css/track.css`:

```css
.lyrics-header {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 14px; border-bottom: 1px solid var(--bg-3);
  font-size: 12px; color: var(--fg-1);
}
.lyrics-artist, .lyrics-title { outline: none; color: var(--fg-1); }
.lyrics-artist:focus, .lyrics-title:focus { color: var(--c-vocals); }
.lyrics-sep { color: var(--fg-2); }
.lyrics-refresh {
  margin-left: auto; background: transparent; border: 1px solid var(--bg-3);
  color: var(--fg-2); border-radius: 4px; padding: 2px 8px; cursor: pointer; font-size: 12px;
}
.lyrics-refresh:hover { color: var(--fg-1); border-color: var(--c-vocals); }

.lyrics-scroll {
  height: calc(100% - 44px); overflow-y: auto;
  padding: 12px 14px;
}
.lyric-line {
  font-size: 13px; line-height: 1.5; color: var(--fg-2);
  padding: 4px 8px; border-left: 2px solid transparent;
  cursor: pointer; transition: color .15s ease;
}
.lyric-line:hover { color: var(--fg-1); }
.lyric-line.active {
  color: #ffb86b; font-weight: 700; font-size: 14px;
  border-left-color: #ffb86b;
}
.lyrics-plain { color: var(--fg-2); white-space: pre-wrap; font-size: 13px; }
.lyrics-banner {
  margin-top: 10px; font-size: 11px; color: var(--fg-2); padding: 6px 8px;
  border: 1px dashed var(--bg-3); border-radius: 4px;
}
.lyrics-empty { color: var(--fg-2); text-align: center; padding: 32px 12px; font-size: 13px; }
.lyrics-error { color: #ff8866; }
```

- [ ] **Step 5: Manual smoke**

Restart the dev server, open a track. Click the Lyrics tab. Expected:
- First open shows "Loading lyrics…", then either renders the synced lines or shows "No lyrics found."
- During playback, the active line is highlighted and auto-scrolls.
- Clicking a line seeks to its time.
- Editing artist/title and clicking refresh re-fetches.

Save screenshots to `tests/screenshots/sidebar-tabs/04-lyrics-synced.png` (a track with synced lyrics) and `05-lyrics-empty.png` (a track with none).

- [ ] **Step 6: Commit**

```bash
git add webui/static/js/ui/lyrics-tab.js webui/static/js/api.js webui/static/js/ui/tabbed-sidebar.js webui/static/css/track.css tests/screenshots/sidebar-tabs/
git commit -m "feat(webui): lyrics tab — lazy LRCLIB fetch, synced render, click-to-seek, auto-scroll"
```

---

### Task 19: Lyrics tab — refresh menu (LRCLIB / Claude / Paste)

**Files:**
- Modify: `webui/static/js/ui/lyrics-tab.js`
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Replace the simple refresh button with a 3-option dropdown**

In `lyrics-tab.js`, replace `_buildHeader`'s refresh button with a menu:

```js
const refreshWrap = el("div", { class: "lyrics-refresh-wrap" });
const refreshBtn = el("button", { class: "lyrics-refresh", text: "⟳ ▾", attrs: { type: "button" } });
const menu = el("div", { class: "lyrics-refresh-menu hidden" }, [
  el("button", { class: "menu-item", text: "Refetch from LRCLIB", attrs: { type: "button" }, onClick: async () => {
    menu.classList.add("hidden");
    this.data = null; this._render();
    try {
      await api.deleteLyrics(this.slug);
      this.data = await api.fetchLyrics(this.slug, {
        artist: this._editedArtist(), title: this._editedTitle(),
      });
      this._render();
    } catch (e) { this._renderError(e.message); }
  }}),
  el("button", { class: "menu-item", text: "Ask Claude to find lyrics", attrs: { type: "button" }, onClick: () => {
    menu.classList.add("hidden");
    // Switch to Claude tab and prefill a request — handled in Task 23 by exposing a global hook.
    if (window.__musiqClaudeAsk) {
      window.__musiqClaudeAsk(`Please find lyrics for "${this._editedTitle()}" by ${this._editedArtist()} and call fetch_lyrics.`);
    }
  }}),
  el("button", { class: "menu-item", text: "Paste lyrics manually", attrs: { type: "button" }, onClick: () => {
    menu.classList.add("hidden");
    this._showPasteDialog();
  }}),
]);
refreshBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  menu.classList.toggle("hidden");
});
document.addEventListener("click", () => menu.classList.add("hidden"));
refreshWrap.appendChild(refreshBtn);
refreshWrap.appendChild(menu);
// replace the `head.appendChild(refresh)` line with `head.appendChild(refreshWrap)`.
```

Add helpers:

```js
_editedArtist() { return this.host.querySelector(".lyrics-artist")?.textContent?.trim() || ""; }
_editedTitle()  { return this.host.querySelector(".lyrics-title")?.textContent?.trim() || ""; }

_showPasteDialog() {
  const overlay = el("div", { class: "paste-overlay" });
  const card = el("div", { class: "paste-card" });
  const ta = el("textarea", { class: "paste-textarea", attrs: { rows: 14, placeholder: "Paste plain or LRC lyrics here…" } });
  const submit = el("button", { class: "btn", text: "Save", attrs: { type: "button" } });
  const cancel = el("button", { class: "btn", text: "Cancel", attrs: { type: "button" } });
  submit.addEventListener("click", async () => {
    try {
      this.data = await api.pasteLyrics(this.slug, ta.value);
      document.body.removeChild(overlay);
      this._render();
    } catch (e) { this._renderError(e.message); }
  });
  cancel.addEventListener("click", () => document.body.removeChild(overlay));
  card.appendChild(ta);
  card.appendChild(el("div", { class: "row" }, [submit, cancel]));
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  ta.focus();
}
```

- [ ] **Step 2: CSS for the menu and paste dialog**

Append to `webui/static/css/track.css`:

```css
.lyrics-refresh-wrap { position: relative; margin-left: auto; }
.lyrics-refresh-menu {
  position: absolute; right: 0; top: 100%;
  background: var(--bg-2); border: 1px solid var(--bg-3); border-radius: 4px;
  display: flex; flex-direction: column; min-width: 180px; z-index: 50;
  box-shadow: 0 4px 12px rgba(0,0,0,.4);
}
.lyrics-refresh-menu.hidden { display: none; }
.lyrics-refresh-menu .menu-item {
  background: transparent; border: none; color: var(--fg-1);
  padding: 8px 12px; text-align: left; font-size: 12px; cursor: pointer;
}
.lyrics-refresh-menu .menu-item:hover { background: var(--bg-3); }

.paste-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.paste-card {
  background: var(--bg-1); border: 1px solid var(--bg-3); border-radius: 6px;
  padding: 16px; width: min(560px, 90vw); display: flex; flex-direction: column; gap: 10px;
}
.paste-textarea {
  background: var(--bg-2); color: var(--fg-1); border: 1px solid var(--bg-3);
  padding: 8px; font-family: monospace; font-size: 12px; resize: vertical; min-height: 200px;
}
.paste-card .row { display: flex; gap: 8px; justify-content: flex-end; }
.paste-card .btn {
  background: transparent; border: 1px solid var(--bg-3); color: var(--fg-1);
  padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.paste-card .btn:hover { background: var(--bg-3); }
```

- [ ] **Step 3: Manual smoke**

Verify:
- Clicking ⟳ ▾ shows the 3-item menu.
- "Paste lyrics manually" opens an overlay with a textarea; submitting populates the tab with synced or plain depending on input.
- "Refetch" deletes the cache and re-queries LRCLIB.
- "Ask Claude" is currently a no-op until Task 23 wires `window.__musiqClaudeAsk` — verify the menu hides cleanly and no error is thrown (check console).

Save screenshots `06-lyrics-menu.png` and `07-lyrics-paste.png`.

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/ui/lyrics-tab.js webui/static/css/track.css tests/screenshots/sidebar-tabs/
git commit -m "feat(webui): lyrics tab — refresh menu + paste dialog"
```

---

## Phase 8 — Claude tab (Tab 2)

### Task 20: Chat tab skeleton + composer + clear/stop buttons

**Files:**
- Create: `webui/static/js/ui/claude-tab.js`
- Modify: `webui/static/js/api.js` (chat wrappers)
- Modify: `webui/static/js/ui/tabbed-sidebar.js`
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Add chat API wrappers**

Append to `webui/static/js/api.js`:

```js
async function getChatHistory(slug) {
  const r = await fetch(`/api/chat/${encodeURIComponent(slug)}`);
  if (!r.ok) throw httpError(r);
  return r.json();
}
async function clearChat(slug) {
  const r = await fetch(`/api/chat/${encodeURIComponent(slug)}`, { method: "DELETE" });
  if (!r.ok) throw httpError(r);
  return r.json();
}
function chatTurnUrl(slug) { return `/api/chat/${encodeURIComponent(slug)}/turn`; }
// add to api: getChatHistory, clearChat, chatTurnUrl
```

- [ ] **Step 2: Create `webui/static/js/ui/claude-tab.js` with skeleton + composer**

```js
import { el, clear } from "./dom.js";
import { api } from "../api.js";

export class ClaudeTab {
  constructor(host) {
    this.host = host;
    this.slug = null;
    this.engine = null;
    this.viewState = null;
    this.tabbedSidebar = null;
    this.lyricsTab = null;
    this._abort = null;
    this._tokens = null;
    this._messages = [];
    this._streamingAssistantBubble = null;
  }

  mount({ trackData, viewState, engine, tabbedSidebar, lyricsTab }) {
    this.slug = trackData.meta.slug;
    this.viewState = viewState;
    this.engine = engine;
    this.tabbedSidebar = tabbedSidebar;
    this.lyricsTab = lyricsTab;
    window.__musiqClaudeAsk = (text) => this._prefillAndSend(text);
    this._build();
    this._restoreHistory();
  }

  _build() {
    clear(this.host);
    this.headerEl = el("div", { class: "claude-header" });
    const clearBtn = el("button", { class: "btn", text: "Clear chat", attrs: { type: "button" } });
    const stopBtn = el("button", { class: "btn", text: "Stop", attrs: { type: "button", disabled: "" } });
    this.tokensEl = el("span", { class: "claude-tokens", text: "" });
    clearBtn.addEventListener("click", () => this._clear());
    stopBtn.addEventListener("click", () => this._stop());
    this.headerEl.appendChild(clearBtn);
    this.headerEl.appendChild(stopBtn);
    this.headerEl.appendChild(this.tokensEl);
    this.stopBtn = stopBtn;

    this.transcriptEl = el("div", { class: "claude-transcript" });

    this.composerForm = el("form", { class: "claude-composer" });
    this.textarea = el("textarea", { class: "claude-textarea", attrs: { rows: 2, placeholder: "Ask about this song" } });
    this.sendBtn = el("button", { class: "btn", text: "Send", attrs: { type: "submit" } });
    this.composerForm.appendChild(this.textarea);
    this.composerForm.appendChild(this.sendBtn);
    this.composerForm.addEventListener("submit", (e) => { e.preventDefault(); this._send(); });
    this.textarea.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); this._send(); }
    });

    this.host.appendChild(this.headerEl);
    this.host.appendChild(this.transcriptEl);
    this.host.appendChild(this.composerForm);
  }

  async _restoreHistory() {
    try {
      const { messages } = await api.getChatHistory(this.slug);
      this._messages = messages;
      this._renderTranscript();
    } catch (e) { /* nonfatal */ }
  }

  _renderTranscript() {
    clear(this.transcriptEl);
    for (const m of this._messages) {
      this.transcriptEl.appendChild(this._renderMessage(m));
    }
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
  }

  _renderMessage(m) {
    const cls = m.role === "user" ? "msg msg-user" : "msg msg-assistant";
    const wrap = el("div", { class: cls });
    for (const b of (m.blocks || [])) {
      if (b.type === "text") wrap.appendChild(el("div", { class: "msg-text", text: b.text }));
      else if (b.type === "tool_use") wrap.appendChild(this._renderToolChip(b));
      else if (b.type === "tool_result") {
        // attach success/fail mark to the matching tool_use chip if rendered
      }
    }
    return wrap;
  }

  _renderToolChip(block) {
    const ok = block.ok !== false;
    const cls = `tool-chip ${ok ? "ok" : "fail"}`;
    const inputStr = JSON.stringify(block.input ?? block.args ?? {});
    return el("div", { class: cls, text: `[tool: ${block.name?.replace(/^mcp__musiq-tools__/, "")}(${inputStr})] ${ok ? "✓" : "✗"}` });
  }

  async _clear() {
    await api.clearChat(this.slug);
    this._messages = [];
    this._renderTranscript();
  }

  _prefillAndSend(text) {
    this.tabbedSidebar?.bar.activate("claude");
    this.textarea.value = text;
    this._send();
  }

  _stop() {
    if (this._abort) this._abort.abort();
  }

  async _send() {
    const text = this.textarea.value.trim();
    if (!text) return;
    this.textarea.value = "";
    this._messages.push({ role: "user", blocks: [{ type: "text", text }] });
    this._renderTranscript();

    // Build assistant streaming bubble
    this._streamingAssistantBubble = el("div", { class: "msg msg-assistant streaming" });
    this._streamingTextNode = el("div", { class: "msg-text", text: "" });
    this._streamingAssistantBubble.appendChild(this._streamingTextNode);
    this.transcriptEl.appendChild(this._streamingAssistantBubble);
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;

    this.sendBtn.disabled = true;
    this.stopBtn.removeAttribute("disabled");
    this._abort = new AbortController();
    try {
      await this._streamTurn(text);
    } catch (e) {
      this._appendErrorBubble(e.message || String(e));
    } finally {
      this.sendBtn.disabled = false;
      this.stopBtn.setAttribute("disabled", "");
      this._abort = null;
      this._streamingAssistantBubble?.classList.remove("streaming");
      // Refresh from server to canonical history (with persisted tool blocks)
      this._restoreHistory();
    }
  }

  async _streamTurn(text) {
    const view_state = this._buildViewState();
    const r = await fetch(api.chatTurnUrl(this.slug), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, view_state }),
      signal: this._abort.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) this._handleEvent(JSON.parse(line));
      }
    }
  }

  _handleEvent(ev) {
    switch (ev.type) {
      case "text":
        this._streamingTextNode.textContent += ev.delta;
        this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
        break;
      case "tool_use":
        this._streamingAssistantBubble.appendChild(this._renderToolChip(ev));
        break;
      case "tool_result":
        // optional: update the chip in-place
        break;
      case "ui_action":
        this._dispatchUiAction(ev);
        break;
      case "done":
        this._tokens = ev.tokens;
        this._renderTokens();
        break;
      case "error":
        this._appendErrorBubble(`${ev.kind || "error"}: ${ev.message}`);
        break;
      case "auth_required":
        this._renderAuthRequired();
        break;
    }
  }

  _dispatchUiAction(ev) {
    const { action, args } = ev;
    switch (action) {
      case "seek_to":           this.engine?.seek(args.time_sec); break;
      case "set_loop_region":   this.viewState?.setLoop(args.start_sec, args.end_sec); break;
      case "set_stem_state":
        if (args.mute   != null) this.engine?.setStemMute(args.stem, args.mute);
        if (args.solo   != null) this.engine?.setStemSolo(args.stem, args.solo);
        if (args.volume != null) this.engine?.setStemVolume(args.stem, args.volume);
        break;
      case "highlight_stem":    if (this.viewState) this.viewState.highlightedStem = args.stem; break;
      case "open_midi":         fetch(`/api/tools/open-midi/${this.slug}/${args.stem}`, { method: "POST" }); break;
      case "switch_tab":        this.tabbedSidebar?.bar.activate(args.tab); break;
      case "highlight_lyric_line": this.lyricsTab?.highlightLineByIndex(args.index); break;
      case "reload_lyrics":     this.lyricsTab?._lazyLoad(); break;
      default: console.warn("unknown ui_action", action);
    }
  }

  _buildViewState() {
    return {
      playhead_sec: this.engine?.currentTime ?? 0,
      highlighted_stem: this.viewState?.highlightedStem,
      mutes: this.engine?.muted,
      solos: this.engine?.soloed,
      loop_start_sec: this.viewState?.loopStart,
      loop_end_sec: this.viewState?.loopEnd,
      active_tab: this.tabbedSidebar?.bar.current(),
    };
  }

  _renderTokens() {
    if (!this._tokens) { this.tokensEl.textContent = ""; return; }
    const { input, output, cache_read } = this._tokens;
    this.tokensEl.textContent = `cache ${cache_read} · in ${input} · out ${output}`;
  }

  _appendErrorBubble(msg) {
    const b = el("div", { class: "msg msg-error", text: msg });
    this.transcriptEl.appendChild(b);
  }

  _renderAuthRequired() {
    clear(this.transcriptEl);
    const card = el("div", { class: "auth-card" });
    card.appendChild(el("div", { class: "auth-title", text: "Claude is signed out." }));
    card.appendChild(el("div", { class: "auth-body", text: "Run `claude /login` in a terminal, then click Retry." }));
    const retry = el("button", { class: "btn", text: "Retry", attrs: { type: "button" } });
    retry.addEventListener("click", () => this._restoreHistory());
    card.appendChild(retry);
    this.transcriptEl.appendChild(card);
  }
}
```

- [ ] **Step 3: Wire ClaudeTab into TabbedSidebar**

Modify `tabbed-sidebar.js`:

```js
import { ClaudeTab } from "./claude-tab.js";
// in mount(), after lyricsTab:
this.claudeTab = new ClaudeTab(this.bar.panelFor("claude"));
this.claudeTab.mount({ trackData, viewState, engine, tabbedSidebar: this, lyricsTab: this.lyricsTab });
```

(Expose `this.bar` so claude-tab can call `tabbedSidebar.bar.activate("claude")` for `_prefillAndSend`. Already exposed since `this.bar = new TabBar(...)`.)

- [ ] **Step 4: CSS for the chat tab**

Append to `webui/static/css/track.css`:

```css
.claude-header {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 12px; border-bottom: 1px solid var(--bg-3);
}
.claude-header .btn {
  background: transparent; border: 1px solid var(--bg-3); color: var(--fg-2);
  padding: 3px 10px; border-radius: 4px; font-size: 11px; cursor: pointer;
}
.claude-header .btn:hover:not([disabled]) { color: var(--fg-1); border-color: var(--c-vocals); }
.claude-header .btn[disabled] { opacity: .4; cursor: not-allowed; }
.claude-tokens { margin-left: auto; font-size: 10px; color: var(--fg-2); font-family: monospace; }

.claude-transcript {
  height: calc(100% - 110px); overflow-y: auto;
  padding: 10px 12px; display: flex; flex-direction: column; gap: 8px;
}
.msg { padding: 8px 10px; border-radius: 5px; font-size: 12px; line-height: 1.5; }
.msg-user { background: var(--bg-2); color: var(--fg-1); align-self: flex-end; max-width: 85%; }
.msg-assistant { background: rgba(255,184,107,.06); border-left: 2px solid #ffb86b; color: var(--fg-1); }
.msg.streaming::after { content: "▌"; color: #ffb86b; animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
.msg-error { background: rgba(255,136,102,.10); border-left: 2px solid #ff8866; color: #ffaa99; }
.tool-chip {
  display: inline-block; margin-top: 6px;
  font-family: monospace; font-size: 11px; color: var(--fg-2);
  background: var(--bg-2); padding: 2px 8px; border-radius: 4px;
}
.tool-chip.fail { color: #ff8866; }

.claude-composer {
  display: flex; gap: 6px; padding: 10px 12px; border-top: 1px solid var(--bg-3);
}
.claude-textarea {
  flex: 1; background: var(--bg-2); color: var(--fg-1); border: 1px solid var(--bg-3);
  padding: 6px 8px; font-size: 12px; resize: vertical; min-height: 40px; max-height: 140px;
}
.claude-composer .btn {
  background: var(--c-vocals); color: #1a1a25; border: none;
  padding: 6px 16px; border-radius: 4px; font-weight: 600; font-size: 12px; cursor: pointer;
}
.claude-composer .btn:disabled { opacity: .4; cursor: not-allowed; }

.auth-card {
  background: rgba(255,136,102,.08); border: 1px solid rgba(255,136,102,.4);
  border-radius: 5px; padding: 16px; display: flex; flex-direction: column; gap: 8px;
}
.auth-title { font-size: 13px; font-weight: 700; color: #ffaa99; }
.auth-body { font-size: 12px; color: var(--fg-2); }
.auth-card .btn {
  align-self: flex-start; background: transparent; border: 1px solid #ffaa99; color: #ffaa99;
  padding: 4px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;
}
```

- [ ] **Step 5: Manual smoke**

Restart webui. Click Claude tab. Expected:
- Empty transcript on first load.
- Type "what is the key of this track?" + Enter (or Send) → Claude streams a response.
- Try "loop bars 8 to 16" → Claude calls `set_loop_region`; minimap and pianoroll show the band; transport shows the chip.
- Try "mute everything except piano" → all stems mute except piano.
- Reload page → conversation restored.
- Click Clear chat → empty.

Save screenshots `08-claude-empty.png`, `09-claude-conversation.png`, `10-claude-tool-action.png`.

- [ ] **Step 6: Commit**

```bash
git add webui/static/js/ui/claude-tab.js webui/static/js/api.js webui/static/js/ui/tabbed-sidebar.js webui/static/css/track.css tests/screenshots/sidebar-tabs/
git commit -m "feat(webui): Claude tab — chat, NDJSON streaming, tool dispatch, persistence"
```

---

### Task 21: Auth-required surfacing — verify by simulating

**Files:**
- (verification only)

- [ ] **Step 1: Simulate the auth-required path**

The chat code has the `auth_required` event handler. To verify it works without actually logging out, temporarily patch `webui/webui/chat.py` to force the path:

```python
# In stream_turn(), at the top, add (and remove after smoke):
if False:  # temp test
    yield {"type": "auth_required"}
    return
```

Restart server, send a message, confirm the auth card appears in the tab.

Remove the temp lines.

- [ ] **Step 2: Save screenshot**

`tests/screenshots/sidebar-tabs/11-claude-auth.png`

- [ ] **Step 3: Commit (screenshot only)**

```bash
git add tests/screenshots/sidebar-tabs/11-claude-auth.png
git commit -m "test(webui): screenshot — Claude tab auth-required state"
```

---

## Phase 9 — Integration smoke + README

### Task 22: End-to-end smoke checklist + README updates

**Files:**
- Modify: `webui/README.md`

- [ ] **Step 1: Run the full test suite**

```bash
cd webui && .venv/Scripts/python -m pytest tests/ -v
```

Expected: all tests PASS, including new tests in `test_chat.py`, `test_lyrics.py`, and the lyrics + chat + preserve cases in `test_server.py`.

- [ ] **Step 2: Manual smoke checklist**

Document and execute in order. Each step has an expected outcome:

1. Open a track → sidebar shows three tabs: Track / Claude / Lyrics. Track tab is active by default.
2. Click Lyrics → first time per track, "Loading lyrics…" appears, then either lyrics or "No lyrics found". Save `12-end-to-end-1.png`.
3. With synced lyrics, play the track → active line highlights and auto-scrolls to upper third. Save `12-end-to-end-2.png`.
4. Click any line → playhead jumps. ✓
5. Switch to Claude → empty transcript.
6. Send "what's the chord at the playhead?" → text answer streams in. Save `12-end-to-end-3.png`.
7. Send "loop the next 16 seconds" → minimap + pianoroll show loop band; transport shows chip. Save `12-end-to-end-4.png`.
8. Click the loop chip → loop clears.
9. Send "show me where the modal interchange chords are" → `find_chord_occurrences` tool fires; Claude lists times.
10. Send "play me the chorus with only vocals + bass" → multiple `set_stem_state` and possibly `seek_to`/`set_loop_region` actions.
11. Reload page → conversation restored on Claude tab. ✓
12. Click "Clear chat" → empty. ✓
13. Trigger Reanalyze on the track from the existing modal → after completion, Lyrics tab still has cached lyrics; Claude tab still has its conversation.

- [ ] **Step 3: Update `webui/README.md` with the new features**

Append a section:

```markdown
## Sidebar tabs

The sidebar has three tabs:

- **Track** — the existing analysis sidebar (unchanged).
- **Claude** — chat with an in-app music tutor. Authenticates via your existing `claude /login` (Pro/Max subscription); no API key required. Conversations are persisted per-track under `cache/<slug>/chat.json`.
- **Lyrics** — synced lyrics from LRCLIB with karaoke-style auto-scroll. Click any line to seek. Stored under `cache/<slug>/lyrics/`.

Both `chat.json` and `lyrics/` are preserved across re-analysis.

If Claude shows "signed out", run `claude /login` in a terminal and click Retry.
```

- [ ] **Step 4: Commit + final cleanup**

```bash
git add webui/README.md tests/screenshots/sidebar-tabs/
git commit -m "docs(webui): document sidebar tabs + Claude + lyrics features"
```

- [ ] **Step 5: Open the PR (or merge to main)**

If running in a worktree:

```bash
# Push the branch
git push -u origin feat/sidebar-tabs-claude-lyrics
# Open a PR against main, or merge directly per the project's branching workflow
# (memory: user commits straight to main on this project; merging is fine if the branch is clean)
git checkout main
git merge --ff-only feat/sidebar-tabs-claude-lyrics
git worktree remove .claude/worktrees/sidebar-tabs
```

---

## Self-review checklist (for the plan author, not the executor)

- [x] Spec coverage: every locked-decision row maps to a task. Tab shell → Task 13/14. Tutor/Guide/Operator/Lyricist/Librarian roles → Task 7 (tools) + Task 8 (streaming). LRCLIB cascade → Task 4 + Task 5 (orchestration in Task 7's `fetch_lyrics_tool`). Karaoke layout B → Task 18. Per-track + persisted chat → Task 9 + Task 11. ID3 + filename fallback → Task 3. Loop region → Tasks 15-17. Cache preservation → Task 12. Auth-required → Task 8 (`_classify_exception`) + Task 21 (smoke).
- [x] Placeholder scan: no TBD/TODO/"add error handling"/etc. in the executable steps. The one "verify with debug print" note in Task 8 step 3 is a tagged risk with a concrete remediation, not a placeholder.
- [x] Type consistency: tool names match between `chat.py` definitions, `ALLOWED_TOOLS`, the streaming wrapper, and the JS dispatcher (`_dispatchUiAction`). Persistence schema (`{role, blocks, ts}`) matches between `append_user_message`, `append_assistant_message`, the route handler, and `_renderMessage`.
- [x] Worktree-first: Task 1 creates the worktree before any code change.
- [x] Frequent commits: each task ends with a `git commit`. ~22 commits total.
