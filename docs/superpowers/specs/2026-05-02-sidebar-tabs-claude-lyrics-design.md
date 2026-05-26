# Sidebar tabs + Claude assistant + Karaoke lyrics — design

**Date:** 2026-05-02
**Status:** Drafting — pending user review.
**Scope:** v1 of a multi-tab sidebar in the webui. The existing sidebar contents become **Tab 1 (Track)**. **Tab 2 (Claude)** adds an in-app chat assistant powered by the Claude Agent SDK over OAuth/subscription auth, with a tool surface that can read pipeline artifacts and dispatch UI commands back to the browser. **Tab 3 (Lyrics)** adds a karaoke-style synced-lyrics view sourced from LRCLIB, falling back to plain lyrics or user paste.

## Context

The current webui (see [`docs/superpowers/specs/2026-04-30-webui-design.md`](2026-04-30-webui-design.md)) renders a fixed five-section sidebar (`Now playing` · `Stems` · `Loop` · `Function` · `Harmony stats`) as a unidirectional view of `summary.json`. It answers the question *what does the pipeline say about this track*. It doesn't help the user *interpret* what the pipeline says, *practice* with it, or *sing along* to it.

This spec adds three things, structured as three tabs sharing the existing right-side sidebar host (`#viewer-side` in `webui/static/js/main.js:135`):

1. The existing five sections are unchanged in content, relocated to **Tab 1 (Track)**.
2. **Tab 2 (Claude)** — a single-user chat assistant. The user asks Claude questions about the current track or library; Claude answers with text, optionally invoking tools that either read pipeline artifacts (server-side) or dispatch actions to the browser (seek, mute, set loop region, switch tab, highlight a chord/lyric line). Auth is OAuth via the user's Claude Pro/Max subscription — no API key is configured anywhere.
3. **Tab 3 (Lyrics)** — a full-transcript scrolling karaoke view. Lyrics come from LRCLIB (synced LRC if available, plain text otherwise), with a Claude-driven web fallback and a user-paste escape hatch. Click any line to seek; the active line is highlighted and auto-scrolls to the upper third of the panel during playback.

This is a single-user local app. There is no multi-tenancy, no rate-limiting, no API-key management. Authentication is whatever `~/.claude/` already holds — the same credentials this Claude Code session is running under.

## Coordination with parallel work

A separate work-stream — [`2026-05-02-analyze-from-library-design.md`](2026-05-02-analyze-from-library-design.md) — adds two new ingest entry points (file upload + YouTube URL) under the existing topbar's track-picker. That work is **orthogonal** to this spec:

| Surface | Their changes | Our changes | Conflict? |
|---|---|---|---|
| `webui/webui/server.py` | New `POST /api/tools/analyze-file`, `/api/tools/analyze-youtube`, `/api/tools/check-yt-update` | New `POST /api/chat/<slug>/turn`, `GET/POST/DELETE /api/tracks/<slug>/lyrics*` | None — additive routes, distinct prefixes |
| `webui/static/css/track.css` | Tab-strip pill styles for `+ File` / `+ YT` buttons in the picker header | Tab-strip styles for the sidebar's three tabs; karaoke-line styles | None — additive blocks, distinct selectors |
| Sidebar (`#viewer-side`) | Untouched | Refactored into a tabbed shell | None |
| Topbar / track-picker | Header buttons, analyze modal | Untouched | None |

Implementation phase will start from a worktree branched off `main` *after* the analyze-from-library work has merged (or from a worktree explicitly rebased on top of it). The shared `server.py` will not have textual conflicts because both work-streams add to disjoint regions of the file, but we rebase rather than merge to keep history linear.

## Locked decisions (from brainstorm)

