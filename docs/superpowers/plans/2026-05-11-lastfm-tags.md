# Last.fm Tags + Similar Artists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Last.fm crowd-sourced tags and similar artists in the Track sidebar, keyed by the MBIDs that Plan A's identify stage writes to `cache/<slug>/identify.json`.

**Architecture:** All Last.fm work runs webui-side (Windows-side `.venv`, not WSL). A new `webui/webui/lastfm.py` module owns the HTTP client + disk cache with a 7-day TTL. A new FastAPI endpoint `GET /api/track/<slug>/lastfm` returns `{tags, similar_artists, ...}` or `{available: false, reason}` when keys / MBIDs are missing. The Track tab grows a new section below the existing analysis stats: a tag-chip row + a similar-artists list. Failures are silent (UI hides the section); a missing API key is treated as "available: false" rather than an error.

**Tech Stack:** Python 3.11 (webui `.venv`); `httpx` (already in webui requirements); FastAPI (existing). No new pip deps required.

**Depends on:** Plan A has shipped (`cache/<slug>/identify.json` exists and contains `mbid_recording` / `mbid_artist` when `identified=true`).

---

## File Structure

```
webui/webui/
  lastfm.py                       [NEW] Last.fm client + disk cache + TTL
  server.py                       [MOD] register /api/track/<slug>/lastfm route
webui/tests/
  test_lastfm_client.py           [NEW] mocked-HTTP tests
  test_lastfm_endpoint.py         [NEW] FastAPI route test (TestClient)
webui/static/js/sidebar/
  tags-row.js                     [NEW] renders tag chips + similar artists list
  index.js                        [MOD] mount tags-row in Track tab
webui/static/css/sidebar.css      [MOD] .tags-row + .similar-artists styles
webui/tests-js/
  tags-row.test.js                [NEW] node --test
```

---

## Task 1: Last.fm HTTP client + disk cache

**Files:**
- Create: `webui/webui/lastfm.py`
- Create: `webui/tests/test_lastfm_client.py`

- [ ] **Step 1: Write the failing test**

```python
# webui/tests/test_lastfm_client.py
import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from webui import lastfm


def _mock_resp(payload):
    return httpx.Response(200, json=payload)


def test_fetch_track_info_returns_tags(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    payload = {
        "track": {
            "name": "Silent Running",
            "toptags": {"tag": [
                {"name": "hip-hop", "count": 100},
                {"name": "alternative", "count": 50},
            ]},
        },
    }
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _mock_resp(payload))
    result = lastfm.fetch_track_info(mbid_recording="rec-mbid")
    assert result["tags"] == ["hip-hop", "alternative"]


def test_fetch_similar_artists(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    payload = {
        "similarartists": {"artist": [
            {"name": "Blur", "match": "0.95", "mbid": "blur-mbid"},
            {"name": "Beck", "match": "0.78", "mbid": "beck-mbid"},
        ]},
    }
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _mock_resp(payload))
    result = lastfm.fetch_similar_artists(mbid_artist="gorillaz-mbid", limit=10)
    assert len(result) == 2
    assert result[0] == {"name": "Blur", "match": 0.95, "mbid": "blur-mbid"}


def test_fetch_track_info_no_api_key(monkeypatch):
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    # Also poison analyze.keys' .env loader
    from analyze import keys as ak
    ak._loaded = True
    with pytest.raises(lastfm.LastFmError, match="no api key"):
        lastfm.fetch_track_info(mbid_recording="x")


def test_fetch_track_info_404(monkeypatch):
    monkeypatch.setenv("LASTFM_API_KEY", "abc")
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json={"error": 6, "message": "not found"}),
    )
    with pytest.raises(lastfm.LastFmError, match="not found"):
        lastfm.fetch_track_info(mbid_recording="missing")


def test_load_cache_returns_payload_within_ttl(tmp_path):
    payload = {"tags": ["a"], "similar_artists": []}
    cache_file = tmp_path / "lastfm.json"
    cache_file.write_text(json.dumps({"fetched_at": time.time(), "payload": payload}))
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400 * 7)
    assert result == payload


def test_load_cache_returns_none_past_ttl(tmp_path):
    payload = {"tags": ["a"]}
    cache_file = tmp_path / "lastfm.json"
    old_ts = time.time() - 86400 * 30  # 30 days ago
    cache_file.write_text(json.dumps({"fetched_at": old_ts, "payload": payload}))
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400 * 7)
    assert result is None


def test_load_cache_returns_none_when_missing(tmp_path):
    assert lastfm.load_cache(tmp_path, ttl_seconds=86400) is None


def test_write_cache_roundtrips(tmp_path):
    payload = {"tags": ["a", "b"], "similar_artists": [{"name": "X"}]}
    lastfm.write_cache(tmp_path, payload)
    result = lastfm.load_cache(tmp_path, ttl_seconds=86400)
    assert result == payload
```

