# Track Rename Implementation Plan

> **Status: SHIPPED 2026-05-03 → 2026-05-04** via `3ddef9a feat(webui): PATCH /api/tracks/{slug} — display_name rename + lyrics meta side effect` and `767576b feat(webui): rename modal — ✎ pencil button, modal UI, lyrics refresh hook`. Iterated polish: `653b2f1` (identify_track slug prettifier), `6337b4d` (paste-preserves-rename), `99cdedc` (lyrics fetch preserves cached meta), `5366c57`/`55e2fa2`/`5d6f33d` (rename survives Refetch + lyrics-tab seeding), `4fdbb13` (picker dropdown updates without page reload), `9bf305d` (Unknown-artist/title placeholder fallback). **Note:** the runbook's `bash webui/scripts/webui-stop.sh` references were patched in `2cf7e20` (2026-05-09) to use `webui\webui.ps1` after the bash scripts were retired in favor of the PowerShell helper. **Plan body retained as historical narrative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user override a track's display name from a topbar pencil button, persisting in a new `cache/<slug>/user_meta.json` file that survives reanalyze, with the side effect of repairing the lyrics-tab artist/title via smart split on " - ".

**Architecture:** Server stores user-authored display name in `cache/<slug>/user_meta.json`; `tracks.get_summary` and `tracks.list_tracks` merge it into responses; new `PATCH /api/tracks/{slug}` route writes both `user_meta.json` and (with smart artist/title split) `lyrics/meta.json`; topbar adds a ✎ button that opens a small modal to edit the name.

**Tech Stack:** FastAPI, vanilla JS (no framework), pytest (server), Playwright (e2e). Existing patterns in `webui/webui/lyrics.py` (file-backed JSON with non-atomic writes — match for consistency) and `webui/static/js/ui/*.js` (modal overlays, dynamic imports).

**Spec:** `docs/superpowers/specs/2026-05-03-track-rename-design.md`

---

## File Structure

**New files:**
- `webui/webui/user_meta.py` — read/write/validate helpers for the per-slug user_meta.json
- `webui/static/js/ui/rename-modal.js` — modal UI (lazy-imported on first pencil click)
- `webui/tests-e2e/rename.spec.js` — Playwright happy-path

**Modified:**
- `webui/webui/server.py` — new `PATCH /api/tracks/{slug}` route
- `webui/webui/tracks.py` — `get_summary` + `_build_entry` use display_name override
- `webui/webui/analyze_runner.py` — `PRESERVE` set adds `"user_meta.json"`
- `webui/static/js/api.js` — `renameTrack(slug, displayName)` helper
- `webui/static/js/ui/topbar.js` — ✎ button + display_name fallback
- `webui/static/js/ui/track-picker.js` — display_name fallback in the list
- `webui/static/js/ui/lyrics-tab.js` — register `window.__musiqLyricsRefreshMeta` on mount
- `webui/static/js/ui/shortcuts.js` — focus-target guard so canvas shortcuts don't fire while typing
- `webui/static/js/main.js` — set `document.title` from track name (currently always "MusIQ-Lab")
- `webui/static/css/track.css` — `.title-edit` button + `.rename-modal-*` styles
- `webui/tests/test_server.py` — rename route tests
- `webui/tests/test_tracks.py` (new file if absent, or extend existing) — get_summary/list_tracks merge tests

---

## Task 1: `user_meta` module — read, validate, write

**Files:**
- Create: `webui/webui/user_meta.py`
- Test: `webui/tests/test_user_meta.py` (new file)

- [ ] **Step 1: Write the failing tests**

