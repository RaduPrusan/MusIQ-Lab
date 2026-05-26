# Analyze-from-library design

**Date:** 2026-05-02
**Status:** Approved (design phase)
**Scope:** Add two new entry points to the webui — "Analyze new audio file" and "Analyze YouTube URL" — both surfacing in the Library Tracks dropdown header. Default the stem-separation quality to **Best** for the new flows and for the existing Reanalyze modal.

## Goals

- The user can pick a local audio file (`.mp3` / `.wav` / `.flac`) from the Library Tracks dropdown, have it transcoded if needed, and run the full analyze pipeline against it without leaving the browser.
- The user can paste a YouTube URL, have the audio downloaded via the project's canonical `yt-dlp.exe`, and analyzed end-to-end.
- Both new flows reuse the existing reanalyze modal's streaming UX (NDJSON event protocol, stage chips, log box, stats panel) so there's a single mental model for "the pipeline is running."
- Sensible behavior on slug collisions (would-be cache slug already in `cache/`): user gets a three-button choice — `Add New <slug>-2` / `Reanalyze` / `Cancel`.
- Default quality: **Best** everywhere a user-facing analyze action is initiated.

## Non-goals

- Multi-format source-of-truth in the pipeline. WAV/FLAC inputs are transcoded to MP3 V0 at staging; pipeline + webui playback continue to assume `.mp3` source. Revisit if a quality complaint arrives.
- Concurrent analyses, queueing, or resumability. One analysis at a time across all flows (existing single-flight lock, broadened).
- Multi-user / multi-tab safety beyond what the existing single-user 127.0.0.1 webui already provides. Browser tab races are guarded by a server-side recheck but not optimized away.
- Drag-and-drop in the picker. `<input type="file">` covers v1.
- Playlist URL semantics for YouTube. yt-dlp will pick item 1 and emit a warning, surfaced as a log line.
- Pre-emptive yt-dlp auto-update at server startup. User-initiated only, via the modal's `Update yt-dlp & retry` affordance.
- Changing the API/CLI default for `--stems-quality` (stays `"normal"`). Only the UI default flips to `"best"`.

## UI

### Library Tracks dropdown — header buttons

`webui/static/js/ui/track-picker.js` builds the `tp-panel` overlay. The header today reads `LIBRARY · N TRACKS`. Add two compact buttons right-aligned within the same flex container:

```
LIBRARY · 47 TRACKS                              [+ File]  [+ YT]
```

- `+ File` → opens the new **Analyze modal** in file-picker state.
- `+ YT` → opens the same modal in URL state.

CSS update lives in `webui/static/css/track.css`: header becomes a flex row with `justify-content: space-between`; buttons styled like the existing `.show-suppressed-btn` outlined pill (consistent vocabulary).

### Analyze modal — states

A new modal in `webui/static/js/ui/analyze-modal.js`, distinct from the reanalyze modal but built from the same primitives. Implementation note for the planner: `buildQualitySelector`, the NDJSON stream-reader (currently `streamReanalyze`), and `renderStats` should be extracted to a shared module (e.g. `webui/static/js/ui/analyze-shared.js`) and imported by both `reanalyze.js` and `analyze-modal.js`. The reanalyze module keeps its existing public entry (`showReanalyzeModal`) and its existing on-the-wire endpoint — only its private helpers move.

The modal is a single overlay/panel that swaps content between five states:

#### 1. Input step

Two variants depending on which button opened the modal:

**File variant:**
- Heading: "Analyze new audio file"
- `<input type="file" accept=".mp3,.wav,.flac">` with file-name display when chosen (browser only exposes `file.name` — basename, no path — for security)
- Quality selector (segmented control, defaults to **Best**)
- Footer: `Cancel` / `Analyze` (Analyze disabled until a file is chosen *and* the slug-for pre-check returns a valid extension; on 415, an inline `Unsupported file type: .m4a` message appears next to the file-name display and the Analyze button stays disabled — no popup)

**URL variant:**
- Heading: "Analyze YouTube URL"
- `<input type="text" placeholder="https://www.youtube.com/watch?v=...">`
- Quality selector (defaults to **Best**)
- Footer: `Cancel` / `Analyze` (Analyze disabled until input is non-empty)