- [ ] **Step 2: Run — verify fail**

Run (from `webui/`): `.venv/Scripts/python -m pytest tests/test_lastfm_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webui.lastfm'`.

- [ ] **Step 3: Implement the module**

```python
# webui/webui/lastfm.py
"""Last.fm API client + per-track disk cache.

Reuses the project-level analyze.keys helper (set in Plan A) for the
LASTFM_API_KEY .env load. Cache lives at cache/<slug>/lastfm.json with
a default TTL of 7 days.

Failure modes
-------------
- No API key:        raises LastFmError; endpoint catches and returns available=false
- HTTP non-200:      raises LastFmError
- Last.fm error obj: raises LastFmError (Last.fm returns 200 with {"error": N, "message": "..."})
- Cache stale:       returns None from load_cache; caller re-fetches
- Cache corrupt:     returns None (caller re-fetches)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from analyze import keys as _project_keys

ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_TTL_SECONDS = 7 * 86400
CACHE_FILE = "lastfm.json"
log = logging.getLogger(__name__)


class LastFmError(RuntimeError):
    pass


def _get_key() -> str:
    key = _project_keys.get_lastfm_key()
    if not key:
        raise LastFmError("no api key (set LASTFM_API_KEY in .env)")
    return key


def _request(params: dict) -> dict:
    params = {"api_key": _get_key(), "format": "json", **params}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(ENDPOINT, params=params)
    if resp.status_code != 200:
        raise LastFmError(f"HTTP {resp.status_code}")
    data = resp.json()
    if "error" in data:
        raise LastFmError(f"Last.fm error {data['error']}: {data.get('message', '')}")
    return data


def fetch_track_info(*, mbid_recording: str) -> dict:
    """Fetch toptags for a recording MBID. Returns {tags: [str, ...]}."""
    data = _request({"method": "track.getInfo", "mbid": mbid_recording})
    tags_raw = (data.get("track") or {}).get("toptags") or {}
    tag_list = tags_raw.get("tag") or []
    if isinstance(tag_list, dict):  # Last.fm returns dict if only 1 tag
        tag_list = [tag_list]
    return {"tags": [t["name"] for t in tag_list if t.get("name")]}


def fetch_similar_artists(*, mbid_artist: str, limit: int = 10) -> list[dict]:
    """Fetch similar artists for an artist MBID. Returns list of dicts."""
    data = _request({
        "method": "artist.getSimilar",
        "mbid": mbid_artist,
        "limit": limit,
    })
    artists_raw = (data.get("similarartists") or {}).get("artist") or []
    if isinstance(artists_raw, dict):
        artists_raw = [artists_raw]
    out = []
    for a in artists_raw:
        out.append({
            "name": a.get("name", ""),
            "match": float(a.get("match", 0.0)),
            "mbid": a.get("mbid", ""),
        })
    return out


def load_cache(cache_dir: Path, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict | None:
    path = cache_dir / CACHE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log.warning("lastfm.json corrupt at %s: %s", path, e)
        return None
    fetched_at = data.get("fetched_at", 0)
    if time.time() - fetched_at > ttl_seconds:
        return None
    return data.get("payload")


def write_cache(cache_dir: Path, payload: dict) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / CACHE_FILE).write_text(
        json.dumps({"fetched_at": time.time(), "payload": payload}, indent=2)
    )
```