```python
# webui/tests/test_user_meta.py
import json
from pathlib import Path
import pytest
from webui import user_meta


def test_read_returns_empty_when_file_missing(tmp_path):
    assert user_meta.read(tmp_path) == {}


def test_read_returns_parsed_when_present(tmp_path):
    (tmp_path / "user_meta.json").write_text('{"display_name": "X"}', encoding="utf-8")
    assert user_meta.read(tmp_path) == {"display_name": "X"}


def test_read_returns_empty_when_corrupt(tmp_path):
    (tmp_path / "user_meta.json").write_text("not json", encoding="utf-8")
    assert user_meta.read(tmp_path) == {}


def test_write_creates_file_with_indent(tmp_path):
    user_meta.write(tmp_path, {"display_name": "Charlie Puth - Attention"})
    raw = (tmp_path / "user_meta.json").read_text(encoding="utf-8")
    assert json.loads(raw) == {"display_name": "Charlie Puth - Attention"}
    assert "\n" in raw  # pretty-printed


def test_validate_display_name_strips_and_accepts():
    assert user_meta.validate_display_name("  Charlie Puth - Attention  ") == "Charlie Puth - Attention"


def test_validate_display_name_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        user_meta.validate_display_name("   ")


def test_validate_display_name_rejects_too_long():
    with pytest.raises(ValueError, match="too long"):
        user_meta.validate_display_name("x" * 201)


@pytest.mark.parametrize("ch", ["\\", "/", "\n", "\r", "\x00"])
def test_validate_display_name_rejects_path_chars(ch):
    with pytest.raises(ValueError, match="invalid character"):
        user_meta.validate_display_name(f"foo{ch}bar")


def test_validate_display_name_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        user_meta.validate_display_name(42)


def test_split_artist_title_with_dash():
    assert user_meta.split_artist_title("Charlie Puth - Attention") == ("Charlie Puth", "Attention")


def test_split_artist_title_without_dash():
    assert user_meta.split_artist_title("Track 03 fragment") == ("", "Track 03 fragment")


def test_split_artist_title_partition_first_only():
    # Only the FIRST " - " is the boundary; the rest stays in the title.
    assert user_meta.split_artist_title("A - B - C") == ("A", "B - C")


def test_split_artist_title_strips_each_side():
    assert user_meta.split_artist_title("  Foo   -   Bar  ") == ("Foo", "Bar")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webui && .venv/Scripts/pytest tests/test_user_meta.py -v`
Expected: ALL FAIL with `ModuleNotFoundError: No module named 'webui.user_meta'`.

- [ ] **Step 3: Write the module**

```python
# webui/webui/user_meta.py
"""Per-slug user-authored metadata (display_name override etc.).

Lives at cache/<slug>/user_meta.json — separated from analyze-pipeline output
(summary.json, which is regenerated on every reanalyze) so user edits survive
reanalysis. Listed in analyze_runner._clear_cache_dir's PRESERVE set.

Schema is open (an arbitrary JSON object); today the only key is `display_name`.
"""
from __future__ import annotations

import json
from pathlib import Path

_FILENAME = "user_meta.json"
_MAX_DISPLAY_NAME_LEN = 200
_FORBIDDEN_CHARS = ("\\", "/", "\n", "\r", "\x00")


def path_for(slug_cache: Path) -> Path:
    """Given cache/<slug>/, return the user_meta.json path inside it."""
    return slug_cache / _FILENAME


def read(slug_cache: Path) -> dict:
    """Return the parsed user_meta.json contents, or {} if missing/corrupt.

    Corrupt-as-empty matches our other cache reads — a stray bad file should
    never break the API; the user will just see the default behavior and can
    re-rename to overwrite.
    """
    p = path_for(slug_cache)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write(slug_cache: Path, data: dict) -> None:
    """Write user_meta.json. Creates the parent dir if needed."""
    slug_cache.mkdir(parents=True, exist_ok=True)
    path_for(slug_cache).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def validate_display_name(value) -> str:
    """Return a trimmed, validated display name. Raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("display_name must be a string")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("display_name is empty")
    if len(trimmed) > _MAX_DISPLAY_NAME_LEN:
        raise ValueError(f"display_name too long (max {_MAX_DISPLAY_NAME_LEN})")
    for ch in _FORBIDDEN_CHARS:
        if ch in trimmed:
            raise ValueError(f"display_name contains invalid character: {ch!r}")
    return trimmed


def split_artist_title(display_name: str) -> tuple[str, str]:
    """Split on the FIRST ' - ' into (artist, title).

    No ' - ' means the user typed a single label; we keep it as the title and
    return an empty artist (predictable: 'what you type is what you get' —
    we don't silently preserve a prior artist value across renames).
    """
    if " - " in display_name:
        artist, _, title = display_name.partition(" - ")
        return artist.strip(), title.strip()
    return "", display_name.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webui && .venv/Scripts/pytest tests/test_user_meta.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/user_meta.py webui/tests/test_user_meta.py
git commit -m "feat(webui): user_meta module — display_name read/write/validate"
```

---

## Task 2: `tracks.get_summary` merges display_name