On `Analyze` click:
- File variant: hits `GET /api/util/slug-for?filename=<file.name>` to pre-check collision.
- URL variant: hits `POST /api/tools/analyze/youtube` with a `dry_run:true` flag (or equivalent — see Endpoints) which returns the predicted slug + collision info as a single JSON response (not a stream).

If `exists: false` → transition straight to streaming step. If `exists: true` → transition to collision step.

#### 2. Slug-collision step

Replaces the input step's body in-place:

- Heading retained.
- Body: "Already in library: `bohemian_rhapsody`"
- Three buttons stacked horizontally:
  - `Add New bohemian_rhapsody-2` (primary) — POSTs with `mode="new"`, `slug=<suggested>`
  - `Reanalyze` — POSTs with `mode="reanalyze"`, `slug=<existing>`. Wipes existing cache. **Source-of-truth semantics differ between flows:**
    - **Upload flow:** the *newly uploaded file* becomes the source. The user's intent is "replace the existing track with this new file" — they're holding a fresh copy in the file picker, that wins.
    - **YouTube flow:** the *existing cached source MP3* is reused. No re-download. Identical to clicking Reanalyze on the existing track in the picker. Rationale: a YouTube URL collision means the same video-id, so the bytes would be identical anyway, and skipping the download saves 5-30 seconds.
  - `Cancel` — closes modal.

Suggested suffix increments to find the first free slot (`-2`, `-3`, …) — server returns the first one that doesn't exist.

**YouTube `Add New` semantics (asymmetry note):** because YouTube filenames embed an 11-char video ID, a YouTube collision means "this exact video was already analyzed" (not just "same title"). `Add New <slug>-2` produces a second cache entry mirroring the same on-disk download; both `summary.json` files end up with `windows_path` pointing at the same file. This is rare-but-supported (e.g., the user wants to compare two analyses of the same video at different qualities). For uploads, `Add New` is the common case (different files, same filename); for YouTube, it's an edge case but offered for symmetry.

#### 3. Streaming step

Identical layout to the existing reanalyze streaming UI, with one addition: a **phase strip** above the stage chips, showing high-level orchestration phases:

- Upload flow: `[● Upload] [● Transcode] [● Analyze]` (Transcode hidden if input is `.mp3`)
- YouTube flow: `[● Download] [● Analyze]`

Each phase chip lights up when its `{type:"phase",name,status:"start"}` event arrives and dims (or marks done) on `status:"end"`. The Analyze phase contains the existing per-stage chips (`stems`, `beats`, …) which behave exactly as in the reanalyze modal.

For YouTube, the Download phase also shows a thin progress bar driven by `{type:"progress",phase:"download",pct,eta_sec,speed}` events parsed from yt-dlp's `--newline` output.

The log box and rest of the streaming UI is unchanged.

#### 4. Done step

Stats panel renders identically to the reanalyze modal (uses the same `renderStats` helper). Footer:

- `Open new track` (primary) — sets `location.search = "?slug=<new>"`. The webui's existing `popstate`/router logic handles the rest.
- `Stay here` (secondary) — closes the modal. The library list refreshes in the background so the new track is in the picker on next open.

#### 5. Error step

Error banner replaces the stats area. Footer behavior depends on `error.kind`:

- `ytdlp_stale` → footer shows `Update yt-dlp & retry` (primary) + `Close`. Clicking retry re-POSTs the YouTube endpoint with `update_ytdlp:true`.
- `slug_collision` (race-loss case) → footer shows `Show options` which transitions back to the collision step with the freshly-detected existing slug.
- All other kinds → footer shows `Close` only.

### Reanalyze modal default change

`webui/static/js/ui/reanalyze.js:32` — flip:
```js
const DEFAULT_QUALITY = "normal";  // before
const DEFAULT_QUALITY = "best";    // after
```
Single-line change. No other reanalyze logic is touched.

## Endpoints

All three new routes return `application/x-ndjson` streams (except the slug-for util which returns plain JSON). They share the existing event protocol from `_reanalyze_stream` plus three new event types (see Protocol below).

### `GET /api/util/slug-for`

Pre-flight collision check for the upload flow.