- [ ] **Step 4: Run — verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_lastfm_client.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lastfm.py webui/tests/test_lastfm_client.py
git commit -m "feat(lastfm): client + disk cache with 7-day TTL

webui.lastfm exposes fetch_track_info (tags) + fetch_similar_artists,
keyed by MBIDs. Disk cache at cache/<slug>/lastfm.json honors a TTL
(default 7 days). Reuses analyze.keys.get_lastfm_key for .env loading.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: FastAPI endpoint `/api/track/<slug>/lastfm`

**Files:**
- Modify: `webui/webui/server.py`
- Create: `webui/tests/test_lastfm_endpoint.py`

- [ ] **Step 1: Inspect the existing server routes**

Read `webui/webui/server.py` and identify the existing `/api/track/<slug>` pattern. The new endpoint follows the same conventions for slug validation + 404-on-missing.

- [ ] **Step 2: Write the failing test**

```python
# webui/tests/test_lastfm_endpoint.py
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from webui import server
from webui import lastfm


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server._paths, "cache_root", lambda: tmp_path)
    return TestClient(server.app), tmp_path


def _seed_track(cache_dir: Path, *, mbid_rec=None, mbid_art=None):
    cache_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "duration_sec": 180.0, "tempo_bpm": 120.0, "key": "A:minor",
        "scale": "A natural minor", "stems_enriched": {}, "warnings": [],
    }
    (cache_dir / f"{cache_dir.name}.summary.json").write_text(json.dumps(summary))
    if mbid_rec or mbid_art:
        (cache_dir / "identify.json").write_text(json.dumps({
            "identified": True,
            "mbid_recording": mbid_rec, "mbid_artist": mbid_art,
            "title": "T", "artist": "A",
        }))


def test_endpoint_uses_cached_payload(client):
    tc, root = client
    cache = root / "my-track"
    _seed_track(cache, mbid_rec="r", mbid_art="a")
    payload = {"tags": ["rock"], "similar_artists": [{"name": "X", "match": 0.9, "mbid": ""}]}
    lastfm.write_cache(cache, payload)

    r = tc.get("/api/track/my-track/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["tags"] == ["rock"]


def test_endpoint_returns_unavailable_when_no_identify(client):
    tc, root = client
    cache = root / "no-mbid"
    _seed_track(cache)  # no identify.json

    r = tc.get("/api/track/no-mbid/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "mbid" in body["reason"].lower()


def test_endpoint_404_for_unknown_slug(client):
    tc, _ = client
    r = tc.get("/api/track/nonexistent/lastfm")
    assert r.status_code == 404


def test_endpoint_fetches_when_cache_missing(client, monkeypatch):
    tc, root = client
    cache = root / "fresh-fetch"
    _seed_track(cache, mbid_rec="r", mbid_art="a")

    monkeypatch.setattr(lastfm, "fetch_track_info", lambda *, mbid_recording: {"tags": ["a", "b"]})
    monkeypatch.setattr(lastfm, "fetch_similar_artists", lambda *, mbid_artist, limit=10: [
        {"name": "Sim", "match": 0.5, "mbid": ""},
    ])

    r = tc.get("/api/track/fresh-fetch/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["tags"] == ["a", "b"]
    assert body["similar_artists"][0]["name"] == "Sim"
    # And: the cache file should now exist.
    assert (cache / "lastfm.json").exists()


def test_endpoint_unavailable_when_lastfm_errors(client, monkeypatch):
    tc, root = client
    cache = root / "errors-out"
    _seed_track(cache, mbid_rec="r", mbid_art="a")

    def boom(**_kw):
        raise lastfm.LastFmError("no api key")
    monkeypatch.setattr(lastfm, "fetch_track_info", boom)

    r = tc.get("/api/track/errors-out/lastfm")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "api key" in body["reason"]
```

