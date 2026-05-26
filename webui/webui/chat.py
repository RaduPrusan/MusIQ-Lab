"""Claude assistant: system prompt, message assembly, tools, SDK options, persistence.

The actual SDK call lives in `chat_actor.ChatActor`, which keeps a
`ClaudeSDKClient` open across turns for true bidirectional streaming and
in-memory context. This module is the side-effect-free building blocks
(prompt rendering, tool definitions, message translation, history file I/O).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ._security import is_safe_slug, is_safe_stem


def _reject_slug(slug: Any) -> dict[str, Any]:
    """Return an MCP-shaped error response for a model-supplied bad slug.

    The chat tools take `current_slug` from the model, so the model itself
    (under prompt injection) could try to escape the cache via `..` or
    similar. We refuse and return an is_error result; the model sees the
    rejection and typically self-corrects.
    """
    return {
        "content": [{"type": "text", "text": f"invalid slug: {slug!r}"}],
        "is_error": True,
    }


def _reject_stem(stem: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"invalid stem: {stem!r}"}],
        "is_error": True,
    }


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
- Researcher: look up things outside the local analysis — artist biographies, album context, song
  meanings, music-theory references, similar tracks across the web — using WebSearch and WebFetch.
  Reach for these freely when the answer isn't in the track summary or the user's library. Examples:
  "who produced this album?", "what does this lyric reference?", "explain this scale name", "find
  a chord chart for this progression". Cite sources when you fetch a page.

Default to text answers. Reach for tools when they're the cleanest path: an action ("show me the
modulation" → seek + highlight), specific local data ("what bass note is on beat 3 of bar 12" →
get_notes_at), or outside knowledge ("what's the story behind this song" → WebSearch). Do not
narrate every tool you intend to use; just use it. Prefer get_chord_at / get_notes_at /
get_current_view over get_summary — they return only what you need.

Each user message is prefixed with a <view_state>...</view_state> block carrying the playhead,
the chord currently under it, the current bar/beat, mute/solo state, active tab, and (when synced
lyrics exist) the current lyric line. Read it but do not mention it unless the user asks about the
current moment. When the user says "this chord", "right here", "this line" — that block is your
referent.

Track summary follows.

<track_summary>
{summary_json}
</track_summary>
"""


def build_system_prompt(summary: dict) -> str:
    """Render the system prompt with a compact projection of the summary embedded.

    The full summary can be hundreds of KB (every stem's notes array, every drum
    hit timestamp). Embedding it inline blows past Windows' 32 KB CreateProcess
    command-line limit (WinError 206) when the SDK passes --system-prompt as an
    argv entry. Stems' note lists and drum timestamps are reduced to counts;
    callers can use the find_chord_occurrences / similar tools when detail is
    needed.
    """
    compact = _compact_summary(summary)
    return SYSTEM_PROMPT_TEMPLATE.format(summary_json=json.dumps(compact, ensure_ascii=False))


def _compact_summary(summary: dict) -> dict:
    track = dict(summary.get("track") or {})
    analysis = dict(summary.get("analysis") or {})
    stems = summary.get("stems") or {}
    chords = summary.get("chords") or []
    downbeats = summary.get("downbeats") or []

    stems_compact: dict[str, Any] = {}
    for name, info in stems.items():
        if not isinstance(info, dict):
            continue
        if name == "drums":
            d = {"transcribed": bool(info.get("transcribed"))}
            if info.get("transcribed"):
                pieces = {}
                for p in ("kick", "snare", "toms", "hihat", "cymbals"):
                    v = info.get(p)
                    if isinstance(v, dict) and isinstance(v.get("t"), list):
                        pieces[p] = len(v["t"])
                d["piece_hit_counts"] = pieces
            elif info.get("reason"):
                d["reason"] = info["reason"]
            stems_compact["drums"] = d
        else:
            notes = info.get("notes")
            if isinstance(notes, list):
                stems_compact[name] = {"note_count": len(notes)}
            else:
                stems_compact[name] = {k: v for k, v in info.items() if k != "notes"}

    return {
        "track": track,
        "analysis": analysis,
        "chord_count": len(chords),
        "downbeat_count": len(downbeats),
        "stems": stems_compact,
    }


def build_user_message(text: str, view_state: dict | None) -> str:
    """Prepend a <view_state> block to the user's text. Returns text unchanged
    if view_state is None (used for the very first turn or stateless tests)."""
    if view_state is None:
        return text
    snapshot = json.dumps(view_state, ensure_ascii=False)
    return f"<view_state>{snapshot}</view_state>\n{text}"


from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server