**Files:**
- Modify: `webui/webui/tracks.py:124-129`
- Test: `webui/tests/test_tracks.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# webui/tests/test_tracks.py
import json
from pathlib import Path

import pytest

from webui import tracks, user_meta


@pytest.fixture
def cache_with_summary(tmp_path):
    cache = tmp_path / "cache"
    slug = "demo"
    sd = cache / slug
    sd.mkdir(parents=True)
    (sd / f"{slug}.summary.json").write_text(json.dumps({
        "track": {"file": "demo.mp3", "duration_sec": 100.0, "tempo_bpm": 120.0, "key": "C"},
        "analysis": {"scale": "major"},
        "provenance": {"warnings": []},
    }), encoding="utf-8")
    tracks._cache.clear()
    return cache, slug


def test_get_summary_returns_track_without_display_name_when_no_user_meta(cache_with_summary):
    cache, slug = cache_with_summary
    summary = tracks.get_summary(slug, cache=cache)
    assert "display_name" not in summary["track"]


def test_get_summary_merges_display_name_from_user_meta(cache_with_summary):
    cache, slug = cache_with_summary
    user_meta.write(cache / slug, {"display_name": "Charlie Puth - Attention"})
    summary = tracks.get_summary(slug, cache=cache)
    assert summary["track"]["display_name"] == "Charlie Puth - Attention"


def test_get_summary_ignores_blank_display_name(cache_with_summary):
    cache, slug = cache_with_summary
    user_meta.write(cache / slug, {"display_name": "   "})
    summary = tracks.get_summary(slug, cache=cache)
    assert "display_name" not in summary["track"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && .venv/Scripts/pytest tests/test_tracks.py -v`
Expected: `test_get_summary_merges_display_name_from_user_meta` FAILS (no display_name key in returned track).

- [ ] **Step 3: Modify `get_summary`**

In `webui/webui/tracks.py`, replace the existing `get_summary` (lines 124-129):

```python
def get_summary(slug: str, cache: Path | None = None) -> dict:
    cache = cache or _paths.cache_dir()
    sj = _summary_path(slug, cache)
    if not sj.is_file():
        raise KeyError(slug)
    summary = json.loads(sj.read_text(encoding="utf-8"))
    # Merge user-authored display_name override (separate file so it survives
    # reanalyze, which regenerates summary.json from scratch).
    from . import user_meta
    um = user_meta.read(cache / slug)
    dn = (um.get("display_name") or "").strip()
    if dn:
        summary.setdefault("track", {})["display_name"] = dn
    return summary
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webui && .venv/Scripts/pytest tests/test_tracks.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/tracks.py webui/tests/test_tracks.py
git commit -m "feat(webui): tracks.get_summary merges display_name from user_meta"
```

---

## Task 3: `tracks.list_tracks` honors display_name in `TrackEntry.title`

**Files:**
- Modify: `webui/webui/tracks.py` — `_build_entry` and `list_tracks`
- Test: `webui/tests/test_tracks.py` (extend)

- [ ] **Step 1: Add the failing test**

Append to `webui/tests/test_tracks.py`:

```python
def test_list_tracks_uses_display_name_for_title(cache_with_summary):
    cache, slug = cache_with_summary
    # Without override, title is derived from filename ("demo" → "Demo")
    [entry] = tracks.list_tracks(cache=cache)
    assert entry.title == "Demo"
    # With override, title is the user-authored display_name
    user_meta.write(cache / slug, {"display_name": "Charlie Puth - Attention"})
    tracks._cache.clear()  # bypass mtime-based memoization for test
    [entry] = tracks.list_tracks(cache=cache)
    assert entry.title == "Charlie Puth - Attention"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && .venv/Scripts/pytest tests/test_tracks.py::test_list_tracks_uses_display_name_for_title -v`
Expected: FAIL on the second assertion (title still "Demo").

- [ ] **Step 3: Wire display_name into `_build_entry` and `list_tracks`**

In `webui/webui/tracks.py`:

Add an import at the top:
```python
from . import user_meta
```

Change `_build_entry` signature and body (around line 65) to accept an override:

```python
def _build_entry(slug: str, summary: dict, mtime_ns: int, display_override: str | None = None) -> TrackEntry:
    track = summary["track"]
    analysis = summary.get("analysis", {})
    provenance = summary.get("provenance", {})
    file_title = _derive_title(track["file"])
    derived = file_title if " " in file_title else derive_display_title(slug)
    title = display_override or derived
    return TrackEntry(
        slug=slug,
        title=title,
        duration_sec=float(track["duration_sec"]),
        tempo_bpm=float(track["tempo_bpm"]),
        key=track["key"],
        scale=analysis.get("scale", ""),
        has_vocals=analysis.get("vocal_range") is not None,
        warnings=list(provenance.get("warnings", [])),
        summary_mtime_ns=mtime_ns,
    )
```