- [ ] **Step 3: Run — verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_lastfm_endpoint.py -v`
Expected: FAIL — endpoint not registered (404 on the valid-track case).

- [ ] **Step 4: Implement the endpoint**

Read `webui/webui/server.py` to confirm conventions (slug validation, cache_dir resolution helper). Then add (placement near other `/api/track/<slug>/...` routes):

```python
from webui import lastfm
from webui.identify import read_identify


@app.get("/api/track/{slug}/lastfm")
def get_lastfm(slug: str):
    cache_dir = _paths.cache_root() / slug
    if not cache_dir.exists():
        raise HTTPException(status_code=404, detail="track not found")

    identified = read_identify(cache_dir)
    if not identified or not identified.get("identified"):
        return {"available": False, "reason": "no MBID (track not identified)"}

    mbid_rec = identified.get("mbid_recording")
    mbid_art = identified.get("mbid_artist")
    if not mbid_rec and not mbid_art:
        return {"available": False, "reason": "identify.json missing both MBIDs"}

    cached = lastfm.load_cache(cache_dir)
    if cached is not None:
        return {"available": True, **cached}

    try:
        tags = lastfm.fetch_track_info(mbid_recording=mbid_rec)["tags"] if mbid_rec else []
        similar = lastfm.fetch_similar_artists(mbid_artist=mbid_art) if mbid_art else []
    except lastfm.LastFmError as e:
        return {"available": False, "reason": str(e)}

    payload = {"tags": tags, "similar_artists": similar}
    lastfm.write_cache(cache_dir, payload)
    return {"available": True, **payload}
```

(Imports may already exist for `HTTPException`. If not, add `from fastapi import HTTPException` to the existing import block.)

- [ ] **Step 5: Run — verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_lastfm_endpoint.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add webui/webui/server.py webui/tests/test_lastfm_endpoint.py
git commit -m "feat(lastfm): GET /api/track/<slug>/lastfm endpoint

Returns {available: bool, tags?, similar_artists?, reason?}. Reads
the disk cache first; on miss, fetches from Last.fm + writes the cache.
Soft-fails to available=false when no MBID is on disk or Last.fm
errors. Never 500s on missing keys / network issues — only 404s for
unknown slugs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend tags row + similar artists

**Files:**
- Create: `webui/static/js/sidebar/tags-row.js`
- Create: `webui/tests-js/tags-row.test.js`

- [ ] **Step 1: Write the failing JS test**

```js
// webui/tests-js/tags-row.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderTagsSection } from '../static/js/sidebar/tags-row.js';

test('renders tag chips when available', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['hip-hop', 'alternative', 'electronic'],
    similar_artists: [],
  });
  assert.ok(html.includes('hip-hop'));
  assert.ok(html.includes('alternative'));
  assert.ok(html.includes('chip'));
});

test('renders similar artists list', () => {
  const html = renderTagsSection({
    available: true,
    tags: [],
    similar_artists: [
      { name: 'Blur', match: 0.95, mbid: 'blur' },
      { name: 'Beck', match: 0.78, mbid: 'beck' },
    ],
  });
  assert.ok(html.includes('Blur'));
  assert.ok(html.includes('Beck'));
});

test('returns empty when available=false', () => {
  const html = renderTagsSection({ available: false, reason: 'no MBID' });
  assert.equal(html, '');
});

test('escapes tag names (XSS)', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['<script>evil</script>'],
    similar_artists: [],
  });
  assert.ok(!html.includes('<script>'));
});