**Query params:** `filename` (string, required)

**Response (200 JSON):**
```json
{
  "slug": "bohemian_rhapsody",
  "exists": true,
  "suggested_new_slug": "bohemian_rhapsody-2"
}
```
- `slug`: result of running `analyze.cache.slug_for` on `Path(filename)`.
- `exists`: `True` iff `cache/<slug>/summary.json` is present.
- `suggested_new_slug`: first free `<slug>-N` slot (N starting at 2). Always returned, even if `exists:false`, so the modal can decide UI flow without a second roundtrip.

**Response (415 JSON):** `{ "error": "unsupported_type", "extension": ".m4a" }` if the filename's extension isn't in the allowlist `{.mp3, .wav, .flac}` (case-insensitive). Filenames with no extension are also rejected as `unsupported_type` with `extension: ""` — we won't try to guess.

### `POST /api/tools/analyze/upload`

**Request:** `multipart/form-data`
- `file` (file, required): `.mp3` / `.wav` / `.flac`, ≤ 500 MB
- `quality` (form field, required): `fast` | `normal` | `best`
- `mode` (form field, optional, default `new`): `new` | `reanalyze`
- `slug` (form field, required): the explicit target slug. The modal computes this via `GET /api/util/slug-for` and passes it back, so the server has a single source of truth and the user-facing slug shown in the collision step is the slug actually used.

Implementation note: uses FastAPI `UploadFile` (whole-body buffered to temp via Starlette). Cap enforced by middleware on `Content-Length`; mid-stream cap-busting yields a stream-terminating error event before transcode/analyze begins.

**Response:** NDJSON stream (see Protocol).

**Validation errors** (returned as HTTP 4xx *before* the stream begins):
- 400 if the client-sent `slug` doesn't match the server-computed expectation. **Slug validation rule:** server computes `expected_base = slug_for(Path(file.filename))`. The client-sent `slug` is accepted iff:
  - `mode="new"` and `slug == expected_base` (no-collision case), OR
  - `mode="new"` and `slug == f"{expected_base}-{N}"` for some integer N ≥ 2 (collision "Add New" case), OR
  - `mode="reanalyze"` and `slug == expected_base` (collision "Reanalyze" case).

  Anything else → 400. This forecloses path traversal (`../`, `/etc/passwd`) and contract violations.
- 413 if `Content-Length` > 500 MB
- 415 if file extension or content-type fails allowlist (`audio/mpeg`, `audio/wav`, `audio/x-wav`, `audio/flac`, `audio/x-flac`)
- 409 if server-side slug-collision recheck fails (client sent `mode="new"` but the chosen `slug` now exists)
- 423 if the analyze lock is busy (another flow running) — single error event in the stream then close

### `POST /api/tools/analyze/youtube`