| Question | Choice | Implication |
|---|---|---|
| Roles in scope | **All five: Tutor, Guide, Operator, Lyricist, Librarian.** | The tool surface must include both server-only data-lookup tools and UI-action dispatch tools. |
| Auth model | **OAuth via Claude Code CLI subscription** (Pro/Max), inherited from `~/.claude/`. | No `ANTHROPIC_API_KEY` env var. No in-app key configuration. If `~/.claude/` is logged out, Claude tab shows a `Run claude /login` banner; rest of UI works. |
| Claude SDK | **`claude-agent-sdk` (Python)** — the official SDK that bundles the Claude Code CLI and reuses its credentials. | Adds `claude-agent-sdk>=0.x` to `webui/requirements.txt`. Requires Python 3.10+ (already satisfied — webui uses 3.11+ via `uv`). |
| Conversation API style | **Stateless `query()` per turn**, history persisted server-side as a JSON file and replayed each turn. | No long-lived `ClaudeSDKClient` to lifecycle. Each HTTP request to `/api/chat/<slug>/turn` is self-contained. The SDK handles prompt-caching on the cached prefix transparently. |
| Tools-eager vs. tools-as-needed | **Tools-as-needed.** | System prompt instructs Claude to answer with text by default, reaching for tools only when the user explicitly asks for an action or when an action is the cleanest answer. |
| UI-action permission | **Auto-approved.** All tools are listed in `allowed_tools=[...]`. No per-action confirmation popup. | The "Stop" button in the Claude tab header is the global escape hatch; it aborts the in-flight stream and any UI actions queued behind already-emitted ones still apply (browser doesn't unsend a `seek_to`). |
| What Claude sees per turn | System prompt (cached) · current track's `summary.json` (cached, mtime-fingerprinted) · loaded lyrics, when present (cached) · conversation history (replayed verbatim including any prior tool-use / tool-result blocks) · per-turn view-state snapshot prepended as a `<view_state>{json}</view_state>` block to the new user message. | A turn-1 cold call sends ~5–100 KB; turn-2+ sends ~1–3 KB of dynamic content on top of the cached prefix. The view-state snapshot is the only per-turn invalidation point; it sits *after* the cached prefix, so cache hits are preserved. |
| Lyrics source cascade | **LRCLIB synced → LRCLIB plain → Claude `WebFetch`/`WebSearch` → user paste.** | Synced gives karaoke timing; everything else degrades to plain-text scroll (no per-line highlight). |
| Lyrics fetch trigger | **Lazy on first Tab-3 open**, cached per-track. Manual refresh available. | One LRCLIB request per (track, ever) on the happy path. No fetch on track load. |
| Track identification for LRCLIB | **ID3 tags via `mutagen`**, with filename-parse fallback and an editable "Artist · Title" header in the lyrics tab. | Adds `mutagen` to `webui/requirements.txt`. Editing the header and clicking "Refresh" re-queries LRCLIB. |
| Karaoke layout | **Full-transcript scroll** with per-line auto-scroll to the upper third, current-line highlight (color + left rule), click-to-seek on any line. | One layout, no toggles for v1. (Three-line focus and stage-prompter modes are out of scope.) |
| Conversation persistence | **Per-track**, persisted to `cache/<slug>/chat.json`. Browser reload restores the conversation. "Clear chat" button always available. | `cache/<slug>/chat.json` and `cache/<slug>/lyrics/` are excluded from `_clear_cache_dir()` (the reanalyze nuke) so a re-analysis does not destroy the user's notes. |
| Aligner-from-audio for unsynced lyrics | **Out of scope.** | Future spec. Unsynced lyrics render as plain text without karaoke timing. |
| Word-level karaoke ball (LRC enhanced) | **Out of scope.** | LRCLIB rarely has enhanced LRC; not worth the optional-format branching for v1. |

## Architecture

### Package additions

```
webui/
├── requirements.txt          # + claude-agent-sdk, + mutagen, + httpx is already present
├── requirements.lock         # regenerated
└── webui/
    ├── chat.py               # NEW — Claude SDK integration, in-process MCP tools, streaming
    ├── lyrics.py             # NEW — LRCLIB client, ID3 reader, parse/serialize LRC, cache I/O
    └── server.py             # MOD — adds /api/chat/* and /api/tracks/<slug>/lyrics* routes

webui/static/
├── css/track.css             # MOD — tab-strip styles, claude-tab styles, lyrics-tab styles
├── index.html                # unchanged
└── js/
    ├── main.js               # MOD — mounts a TabbedSidebar in #viewer-side instead of Sidebar
    └── ui/
        ├── tabs.js           # NEW — TabBar component, panel-swapping, last-tab persistence
        ├── tabbed-sidebar.js # NEW — orchestrates the three tabs and their lifecycle
        ├── sidebar.js        # MOD — class becomes the Tab 1 panel (no API change)
        ├── claude-tab.js     # NEW — chat panel, NDJSON stream reader, message rendering, tool indicators
        └── lyrics-tab.js     # NEW — karaoke panel, LRC parsing/rendering, click-to-seek, refresh menu
```

### Frontend — tab shell

`webui/static/js/ui/tabs.js` exports a small `TabBar` class with this contract:

```js
class TabBar {
  constructor(host, tabs)        // tabs = [{ id, label, render: (panelEl) => void, onActivate?, onDeactivate? }]
  activate(id)                    // switches active tab; calls onDeactivate then onActivate
  current()                       // returns current tab id
}
```

Tab style: a single horizontal strip pinned to the top of `#viewer-side`. Each tab is a button with the existing `.side-section h4` typography (9px uppercase, `--ls-caps` letter-spacing, `--fg-2` color), with a 2px bottom border in the stem-style accent color when active. No new design vocabulary — reuses the existing aesthetic from `track.css:155`.

`webui/static/js/ui/tabbed-sidebar.js` is the orchestrator: it constructs the `TabBar`, owns the three panels' lifecycle, and exposes the same external surface that `Sidebar` exposes today (`mount(trackData, viewState, engine)`, `setCurrentTime(t)`, `setStemStatus(name, status, detail)`). `main.js` swaps `Sidebar` → `TabbedSidebar` at the mount site (`main.js:157`); the `setCurrentTime`, `stemLoaded`, `stemFailed`, `stemsReady` wiring stays unchanged. Internally, `TabbedSidebar` delegates `setCurrentTime` to all three panels (Tab 1 for the now-playing card, Tab 3 for the active-line highlight). Tab 2 ignores it.

Active-tab persistence: localStorage key `musiq:activeTab`, restored on `mount()`. Default is `track`.

### Frontend — Tab 1 (Track)

The existing `Sidebar` class moves verbatim into a Tab 1 panel renderer. No content changes. Implementation note: `Sidebar.mount()` already accepts a host element and an idempotent `clear(host)`; we just hand it the Tab 1 panel container instead of `#viewer-side`. The class name and module path are unchanged so the diff is small.

### Frontend — Tab 2 (Claude)

A vertical column inside the Tab 2 panel:

```
┌─ Tab strip ───────────────────────┐
│  Track   Claude*   Lyrics         │
├───────────────────────────────────┤
│  [ Clear chat ]   [ Stop ]        │  ← header
├───────────────────────────────────┤
│                                   │
│  user:  what's the chord at 1:23? │
│  Claude: That's a Bb major,       │
│           which functions as ♭VII │
│           — modal interchange.    │
│                                   │
│  [tool: highlight_stem(piano)] ✓  │
│                                   │
│  user:  show me where the loop    │
│         starts                    │
│  Claude: …                        │  ← scroll container, auto-scrolls to bottom
│                                   │
├───────────────────────────────────┤
│  ┌─ textarea ──────────┐ [Send]   │  ← composer
│  │ Ask about this song │          │
│  └─────────────────────┘          │
└───────────────────────────────────┘
```

Three regions:

- **Header** — `Clear chat` button (calls `DELETE /api/chat/<slug>`), `Stop` button (only enabled when a stream is in flight; calls `AbortController.abort()` on the open fetch). Token-budget readout in the corner: `cache 4231 · in 142 · out 88` after the previous turn (driven by `ResultMessage` from the SDK).
- **Transcript** — a scrollable column. Each user message is a left-aligned plain block; each assistant message is a card with optional inline tool-use indicators rendered as small chips between or inside text blocks. Tool-use chips look like `[tool: seek_to(83.5)] ✓` (success) or `[tool: fetch_lyrics(…)] ✗ no LRC found` (error). Streaming text appends incrementally to the current assistant message bubble.
- **Composer** — a `<textarea>` with auto-grow up to ~6 lines, `Cmd/Ctrl+Enter` to send, `Send` button on the right. Disabled while a stream is in flight. Pressing `Stop` returns the textarea to the enabled state and preserves what was typed.

Auth-error state: if the first chat turn fails with `auth_required`, the entire transcript area is replaced by a single card:

> **Claude is signed out.**
> Run `claude /login` in a terminal, then click Retry.
> [Retry]

Other tabs continue to work.

### Frontend — Tab 3 (Lyrics)

Three layout layers stacked top-to-bottom:

```
┌───────────────────────────────────┐
│  Artist · Title          [⟳ Refresh ▾]  │  ← editable header + refresh menu
├───────────────────────────────────┤
│                                   │
│  ┌─ scroll container ──────────┐  │
│  │ Verse 1                     │  │
│  │ She walked through the rain │  │
│  │ → The neon lights bled into │  │  ← active line: bright + 2px left rule
│  │ And nothing in her world    │  │
│  │ A whisper carried by …      │  │
│  │ …                           │  │
│  └─────────────────────────────┘  │
│                                   │
└───────────────────────────────────┘
```

- **Header** — two contenteditable spans for artist and title separated by `·`. Right-aligned actions: a refresh dropdown with three menu items: `Refetch from LRCLIB`, `Ask Claude to find lyrics`, `Paste lyrics manually` (opens an inline `<textarea>` overlay; submit replaces current lyrics).
- **Scroll container** — full transcript, all lines rendered. Active line is determined by binary search over `lines[i].time_sec` against the current playhead. On active-line change, the panel auto-scrolls so the active line lands ~33% from the top of the visible area (smooth-scroll, 200 ms). User scrolls suspend auto-scroll for 4 seconds (same idiom as the canvas auto-scroll badge).
- **Click-to-seek** — clicking a line calls `engine.seek(line.time_sec)`. Lines without timing data (plain-text mode) are not click-to-seek; the cursor and underline cue both signal that.

Empty state (no lyrics yet, first open of the tab triggers fetch): shows a centered spinner with the text `Looking up lyrics on LRCLIB…` for up to 4 s, then either renders the lyrics or shows the no-result state:

> **No synced lyrics found for this track.**
> [Try LRCLIB plain]   [Ask Claude to find them]   [Paste lyrics]

Sectional markers like `Verse 1`, `Chorus`, `Bridge` (when LRCLIB ships them) are rendered as smaller, dimmer headings inline in the scroll, not as click targets.

### Backend — `webui/webui/chat.py`

Owns:
- The Claude system prompt template.
- The in-process MCP tool definitions.
- The per-turn message-assembly logic (system + cached `summary.json` + view-state snapshot + history + new user message).
- The NDJSON event-emission loop that wraps `claude_agent_sdk.query(...)`.
- Conversation file I/O (`cache/<slug>/chat.json`) — load, append, persist atomically.

Sketch:

```python
# webui/webui/chat.py
from pathlib import Path
import json
from typing import AsyncIterator, Any
from claude_agent_sdk import query, ClaudeAgentOptions, create_sdk_mcp_server, tool
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, ToolResultBlock
from . import _paths, tracks, lyrics

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

Track summary follows. Each user message is prefixed with a `<view_state>...</view_state>` block describing the playhead, current chord, mute/solo state, and active tab at message time — read it but do not mention it unless the user asks about the current moment.
"""

@tool("seek_to", "Move the playhead to a time in seconds.", {"time_sec": float})
async def seek_to(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"Queued seek to {args['time_sec']:.2f}s"}],
        "_ui_action": {"action": "seek_to", "args": {"time_sec": args["time_sec"]}},
    }
# … (all UI-action tools follow the same pattern: return text confirmation + a "_ui_action" key)

@tool("list_tracks", "List all analyzed tracks in the library.", {})
async def list_tracks_tool(args: dict[str, Any]) -> dict[str, Any]:
    items = [{"slug": t.slug, "title": t.title} for t in tracks.list_tracks()]
    return {"content": [{"type": "text", "text": json.dumps(items)}]}

# create_sdk_mcp_server(...) wires these into a single server passed in via ClaudeAgentOptions.
```

The `_ui_action` convention: a tool's return dict carries a private `_ui_action` key that the streaming wrapper extracts and emits as a separate `{"type": "ui_action", ...}` NDJSON event to the browser. The CLI/SDK doesn't see `_ui_action` — only `content` is sent back to Claude. (The SDK passes `content` through; extra keys are returned to our caller code via the tool-result block but don't appear in Claude's transcript context.)

### Backend — `webui/webui/lyrics.py`

Owns:
- ID3 / Vorbis / APE tag reading via `mutagen` against the source MP3 (resolved through `summary.json`'s `windows_path`).
- LRCLIB client (HTTPX over `https://lrclib.net/api/get` first, falling back to `/api/search`).
- LRC parsing into `{lines: [{time_sec: float, text: str}], plain_text: str, has_sync: bool, sections: [{label, time_sec}]}`.
- Cache I/O under `cache/<slug>/lyrics/{synced.lrc, plain.txt, meta.json}`.
- A "save user paste" path: if the pasted text is detected as LRC (any `[mm:ss.xx]` line), it's stored as `synced.lrc`; otherwise as `plain.txt`.

Identification flow:
1. Read tags from `summary.track.windows_path` via `mutagen.File(path, easy=True)`. Pull `artist`, `title`, `album`.
2. If any of `artist` or `title` is missing, parse the file basename as a fallback. Heuristic: split on ` - `, then on `_`, then take the slug as title-fallback.
3. Return `{artist, title, album, duration_sec}`. The lyrics tab's editable header sends back overrides on refresh; those flow as request params and replace the auto-detected values for that fetch.

LRCLIB etiquette: User-Agent header `MusIQ-Lab/0.1 (local single-user music analysis app)`. One request per refresh. No retry-on-404.

### Backend — `webui/webui/server.py` route additions

```python
# Chat routes ----------------------------------------------------------------
@app.post("/api/chat/{slug}/turn")
async def chat_turn(slug: str, request: Request) -> StreamingResponse: ...
@app.delete("/api/chat/{slug}")
def chat_clear(slug: str) -> dict: ...
@app.get("/api/chat/{slug}")
def chat_history(slug: str) -> dict: ...   # returns { messages: [...] } for restore-on-reload

# Lyrics routes --------------------------------------------------------------
@app.get("/api/tracks/{slug}/lyrics")
def lyrics_get(slug: str) -> dict: ...        # 404 if none cached
@app.post("/api/tracks/{slug}/lyrics/fetch")
async def lyrics_fetch(slug: str, request: Request) -> dict: ...
@app.post("/api/tracks/{slug}/lyrics/paste")
async def lyrics_paste(slug: str, request: Request) -> dict: ...
@app.delete("/api/tracks/{slug}/lyrics")
def lyrics_clear(slug: str) -> dict: ...
```

Single-flight: the chat-turn endpoint takes the same per-process lock pattern as `_reanalyze_lock` — one chat turn at a time. Concurrent requests from the same browser get a 409. (Two browser tabs open to the same slug shouldn't happen in practice; if it does, the second's send gets the conflict and surfaces as a toast.)

## Data flows

### Chat turn

```
Browser                                 Server                               Claude SDK / CLI
   │                                        │                                       │
   │  POST /api/chat/<slug>/turn            │                                       │
   │  { user_message, view_state }          │                                       │
   │───────────────────────────────────────▶│                                       │
   │                                        │  load chat.json                       │
   │                                        │  load summary.json (mtime cached)     │
   │                                        │  build messages = [system, history,   │
   │                                        │                    new user]          │
   │                                        │  query(prompt=…, options=…)           │
   │                                        │──────────────────────────────────────▶│
   │                                        │                                       │  [text deltas]
   │                                        │ {"type":"text","delta":"That's"}      │
   │◀───────────────────────────────────────│◀──────────────────────────────────────│
   │  append to current bubble              │                                       │
   │                                        │                                       │  [tool_use]
   │                                        │  intercept ToolUseBlock,              │
   │                                        │  await tool, capture _ui_action       │
   │ {"type":"tool_use","name":"seek_to"}   │                                       │
   │ {"type":"ui_action","action":"seek…"}  │                                       │
   │◀───────────────────────────────────────│                                       │
   │  dispatch to engine                    │                                       │
   │                                        │                                       │  [more text]
   │ {"type":"text","delta":"…"}            │                                       │
   │◀───────────────────────────────────────│◀──────────────────────────────────────│
   │                                        │                                       │  [done — ResultMessage]
   │                                        │  append assistant msg to chat.json    │
   │                                        │  atomic-write                         │
   │ {"type":"done","tokens":{…}}           │                                       │
   │◀───────────────────────────────────────│                                       │
```

### Lyrics fetch (lazy on first tab-3 open)

```
Browser                          Server                          LRCLIB
   │                                │                              │
   │  user clicks Lyrics tab        │                              │
   │  GET /api/tracks/<slug>/lyrics │                              │
   │───────────────────────────────▶│                              │
   │ 404 (not yet cached)           │                              │
   │◀───────────────────────────────│                              │
   │                                │                              │
   │ POST .../lyrics/fetch          │                              │
   │ {} (no overrides)              │                              │
   │───────────────────────────────▶│                              │
   │                                │  read ID3 from summary path  │
   │                                │  GET /api/get?artist=…       │
   │                                │─────────────────────────────▶│
   │                                │ 200 { syncedLyrics, … }      │
   │                                │◀─────────────────────────────│
   │                                │  write cache/.../lyrics/{…}  │
   │ 200 { synced: true, lines: [], header: { artist, title } }    │
   │◀───────────────────────────────│                              │
   │  render karaoke view           │                              │
```

If LRCLIB returns no synced track but plain lyrics exist: same shape but `synced: false`, `plain_text: "..."`. If LRCLIB 404s entirely: response is `{ synced: false, plain_text: null, error: "not_found" }` and the empty-state UI takes over.

### Tool-use → UI action

For every `ToolUseBlock` Claude emits, the wrapper:

1. Resolves the tool function (in-process MCP).
2. `await`s it.
3. Emits a `{"type": "tool_use", "id": <block.id>, "name": <block.name>, "input": <block.input>}` event.
4. If the tool's return dict has `_ui_action`, emits a `{"type": "ui_action", "id": <block.id>, "action": <name>, "args": <args>}` event right after.
5. Feeds the `content` portion back to Claude as a tool-result so the conversation continues.

Browser-side dispatcher in `claude-tab.js`:

```js
function dispatchUiAction({ action, args }) {
  switch (action) {
    case "seek_to":         return engine.seek(args.time_sec);
    case "set_loop_region": return viewState.setLoop(args.start_sec, args.end_sec);
    case "set_stem_state":  return applyStemState(args);
    case "highlight_stem":  return (viewState.highlightedStem = args.stem);
    case "open_midi":       return api.openMidi(currentSlug, args.stem);
    case "switch_tab":      return tabbedSidebar.activate(args.tab);
    case "highlight_lyric_line": return lyricsTab.highlightLineByIndex(args.index);
  }
}
```

## Tool surface

Final list. Each entry: tool name · params · effect · which role.

### Server-only (data lookup; no UI side effect)

| Tool | Params | Effect | Role |
|---|---|---|---|
| `list_tracks` | none | Returns `[{slug, title, duration_sec, key, tempo_bpm}]` for every entry under `cache/`. | Librarian |
| `get_summary` | `slug: str` | Returns the full `summary.json` for a *different* track than the current one. | Librarian |
| `find_chord_occurrences` | `query: str` (e.g. `"V"`, `"Bb"`, `"♭VII"`) | Scans `chords[]` in the current summary, returns `[{start, end, label, roman}]` matching the query. | Tutor |

### UI-action (queued via `_ui_action`)

| Tool | Params | Browser effect | Role |
|---|---|---|---|
| `seek_to` | `time_sec: float` | `engine.seek(time_sec)` | Operator |
| `set_loop_region` | `start_sec: float, end_sec: float` | `viewState.setLoop(...)` (new method on view-state — see *View-state additions* below) | Operator |
| `set_stem_state` | `stem: str, mute?: bool, solo?: bool, volume?: float` | Calls `engine.setStemMute/Solo/Volume`; updates sidebar UI via the existing `change` event | Operator |
| `highlight_stem` | `stem: str` | Sets `viewState.highlightedStem` | Operator |
| `open_midi` | `stem: str` | Calls existing `POST /api/tools/open-midi/<slug>/<stem>` | Operator |
| `switch_tab` | `tab: str` (one of `"track"`, `"claude"`, `"lyrics"`; rejected otherwise) | `tabbedSidebar.activate(tab)` | Operator |
| `highlight_lyric_line` | `index: int` | Tab 3 highlights line `index` and scrolls it into focus, even if not currently active | Lyricist |

### Lyrics

| Tool | Params | Effect | Role |
|---|---|---|---|
| `fetch_lyrics` | `artist?: str, title?: str` | Calls `lyrics.fetch(slug, artist, title)`. If currently cached, returns existing. If `synced: true`, also emits a `ui_action` to populate Tab 3. | Lyricist |

Built-in SDK tools enabled via `allowed_tools`: `WebFetch`, `WebSearch` (for the lyrics-cascade step 3). All others are disabled in the v1 system prompt to keep Claude focused on music.

## NDJSON streaming protocol

Stream emitted from `POST /api/chat/<slug>/turn`. One JSON object per line, `Content-Type: application/x-ndjson`.

| Event | Schema | Browser handling |
|---|---|---|
| `text` | `{"type": "text", "delta": str}` | Append to current assistant bubble. |
| `tool_use` | `{"type": "tool_use", "id": str, "name": str, "input": object}` | Render a tool-chip placeholder; mark spinner. |
| `tool_result` | `{"type": "tool_result", "id": str, "ok": bool, "summary": str}` | Update tool-chip to ✓ or ✗. |
| `ui_action` | `{"type": "ui_action", "id": str, "action": str, "args": object}` | Dispatch immediately. |
| `done` | `{"type": "done", "tokens": {"input": int, "output": int, "cache_read": int}, "session_id": str}` | Re-enable composer, refresh token-budget readout. |
| `error` | `{"type": "error", "message": str, "kind": str}` | Surface in chat as an error bubble; re-enable composer. |
| `auth_required` | `{"type": "auth_required"}` | Replace transcript with the signed-out card. |

Stop-button behavior: browser calls `AbortController.abort()` on the fetch. Server detects the disconnect via `await request.is_disconnected()` polling inside the stream loop, cancels the SDK's async iterator, persists whatever partial assistant message was assembled (with a `[interrupted]` suffix), and exits the generator cleanly.

## View-state additions

The existing `view-state.js` doesn't model loop regions. We add:

```js
// view-state.js (additions)
this.loopStart = null;   // seconds | null
this.loopEnd   = null;   // seconds | null
setLoop(start, end) { this.loopStart = start; this.loopEnd = end; this._emit("change"); }
clearLoop()        { this.loopStart = null; this.loopEnd = null; this._emit("change"); }
```

The audio engine's `play()` loop respects the region: if `loopEnd != null && currentTime >= loopEnd`, seek to `loopStart`. Minimap and piano-roll render a translucent band over `[loopStart, loopEnd]` (existing canvas overlay infrastructure, ~30 lines added in `pianoroll.js` and `minimap.js`). Transport gets a small `Loop: 1:23–2:14 ✕` chip when active.

## Cache layout updates

```
cache/<slug>/
├── <slug>.summary.json        existing
├── <slug>.jams                existing
├── <slug>.mp3                 existing
├── stems_6s/                  existing
├── stems_bsroformer/          existing
├── midi/                      existing
├── vocal_f0.npz               existing
│
├── chat.json                  NEW — { schema_version, messages: [{role, blocks: [{type, ...}], ts}], last_session_id?, model? }
└── lyrics/                    NEW
    ├── synced.lrc             NEW — raw LRC if available
    ├── plain.txt              NEW — plain lyrics (LRCLIB plain, web fallback, or paste)
    └── meta.json              NEW — { source, fetched_at, lrclib_id?, artist, title, album, duration_sec }
```

Changes to `_clear_cache_dir()` in `server.py:213`:

```python
def _clear_cache_dir(cache: Path) -> None:
    PRESERVE = {"chat.json", "lyrics"}     # preserved across reanalysis
    for child in cache.iterdir():
        if child.name in PRESERVE:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
```

A reanalysis of a track preserves user notes (chat) and lyrics. The `summary.json` mtime change still invalidates Claude's cached prefix on the next turn (the next `query()` call sees fresh content), so post-reanalysis chats reflect the new analysis correctly.

## Error handling and degraded modes

| Failure | UX |
|---|---|
| Claude CLI logged out / no `~/.claude/` credentials | First turn returns `auth_required`. Tab 2 shows the signed-out card. Tabs 1 + 3 unaffected. |
| Network down / LRCLIB unreachable | Lyrics fetch returns `{error: "network", message: "..."}`. Empty-state shows "LRCLIB unreachable — check connection or paste lyrics." |
| LRCLIB has plain but not synced | Lyrics tab renders plain-text scroll; click-to-seek disabled; "No timing data" banner with "Try Claude web search" affordance. |
| Source MP3 missing for ID3 read | Editable artist/title header starts empty, populated by filename fallback; user can manually fill and refresh. |
| `chat.json` corrupt JSON on disk | Treated as empty; new turn appends to a fresh history; corrupt file moved to `chat.json.bak.<ts>` once per occurrence. |
| Tool emits exception | Tool-chip shows ✗ with the exception message (truncated to 200 chars); Claude receives the error as a tool-result and can retry or apologize. |
| Stream interrupted mid-turn (browser close, Stop) | Server persists partial assistant message with `[interrupted]` suffix, releases the chat lock. |
| Conversation history exceeds context | Server-side, oldest non-system messages are dropped until total prompt fits. A warning banner appears in the next assistant bubble: "Earlier turns were dropped." (Heuristic threshold: ~150K input tokens.) |
| Concurrent chat turn from second browser tab | 409 with `{ "error": "chat_busy" }`. Browser shows a toast: "Another chat turn is in progress." |

## Security and privacy notes

This is a 127.0.0.1-only single-user app. Nonetheless:

- The Claude SDK has access to the user's full Claude Code subscription. Scope is implicitly bounded by the system prompt and the `allowed_tools` list. Built-in tools that could be dangerous (`Bash`, `Read`, `Write`, `Edit`) are **not** included in `allowed_tools` and are explicitly listed in `disallowed_tools` to be safe.
- LRCLIB receives `(artist, title, duration)` for every fetched track. Acceptable.
- `WebFetch` / `WebSearch`, when invoked by Claude as a fallback for lyrics, reaches the public web. Acceptable for a personal lyrics-lookup feature; out of scope for restriction.
- `chat.json` may contain personal notes / questions. Lives only on disk in `cache/<slug>/`. Not exposed by any route except the chat history endpoint.

## Testing strategy

Three layers, mirroring the existing webui test layout (`webui/tests/`):

- **`test_lyrics.py`** — unit tests for the LRC parser (well-formed LRC, empty bracket lines, sectional markers, malformed entries discarded), the ID3 reader against fixture MP3s (tagged, untagged, only-filename), the LRCLIB client with HTTPX-mock (200 synced, 200 plain, 404, network error). Snapshot tests for the parsed-line JSON shape.
- **`test_chat.py`** — unit tests for the message-assembly pipeline (system prompt rendering, `summary.json` injection, view-state shaping, history truncation at the size threshold), the `_ui_action` extraction wrapper, the NDJSON event serializer. Mock `claude_agent_sdk.query` to yield a scripted sequence of `AssistantMessage` / `ToolUseBlock` / `ResultMessage` instances.
- **`test_server.py`** — extends the existing FastAPI TestClient suite. New cases: `POST /api/chat/<slug>/turn` happy path with mocked SDK; concurrent-turn 409; `auth_required` propagation; lyrics fetch lifecycle (fetch → cached → clear → fetch again); `_clear_cache_dir` preserves chat + lyrics directories.

Frontend testing: manual via the existing `tests/screenshots/` workflow. Add a `tests/screenshots/sidebar-tabs/` subdirectory for the three-tab visual regression set (track tab unchanged, claude tab empty + populated + auth-error, lyrics tab loading + synced + plain + empty).

End-to-end: a manual smoke checklist in `webui/README.md` for the chat happy path: (1) open a track, (2) click Claude, (3) ask "what's the chord at the playhead?", expect text answer; (4) ask "loop the chorus", expect a `set_loop_region` UI action and the minimap band appears; (5) reload the page, expect the conversation restored.

## Out of scope (deferred)

- **Aligner-from-audio** — fitting unsynced lyrics to vocal F0 voicing windows. Future spec.
- **Word-level karaoke ball** — requires LRC enhanced format which is rare in LRCLIB. Re-evaluate if a music-video sync feature ever lands.
- **Three-line focus** and **stage prompter** karaoke modes — picked layout B only for v1.
- **Custom system prompt** — power-user setting to override the canned tutor prompt. Defer.
- **Cost-tracking UI** — OAuth subscription bills are flat-rate; per-token cost readouts would be misleading. Token counts are surfaced; dollars are not.
- **Voice input / Claude TTS reply** — no.
- **Chat-message export** — Claude's chat per track is a private cache file; no in-app "export" button. User can read `cache/<slug>/chat.json` directly.
- **Library-wide search UI** — Librarian is in scope as a Claude *capability* (the `list_tracks`/`get_summary` tools), not as a dedicated "Search Library" tab.
- **Multi-user / shared sessions** — single-user app.

## Risks and open questions

1. **SDK version pinning.** `claude-agent-sdk` is recent; minor releases may shift the streaming-event types we rely on (`AssistantMessage`, `ToolUseBlock`, `ResultMessage` shapes). Mitigation: pin a known-good version in `requirements.txt` (no `>=` only); regenerate `requirements.lock`. Smoke test on every bump.
2. **Prompt-cache effectiveness.** The SDK transparently inserts cache breakpoints, but our message-assembly order matters: the cached prefix (system prompt + `summary.json`) must come *before* the dynamic per-turn snapshot. We control the order. Verify in dev that turn-2 sees a meaningful `cache_read_tokens` count.
3. **`mutagen` cross-format coverage.** ID3v2.3 / v2.4 / APE / Vorbis are all standard. Edge case: WAV files with no INFO chunk → `mutagen.File()` returns None. Filename fallback covers it.
4. **LRCLIB availability.** Single point of failure for primary lyrics. Mitigated by Claude web fallback and user paste, but if LRCLIB is down, first-time fetches degrade.
5. **Browser fetch streaming on Windows.** The webui already uses `application/x-ndjson` from the reanalyze endpoint and it works in current Chrome/Edge/Firefox. No new streaming surface.
6. **Tool result back-pressure.** If Claude calls many UI tools in a row (e.g. "mute everything except piano" → six `set_stem_state` calls), the browser must apply them in order. The NDJSON stream is naturally ordered; the dispatcher is synchronous per-event. No buffering needed.
7. **Reanalyze + lyrics interaction.** A reanalysis preserves `cache/<slug>/lyrics/`. If the reanalysis changes the `duration_sec`, cached LRCLIB-id-based identification may now point at a slightly-mismatched track. Acceptable for v1; user can manually refresh.

## File-by-file change inventory (planning aid)

This is a planning-time map, not the implementation order. The implementation plan (next phase, via `superpowers:writing-plans`) will sequence and chunk these.

| File | Change | Rough size |
|---|---|---|
| `webui/requirements.txt` | + `claude-agent-sdk`, + `mutagen` | 2 lines |
| `webui/requirements.lock` | regenerated | (auto) |
| `webui/webui/chat.py` | NEW | ~250 lines |
| `webui/webui/lyrics.py` | NEW | ~200 lines |
| `webui/webui/server.py` | + 7 routes, + `_clear_cache_dir` change | ~120 lines added |
| `webui/static/index.html` | unchanged | — |
| `webui/static/css/track.css` | + tab strip styles, + chat styles, + lyrics styles | ~200 lines added |
| `webui/static/js/main.js` | swap `Sidebar` → `TabbedSidebar` mount | ~5 lines changed |
| `webui/static/js/ui/tabs.js` | NEW | ~80 lines |
| `webui/static/js/ui/tabbed-sidebar.js` | NEW | ~120 lines |
| `webui/static/js/ui/sidebar.js` | unchanged (relocated as Tab 1's panel renderer) | — |
| `webui/static/js/ui/claude-tab.js` | NEW | ~350 lines |
| `webui/static/js/ui/lyrics-tab.js` | NEW | ~280 lines |
| `webui/static/js/api.js` | + chat + lyrics fetch wrappers | ~40 lines |
| `webui/static/js/view/view-state.js` | + loop region | ~20 lines |
| `webui/static/js/render/pianoroll.js` | + loop-band overlay | ~30 lines |
| `webui/static/js/ui/minimap.js` | + loop-band overlay | ~25 lines |
| `webui/static/js/ui/transport.js` | + loop-active chip | ~20 lines |
| `webui/static/js/audio/web-audio-engine.js` | + loop-region honoring in playback loop | ~15 lines |
| `webui/tests/test_chat.py` | NEW | ~250 lines |
| `webui/tests/test_lyrics.py` | NEW | ~200 lines |
| `webui/tests/test_server.py` | + chat + lyrics route cases | ~150 lines added |

Approximate total: ~2,400 net new lines, ~150 changed.