test('caps similar artists at 10', () => {
  const many = Array.from({ length: 25 }, (_, i) => ({
    name: `Artist${i}`, match: 0.9 - i * 0.01, mbid: '',
  }));
  const html = renderTagsSection({ available: true, tags: [], similar_artists: many });
  // Count list items
  const matches = html.match(/<li/g) || [];
  assert.ok(matches.length <= 10);
});
```

- [ ] **Step 2: Run — verify fail**

Run: `node --test webui/tests-js/tags-row.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```js
// webui/static/js/sidebar/tags-row.js
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const MAX_TAGS = 12;
const MAX_SIMILAR = 10;

export function renderTagsSection(lastfm) {
  if (!lastfm || !lastfm.available) return '';

  const sections = [];

  const tags = (lastfm.tags || []).slice(0, MAX_TAGS);
  if (tags.length > 0) {
    const chips = tags.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('');
    sections.push(`<div class="tags-row">${chips}</div>`);
  }

  const similar = (lastfm.similar_artists || []).slice(0, MAX_SIMILAR);
  if (similar.length > 0) {
    const items = similar.map(a =>
      `<li><span class="name">${escapeHtml(a.name)}</span>` +
      `<span class="match">${Math.round((a.match || 0) * 100)}%</span></li>`
    ).join('');
    sections.push(`<ul class="similar-artists">${items}</ul>`);
  }

  if (sections.length === 0) return '';

  return `<section class="sidebar-card lastfm-card">` +
    `<h3>Tags &amp; Similar</h3>${sections.join('')}</section>`;
}
```

- [ ] **Step 4: Run — verify pass**

Run: `node --test webui/tests-js/tags-row.test.js`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add webui/static/js/sidebar/tags-row.js webui/tests-js/tags-row.test.js
git commit -m "feat(lastfm): tags + similar artists sidebar section

renderTagsSection(lastfmPayload) returns chip-row + similar list HTML.
Caps at 12 tags / 10 similar. XSS-escaped. Empty when available=false.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Mount section in Track tab + CSS

**Files:**
- Modify: whichever file composes the Track tab sidebar (read `webui/static/js/sidebar/index.js` to find)
- Modify: `webui/static/css/sidebar.css`
- Modify: whichever JS module loads `/api/track/<slug>` data — needs to also fetch `/api/track/<slug>/lastfm` (likely the same one)

- [ ] **Step 1: Inspect**