**Request:** `application/json`
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "quality": "best",
  "mode": "new",
  "slug": "title-vidid",
  "update_ytdlp": false,
  "dry_run": false
}
```
- `url` (required): any URL yt-dlp accepts; not pre-validated beyond non-empty.
- `quality` (required): `fast` | `normal` | `best`.
- `mode`: `new` | `reanalyze`. Required *unless* `dry_run:true`. When `dry_run:true`, `mode` is ignored if sent.
- `slug`: target slug. Required *unless* `dry_run:true`. When `dry_run:true`, `slug` is ignored if sent. Validated server-side against the metadata-derived `expected_base` using the same rule documented for the upload endpoint.
- `update_ytdlp` (optional, default `false`): when `true`, server runs `yt-dlp -U` before metadata fetch + download. Set by the modal when the user clicks `Update yt-dlp & retry`.
- `dry_run` (optional, default `false`): when `true`, server runs only the metadata simulate + slug compute + collision check, returning a single JSON response (not a stream):
  ```json
  {
    "predicted_slug": "title-vidid",
    "exists": false,
    "suggested_new_slug": "title-vidid-2"
  }
  ```
  Used by the modal to do the collision pre-check for the YouTube flow (parallels `/api/util/slug-for` for the upload flow). The `update_ytdlp:true` flag is honored on the dry_run path too — the modal sends it when retrying a dry_run that previously returned a stale error, so the metadata fetch + the eventual download both benefit from the freshly-updated yt-dlp.

**Response:** NDJSON stream when `dry_run:false` (see Protocol). Plain JSON when `dry_run:true`.

**Errors:** Same shape as upload, plus `ytdlp_metadata_failed` / `ytdlp_stale` / `ytdlp_download_failed` (surfaced as in-stream `{type:"error"}` events with `kind` set).

### `POST /api/tools/reanalyze/{slug}`

Unchanged externally. Internally refactored to delegate to `_run_analyze_stream(slug, source_path, quality)` (the shared helper). The pre-existing payload `{quality}` and behavior are preserved.

## Protocol

NDJSON events extending the existing reanalyze protocol:

```json
{"type":"log","line":"..."}
{"type":"stage","name":"stems","status":"running"|"cached"|"done"|"error"}
{"type":"phase","name":"upload"|"transcode"|"download"|"analyze","status":"start"|"end"}    // NEW
{"type":"progress","phase":"download","pct":42.7,"eta_sec":89,"speed":"3.21MiB/s"}          // NEW
{"type":"slug","slug":"<final-slug>"}                                                       // NEW
{"type":"done","stats":{...},"slug":"..."}
{"type":"error","message":"...","kind":"ytdlp_stale"|"slug_collision"|"upload_too_large"|"unsupported_type"|"ytdlp_metadata_failed"|"ytdlp_download_failed"|"ffmpeg_failed"|"analyze_failed"|"lock_busy"|"internal"|null}
```

`kind` on error events drives the modal's recovery affordance (e.g. `Update yt-dlp & retry` only appears when `kind:"ytdlp_stale"`).

## Server-side orchestration

### Shared helper: `_run_analyze_stream(slug, source_path, quality)`

Lives in a new module `webui/webui/analyze_runner.py`. Generic analyze runner that:
1. Acquires `_analyze_lock` (renamed from `_reanalyze_lock`); emits `{type:"error",kind:"lock_busy"}` and exits if busy. **Lock-leak fix (in scope):** the existing reanalyze code releases the lock when the response generator exits — including on client disconnect mid-stream. This orphans the WSL subprocess (still writing to `cache/<slug>/`) while a new analyze can immediately acquire the lock and clobber the same directory. Since we're refactoring this code anyway, fix it here: wrap the subprocess lifetime in a `try/finally` that calls `proc.kill()` followed by `await proc.wait()` on early exit. Unblocks: future enhancement of an explicit user-cancel button. Cost: ~6 lines.
2. If `cache/<slug>/` exists: emits a log line and clears it (`_clear_cache_dir`).
3. Stages `source_path` outside cache (tempdir) so the cache wipe doesn't take it out.
4. Emits `{type:"phase",name:"analyze",status:"start"}`.
5. Spawns `wsl -- bash -c "cd <project> && source .venv/bin/activate && python -u -m analyze <staged_mp3> --stems-quality <q> 2>&1"` (same WSL invocation the existing reanalyze uses; existing `_to_wsl_path` reused).
6. Pumps stdout line-by-line, emitting `{type:"stage"}` for `==> Stage X: ...` lines and `{type:"log"}` for everything.
7. On non-zero exit: emits `{type:"error",kind:"analyze_failed"}` and exits.
8. On success: re-reads `summary.json` via `tracks.get_summary`, emits `{type:"slug",slug:...}`, `{type:"phase",name:"analyze",status:"end"}`, then `{type:"done",stats:...,slug:...}`.

Used by all three flows.

### Upload flow

`POST /api/tools/analyze/upload` handler:
1. Validates extension + content-type. (Reject with 415 before reading the body if possible — note that `Content-Type` of the *upload* is multipart; the per-file content-type is in the form-data envelope.)
2. Server-side slug-collision recheck on the provided `slug`/`mode` combo. Reject with 409 if `mode="new"` and slug exists, or `mode="reanalyze"` and slug doesn't exist.
3. Begins the NDJSON stream.
4. Emits `{type:"phase",name:"upload",status:"start"}`. Reads the `UploadFile` to a tempdir. Emits `phase:upload status:end`.
5. If extension is `.wav` or `.flac`: emits `phase:transcode status:start`. Spawns:
   ```
   ffmpeg -y -loglevel warning -i <tmp_in> -c:a libmp3lame -q:a 0 <tmp_out.mp3>
   ```
   Streams stderr lines as `{type:"log"}`. On success, deletes `tmp_in`, swaps `source_path = tmp_out`. Emits `phase:transcode status:end`. On non-zero exit: `{type:"error",kind:"ffmpeg_failed"}`.
6. Calls `_run_analyze_stream(slug, source_path, quality)`.

Provenance: uploaded files have `windows_path: null` in the resulting `summary.json` (the browser doesn't expose the original path). The pipeline already writes a cache mirror at `cache/<slug>/<slug>.mp3`, and `server.py:309` falls back to it for playback when `windows_path` is missing — no additional change needed.

### YouTube flow — Reanalyze branch

When the streaming-path POST arrives with `mode="reanalyze"`, the handler skips the download phase entirely and delegates straight to `_run_analyze_stream(slug, cache/<slug>/<slug>.mp3, quality)` (or `windows_path` if recorded and present, matching the existing reanalyze fallback chain in `server.py:300-313`). No yt-dlp invocation. No phase events for `download`. The user gets the same experience as clicking Reanalyze in the existing tools menu.

### YouTube flow — Add New / no-collision branch

`POST /api/tools/analyze/youtube` handler:

**`dry_run:true` path (single JSON response):**
1. Spawns `yt-dlp.exe --skip-download --print "%(title)s-%(id)s" --no-update <URL>` (argv list, no shell — `$` chars in the binary path are literal).
2. Captures stdout (one line: `<title>-<id>`). Computes `slug_for(Path(<title>-<id> + ".mp3"))` — **the synthetic `.mp3` extension is critical.** `Path("Track 1.0 (Live)-zXYz").stem` returns `"Track 1"` because `Path` treats the last dot as the extension separator; without appending `.mp3`, slugs would silently differ from what the real download produces. Implementation must always pass a `.mp3`-suffixed string to `slug_for` here.
3. Checks `cache/<slug>/`. Returns `{predicted_slug, exists, suggested_new_slug}`.
4. On stderr matching the stale-yt-dlp pattern: returns 503 with `{error:"ytdlp_stale", message:...}`. The modal interprets this as "show Update + retry button on this very same dialog state" (the stale check happens before the user even sees the streaming UI — special-case the error in the input step).
5. On other failures: returns 502 with `{error:"ytdlp_metadata_failed", message:...}`.

**Streaming path (`dry_run:false`):**
1. Server-side slug recheck (same as upload).
2. Begins NDJSON stream.
3. If `update_ytdlp:true`: emits `{type:"phase",name:"download",status:"start"}` (download phase encompasses the update too), then runs `yt-dlp.exe -U`, streaming output to log.
4. Emits `phase:download status:start` (or continues from the update). Spawns:
   ```
   yt-dlp.exe -x --audio-format mp3 --audio-quality 0 --no-update --newline
              -o "<YT_OUT>/%(title)s-%(id)s.%(ext)s"
              --print after_move:filepath
              <URL>
   ```
   - `YT_OUT = C:/Users/<you>/Videos/Any Video Converter Ultimate/Youtube` (CLAUDE.md canonical location).
   - argv list, no shell.
   - Captures stdout/stderr line-by-line. Two parsers run on each line:
     - `[download] N.N% of XXX MiB at YYY MiB/s ETA HH:MM:SS` → emit `{type:"progress",phase:"download",pct,eta_sec,speed}`. Always also emit `{type:"log"}`.
     - The lone non-prefixed final line (the `--print after_move:filepath` output) → recorded as `final_path`.
5. On non-zero exit:
   - If stderr matches stale-yt-dlp patterns (`HTTP Error 403: Forbidden`, `Your yt-dlp version (...) is older than 90 days`, `Sign in to confirm you're not a bot`, `Requested format is not available`, `formats have been skipped as they are missing a url` + download failure): emit `{type:"error",kind:"ytdlp_stale"}`.
   - Otherwise: emit `{type:"error",kind:"ytdlp_download_failed"}`.