# --- UI-action tools — return text confirmations only.
# Validation still happens here; the actor's _translate_message translates
# the tool's MCP-namespaced name to a short ui_action name and emits a
# separate ui_action event with the same input dict.

async def seek_to(args: dict[str, Any]) -> dict[str, Any]:
    t = float(args["time_sec"])
    return {"content": [{"type": "text", "text": f"Queued seek to {t:.2f}s"}]}


async def set_loop_region(args: dict[str, Any]) -> dict[str, Any]:
    s, e = float(args["start_sec"]), float(args["end_sec"])
    if e <= s:
        return {"content": [{"type": "text", "text": "end_sec must be greater than start_sec"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"Loop region: {s:.2f}s – {e:.2f}s"}]}


async def set_stem_state(args: dict[str, Any]) -> dict[str, Any]:
    parts = [f"stem={args['stem']}"]
    for k in ("mute", "solo", "volume"):
        if k in args and args[k] is not None:
            parts.append(f"{k}={args[k]}")
    return {"content": [{"type": "text", "text": "Updated " + " ".join(parts)}]}


async def highlight_stem(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Highlighted: {args['stem']}"}]}


async def open_midi_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"Opening {args['stem']}.mid"}]}


_TAB_CHOICES = {"track", "claude", "lyrics"}


async def switch_tab(args: dict[str, Any]) -> dict[str, Any]:
    if args["tab"] not in _TAB_CHOICES:
        return {"content": [{"type": "text", "text": f"Unknown tab: {args['tab']}"}], "is_error": True}
    return {"content": [{"type": "text", "text": f"Switched to {args['tab']} tab"}]}


async def highlight_lyric_line(args: dict[str, Any]) -> dict[str, Any]:
    idx = int(args["index"])
    return {"content": [{"type": "text", "text": f"Highlighting lyric line #{idx}"}]}


# --- Server-only tools — read pipeline artifacts. Lazy import avoids circular deps.

async def list_tracks_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    items = [{"slug": t.slug, "title": t.title, "duration_sec": t.duration_sec} for t in _tracks.list_tracks()]
    return {"content": [{"type": "text", "text": json.dumps(items, ensure_ascii=False)}]}