Read `webui/static/js/sidebar/index.js` (or whichever index file mounts the cards from Plan A's Task 11). Identify:
- Where the Track tab's section list is composed (where Plan A inserted `renderMetadataCard`).
- Where the track data is loaded (probably an `await fetch(/api/track/<slug>)` somewhere).

- [ ] **Step 2: Fetch + mount**

In the data-loading function, after the existing track-data fetch, fan-out to the lastfm endpoint:

```js
async function loadTrackData(slug) {
  const [trackResp, lastfmResp] = await Promise.all([
    fetch(`/api/track/${encodeURIComponent(slug)}`),
    fetch(`/api/track/${encodeURIComponent(slug)}/lastfm`),
  ]);
  const trackData = await trackResp.json();
  trackData.lastfm = await lastfmResp.json();  // {available: bool, tags?, similar_artists?}
  return trackData;
}
```

In the composition function, add the import + insertion:

```js
import { renderTagsSection } from './tags-row.js';

// Inside the section list, after renderMetadataCard (or wherever fits the
// information hierarchy — tags-and-similar belong below the analysis stats,
// since they're external context rather than primary track info):
const sections = [
  renderMetadataCard(trackData),         // from Plan A
  /* ...existing sections (Now playing / Stems / Loop / etc.)... */
  renderTagsSection(trackData.lastfm),    // NEW
];
```

- [ ] **Step 3: Add CSS**

In `webui/static/css/sidebar.css`, append:

```css
.lastfm-card .tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 8px 0;
}
.lastfm-card .chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--chip-bg, rgba(255,255,255,0.08));
  color: var(--chip-fg, var(--text-muted));
  font-size: 0.8em;
}
.lastfm-card .similar-artists {
  list-style: none;
  padding: 0;
  margin: 8px 0 0 0;
}
.lastfm-card .similar-artists li {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
}
.lastfm-card .similar-artists .match {
  color: var(--text-muted);
  font-size: 0.8em;
}
```

- [ ] **Step 4: Smoke-check in browser**

`webui.ps1 restart`. Open http://127.0.0.1:8765. Open a track that has been through the analyze pipeline (and so has `identify.json`). The Track tab should now show a "Tags & Similar" section.

If the test track wasn't identified by AcoustID, the section won't appear (expected — `available: false`). If it was, you should see the chip row + list of similar artists, with disk-cached results on subsequent loads (`cache/<slug>/lastfm.json` should exist after the first hit).

- [ ] **Step 5: Commit**

```bash
git add webui/static/js/sidebar/index.js webui/static/css/sidebar.css
git commit -m "feat(lastfm): mount Tags & Similar card in Track tab

Fan-out to /api/track/<slug>/lastfm in parallel with the main track-
data fetch; render renderTagsSection() into the Track tab card list.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Environment variable for TTL override

**Files:**
- Modify: `webui/webui/lastfm.py`
- Modify: `webui/tests/test_lastfm_client.py` (add one test)

This is a small polish task — make the TTL configurable so the user can set `LASTFM_TTL_DAYS=1` for fresh-fetches if they want.

- [ ] **Step 1: Failing test**

Append to `webui/tests/test_lastfm_client.py`:

```python
def test_default_ttl_respects_env_var(monkeypatch):
    monkeypatch.setenv("LASTFM_TTL_DAYS", "1")
    # Reload module-level default if needed (the impl uses a getter, not a constant)
    assert lastfm.get_default_ttl_seconds() == 86400
```

- [ ] **Step 2: Run — verify fail**

Run: `.venv/Scripts/python -m pytest tests/test_lastfm_client.py::test_default_ttl_respects_env_var -v`
Expected: FAIL — `get_default_ttl_seconds` undefined.

- [ ] **Step 3: Implement**

In `webui/webui/lastfm.py`, replace the module-level `DEFAULT_TTL_SECONDS` constant with a function:

```python
def get_default_ttl_seconds() -> int:
    import os
    days = os.environ.get("LASTFM_TTL_DAYS")
    if days:
        try:
            return int(days) * 86400
        except ValueError:
            pass
    return 7 * 86400
```

Update `load_cache` to use it when the caller doesn't pass `ttl_seconds`:

```python
def load_cache(cache_dir: Path, *, ttl_seconds: int | None = None) -> dict | None:
    if ttl_seconds is None:
        ttl_seconds = get_default_ttl_seconds()
    ...
```

And update the endpoint call site in `server.py` if it passes `ttl_seconds` explicitly (it doesn't in the Task 2 code shown above, so probably nothing to change).

- [ ] **Step 4: Run — verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_lastfm_client.py -v`
Expected: 9 passed (8 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add webui/webui/lastfm.py webui/tests/test_lastfm_client.py
git commit -m "feat(lastfm): LASTFM_TTL_DAYS env-var override

Default TTL is now sourced from get_default_ttl_seconds() which reads
LASTFM_TTL_DAYS at call time. Defaults to 7 days when unset/invalid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- ✅ Last.fm client with both endpoints (Task 1)
- ✅ Disk cache with TTL (Task 1)
- ✅ FastAPI endpoint (Task 2)
- ✅ Tag chip row + similar artists list UI (Task 3)
- ✅ Track tab mount + parallel fetch (Task 4)
- ✅ Configurable TTL (Task 5)

**Failure modes covered:**
- ✅ No API key → endpoint returns `available: false` (Tasks 1, 2)
- ✅ No MBID on disk → endpoint returns `available: false` before any HTTP (Task 2)
- ✅ Last.fm 200-with-error → raises LastFmError → endpoint catches (Task 1)
- ✅ Cache stale → reload (Task 1)
- ✅ Cache corrupt → treat as missing (Task 1)
- ✅ XSS in tags (Task 3)
- ✅ Excessive similar-artists from API → capped (Task 3)

**Type consistency:**
- `fetch_track_info()` returns `{"tags": [str, ...]}` — Task 2 endpoint spreads it.
- `fetch_similar_artists()` returns `[{name, match, mbid}, ...]` — Task 3 UI iterates the same shape.
- Endpoint response shape `{available: bool, tags?, similar_artists?, reason?}` — Task 3 UI checks `available` first.

**Placeholders:** None. Every code step shows code. The two "look at existing file" steps (Task 2 Step 1, Task 4 Step 1) state what to find but the subsequent steps include the actual code that gets written.
