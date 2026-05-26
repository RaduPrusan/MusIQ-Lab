import asyncio
import json

import pytest
from unittest.mock import MagicMock

from webui import chat as chat_mod
from webui.chat import (
    build_system_prompt, build_user_message,
    build_actor_options, classify_exception, translate_message,
    load_history, load_last_session_id, append_user_message,
    append_assistant_message, clear_history, _save_history,
    TOOL_NAME_TO_UI_ACTION, TOOL_NAME_TO_DEFERRED_UI_ACTION, ALLOWED_TOOLS,
    make_mcp_server,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- Prompt assembly --------------------------------------------------------

def test_build_system_prompt_includes_track_summary():
    summary = {
        "track": {"slug": "demo", "key": "C major", "tempo_bpm": 120, "duration_sec": 180},
        "chords": [], "downbeats": [], "stems": {}, "analysis": {},
    }
    prompt = build_system_prompt(summary)
    assert "music tutor" in prompt.lower()
    assert "C major" in prompt
    assert "120" in prompt


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


# --- UI-action tool handlers -----------------------------------------------

def test_seek_to_returns_confirmation():
    out = _run(chat_mod.seek_to({"time_sec": 12.34}))
    assert "12.34" in out["content"][0]["text"]
    assert not out.get("is_error")


def test_set_loop_region_accepts_valid():
    out = _run(chat_mod.set_loop_region({"start_sec": 5.0, "end_sec": 12.0}))
    assert not out.get("is_error")


def test_set_loop_region_rejects_inverted():
    out = _run(chat_mod.set_loop_region({"start_sec": 12.0, "end_sec": 5.0}))
    assert out.get("is_error") is True


def test_set_stem_state_text_includes_stem():
    out = _run(chat_mod.set_stem_state({"stem": "vocals", "mute": True}))
    assert "vocals" in out["content"][0]["text"]


def test_set_stem_state_accepts_only_required_field():
    # B1 regression: handler must work with just `stem` set; the schema
    # marks mute/solo/volume as optional.
    out = _run(chat_mod.set_stem_state({"stem": "vocals"}))
    assert not out.get("is_error")
    assert "vocals" in out["content"][0]["text"]


def test_highlight_stem_text():
    out = _run(chat_mod.highlight_stem({"stem": "piano"}))
    assert "piano" in out["content"][0]["text"]


def test_open_midi_text():
    out = _run(chat_mod.open_midi_tool({"stem": "vocals"}))
    assert "vocals" in out["content"][0]["text"]


def test_switch_tab_accepts_valid():
    out = _run(chat_mod.switch_tab({"tab": "lyrics"}))
    assert not out.get("is_error")


def test_switch_tab_rejects_invalid():
    out = _run(chat_mod.switch_tab({"tab": "not_a_tab"}))
    assert out.get("is_error") is True


def test_highlight_lyric_line_text():
    out = _run(chat_mod.highlight_lyric_line({"index": 7}))
    assert "7" in out["content"][0]["text"]


# --- Server-only tool handlers ---------------------------------------------

def test_list_tracks_returns_json(monkeypatch):
    class FakeTrack:
        def __init__(self, slug, title, duration_sec):
            self.slug = slug; self.title = title; self.duration_sec = duration_sec
    monkeypatch.setattr("webui.tracks.list_tracks", lambda: [
        FakeTrack("a", "Track A", 100),
        FakeTrack("b", "Track B", 200),
    ])
    out = _run(chat_mod.list_tracks_tool({}))
    parsed = json.loads(out["content"][0]["text"])
    assert len(parsed) == 2
    assert parsed[0]["slug"] == "a"


def test_get_summary_unknown_slug(monkeypatch):
    def raise_keyerror(slug):
        raise KeyError(slug)
    monkeypatch.setattr("webui.tracks.get_summary", raise_keyerror)
    out = _run(chat_mod.get_summary_tool({"slug": "__nope__"}))
    assert out.get("is_error") is True


def test_get_summary_known_slug(monkeypatch):
    monkeypatch.setattr("webui.tracks.get_summary", lambda slug: {"track": {"slug": slug, "key": "C major"}})
    out = _run(chat_mod.get_summary_tool({"slug": "demo"}))
    s = json.loads(out["content"][0]["text"])
    assert s["track"]["slug"] == "demo"


def test_find_chord_occurrences_filters_by_roman(monkeypatch):
    fake = {"chords": [
        {"start": 0.0, "end": 2.0, "label": "C:maj", "roman": "I"},
        {"start": 2.0, "end": 4.0, "label": "G:maj", "roman": "V"},
        {"start": 4.0, "end": 6.0, "label": "C:maj", "roman": "I"},
    ]}
    monkeypatch.setattr("webui.tracks.get_summary", lambda slug: fake)
    out = _run(chat_mod.find_chord_occurrences({"query": "I", "current_slug": "demo"}))
    hits = json.loads(out["content"][0]["text"])
    assert len(hits) == 2


def test_find_chord_occurrences_filters_by_label(monkeypatch):
    fake = {"chords": [
        {"start": 0.0, "end": 2.0, "label": "C:maj", "roman": "I"},
        {"start": 2.0, "end": 4.0, "label": "G:maj", "roman": "V"},
    ]}
    monkeypatch.setattr("webui.tracks.get_summary", lambda slug: fake)
    out = _run(chat_mod.find_chord_occurrences({"query": "G:maj", "current_slug": "demo"}))
    hits = json.loads(out["content"][0]["text"])
    assert len(hits) == 1
    assert hits[0]["label"] == "G:maj"


# --- Context tools (get_chord_at, get_notes_at, get_progression, etc.) ----

_FAKE_SUMMARY = {
    "track": {"duration_sec": 60, "key": "C major", "tempo_bpm": 120, "time_signature": "4/4"},
    "analysis": {"scale": "C major", "modal_interchange_count": 3},
    "downbeats": [0.0, 2.0, 4.0, 6.0],
    "chords": [
        {"start": 0.0, "end": 2.0, "label": "C:maj", "root": "C", "bass": "C",
         "type": "maj", "roman": "I", "function": "tonic", "confidence": 0.9},
        {"start": 2.0, "end": 4.0, "label": "G:maj", "root": "G", "bass": "G",
         "type": "maj", "roman": "V", "function": "dominant", "confidence": 0.85},
        {"start": 4.0, "end": 6.0, "label": "F:maj", "root": "F", "bass": "F",
         "type": "maj", "roman": "IV", "function": "subdominant", "confidence": 0.8},
    ],
    "stems": {
        "bass": {"notes": [
            {"t": 0.0, "dur": 1.0, "midi": 36, "name": "C2", "vel": 0.7,
             "scale_deg": "1", "in_chord": "C:maj", "role": "chord_tone"},
            {"t": 1.5, "dur": 0.5, "midi": 38, "name": "D2", "vel": 0.5,
             "scale_deg": "2", "in_chord": "C:maj", "role": "non_chord_tone"},
            {"t": 4.0, "dur": 1.0, "midi": 41, "name": "F2", "vel": 0.6,
             "scale_deg": "4", "in_chord": "F:maj", "role": "chord_tone"},
        ]},
        "drums": {"transcribed": False, "reason": "skipped"},
    },
}


def _patch_summary(monkeypatch, summary=_FAKE_SUMMARY):
    monkeypatch.setattr("webui.tracks.get_summary", lambda slug: summary)


def test_get_chord_at_returns_chord(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_chord_at({"time_sec": 2.5, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    assert body["label"] == "G:maj"
    assert body["roman"] == "V"
    assert body["function"] == "dominant"


def test_get_chord_at_empty_when_outside(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_chord_at({"time_sec": 999.0, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    assert body["chord"] is None


def test_get_chord_at_unknown_slug_errors(monkeypatch):
    def raise_ke(slug):
        raise KeyError(slug)
    monkeypatch.setattr("webui.tracks.get_summary", raise_ke)
    out = _run(chat_mod.get_chord_at({"time_sec": 1.0, "current_slug": "__nope__"}))
    assert out.get("is_error") is True


def test_get_progression_filters_window(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_progression({"start_sec": 1.0, "end_sec": 5.0, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    labels = [c["label"] for c in body["chords"]]
    assert labels == ["C:maj", "G:maj", "F:maj"]


def test_get_progression_rejects_inverted(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_progression({"start_sec": 5.0, "end_sec": 1.0, "current_slug": "demo"}))
    assert out.get("is_error") is True


def test_get_notes_at_returns_overlapping_notes(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_notes_at({"time_sec": 0.5, "stem": "bass", "window_sec": 0.5, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    # Note at t=0.0 dur=1.0 overlaps [0.0, 1.0]. Note at t=1.5 dur=0.5 doesn't reach down to 1.0.
    assert body["count"] == 1
    assert body["notes"][0]["name"] == "C2"


def test_get_notes_at_unknown_stem(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_notes_at({"time_sec": 0.5, "stem": "kazoo", "window_sec": 0.5, "current_slug": "demo"}))
    assert out.get("is_error") is True


def test_get_notes_at_drums_falls_through_softly(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_notes_at({"time_sec": 0.5, "stem": "drums", "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    # Drums entry has no `notes` list → soft "not pitched", not an error.
    assert not out.get("is_error")
    assert body["notes"] == []


def test_get_bar_time_first_bar(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_bar_time({"bar_number": 1, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    assert body["start_sec"] == 0.0
    assert body["end_sec"] == 2.0
    assert body["total_bars"] == 4


def test_get_bar_time_multi_bar_range(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_bar_time({"bar_number": 1, "bars": 3, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    assert body["start_sec"] == 0.0
    assert body["end_sec"] == 6.0


def test_get_bar_time_out_of_range(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_bar_time({"bar_number": 999, "current_slug": "demo"}))
    assert out.get("is_error") is True


def test_get_current_view_combines_chord_and_bar(monkeypatch):
    _patch_summary(monkeypatch)
    out = _run(chat_mod.get_current_view({"time_sec": 3.0, "current_slug": "demo"}))
    body = json.loads(out["content"][0]["text"])
    assert body["current_chord"]["label"] == "G:maj"
    assert body["current_bar"]["bar_number"] == 2
    assert body["track"]["key"] == "C major"


# get_lyric_at, get_track_dynamics, get_vocal_pitch use file I/O —
# exercised at the integration layer in test_server.py rather than here.


# --- ALLOWED_TOOLS coverage ------------------------------------------------

def test_allowed_tools_includes_all_new_context_tools():
    expected = {
        "mcp__musiq-tools__get_chord_at",
        "mcp__musiq-tools__get_progression",
        "mcp__musiq-tools__get_notes_at",
        "mcp__musiq-tools__get_lyric_at",
        "mcp__musiq-tools__get_current_view",
        "mcp__musiq-tools__get_bar_time",
        "mcp__musiq-tools__get_track_dynamics",
        "mcp__musiq-tools__get_vocal_pitch",
    }
    assert expected.issubset(set(ALLOWED_TOOLS))


def test_system_prompt_advertises_researcher_role_and_web_tools():
    summary = {"track": {"key": "C", "tempo_bpm": 120, "duration_sec": 60},
               "chords": [], "downbeats": [], "stems": {}, "analysis": {}}
    prompt = build_system_prompt(summary)
    assert "Researcher" in prompt
    assert "WebSearch" in prompt
    assert "WebFetch" in prompt


# --- Module-level constants & MCP server -----------------------------------

def test_tool_name_to_ui_action_covers_all_seven_ui_tools():
    expected = {"seek_to", "set_loop_region", "set_stem_state", "highlight_stem",
                "open_midi", "switch_tab", "highlight_lyric_line"}
    assert set(TOOL_NAME_TO_UI_ACTION.values()) == expected
    for k in TOOL_NAME_TO_UI_ACTION:
        assert k.startswith("mcp__musiq-tools__")


def test_allowed_tools_includes_web_tools():
    assert "WebFetch" in ALLOWED_TOOLS
    assert "WebSearch" in ALLOWED_TOOLS


def test_make_mcp_server_constructs():
    server = make_mcp_server()
    assert server is not None


def test_set_stem_state_schema_marks_only_stem_required():
    # B1 regression: SDK auto-marks every shorthand-schema key as required.
    # set_stem_state must use the full-schema form so mute/solo/volume can be omitted.
    schema = chat_mod._FULL_SCHEMA_SET_STEM_STATE
    assert schema["type"] == "object"
    assert schema["required"] == ["stem"]
    for k in ("mute", "solo", "volume"):
        assert k in schema["properties"]


def test_fetch_lyrics_schema_marks_only_current_slug_required():
    schema = chat_mod._FULL_SCHEMA_FETCH_LYRICS
    assert schema["required"] == ["current_slug"]
    for k in ("artist", "title", "force"):
        assert k in schema["properties"]


# --- build_actor_options ---------------------------------------------------

def test_build_actor_options_sets_resume_when_provided():
    server = make_mcp_server()
    opts = build_actor_options(
        system_prompt="sys",
        mcp_server=server,
        allowed_tools=["X"],
        resume_session_id="sid-prev",
    )
    assert getattr(opts, "resume", None) == "sid-prev"
    # Always isolated: no user/project/local settings.json loaded.
    assert getattr(opts, "setting_sources", None) == []


def test_build_actor_options_omits_resume_when_none():
    server = make_mcp_server()
    opts = build_actor_options(
        system_prompt="sys",
        mcp_server=server,
        allowed_tools=["X"],
        resume_session_id=None,
    )
    # Either unset or None — both fine. Asserting unset/falsy.
    assert not getattr(opts, "resume", None)


# --- translate_message -----------------------------------------------------

def _mk_text_block(text):
    b = MagicMock(spec=["text"])
    b.text = text
    return b


def _mk_tool_use_block(id_, name, input_):
    b = MagicMock(spec=["id", "name", "input"])
    b.id = id_
    b.name = name
    b.input = input_
    return b


def _mk_tool_result_block(tool_use_id, content, is_error=False):
    b = MagicMock(spec=["tool_use_id", "content", "is_error"])
    b.tool_use_id = tool_use_id
    b.content = content
    b.is_error = is_error
    return b


def _mk_assistant_msg(blocks):
    m = MagicMock(spec=["content"])
    m.content = blocks
    return m


def _mk_result_msg(session_id="sid-1", input_tokens=100, output_tokens=50, cache_read=80):
    # `duration_ms` is the unique-to-ResultMessage attribute that
    # translate_message uses to gate the "done" event.
    m = MagicMock(spec=["session_id", "usage", "duration_ms"])
    m.session_id = session_id
    m.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_input_tokens": cache_read}
    m.duration_ms = 100
    return m


def test_translate_message_emits_text_deltas():
    msg = _mk_assistant_msg([_mk_text_block("hello "), _mk_text_block("world")])
    events = list(translate_message(msg, {}))
    assert events == [{"type": "text", "delta": "hello "}, {"type": "text", "delta": "world"}]


def test_translate_message_emits_tool_use_and_immediate_ui_action():
    tool_calls: dict = {}
    msg = _mk_assistant_msg([_mk_tool_use_block("tu1", "mcp__musiq-tools__seek_to", {"time_sec": 12.0})])
    events = list(translate_message(msg, tool_calls))
    assert events[0] == {"type": "tool_use", "id": "tu1", "name": "mcp__musiq-tools__seek_to", "input": {"time_sec": 12.0}}
    assert events[1] == {"type": "ui_action", "id": "tu1", "action": "seek_to", "args": {"time_sec": 12.0}}
    assert tool_calls == {"tu1": ("mcp__musiq-tools__seek_to", {"time_sec": 12.0})}


def test_translate_message_no_ui_action_for_unmapped_tool():
    msg = _mk_assistant_msg([_mk_tool_use_block("tu2", "mcp__musiq-tools__list_tracks", {})])
    events = list(translate_message(msg, {}))
    assert any(e["type"] == "tool_use" for e in events)
    assert not any(e["type"] == "ui_action" for e in events)


def test_translate_message_emits_deferred_ui_action_for_fetch_lyrics_tool_result():
    tool_calls = {"tu3": ("mcp__musiq-tools__fetch_lyrics", {"current_slug": "demo", "force": True})}
    msg = _mk_assistant_msg([_mk_tool_result_block("tu3", [{"type": "text", "text": "Synced lyrics fetched."}])])
    events = list(translate_message(msg, tool_calls))
    assert events[0]["type"] == "tool_result"
    assert events[0]["ok"] is True
    assert any(e["type"] == "ui_action" and e["action"] == "reload_lyrics" for e in events)


def test_translate_message_no_deferred_ui_action_on_tool_result_error():
    tool_calls = {"tu4": ("mcp__musiq-tools__fetch_lyrics", {"current_slug": "demo"})}
    msg = _mk_assistant_msg([_mk_tool_result_block("tu4", [{"type": "text", "text": "no lyrics"}], is_error=True)])
    events = list(translate_message(msg, tool_calls))
    assert events[0]["type"] == "tool_result"
    assert events[0]["ok"] is False
    assert not any(e["type"] == "ui_action" for e in events)


def test_translate_message_emits_done_for_result_message():
    events = list(translate_message(_mk_result_msg(session_id="sid-x"), {}))
    assert events == [{"type": "done", "session_id": "sid-x", "tokens": {"input": 100, "output": 50, "cache_read": 80}}]


def test_translate_message_done_handles_object_usage():
    class FakeUsage:
        input_tokens = 7
        output_tokens = 3
        cache_read_input_tokens = 5
    m = MagicMock(spec=["session_id", "usage", "duration_ms"])
    m.session_id = "s"
    m.usage = FakeUsage()
    m.duration_ms = 100
    events = list(translate_message(m, {}))
    assert events[0]["tokens"] == {"input": 7, "output": 3, "cache_read": 5}


def test_translate_message_skips_rate_limit_event():
    # RateLimitEvent has session_id but no duration_ms — must NOT emit "done".
    rle = MagicMock(spec=["session_id"])
    rle.session_id = "sid-x"
    events = list(translate_message(rle, {}))
    assert events == []


def test_translate_message_skips_assistant_message_for_done():
    # AssistantMessage has session_id and usage and content. The content
    # branch handles its blocks; it must NOT also emit "done".
    am = MagicMock(spec=["content", "session_id", "usage"])
    am.session_id = "sid-x"
    am.usage = {"input_tokens": 1}
    am.content = []  # empty content list; branch takes content path and returns
    events = list(translate_message(am, {}))
    assert events == []


# --- classify_exception ----------------------------------------------------

def test_classify_exception_cli_not_found_is_auth():
    from claude_agent_sdk import CLINotFoundError
    kind, _ = classify_exception(CLINotFoundError("not found"))
    assert kind == "auth"


def test_classify_exception_process_error_with_login_stderr_is_auth():
    from claude_agent_sdk import ProcessError
    e = ProcessError("crashed", exit_code=1, stderr="please run claude login")
    kind, _ = classify_exception(e)
    assert kind == "auth"


def test_classify_exception_process_error_other_is_internal():
    from claude_agent_sdk import ProcessError
    e = ProcessError("crashed", exit_code=99, stderr="segfault")
    kind, _ = classify_exception(e)
    assert kind == "internal"


def test_classify_exception_connection_is_network():
    from claude_agent_sdk import CLIConnectionError
    kind, _ = classify_exception(CLIConnectionError("disconnected"))
    assert kind == "network"


def test_classify_exception_unknown_is_internal():
    kind, _ = classify_exception(RuntimeError("something else broke"))
    assert kind == "internal"


# --- History persistence ---------------------------------------------------

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


def test_load_last_session_id_roundtrip(tmp_path):
    p = tmp_path / "chat.json"
    append_user_message(p, "hi")
    append_assistant_message(p, blocks=[{"type": "text", "text": "yo"}], session_id="sid-abc")
    assert load_last_session_id(p) == "sid-abc"


def test_load_last_session_id_returns_none_when_missing(tmp_path):
    p = tmp_path / "chat.json"
    assert load_last_session_id(p) is None
    append_user_message(p, "hi")  # no session_id ever stored
    assert load_last_session_id(p) is None


def test_save_history_preserves_existing_session_id_when_caller_omits(tmp_path):
    # Regression: append_user_message (no session_id) must not erase a
    # previously-stored last_session_id, otherwise resume bootstrap breaks
    # after the very next user message.
    p = tmp_path / "chat.json"
    _save_history(p, [{"role": "user", "blocks": [{"type": "text", "text": "x"}]}], session_id="sid-keep")
    assert load_last_session_id(p) == "sid-keep"
    append_user_message(p, "follow-up")
    assert load_last_session_id(p) == "sid-keep"
