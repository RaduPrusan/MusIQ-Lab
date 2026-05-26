# Round 1 — Subagent A3: Key + Auth Sanity Audit

**Date:** 2026-05-12
**Status:** All five gates PASS. R1 can advance to Round 2 without re-investigating this lane.
**Scope:** Read-only audit. No source or cache file modified.

---

## Checklist

- [x] **ACOUSTID_API_KEY loads from .env with no silent fallback**
- [x] **Project .env exists, key is non-empty (value not printed)**
- [x] **Canary lookup against known-identified track succeeds**
- [x] **AcoustID rate-limit doc still says ≤3 req/s**
- [x] **MusicBrainz client sets identifiable User-Agent**

---

## 1. `analyze/keys.py` audit

File: `<PROJECT_PATH>/analyze/keys.py` (40 lines, single source of truth).

- Loads `.env` from the **project root** (`Path(__file__).parent.parent`), i.e. the in-repo `MusIQ-Lab/.env`. **Not** the global `~/.claude/skills/cloud-image-gen/.env` — correct (that one is image-gen only).
- One-shot lazy load gated by module-level `_loaded` flag; `load_dotenv(env_path)` only runs if the file exists. No environment-name override (no `ACOUSTID_KEY`, no `ACOUSTID_CLIENT_KEY`, no test/dev variant) — single canonical env var name `ACOUSTID_API_KEY`.
- `get_acoustid_key()` returns `os.environ.get("ACOUSTID_API_KEY")` — returns `None` when missing, **no empty-string default**, **no fallback to a placeholder**.
- Format validation: **none**. The loader does not check key shape. The downstream caller `analyze/clients/acoustid.py:40-42` does check truthiness (`if not api_key: raise AcoustIDError("no api key …")`) so an empty key fails loudly, not silently. The 8-char Application key format is not enforced, but an invalid format would fail the canary at HTTP 400 within one request — adequate.
- Logging on miss: **none**. There is no `logger.warning` when the key is absent. This is acceptable because `lookup()` raises `AcoustIDError` with a clear message that propagates up to `identify.py`, which writes `identified=false, reason="acoustid error: no api key..."` into the sidecar. Operator-visible at sidecar-read time.

**Verdict:** Loading path is clean. No silent-fallthrough trap.

## 2. `.env` presence & key shape

- File: `<PROJECT_PATH>/.env` exists (76 bytes, 2 lines).
- Keys present: `ACOUSTID_API_KEY`, `LASTFM_API_KEY`.
- `ACOUSTID_API_KEY` is non-empty; **length 10** (consistent with the AcoustID Application API key shape — short alphanumeric, not the 36-char personal user-account key).
- Project `.env` is the source — *not* the global cloud-image-gen `.env`. Confirmed via the `Path(__file__).parent.parent` resolution in `keys.py`.

Value **not** printed to logs or this report.

## 3. Canary round-trip against a known-identified track

Track: `cache/jamiroquai_everyday/jamiroquai_everyday.mp3`
Expected MBID (from cached `identify.json`): `b817cffd-1d5c-4905-90a4-8f9e8367a14a` ("Everyday" / Jamiroquai).

Pipeline:
1. `wsl -e bash -c "<vendor>/fpcalc -json …mp3"` → fingerprint length 3690 chars, duration 270.29 s. fpcalc OK.
2. `httpx.get(https://api.acoustid.org/v2/lookup, params={client, meta=recordings, fingerprint, duration})` with project key.

Response:
- `HTTP 200`, `status="ok"`
- `len(results) == 2`, top `score=0.9584`, top has 3 recordings linked
- Top `recordings[0].id == b817cffd-1d5c-4905-90a4-8f9e8367a14a` — **matches expected MBID exactly**

**Verdict:** The Application API Key is correctly registered. No "HTTP 400 invalid API key", no `status=error`. The historical "AcoustID User Key vs Application Key" failure mode (memory note `acoustid_app_key_vs_user_key`) does **not** apply to the current `.env`.

## 4. AcoustID rate limit confirmation

- `acoustid.py:5` comment: `Rate limit: 3 req/s, enforced per-client.`
- Live fetch of `https://acoustid.org/webservice` (2026-05-12): the page still reads "**do not make more than 3 requests per second**" under the "Rate limiting" section.
- **No change.** The comment is accurate.

Side note (not a blocker): `acoustid.py` does not actually enforce a 3 req/s gate; the comment says "if batch identification is added later, add a `RateLimiter` similar to MusicBrainz's 1 req/s gate." This is intentional and noted in the source. The Round-1-A2 corpus-probe agent will need to self-throttle to 3/s when sweeping the 30-track corpus (already called out in its prompt).

## 5. MusicBrainz User-Agent

- `analyze/clients/musicbrainz.py:48` sends `headers={"User-Agent": keys.get_user_agent()}`.
- `keys.py:15` defines `_USER_AGENT = "MusIQ-Lab/0.1 ( https://github.com/RaduPrusan/MusIQ-Lab )"`.
- This is the canonical MB-required shape: `<app-name>/<version> ( <contact-info> )`. App name, version, and a public contact URL are all present. MB throttles ambiguous/missing UAs harder; this one is identifiable and stable.

**Verdict:** UA is compliant. No change needed.

---

## Summary

Every Round-1 sanity gate is green:

| Gate | Status | Evidence |
|---|---|---|
| `.env` load path | PASS | `keys.py` single-source, no fallback defaults, no alternate env vars |
| Key presence | PASS | 10-char non-empty value in project-root `.env` |
| Round-trip | PASS | Jamiroquai canary returns the expected MBID at score 0.958 |
| Rate limit doc | PASS | Source comment "3 req/s" matches live `acoustid.org/webservice` |
| MB User-Agent | PASS | `MusIQ-Lab/0.1 ( github URL )` — compliant |

**R1 can advance.** No source changes proposed by this lane. The Bucket-A/B/C failure modes documented in the spec are **not** caused by an auth/key/UA problem — the API surface is healthy. Investigation should focus on the Bucket-C result-walking bug, threshold recalibration, and silence-strip preprocessing as planned.

### Minor observations (non-blocking, for the reviewer to consider)

- `keys.py` does not log a warning on key absence. Acceptable because `acoustid.py` raises a clear `AcoustIDError`, but a one-line `logger.warning` in `_ensure_loaded()` when `.env` is missing or the key is `None` would shorten future "why isn't identify working" debug loops. Optional, not load-bearing.
- The 3 req/s rate-limit comment is documentation-only; there is no enforced gate in `acoustid.py`. Today's interactive single-track usage cannot exceed 3/s, but Round 2's probe re-run and any future batch identification path must throttle client-side. Already called out in the Round-1-A2 prompt.
- `acoustid.py:84-88` returns only `recordings[0]` — when AcoustID returns multiple recordings for a single result row (e.g. alternate releases of the same recording), the first is taken without ranking. Not in scope for this lane; flagging for A1 (static analysis) if not already on its list.