In `list_tracks`, update the cache key to include user_meta.json mtime, and pass the display override into `_build_entry`. Replace the body's per-child loop (lines 98-120) with:

```python
    for child in cache.iterdir():
        if not child.is_dir():
            continue
        sj = _summary_path(child.name, cache)
        if not sj.is_file():
            continue
        try:
            summary_mtime = sj.stat().st_mtime_ns
        except OSError as exc:
            log.warning("stat failed for %s: %s", sj, exc)
            continue
        # Include user_meta.json mtime in the cache key so a rename invalidates
        # the cached entry without requiring an explicit pop. Missing file → 0.
        um_path = user_meta.path_for(child)
        try:
            um_mtime = um_path.stat().st_mtime_ns if um_path.is_file() else 0
        except OSError:
            um_mtime = 0
        key = (summary_mtime, um_mtime)
        cached = _cache.get(child.name)
        if cached and cached[0] == key:
            entries.append(cached[1])
            continue
        try:
            data = json.loads(sj.read_text(encoding="utf-8"))
            display_override = (user_meta.read(child).get("display_name") or "").strip() or None
            entry = _build_entry(child.name, data, summary_mtime, display_override=display_override)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            log.warning("skipping %s: %s", sj, exc)
            continue
        _cache[child.name] = (key, entry)
        entries.append(entry)
    return entries
```

Note: `_cache` value tuple shape changes from `(int, TrackEntry)` to `((int, int), TrackEntry)`. Update the type annotation at line 34:

```python
_cache: dict[str, tuple[tuple[int, int], TrackEntry]] = {}
```

- [ ] **Step 4: Run all tracks tests to verify they pass and nothing regressed**

Run: `cd webui && .venv/Scripts/pytest tests/test_tracks.py -v`
Expected: ALL PASS.

Run: `cd webui && .venv/Scripts/pytest tests/test_server.py -v -k "track or library"`
Expected: ALL PASS (existing track-list/library tests still work).

- [ ] **Step 5: Commit**

```bash
git add webui/webui/tracks.py webui/tests/test_tracks.py
git commit -m "feat(webui): list_tracks uses display_name override; user_meta mtime in cache key"
```

---

## Task 4: `_clear_cache_dir` preserves `user_meta.json`

**Files:**
- Modify: `webui/webui/analyze_runner.py:48-49`
- Test: `webui/tests/test_server.py:485` (extend the existing preserve test)

- [ ] **Step 1: Extend the failing test**

In `webui/tests/test_server.py`, modify `test_clear_cache_dir_preserves_chat_and_lyrics` to also assert user_meta.json survives. Replace the function (line 485):

```python
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
    (cache / "summary.json").write_text("{}", encoding="utf-8")
    (cache / "stems_6s").mkdir(exist_ok=True)
    (cache / "stems_6s" / "x.wav").write_bytes(b"")
    _clear_cache_dir(cache)
    assert (cache / "chat.json").is_file()
    assert (cache / "lyrics" / "synced.lrc").is_file()
    assert (cache / "user_meta.json").is_file()
    assert not (cache / "summary.json").exists()
    assert not (cache / "stems_6s").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webui && .venv/Scripts/pytest tests/test_server.py::test_clear_cache_dir_preserves_chat_lyrics_and_user_meta -v`
Expected: FAIL — `user_meta.json` is removed by the clear.

- [ ] **Step 3: Add `user_meta.json` to PRESERVE**

In `webui/webui/analyze_runner.py`, find the `_clear_cache_dir` function and update the PRESERVE set (around line 49):

```python
def _clear_cache_dir(cache: Path) -> None:
    # Preserve chat history (chat.json), cached lyrics (lyrics/), and the
    # user-authored display name (user_meta.json) across reanalysis — they're
    # user-authored / off-the-network artifacts that don't depend on the
    # analysis pipeline state.
    PRESERVE = {"chat.json", "lyrics", "user_meta.json"}
    for child in cache.iterdir():
        if child.name in PRESERVE:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webui && .venv/Scripts/pytest tests/test_server.py::test_clear_cache_dir_preserves_chat_lyrics_and_user_meta -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/analyze_runner.py webui/tests/test_server.py
git commit -m "feat(webui): preserve user_meta.json across reanalyze"
```

---

## Task 5: `PATCH /api/tracks/{slug}` route