async def get_summary_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    slug = args.get("slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    try:
        s = _tracks.get_summary(slug)
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {slug}"}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(s, ensure_ascii=False)}]}


async def find_chord_occurrences(args: dict[str, Any]) -> dict[str, Any]:
    from . import tracks as _tracks
    slug = args.get("current_slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    try:
        s = _tracks.get_summary(slug)
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {slug}"}], "is_error": True}
    q = args["query"].strip()
    hits = []
    for c in s.get("chords") or []:
        if q == c.get("label") or q == c.get("roman"):
            hits.append({"start": c["start"], "end": c["end"], "label": c.get("label"), "roman": c.get("roman")})
    return {"content": [{"type": "text", "text": json.dumps(hits, ensure_ascii=False)}]}


# --- "What's playing right now" tools — cheap reads of the per-slug
# summary.json. These exist because _compact_summary strips the
# per-note arrays (otherwise the system prompt blows past Windows'
# CreateProcess command-line limit), so Claude needs another way to
# answer "what bass note is playing at 30s?". Each tool takes
# `current_slug` so it works for both the active track and (when
# Claude is in librarian mode) other tracks in the library.

def _load_summary_or_error(slug: Any):
    from . import tracks as _tracks
    if not is_safe_slug(slug):
        return None, _reject_slug(slug)
    try:
        return _tracks.get_summary(slug), None
    except KeyError:
        return None, {"content": [{"type": "text", "text": f"unknown slug: {slug}"}], "is_error": True}


def _err_text(msg: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "is_error": True}


def _ok_json(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


async def get_chord_at(args: dict[str, Any]) -> dict[str, Any]:
    s, err = _load_summary_or_error(args["current_slug"])
    if err:
        return err
    t = float(args["time_sec"])
    for c in s.get("chords") or []:
        if c.get("start", 0) <= t < c.get("end", 0):
            return _ok_json({
                "time_sec": t,
                "label": c.get("label"),
                "roman": c.get("roman"),
                "function": c.get("function"),
                "root": c.get("root"),
                "bass": c.get("bass"),
                "type": c.get("type"),
                "start_sec": c.get("start"),
                "end_sec": c.get("end"),
                "confidence": c.get("confidence"),
            })
    return _ok_json({"time_sec": t, "chord": None, "reason": "no chord at this time"})


async def get_progression(args: dict[str, Any]) -> dict[str, Any]:
    s, err = _load_summary_or_error(args["current_slug"])
    if err:
        return err
    start = float(args["start_sec"])
    end = float(args["end_sec"])
    if end <= start:
        return _err_text("end_sec must be greater than start_sec")
    chords = []
    for c in s.get("chords") or []:
        cs, ce = c.get("start", 0), c.get("end", 0)
        if ce <= start or cs >= end:
            continue
        chords.append({
            "label": c.get("label"),
            "roman": c.get("roman"),
            "function": c.get("function"),
            "start_sec": cs,
            "end_sec": ce,
        })
    return _ok_json({"start_sec": start, "end_sec": end, "chords": chords, "count": len(chords)})


async def get_notes_at(args: dict[str, Any]) -> dict[str, Any]:
    s, err = _load_summary_or_error(args["current_slug"])
    if err:
        return err
    stem = args["stem"]
    if not is_safe_stem(stem):
        return _reject_stem(stem)
    t = float(args["time_sec"])
    window = float(args.get("window_sec", 0.5))
    stems = s.get("stems") or {}
    info = stems.get(stem)
    if not isinstance(info, dict):
        return _err_text(f"unknown stem: {stem}")
    notes = info.get("notes")
    if not isinstance(notes, list):
        return _ok_json({"stem": stem, "time_sec": t, "window_sec": window, "notes": [], "reason": "stem is not pitched (e.g. drums)"})
    lo, hi = t - window, t + window
    hits = []
    for n in notes:
        nt = n.get("t", 0)
        nd = n.get("dur", 0)
        # overlap test: [nt, nt+nd] vs [lo, hi]
        if nt + nd >= lo and nt <= hi:
            hits.append({
                "t": nt, "dur": nd, "midi": n.get("midi"),
                "name": n.get("name"), "vel": n.get("vel"),
                "scale_deg": n.get("scale_deg"),
                "in_chord": n.get("in_chord"),
                "role": n.get("role"),
            })
            if len(hits) >= 40:  # cap — Claude doesn't need a wall of notes
                break
    return _ok_json({"stem": stem, "time_sec": t, "window_sec": window, "count": len(hits), "notes": hits})


async def get_lyric_at(args: dict[str, Any]) -> dict[str, Any]:
    from . import _paths, lyrics as _lyrics
    slug = args.get("current_slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    t = float(args["time_sec"])
    cache = _lyrics.cache_dir_for(_paths.cache_dir() / slug)
    cached = _lyrics.load_cached(cache)
    if not cached:
        return _ok_json({"time_sec": t, "line": None, "reason": "no lyrics cached for this track"})
    if not cached.get("has_sync"):
        return _ok_json({"time_sec": t, "line": None, "reason": "lyrics are plain text (no timing)"})
    lines = cached.get("lines") or []
    # Largest line.time_sec <= t.
    idx = -1
    for i, line in enumerate(lines):
        if line.get("time_sec", 0) <= t:
            idx = i
        else:
            break
    if idx < 0:
        return _ok_json({"time_sec": t, "line": None, "reason": "before first lyric line"})
    line = lines[idx]
    return _ok_json({
        "time_sec": t, "index": idx,
        "line": {"time_sec": line.get("time_sec"), "text": line.get("text")},
        "next": (lines[idx + 1] if idx + 1 < len(lines) else None),
    })


async def get_bar_time(args: dict[str, Any]) -> dict[str, Any]:
    """Convert a 1-indexed bar number (+ optional length in bars) to seconds.

    Use when the user asks 'loop bars 17-20' — call this to compute the
    start/end seconds, then call set_loop_region with the result.
    """
    s, err = _load_summary_or_error(args["current_slug"])
    if err:
        return err
    bar = int(args["bar_number"])
    length = max(1, int(args.get("bars", 1)))
    downbeats = s.get("downbeats") or []
    if bar < 1 or bar > len(downbeats):
        return _err_text(f"bar_number out of range; track has {len(downbeats)} bars")
    start_idx = bar - 1
    end_idx = min(start_idx + length, len(downbeats) - 1)
    start_sec = downbeats[start_idx]
    # If we want N bars and there's a downbeat that far, use it; otherwise
    # extrapolate one bar of the last-known interval.
    if end_idx > start_idx:
        end_sec = downbeats[end_idx]
    else:
        track = s.get("track") or {}
        end_sec = float(track.get("duration_sec") or (start_sec + 2.0))
    return _ok_json({
        "bar_number": bar, "bars": length,
        "start_sec": start_sec, "end_sec": end_sec,
        "total_bars": len(downbeats),
    })


async def get_track_dynamics(args: dict[str, Any]) -> dict[str, Any]:
    """Mean / peak RMS for a stem over a time window (linear amplitude)."""
    from . import _paths
    import numpy as np
    slug = args.get("current_slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    stem = args.get("stem")
    if not is_safe_stem(stem):
        return _reject_stem(stem)
    start = float(args["start_sec"])
    end = float(args["end_sec"])
    if end <= start:
        return _err_text("end_sec must be greater than start_sec")
    npz_path = _paths.cache_dir() / slug / "dynamics" / f"{stem}.npz"
    if not npz_path.is_file():
        return _err_text(f"dynamics not available for stem '{stem}' (file missing)")
    with np.load(npz_path) as z:
        if "rms" not in z.files:
            return _err_text(f"dynamics file has no 'rms' array (keys={list(z.files)})")
        rms = z["rms"]
    hop_sec = 0.01  # dynamics stage emits 100 fps, aligned to F0
    n = len(rms)
    i0 = max(0, int(start / hop_sec))
    i1 = min(n, int(end / hop_sec) + 1)
    if i1 <= i0:
        return _ok_json({"stem": stem, "start_sec": start, "end_sec": end, "samples": 0})
    seg = rms[i0:i1]
    return _ok_json({
        "stem": stem,
        "start_sec": start, "end_sec": end,
        "samples": int(i1 - i0),
        "rms_mean": float(seg.mean()),
        "rms_peak": float(seg.max()),
        "rms_min": float(seg.min()),
    })


async def get_vocal_pitch(args: dict[str, Any]) -> dict[str, Any]:
    """Consensus vocal F0 (Hz) + agreement strength at time_sec.

    Reads vocal_consensus.npz (the Phase 0c fused contour). Returns null F0
    when no consensus exists at the requested frame (silence/unvoiced).
    """
    from . import _paths
    import numpy as np
    slug = args.get("current_slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    t = float(args["time_sec"])
    window = float(args.get("window_sec", 0.1))
    npz_path = _paths.cache_dir() / slug / "vocal_consensus.npz"
    if not npz_path.is_file():
        return _err_text("vocal_consensus.npz not available (stage may not have run)")
    with np.load(npz_path) as z:
        f0 = z["consensus_f0"].astype(np.float32, copy=False)
        if "agreement_strength" in z.files:
            strength = z["agreement_strength"].astype(np.float32, copy=False)
        else:
            vc = z["vote_count"]
            strength = np.where(vc == 3, 1.0, np.where(vc == 2, 0.5, 0.0)).astype(np.float32)
    hop_sec = 0.01
    n = int(min(len(f0), len(strength)))
    i_center = max(0, min(n - 1, int(round(t / hop_sec))))
    half_w = max(0, int(round(window / hop_sec)))
    lo, hi = max(0, i_center - half_w), min(n, i_center + half_w + 1)
    seg_f0 = f0[lo:hi]
    seg_strength = strength[lo:hi]
    finite = np.isfinite(seg_f0)
    valid = seg_f0[finite]
    if len(valid) == 0:
        return _ok_json({
            "time_sec": t, "window_sec": window,
            "f0_hz": None, "midi": None, "agreement": 0.0,
            "reason": "no consensus at this frame (silence or low agreement)",
        })
    mean_hz = float(valid.mean())
    midi = float(69 + 12 * np.log2(mean_hz / 440.0)) if mean_hz > 0 else None
    return _ok_json({
        "time_sec": t, "window_sec": window,
        "f0_hz": mean_hz,
        "midi": midi,
        "agreement": float(seg_strength.mean()),
        "frames_valid": int(finite.sum()),
        "frames_total": int(hi - lo),
    })


async def get_current_view(args: dict[str, Any]) -> dict[str, Any]:
    """Aggregate snapshot at a given time: chord + nearest beat + lyric + key.

    Useful when Claude wants the full 'what's happening here' picture in one
    call. Notes per stem are *not* included by default — that's a separate
    get_notes_at call so this stays cheap.
    """
    s, err = _load_summary_or_error(args["current_slug"])
    if err:
        return err
    t = float(args["time_sec"])
    track = s.get("track") or {}
    analysis = s.get("analysis") or {}
    chord = None
    for c in s.get("chords") or []:
        if c.get("start", 0) <= t < c.get("end", 0):
            chord = {
                "label": c.get("label"), "roman": c.get("roman"),
                "function": c.get("function"), "start_sec": c.get("start"),
                "end_sec": c.get("end"),
            }
            break
    downbeats = s.get("downbeats") or []
    bar = None
    if downbeats and t >= downbeats[0]:
        lo, hi, idx = 0, len(downbeats) - 1, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if downbeats[mid] <= t:
                idx = mid
                lo = mid + 1
            else:
                hi = mid - 1
        bar_start = downbeats[idx]
        bar_end = downbeats[idx + 1] if idx + 1 < len(downbeats) else float(track.get("duration_sec") or bar_start + 2.0)
        bar = {"bar_number": idx + 1, "bar_start_sec": bar_start, "bar_end_sec": bar_end}
    return _ok_json({
        "time_sec": t,
        "track": {
            "key": track.get("key"),
            "scale": analysis.get("scale"),
            "tempo_bpm": track.get("tempo_bpm"),
            "time_signature": track.get("time_signature"),
            "duration_sec": track.get("duration_sec"),
        },
        "current_chord": chord,
        "current_bar": bar,
        "modal_interchange_count": analysis.get("modal_interchange_count"),
    })


# --- Lyrics tool ---

async def fetch_lyrics_tool(args: dict[str, Any]) -> dict[str, Any]:
    from . import lyrics as _lyrics, tracks as _tracks, _paths
    slug = args.get("current_slug")
    if not is_safe_slug(slug):
        return _reject_slug(slug)
    try:
        s = _tracks.get_summary(slug)
    except KeyError:
        return {"content": [{"type": "text", "text": f"unknown slug: {slug}"}], "is_error": True}
    duration = (s.get("track") or {}).get("duration_sec") or 0
    cache = _lyrics.cache_dir_for(_paths.cache_dir() / slug)
    force = bool(args.get("force"))
    if force:
        # Explicit re-fetch: the user asked Claude to find lyrics, which
        # usually means the cached set is wrong/missing. Drop the cache so
        # we hit LRCLIB again instead of short-circuiting on stale content.
        _lyrics.clear_cache(cache)
    else:
        cached = _lyrics.load_cached(cache)
        if cached:
            return {"content": [{"type": "text", "text": f"Lyrics already cached (synced={cached['has_sync']}). Pass force=true to re-fetch."}]}
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
        return {"content": [{"type": "text", "text": "Synced lyrics fetched."}]}
    if result.get("plain_text"):
        _lyrics.save_plain(cache, result["plain_text"], meta)
        return {"content": [{"type": "text", "text": "Plain lyrics fetched (no timing)."}]}
    return {"content": [{"type": "text", "text": f"No lyrics found ({result.get('error', 'unknown')})."}], "is_error": True}


# --- Tool registration & name translation ---

# Two schema styles in use:
#   - Shorthand `{"name": type}`: SDK auto-marks every key as required.
#     Use this only when the handler genuinely needs every field.
#   - Full JSON Schema dict (`type: object`, properties, required): SDK
#     passes it through verbatim. Use this when some args are optional —
#     the SDK's all-required default would otherwise reject partial calls.

_FULL_SCHEMA_SET_STEM_STATE = {
    "type": "object",
    "properties": {
        "stem":   {"type": "string"},
        "mute":   {"type": "boolean"},
        "solo":   {"type": "boolean"},
        "volume": {"type": "number"},
    },
    "required": ["stem"],
    "additionalProperties": False,
}

_FULL_SCHEMA_FETCH_LYRICS = {
    "type": "object",
    "properties": {
        "current_slug": {"type": "string"},
        "artist":       {"type": "string"},
        "title":        {"type": "string"},
        "force":        {"type": "boolean"},
    },
    "required": ["current_slug"],
    "additionalProperties": False,
}

_FULL_SCHEMA_GET_NOTES_AT = {
    "type": "object",
    "properties": {
        "current_slug": {"type": "string"},
        "stem":         {"type": "string"},
        "time_sec":     {"type": "number"},
        "window_sec":   {"type": "number"},
    },
    "required": ["current_slug", "stem", "time_sec"],
    "additionalProperties": False,
}

_FULL_SCHEMA_GET_VOCAL_PITCH = {
    "type": "object",
    "properties": {
        "current_slug": {"type": "string"},
        "time_sec":     {"type": "number"},
        "window_sec":   {"type": "number"},
    },
    "required": ["current_slug", "time_sec"],
    "additionalProperties": False,
}

_FULL_SCHEMA_GET_BAR_TIME = {
    "type": "object",
    "properties": {
        "current_slug": {"type": "string"},
        "bar_number":   {"type": "integer"},
        "bars":         {"type": "integer"},
    },
    "required": ["current_slug", "bar_number"],
    "additionalProperties": False,
}


def make_mcp_server():
    tools = [
        SdkMcpTool(
            name="seek_to",
            description="Move the audio playhead to a specific time in the track.",
            input_schema={"time_sec": float},
            handler=seek_to,
        ),
        SdkMcpTool(
            name="set_loop_region",
            description="Set a loop region. Audio loops between start_sec and end_sec until cleared.",
            input_schema={"start_sec": float, "end_sec": float},
            handler=set_loop_region,
        ),
        SdkMcpTool(
            name="set_stem_state",
            description="Update mute/solo/volume for one stem. Provide stem and any of mute (bool), solo (bool), volume (0..1).",
            input_schema=_FULL_SCHEMA_SET_STEM_STATE,
            handler=set_stem_state,
        ),
        SdkMcpTool(
            name="highlight_stem",
            description="Switch which stem is highlighted on the piano roll.",
            input_schema={"stem": str},
            handler=highlight_stem,
        ),
        SdkMcpTool(
            name="open_midi",
            description="Open the MIDI file for a stem in the user's default MIDI handler.",
            input_schema={"stem": str},
            handler=open_midi_tool,
        ),
        SdkMcpTool(
            name="switch_tab",
            description="Switch the sidebar's active tab. tab must be 'track', 'claude', or 'lyrics'.",
            input_schema={"tab": str},
            handler=switch_tab,
        ),
        SdkMcpTool(
            name="highlight_lyric_line",
            description="Highlight a specific lyric line by index in the lyrics tab and scroll it into focus.",
            input_schema={"index": int},
            handler=highlight_lyric_line,
        ),
        SdkMcpTool(
            name="list_tracks",
            description="List all analyzed tracks in the local library.",
            input_schema={},
            handler=list_tracks_tool,
        ),
        SdkMcpTool(
            name="get_summary",
            description="Return the full summary.json for any track in the library by slug.",
            input_schema={"slug": str},
            handler=get_summary_tool,
        ),
        SdkMcpTool(
            name="find_chord_occurrences",
            description="Find all chord occurrences in the current track matching a query (label like 'F:maj' or roman like 'V').",
            input_schema={"query": str, "current_slug": str},
            handler=find_chord_occurrences,
        ),
        SdkMcpTool(
            name="fetch_lyrics",
            description=(
                "Look up lyrics for the current track on LRCLIB. Optionally override "
                "artist/title for the search. Pass force=true to invalidate any cached "
                "lyrics and re-fetch — use this whenever the user explicitly asks for "
                "lyrics (the cached set is likely wrong or they wouldn't be asking)."
            ),
            input_schema=_FULL_SCHEMA_FETCH_LYRICS,
            handler=fetch_lyrics_tool,
        ),
        SdkMcpTool(
            name="get_chord_at",
            description="Return the chord at a given playhead time. Cheaper than get_summary when you only need 'what's playing now'.",
            input_schema={"time_sec": float, "current_slug": str},
            handler=get_chord_at,
        ),
        SdkMcpTool(
            name="get_progression",
            description="List chords overlapping the time window [start_sec, end_sec]. Use when asked about a section's harmony.",
            input_schema={"start_sec": float, "end_sec": float, "current_slug": str},
            handler=get_progression,
        ),
        SdkMcpTool(
            name="get_notes_at",
            description=(
                "Return detected notes for one stem in a window around time_sec. "
                "stem ∈ {vocals, bass, guitar, piano, other}. Returns each note's "
                "midi, name, scale_deg (relative to key), in_chord, and role "
                "(chord_tone | non_chord_tone)."
            ),
            input_schema=_FULL_SCHEMA_GET_NOTES_AT,
            handler=get_notes_at,
        ),
        SdkMcpTool(
            name="get_lyric_at",
            description="Return the lyric line covering time_sec (synced lyrics only). Soft-fails when no lyrics are cached.",
            input_schema={"time_sec": float, "current_slug": str},
            handler=get_lyric_at,
        ),
        SdkMcpTool(
            name="get_current_view",
            description=(
                "Aggregate snapshot at time_sec: chord, current bar, key/tempo/time-signature. "
                "Notes are NOT included — call get_notes_at separately when you need them."
            ),
            input_schema={"time_sec": float, "current_slug": str},
            handler=get_current_view,
        ),
        SdkMcpTool(
            name="get_bar_time",
            description=(
                "Convert a 1-indexed bar number (with optional length in bars) to "
                "start/end seconds. Chain with set_loop_region to loop bars N..N+k."
            ),
            input_schema=_FULL_SCHEMA_GET_BAR_TIME,
            handler=get_bar_time,
        ),
        SdkMcpTool(
            name="get_track_dynamics",
            description="Mean/peak/min RMS amplitude for a stem over [start_sec, end_sec]. Use for 'how loud is the vocal in the bridge?'.",
            input_schema={"stem": str, "start_sec": float, "end_sec": float, "current_slug": str},
            handler=get_track_dynamics,
        ),
        SdkMcpTool(
            name="get_vocal_pitch",
            description="Consensus vocal F0 (Hz) and agreement strength at time_sec. Null when unvoiced/silence.",
            input_schema=_FULL_SCHEMA_GET_VOCAL_PITCH,
            handler=get_vocal_pitch,
        ),
    ]
    return create_sdk_mcp_server(name="musiq-tools", version="1.0.0", tools=tools)


# Map full MCP tool names (as they appear in ToolUseBlock.name) to short
# ui_action names emitted to the browser. Two flavors:
#
#   IMMEDIATE — fired on tool_use, before the tool runs. Safe for actions
#     that just mutate browser state (seek, mute, loop). Speculative; the
#     tool's is_error result is informational to Claude.
#
#   DEFERRED — fired on tool_result, after the tool finishes. Required for
#     actions that read server state the tool just wrote (e.g. fetch_lyrics
#     writes lyrics/meta.json then the browser must re-read it). Firing
#     immediately would race against the tool's I/O.
TOOL_NAME_TO_UI_ACTION = {
    "mcp__musiq-tools__seek_to": "seek_to",
    "mcp__musiq-tools__set_loop_region": "set_loop_region",
    "mcp__musiq-tools__set_stem_state": "set_stem_state",
    "mcp__musiq-tools__highlight_stem": "highlight_stem",
    "mcp__musiq-tools__open_midi": "open_midi",
    "mcp__musiq-tools__switch_tab": "switch_tab",
    "mcp__musiq-tools__highlight_lyric_line": "highlight_lyric_line",
}

TOOL_NAME_TO_DEFERRED_UI_ACTION = {
    "mcp__musiq-tools__fetch_lyrics": "reload_lyrics",
}


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
    "mcp__musiq-tools__get_chord_at",
    "mcp__musiq-tools__get_progression",
    "mcp__musiq-tools__get_notes_at",
    "mcp__musiq-tools__get_lyric_at",
    "mcp__musiq-tools__get_current_view",
    "mcp__musiq-tools__get_bar_time",
    "mcp__musiq-tools__get_track_dynamics",
    "mcp__musiq-tools__get_vocal_pitch",
    "WebFetch",
    "WebSearch",
]


# --- SDK options & message translation ---

from claude_agent_sdk import (
    ClaudeAgentOptions,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
)


def build_actor_options(
    *,
    system_prompt: str,
    mcp_server: Any,
    allowed_tools: list[str],
    cwd: str | None = None,
    resume_session_id: str | None = None,
) -> ClaudeAgentOptions:
    """Construct ClaudeAgentOptions for a per-slug ChatActor.

    setting_sources=[] runs the SDK in isolation mode: no user/project/local
    settings.json get loaded, so user-installed plugin SessionStart hooks
    (e.g. superpowers, explanatory-output-style) don't fire. On Windows
    those hooks deadlock SDK init — see claude-code#9542 / sdk-python#208 —
    and we don't want an app's embedded chat inheriting the user's whole
    Claude Code config anyway.

    resume_session_id, when present, asks the CLI to bootstrap context from
    its own session log on the first turn after (re-)opening the client.
    Subsequent turns within the same client lifetime use in-memory context.
    """
    kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "mcp_servers": {"musiq-tools": mcp_server},
        "allowed_tools": allowed_tools,
        "setting_sources": [],
    }
    if cwd is not None:
        kwargs["cwd"] = cwd
    if resume_session_id:
        kwargs["resume"] = resume_session_id
    return ClaudeAgentOptions(**kwargs)


def translate_message(msg: Any, tool_calls: dict[str, tuple[str, dict]]) -> Iterator[dict]:
    """Translate one SDK message into zero or more browser-facing NDJSON events.

    Event shapes:
      {"type": "text", "delta": str}
      {"type": "tool_use", "id": str, "name": str, "input": dict}
      {"type": "tool_result", "id": str, "ok": bool, "summary": str}
      {"type": "ui_action", "id": str, "action": str, "args": dict}
      {"type": "done", "session_id": str|None, "tokens": {...}}

    Duck-types SDK message classes via attribute presence so the function
    is testable with simple MagicMocks:
      - AssistantMessage-like: has `.content` (a list of blocks)
      - TextBlock-like: has `.text`
      - ToolUseBlock-like: has `.name`, `.input`, `.id`
      - ToolResultBlock-like: has `.tool_use_id`
      - ResultMessage-like: has `.session_id` and/or `.usage`

    `tool_calls` is a per-actor map of tool_use_id → (tool_name, input). It
    lets us emit deferred ui_actions when a tool_result arrives (the
    ToolResultBlock only carries tool_use_id, not the original tool name).
    """
    content = getattr(msg, "content", None)
    if content is not None:
        for block in content:
            # ToolResultBlock: matched by tool_use_id (no .name).
            # Check this BEFORE the .text branch — some result blocks
            # also expose textual content via .content but represent
            # tool completion, not a model utterance.
            if hasattr(block, "tool_use_id"):
                result_id = getattr(block, "tool_use_id", "") or ""
                is_error = bool(getattr(block, "is_error", False))
                summary = _summarize_tool_result(getattr(block, "content", None))
                yield {"type": "tool_result", "id": result_id, "ok": not is_error, "summary": summary}
                call = tool_calls.get(result_id)
                if call:
                    name, input_args = call
                    deferred = TOOL_NAME_TO_DEFERRED_UI_ACTION.get(name)
                    if deferred and not is_error:
                        yield {"type": "ui_action", "id": result_id, "action": deferred, "args": input_args}
                continue
            if hasattr(block, "text"):
                yield {"type": "text", "delta": block.text}
            elif hasattr(block, "name") and hasattr(block, "input"):
                block_id = getattr(block, "id", None) or ""
                block_name = block.name
                raw = block.input
                block_input = dict(raw) if isinstance(raw, dict) else {}
                tool_calls[block_id] = (block_name, block_input)
                yield {"type": "tool_use", "id": block_id, "name": block_name, "input": block_input}
                ui_action = TOOL_NAME_TO_UI_ACTION.get(block_name)
                if ui_action:
                    yield {"type": "ui_action", "id": block_id, "action": ui_action, "args": block_input}
        return
    # Only ResultMessage (the end-of-turn marker) emits a "done" event.
    # `duration_ms` uniquely identifies ResultMessage among SDK message
    # types — RateLimitEvent and AssistantMessage also have `session_id`
    # so the previous `hasattr(msg, "session_id")` guard fired spuriously
    # for them, polluting the token counter and tripping `emitted_done`
    # before the real result arrived.
    if hasattr(msg, "duration_ms"):
        usage = getattr(msg, "usage", None) or {}
        # Usage may be a dict or a Pydantic-like object; `.get` on dict only.
        get = usage.get if isinstance(usage, dict) else (lambda k, default=0: getattr(usage, k, default))
        yield {
            "type": "done",
            "session_id": getattr(msg, "session_id", None),
            "tokens": {
                "input": get("input_tokens", 0),
                "output": get("output_tokens", 0),
                "cache_read": get("cache_read_input_tokens", 0),
            },
        }


def _summarize_tool_result(content: Any) -> str:
    """Flatten a ToolResultBlock's content into a short summary string.
    SDK content is typically a list of {type:'text', text:str} dicts; fall
    back to str() for anything else. Truncated for storage in chat history."""
    if content is None:
        return ""
    if isinstance(content, str):
        s = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        s = " ".join(p for p in parts if p)
    else:
        s = str(content)
    s = s.strip()
    return s if len(s) <= 200 else s[:200] + "…"


def classify_exception(e: BaseException) -> tuple[str, str]:
    """Map an SDK exception to (kind, message) for the browser.

    kind ∈ {"auth", "network", "internal"}. The HTTP route emits an
    "auth_required" event (no payload) when kind == "auth", else an
    "error" event carrying kind + message.
    """
    if isinstance(e, CLINotFoundError):
        return "auth", "Claude CLI not found — install or run `claude /login`."
    if isinstance(e, ProcessError):
        stderr = (getattr(e, "stderr", "") or "").lower()
        if any(tok in stderr for tok in ("login", "credential", "unauthor")):
            return "auth", str(e)
        return "internal", str(e)
    if isinstance(e, (CLIConnectionError, CLIJSONDecodeError)):
        return "network", str(e)
    return "internal", repr(e)


# --- History persistence ---

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


def load_last_session_id(path: Path) -> str | None:
    """Read last_session_id from the chat.json envelope, if any. Used to
    resume the CLI session when the actor is (re-)opened after an idle
    close, server restart, or fresh actor creation for an existing chat."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    sid = data.get("last_session_id")
    return sid if isinstance(sid, str) and sid else None


def _save_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _save_history(path: Path, messages: list[dict], session_id: str | None = None) -> None:
    payload: dict = {"schema_version": CHAT_SCHEMA_VERSION, "messages": messages}
    # Preserve any prior last_session_id when caller didn't supply one
    # (e.g. append_user_message after a turn already established a session).
    existing_sid: str | None = None
    if session_id is None and path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            sid = existing.get("last_session_id")
            if isinstance(sid, str) and sid:
                existing_sid = sid
        except (json.JSONDecodeError, OSError):
            pass
    final_sid = session_id or existing_sid
    if final_sid:
        payload["last_session_id"] = final_sid
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