6. Emits `phase:download status:end`. Calls `_run_analyze_stream(slug, final_path, quality)`.

Downloaded `.mp3` files persist in `YT_OUT/` (per CLAUDE.md, no `-k` to keep intermediates — only the final `.mp3` is left). The pipeline records `windows_path = <YT_OUT>/<title>-<id>.mp3` in `summary.json` for future reanalyze.

### Lock semantics

- Single module-global `_analyze_lock = asyncio.Lock()` shared by reanalyze, upload, and youtube flows.
- Lock acquired *after* the input bytes are in hand: upload flow acquires after the multipart body finishes buffering to temp (so a slow client doesn't gate other analyses); YouTube flow acquires before yt-dlp starts the real download; reanalyze acquires at handler entry (no upload phase). Lock is *not* held during the upload buffer or the yt-dlp metadata simulate.
- Lock held across transcode + download + analyze. Released when the stream closes (success or error).
- yt-dlp metadata fetch (dry_run path) runs *outside* the lock — fast, idempotent, no GPU.
- The `GET /api/util/slug-for` endpoint runs entirely outside the lock.
- A second flow attempting to acquire the lock gets `{type:"error",kind:"lock_busy"}` and the modal shows a Close-only error step. No queueing.

## Defaults change

| Location | Before | After |
|---|---|---|
| `webui/static/js/ui/reanalyze.js:32` `DEFAULT_QUALITY` | `"normal"` | `"best"` |
| New analyze modal initial state | n/a | `quality = "best"` |
| `webui/webui/server.py:53` `_DEFAULT_STEMS_QUALITY` (server fallback) | `"normal"` | **unchanged** |
| `analyze/cli.py` `--stems-quality` default | `"normal"` | **unchanged** |

The CLI and server fallbacks stay at `"normal"` because they're consumed by callers other than the new UI (existing `python -m analyze` muscle memory, hypothetical future API clients). The UI explicitly sends `"best"` every time.

## Error matrix

| `error.kind` | Modal affordance | Trigger |
|---|---|---|
| `upload_too_large` | Error banner + Close | Bytes exceed 500 MB |
| `unsupported_type` | Error banner + Close | Extension or content-type fails allowlist |
| `slug_collision` | Transition back to collision step with fresh data | Server-side recheck found new collision |
| `ytdlp_metadata_failed` | Error banner + Close | Simulate call failed for non-stale reason |
| `ytdlp_stale` | Error banner + `Update yt-dlp & retry` | Stderr matches one of the stale-yt-dlp patterns |
| `ytdlp_download_failed` | Error banner + Close | Real download failed for non-stale reason |
| `ffmpeg_failed` | Error banner + Close | Transcode step failed |
| `analyze_failed` | Error banner + Close | `python -m analyze` exited non-zero |
| `lock_busy` | Error banner + Close | Another analysis already running |
| `internal` (or `null`) | Error banner + Close | Unhandled exception (logged with traceback server-side) |

## Files touched (inventory)

**New:**
- `webui/static/js/ui/analyze-modal.js` — input/collision/streaming/done/error states.
- `webui/webui/analyze_runner.py` — `_run_analyze_stream`, `download_youtube`, `transcode_to_mp3`, `slug_for_filename`, `find_first_free_slug` helpers, plus the `_analyze_lock`.

**Modified:**
- `webui/webui/server.py` — three new routes (`/api/util/slug-for`, `/api/tools/analyze/upload`, `/api/tools/analyze/youtube`); existing `/api/tools/reanalyze/{slug}` refactored to delegate to `_run_analyze_stream`; lock renamed.
- `webui/static/js/ui/track-picker.js` — header gets `+ File` and `+ YT` buttons; click handlers open the new modal.
- `webui/static/js/ui/reanalyze.js` — `DEFAULT_QUALITY = "best"`.
- `webui/static/css/track.css` — header flex update; new button styles.
- `webui/static/js/api.js` — wrappers for the new endpoints.

**Tests:**
- `webui/tests-js/analyze-modal.test.js` — modal state-machine transitions, NDJSON event handling.
- `webui/tests-e2e/analyze-upload.spec.js` — end-to-end upload of a tiny WAV fixture; collision flow surfaces the three-button step.
- `webui/tests-e2e/analyze-youtube.spec.js` — end-to-end YouTube of a known short public-domain video. Tagged `@network`, skipped in CI by default.

## Test plan (high-level)

- **Unit (JS):** modal state machine; phase-strip rendering; progress event formatting; slug-collision step button wiring; `streamAnalyze` NDJSON splitter (cover the boundary case where a JSON event is split across two `read()` chunks — the existing `streamReanalyze` already handles this; verify the rename preserves it).
- **Unit (Python):** `slug_for_filename` parity with `analyze.cache.slug_for`; `find_first_free_slug` against a synthetic cache directory; stale-yt-dlp stderr-pattern matcher (regression-test all five trigger phrases from CLAUDE.md); `transcode_to_mp3` happy path + ffmpeg-not-on-PATH error; lock contention surfaces `lock_busy`.
- **Integration (Python):** `/api/util/slug-for` for fresh / colliding / unsupported-extension cases; `/api/tools/analyze/upload` happy path with a 1-second WAV fixture (end-to-end including transcode + analyze; mocked WSL invocation that fakes a `summary.json`); `/api/tools/analyze/youtube` dry-run path with a mocked yt-dlp metadata stub; full youtube flow with mocked yt-dlp + WSL.
- **E2E (Playwright):** upload happy path; collision flow → `Add New <slug>-2`; collision flow → `Reanalyze`; YouTube happy path (network-tagged); reanalyze default-quality preselected to Best.

## Open questions / risks

- **ffmpeg quality call.** MP3 V0 is the recommended preset. If a future quality complaint arrives ("my FLAC analysis sounds different from analyzing the same source as WAV directly"), the answer is to graduate the pipeline to multi-format source-of-truth (the deferred non-goal). No mitigation needed at v1.
- **yt-dlp progress regex brittleness.** `--newline` makes the format stable, but a future yt-dlp version could change the line shape. Pattern is in one place (`download_youtube`) and is fail-soft: a non-matching line just becomes a plain log entry, the analyze still proceeds, just without a progress bar for that release. Worth a regression-test against a real yt-dlp output sample.
- **Multipart upload of a single 500 MB file.** FastAPI's default `UploadFile` spools to disk via `SpooledTemporaryFile` (1 MB threshold), so memory pressure stays bounded. Verify by uploading a 500 MB fixture in the integration test and watching RSS.
- **Collision pre-check race.** Browser tab A and tab B both pre-check the same slug, both see `exists:false`, both POST `mode="new"`. Tab A wins the lock; tab B's POST sees the lock held and gets `lock_busy` (modal shows close-only error step). If the user then retries from tab B after A has finished, the server-side recheck on POST entry catches the now-existing slug, returns `409 slug_collision`, and the modal transitions back to the collision step with fresh data. No silent overwrite is possible.
- **`Content-Length` enforcement.** A FastAPI middleware that rejects on `Content-Length > 500MB` doesn't catch chunked-encoding clients (no length declared). Modern browsers always send a length for `multipart/form-data`, so this is fine in practice — but if the request lacks a length, fall back to a streaming-write cap that closes the connection on overrun. Document this in the handler's docstring.

## Resolved decisions (for plan author)

- UI placement: header-row buttons on the same line as `LIBRARY · N TRACKS` (pattern A from brainstorming).
- Slug collision: three-button prompt: `Add New <slug>-2` / `Reanalyze` / `Cancel`.
- yt-dlp staleness: surface error + `Update yt-dlp & retry` button (no transparent auto-update). User stays in control.
- Post-analysis: footer offers `Open new track` (primary) + `Stay here` (secondary). No auto-navigate.
- Upload cap: 500 MB. Accepted types: `.mp3`, `.wav`, `.flac`.
- Endpoints: two specific endpoints, not a unified one.
- WAV/FLAC handling: server-side ffmpeg transcode to MP3 V0, pipeline + webui playback unchanged.
- Lock: single `_analyze_lock` shared by all three flows. No queueing.
- Default-quality flip: UI only (reanalyze + new modal). Server fallback and CLI default stay `"normal"`.
- yt-dlp output directory: `C:/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/` (CLAUDE.md canonical).
- Multipart parser: FastAPI `UploadFile` (whole-body buffered to spooled temp), not streaming parser.