**Files:**
- Modify: `webui/webui/server.py` (insert after the `GET /api/tracks/{slug}` route at line 87-96)
- Test: `webui/tests/test_server.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `webui/tests/test_server.py`:

```python
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
    """No lyrics dir yet → create it and seed a meta.json with source=user_rename."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webui && .venv/Scripts/pytest tests/test_server.py -v -k rename`
Expected: ALL FAIL with 405 Method Not Allowed (no PATCH route registered).

- [ ] **Step 3: Add the route**

In `webui/webui/server.py`, after the existing `GET /api/tracks/{slug}` block (around line 96), insert:

```python
@app.patch("/api/tracks/{slug}")
async def api_track_rename(slug: str, request: Request) -> dict:
    """Update user-authored track metadata. Today: just display_name.

    Side effect: writes lyrics/meta.json with smart-split artist/title so the
    lyrics-tab header reflects the rename without a separate edit.
    """
    from . import user_meta

    # 404 first if slug is unknown — surface validation error from a known track.
    try:
        summary = tracks.get_summary(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown slug: {slug}")

    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

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
```

- [ ] **Step 4: Run all rename tests to verify they pass**

Run: `cd webui && .venv/Scripts/pytest tests/test_server.py -v -k rename`
Expected: ALL PASS.

Run the full server suite to confirm nothing regressed:
Run: `cd webui && .venv/Scripts/pytest tests/test_server.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/server.py webui/tests/test_server.py
git commit -m "feat(webui): PATCH /api/tracks/{slug} — display_name rename + lyrics meta side effect"
```

---

## Task 6: `api.js` — `renameTrack` helper

**Files:**
- Modify: `webui/static/js/api.js`

- [ ] **Step 1: Read current api.js to find the right insertion point**

Run: `head -n 110 webui/static/js/api.js`
Look for the lyrics block at line ~92-99.

- [ ] **Step 2: Add the helper**

Insert after the `fetchLyrics` line (around line 99) in the lyrics block:

```js
  // Rename track — PATCH the user-authored display_name. Server splits on
  // " - " and updates lyrics/meta.json artist/title as a side effect.
  renameTrack: (slug, displayName) =>
    patchJson(`/api/tracks/${encodeURIComponent(slug)}`, { display_name: displayName }),
```

- [ ] **Step 3: Add `patchJson` helper if it doesn't exist**

Run: `grep -n "patchJson\|postJson\|deleteJson" webui/static/js/api.js`

If `patchJson` is missing, copy the `postJson` definition (which exists) and add right next to it:

```js
async function patchJson(path, body) {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch {}
    throw new Error(detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}
```

(If the file has a different shared-helper pattern — e.g., a `_request(method, path, body)` — match that pattern instead. The grep result tells you which.)

- [ ] **Step 4: Manual verification (no JS unit tests in this project)**

Open browser devtools console at `http://127.0.0.1:8765/?slug=<some-slug>` and run:

```js
await window.__api?.renameTrack?.("<slug>", "Test - Rename")
```

If `__api` isn't exposed globally, skip — the next task wires this up via the modal.

- [ ] **Step 5: Commit**

```bash
git add webui/static/js/api.js
git commit -m "feat(webui): api.js — renameTrack(slug, displayName) helper"
```

---

## Task 7: Topbar / track-picker / main.js read display_name with fallback

**Files:**
- Modify: `webui/static/js/ui/topbar.js:23, 50` (use display_name fallback)
- Modify: `webui/static/js/ui/track-picker.js` (use entry.title which already reflects the override after Task 3 — verify)
- Modify: `webui/static/js/main.js` (set `document.title` from current track)

- [ ] **Step 1: Confirm track-picker uses entry.title**

Run: `grep -n "title\|name" webui/static/js/ui/track-picker.js | head -30`

Expected: the picker renders `entry.title` (which is now the display_name override or the derived title — Task 3 wired this server-side). If so, NO changes needed to track-picker.js. Move on. If it builds its own derived title client-side, swap to `entry.title`.

- [ ] **Step 2: Update topbar to prefer display_name**

In `webui/static/js/ui/topbar.js`, replace line 23:

```js
const titleSpan = el("span", { class: "title", text: summary?.track ? (summary.track.display_name || deriveTitle(summary.track.file)) : "(no track)" });
```

And update the Tools menu pass-through (around line 50):

```js
el("div", { class: "item", data: { act: "tools" }, text: "⚒ Tools",
  onClick: () => import("./menus.js").then((m) => m.showTools(
    window.__currentSlug,
    summary?.track ? (summary.track.display_name || deriveTitle(summary.track.file)) : window.__currentSlug,
  )) }),
```

- [ ] **Step 3: Set `document.title` from track name in `main.js`**

Run: `grep -n "summary\|trackData\|currentSlug" webui/static/js/main.js | head -20`

Find where the summary is loaded (likely after `api.getTrack(slug)` resolves). Add immediately after the summary is in scope:

```js
// Browser tab title — reflect the active track's display name (or derived).
const tn = summary?.track?.display_name
  || (summary?.track?.file ? summary.track.file.replace(/\.mp3$/i, "") : null);
if (tn) document.title = `${tn} — MusIQ-Lab`;
```

(Place this where `summary` is defined for the loaded track — the exact location depends on the file's structure. Read the file first.)

- [ ] **Step 4: Manual smoke test**

Restart the webui (per the recent stale-process bug; static files don't need restart but the server changes from Tasks 1–5 do):

```powershell
webui\webui.ps1 stop
webui\webui.ps1 start
```

Open `http://127.0.0.1:8765/?slug=<some-slug>` and verify:
- Topbar title still renders correctly (no change visible yet because no rename has happened)
- Browser tab title reads `<derived-title> — MusIQ-Lab`

- [ ] **Step 5: Commit**

```bash
git add webui/static/js/ui/topbar.js webui/static/js/main.js
# Add track-picker.js too if Step 1 found it needed changes
git commit -m "feat(webui): topbar + browser <title> read display_name with derived fallback"
```

---

## Task 8: `shortcuts.js` — focus-target guard

**Files:**
- Modify: `webui/static/js/ui/shortcuts.js`

- [ ] **Step 1: Read shortcuts.js to find the keydown handler**

Run: `cat webui/static/js/ui/shortcuts.js | head -60`

Locate the `addEventListener("keydown", ...)` (or equivalent) entry point.

- [ ] **Step 2: Add the focus guard at the top of the handler**

Insert as the FIRST statement inside the keydown handler (before any key matching):

```js
// Don't capture keys when the user is typing in an input, textarea, or
// contenteditable. Prevents canvas shortcuts (space, digits) from firing
// inside the rename modal, lyrics-tab header, analyze modal, etc.
if (e.target?.matches?.("input, textarea, [contenteditable=true]")) return;
```

- [ ] **Step 3: Manual smoke test**

Reload the browser tab. With the lyrics tab open and the track having a slug-style title:
- Click into the lyrics-tab artist field
- Type characters and press digits/space — they should appear in the field, NOT trigger canvas shortcuts

If digits/space still trigger shortcuts, check that the handler is bound at the right level (document/window) and that `e.target` reflects the focused element. May need `document.activeElement` instead.

- [ ] **Step 4: Commit**

```bash
git add webui/static/js/ui/shortcuts.js
git commit -m "fix(webui): shortcuts.js — skip keys when typing in input/textarea/contenteditable"
```

---

## Task 9: Rename modal + ✎ pencil button + lyrics refresh hook

**Files:**
- Create: `webui/static/js/ui/rename-modal.js`
- Modify: `webui/static/js/ui/topbar.js` (add the pencil button)
- Modify: `webui/static/js/ui/lyrics-tab.js` (register `window.__musiqLyricsRefreshMeta`)
- Modify: `webui/static/css/track.css` (button + modal styles)

- [ ] **Step 1: Create the modal**

Create `webui/static/js/ui/rename-modal.js`:

```js
import { el } from "./dom.js";
import { api } from "../api.js";

export function showRenameModal({ slug, currentName, onSaved }) {
  const overlay = el("div", { class: "rename-modal-overlay" });
  const panel = el("div", { class: "rename-modal-panel" });

  panel.appendChild(el("h2", { class: "rename-modal-title", text: "Rename track" }));

  const input = el("input", {
    class: "rename-modal-input",
    attrs: { type: "text", value: currentName ?? "", spellcheck: "false" },
  });
  panel.appendChild(input);

  panel.appendChild(el("p", {
    class: "rename-modal-hint",
    text: 'Use "Artist - Title" to populate both fields. Otherwise the whole text becomes the title.',
  }));

  const errorBanner = el("div", { class: "rename-modal-error", style: { display: "none" } });
  panel.appendChild(errorBanner);

  const row = el("div", { class: "rename-modal-actions" });
  const cancelBtn = el("button", {
    class: "btn", attrs: { type: "button" }, text: "Cancel",
    onClick: () => overlay.remove(),
  });
  const saveBtn = el("button", {
    class: "btn primary", attrs: { type: "button" }, text: "Save",
    onClick: () => save(),
  });
  row.appendChild(cancelBtn);
  row.appendChild(saveBtn);
  panel.appendChild(row);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  // Autofocus and select-all so paste-and-replace is one motion.
  input.focus();
  input.select();

  const updateSaveEnabled = () => {
    const v = input.value.trim();
    saveBtn.disabled = !v || v === (currentName ?? "").trim();
  };
  updateSaveEnabled();
  input.addEventListener("input", updateSaveEnabled);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); if (!saveBtn.disabled) save(); }
    else if (e.key === "Escape") { e.preventDefault(); overlay.remove(); }
  });

  // Click on the dimmed backdrop closes; clicks on the panel don't bubble.
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
  panel.addEventListener("click", (e) => e.stopPropagation());

  async function save() {
    saveBtn.disabled = true;
    cancelBtn.disabled = true;
    errorBanner.style.display = "none";
    try {
      const resp = await api.renameTrack(slug, input.value.trim());
      onSaved?.(resp);
      overlay.remove();
    } catch (e) {
      errorBanner.textContent = e.message || String(e);
      errorBanner.style.display = "block";
      saveBtn.disabled = false;
      cancelBtn.disabled = false;
    }
  }
}
```

- [ ] **Step 2: Add the pencil button to topbar**

In `webui/static/js/ui/topbar.js`, after the line that creates `titleSpan` (line 23) and before the picker assembly, add a pencil button. Then attach the modal opener.

Replace the picker block (lines 23-30) with:

```js
  const titleSpan = el("span", {
    class: "title",
    text: summary?.track ? (summary.track.display_name || deriveTitle(summary.track.file)) : "(no track)",
  });
  const chev = el("span", { class: "chev", text: "▾" });
  const picker = el("div", {
    class: "track-picker",
    id: "track-picker",
    onClick: (e) => { e.stopPropagation(); onPickerToggle?.(picker); },
  }, [titleSpan, chev]);
  host.appendChild(picker);

  if (summary?.track) {
    const editBtn = el("button", {
      class: "title-edit",
      attrs: { type: "button", title: "Rename track" },
      text: "✎",
      onClick: (e) => {
        e.stopPropagation();
        import("./rename-modal.js").then((m) => m.showRenameModal({
          slug: window.__currentSlug,
          currentName: summary.track.display_name || deriveTitle(summary.track.file),
          onSaved: (resp) => {
            titleSpan.textContent = resp.display_name;
            document.title = `${resp.display_name} — MusIQ-Lab`;
            window.__musiqLyricsRefreshMeta?.();
          },
        }));
      },
    });
    host.appendChild(editBtn);
  }
```

- [ ] **Step 3: Register the lyrics refresh hook**

In `webui/static/js/ui/lyrics-tab.js`, find the `mount()` method (around line 18-24). Add at the bottom of `mount`:

```js
    // Cross-tab handoff: rename-modal in topbar.js calls this after a save
    // so the lyrics header re-reads the (just-updated) cached meta.
    window.__musiqLyricsRefreshMeta = () => {
      this.data = null;
      this._lazyLoad();
    };
```

- [ ] **Step 4: Add CSS for the button and modal**

Append to `webui/static/css/track.css`:

```css
.title-edit {
  background: transparent; border: none; color: var(--fg-2);
  font-size: 13px; cursor: pointer; padding: 0 6px; line-height: 1;
}
.title-edit:hover { color: var(--c-vocals); }

.rename-modal-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center;
}
.rename-modal-panel {
  background: var(--bg-1, #1a1a1a); border: 1px solid var(--bg-3);
  border-radius: 6px; padding: 18px 20px;
  width: min(480px, 92vw);
  display: flex; flex-direction: column; gap: 10px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6);
}
.rename-modal-title { margin: 0; font-size: 15px; color: var(--fg-1); }
.rename-modal-input {
  background: var(--bg-0, #0d0d0d); color: var(--fg-1);
  border: 1px solid var(--bg-3); border-radius: 4px;
  padding: 8px 10px; font-size: 13px; font-family: inherit;
  width: 100%; box-sizing: border-box;
}
.rename-modal-input:focus { outline: none; border-color: var(--c-vocals); }
.rename-modal-hint { margin: 0; color: var(--fg-2); font-size: 11px; }
.rename-modal-error {
  padding: 8px 10px; border: 1px solid #ff6b6b; border-radius: 4px;
  color: #ff6b6b; font-size: 12px; background: rgba(255, 107, 107, 0.08);
}
.rename-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
```

(If `.btn.primary` doesn't already exist in track.css or theme.css, the Save button will be unstyled — quickly grep for `.btn` and either reuse an existing primary style or add one inline here.)

- [ ] **Step 5: Manual end-to-end smoke**

1. Restart the webui (server-side changes from earlier tasks):
   ```powershell
   webui\webui.ps1 restart
   ```
2. Hard-refresh the browser (`Ctrl+F5`) to bypass static-file cache
3. Click the ✎ button next to the title pill — modal opens with the current name pre-selected
4. Type `Charlie Puth - Attention`, press Enter
5. Verify:
   - Title pill updates immediately
   - Browser tab title updates
   - Lyrics tab (open it) shows artist=`Charlie Puth`, title=`Attention` (no longer placeholder)
6. Reanalyze the track → verify the rename survives (lyrics meta + topbar both still correct)
7. Library dropdown → verify the track shows the new name in the picker

- [ ] **Step 6: Commit**

```bash
git add webui/static/js/ui/rename-modal.js webui/static/js/ui/topbar.js webui/static/js/ui/lyrics-tab.js webui/static/css/track.css
git commit -m "feat(webui): ✎ rename button + modal; lyrics tab re-reads meta after save"
```

---

## Task 10: E2E Playwright spec (optional, recommended)

**Files:**
- Create: `webui/tests-e2e/rename.spec.js`

- [ ] **Step 1: Read an existing spec for patterns**

Run: `cat webui/tests-e2e/viewer.spec.js | head -40`
Note the page-load and selector idioms in use.

- [ ] **Step 2: Write the spec**

Create `webui/tests-e2e/rename.spec.js`:

```js
const { test, expect } = require("@playwright/test");

test("rename track via pencil → topbar + lyrics tab update", async ({ page }) => {
  // Use the fixture track Playwright tests already rely on.
  await page.goto("/?slug=gorillaz_silent_running");

  // Open rename modal via pencil
  await page.getByTitle("Rename track").click();

  // Type a new name and Save
  const input = page.locator(".rename-modal-input");
  await input.fill("Test Artist - Test Title");
  await page.getByRole("button", { name: "Save" }).click();

  // Topbar reflects the new name
  await expect(page.locator(".track-picker .title")).toHaveText("Test Artist - Test Title");

  // Open lyrics tab and verify the header
  await page.getByRole("tab", { name: /lyrics/i }).click();
  await expect(page.locator(".lyrics-artist")).toContainText("Test Artist");
  await expect(page.locator(".lyrics-title")).toContainText("Test Title");

  // Cleanup: rename back so the fixture stays clean for other tests
  await page.getByTitle("Rename track").click();
  await page.locator(".rename-modal-input").fill("Gorillaz - Silent Running");
  await page.getByRole("button", { name: "Save" }).click();
});
```

- [ ] **Step 3: Run the spec**

Run: `cd webui/tests-e2e && npx playwright test rename.spec.js --headed`
Expected: PASS.

If it fails on selectors, adjust to match the actual DOM (the existing specs are the source of truth for selector style).

- [ ] **Step 4: Commit**

```bash
git add webui/tests-e2e/rename.spec.js
git commit -m "test(webui): E2E for rename — topbar + lyrics tab update"
```

---

## Self-Review

Spec coverage check:

| Spec section | Covered by |
|---|---|
| `user_meta.json` storage shape | Task 1 |
| `PRESERVE` adds `user_meta.json` | Task 4 |
| `tracks.get_summary` merges display_name | Task 2 |
| `tracks.list_tracks` reflects override | Task 3 |
| `PATCH /api/tracks/{slug}` route | Task 5 |
| Validation (length, path chars, type) | Task 1 + Task 5 |
| Smart split on " - " (first occurrence) | Task 1 + Task 5 |
| Lyrics meta side effect (existing + missing) | Task 5 |
| Cache invalidation | Task 5 (`tracks._cache.pop`) |
| Pencil ✎ button | Task 9 |
| Modal UX (autofocus, Enter/Esc, error) | Task 9 |
| Topbar title fallback | Task 7 |
| Track picker fallback | Task 7 (verified via Task 3's TrackEntry override) |
| Browser `<title>` | Task 7 |
| Lyrics-tab refresh hook | Task 9 |
| Shortcuts focus guard | Task 8 |
| E2E coverage | Task 10 |

No gaps. No "TBD" / "TODO" / placeholder strings in any task. Type and method names are consistent (`renameTrack`, `display_name`, `validate_display_name`, `split_artist_title`, `_clear_cache_dir`, `__musiqLyricsRefreshMeta`).
