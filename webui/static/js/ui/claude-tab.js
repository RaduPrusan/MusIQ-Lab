import { el, clear } from "./dom.js";
import { api } from "../api.js";

export class ClaudeTab {
  constructor(host) {
    this.host = host;
    this.slug = null;
    this.trackData = null;
    this.engine = null;
    this.viewState = null;
    this.tabbedSidebar = null;
    this.lyricsTab = null;
    this._abort = null;
    this._tokens = null;
    this._messages = [];
    this._streamingAssistantBubble = null;
    this._currentTextNode = null;
    // tool_use_id → chip element, for in-flight runs *and* restored history.
    // tool_result events update the chip via this map.
    this._chipById = new Map();
    // Pre-first-byte spinner (transient — replaced by the first text/tool event).
    this._pendingSpinner = null;
    this._inFlight = false;
  }

  mount({ trackData, viewState, engine, tabbedSidebar, lyricsTab }) {
    this.slug = trackData.meta.slug;
    this.trackData = trackData;
    this.viewState = viewState;
    this.engine = engine;
    this.tabbedSidebar = tabbedSidebar;
    this.lyricsTab = lyricsTab;
    // Cross-tab handoff: lyrics-tab.js' "Ask Claude to find lyrics" item calls this.
    window.__musiqClaudeAsk = (text) => this._prefillAndSend(text);
    this._build();
    this._restoreHistory();
  }

  _build() {
    clear(this.host);
    this.headerEl = el("div", { class: "claude-header" });
    const clearBtn = el("button", {
      class: "btn", text: "Clear chat", attrs: { type: "button" },
      onClick: () => this._clear(),
    });
    this.stopBtn = el("button", {
      class: "btn claude-stop", text: "Stop", attrs: { type: "button", disabled: "" },
      onClick: () => this._stop(),
    });
    this.statusEl = el("span", { class: "claude-status", text: "ready" });
    this.tokensEl = el("span", { class: "claude-tokens", text: "" });
    this.headerEl.appendChild(clearBtn);
    this.headerEl.appendChild(this.stopBtn);
    this.headerEl.appendChild(this.statusEl);
    this.headerEl.appendChild(this.tokensEl);

    this.transcriptEl = el("div", { class: "claude-transcript" });

    this.composerForm = el("form", { class: "claude-composer" });
    this.textarea = el("textarea", {
      class: "claude-textarea",
      attrs: { rows: "2", placeholder: "Ask about this song" },
    });
    this.sendBtn = el("button", { class: "btn", text: "Send", attrs: { type: "submit" } });
    this.composerForm.appendChild(this.textarea);
    this.composerForm.appendChild(this.sendBtn);
    this.composerForm.addEventListener("submit", (e) => { e.preventDefault(); this._send(); });
    this.textarea.addEventListener("keydown", (e) => {
      // Enter sends; Shift+Enter inserts a newline. Ctrl/Cmd+Enter also
      // sends, kept for muscle memory. IME composition (e.g. CJK) typing
      // also fires keydown with Enter to commit a candidate — don't
      // hijack that.
      if (e.key !== "Enter" || e.isComposing) return;
      if (e.shiftKey) return;  // newline (default behavior)
      e.preventDefault();
      this._send();
    });

    this.host.appendChild(this.headerEl);
    this.host.appendChild(this.transcriptEl);
    this.host.appendChild(this.composerForm);
  }

  async _restoreHistory() {
    try {
      const { messages } = await api.getChatHistory(this.slug);
      this._messages = messages || [];
      this._renderTranscript();
    } catch {
      // Nonfatal — leave the existing transcript alone.
    }
  }

  _renderTranscript() {
    clear(this.transcriptEl);
    this._chipById.clear();
    for (const m of this._messages) {
      this.transcriptEl.appendChild(this._renderMessage(m));
    }
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
  }

  _renderMessage(m) {
    const cls = m.role === "user" ? "msg msg-user" : "msg msg-assistant";
    const wrap = el("div", { class: cls });
    for (const b of (m.blocks || [])) {
      if (b.type === "text") {
        // Server prepends a <view_state>...</view_state>\n block to user
        // messages so Claude can read playhead/mute/etc state. The system
        // prompt tells Claude not to mention it; strip it from the visible
        // transcript too. Keep persisting the prefixed text on the server
        // so chat history reflects exactly what Claude saw.
        wrap.appendChild(el("div", { class: "msg-text", text: _stripViewState(b.text) }));
      }
      else if (b.type === "tool_use") wrap.appendChild(this._renderToolChip(b));
      else if (b.type === "tool_result") this._applyToolResult(b);
    }
    return wrap;
  }

  // Build a clickable chip that expands to show input + result summary.
  _renderToolChip(block) {
    const name = (block.name || "").replace(/^mcp__musiq-tools__/, "");
    const id = block.id || "";
    const inputStr = _formatToolArgs(block.input ?? block.args);
    const chip = el("div", { class: "tool-chip pending", data: { id } });
    chip.dataset.toolName = name;
    chip.dataset.input = inputStr;
    const head = el("div", { class: "tool-chip-head" });
    const label = el("span", { class: "tool-chip-name", text: name });
    const args = el("span", { class: "tool-chip-args", text: `(${_compactArgs(inputStr)})` });
    const status = el("span", { class: "tool-chip-status", text: "…" });
    head.appendChild(label);
    head.appendChild(args);
    head.appendChild(status);
    chip.appendChild(head);
    const body = el("div", { class: "tool-chip-body", attrs: { hidden: "" } });
    body.appendChild(el("div", { class: "tool-chip-detail-label", text: "input" }));
    body.appendChild(el("pre", { class: "tool-chip-detail", text: inputStr }));
    chip.appendChild(body);
    chip.addEventListener("click", () => {
      const hidden = body.hasAttribute("hidden");
      if (hidden) body.removeAttribute("hidden"); else body.setAttribute("hidden", "");
      chip.classList.toggle("open", hidden);
    });
    if (id) this._chipById.set(id, chip);
    return chip;
  }

  _applyToolResult(block) {
    const chip = this._chipById.get(block.id);
    if (!chip) return;
    const ok = block.ok !== false;
    chip.classList.remove("pending");
    chip.classList.add(ok ? "ok" : "fail");
    const status = chip.querySelector(".tool-chip-status");
    if (status) status.textContent = ok ? "✓" : "✗";
    const body = chip.querySelector(".tool-chip-body");
    const existing = body.querySelector(".tool-chip-result");
    if (existing) existing.remove();
    const existingLabel = body.querySelector('[data-label="result"]');
    if (existingLabel) existingLabel.remove();
    const lab = el("div", { class: "tool-chip-detail-label", text: "result" });
    lab.dataset.label = "result";
    const pre = el("pre", { class: "tool-chip-detail tool-chip-result", text: block.summary || "(no output)" });
    body.appendChild(lab);
    body.appendChild(pre);
  }

  async _clear() {
    try {
      await api.clearChat(this.slug);
    } catch {
      // Even if the server can't clear, reset the UI — user clicked Clear.
    }
    this._messages = [];
    this._renderTranscript();
  }

  _prefillAndSend(text) {
    this.tabbedSidebar?.bar?.activate("claude");
    this.textarea.value = text;
    this._send();
  }

  async _stop() {
    // Hit the server first so the SDK actually interrupts. Then abort the
    // fetch — that's what stops the browser from receiving the trailing
    // ResultMessage event. Order matters: aborting first would race the
    // server's stream-close, sometimes leaving the actor still generating.
    this.stopBtn.setAttribute("disabled", "");
    try { await api.stopChat(this.slug); } catch { /* best-effort */ }
    if (this._abort) this._abort.abort();
  }

  async _send() {
    const text = this.textarea.value.trim();
    if (!text) return;
    if (this._inFlight) return;  // belt-and-suspenders against double-fire
    this.textarea.value = "";
    this._messages.push({ role: "user", blocks: [{ type: "text", text }] });
    this._renderTranscript();

    this._streamingAssistantBubble = el("div", { class: "msg msg-assistant streaming" });
    this._currentTextNode = null;
    this._pendingSpinner = el("div", { class: "claude-spinner", text: "thinking…" });
    this._streamingAssistantBubble.appendChild(this._pendingSpinner);
    this.transcriptEl.appendChild(this._streamingAssistantBubble);
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;

    this._inFlight = true;
    this.sendBtn.disabled = true;
    this.stopBtn.removeAttribute("disabled");
    this.stopBtn.classList.add("active");
    this._abort = new AbortController();
    this._setStatus("sending…");
    try {
      await this._streamTurn(text);
    } catch (e) {
      if (e?.name !== "AbortError") {
        this._appendErrorBubble(e?.message || String(e));
        this._setStatus("error");
      } else {
        this._setStatus("stopped");
      }
    } finally {
      this._inFlight = false;
      this.sendBtn.disabled = false;
      this.stopBtn.setAttribute("disabled", "");
      this.stopBtn.classList.remove("active");
      this._abort = null;
      this._dismissSpinner();
      this._streamingAssistantBubble?.classList.remove("streaming");
      this._restoreHistory();
      // Reset status to "ready" after a brief beat so the user sees terminal state.
      setTimeout(() => this._setStatus("ready"), 800);
    }
  }

  _setStatus(text) {
    if (this.statusEl) this.statusEl.textContent = text;
  }

  _dismissSpinner() {
    if (this._pendingSpinner) {
      this._pendingSpinner.remove();
      this._pendingSpinner = null;
    }
  }

  async _streamTurn(text) {
    const view_state = this._buildViewState();
    const t0 = performance.now();
    let evCount = 0;
    let textChars = 0;
    let toolCount = 0;
    console.info("[claude] turn START", { slug: this.slug, text, view_state });
    const r = await fetch(api.chatTurnUrl(this.slug), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, view_state }),
      signal: this._abort.signal,
    });
    if (!r.ok) {
      // Try to parse FastAPI's {detail: ...} body for a friendlier message.
      let detail = `HTTP ${r.status}`;
      try {
        const body = await r.json();
        if (body?.detail) detail = body.detail;
      } catch { /* not JSON */ }
      if (r.status === 409) {
        detail = "Chat is still processing the previous turn — wait for it to finish, then try again.";
      }
      console.warn("[claude] turn HTTP error", r.status, detail);
      throw new Error(detail);
    }
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
        if (line) {
          try {
            const ev = JSON.parse(line);
            evCount++;
            if (ev.type === "text") textChars += (ev.delta || "").length;
            else if (ev.type === "tool_use") toolCount++;
            console.debug("[claude] ev", ev);
            this._handleEvent(ev);
          }
          catch (parseErr) { console.warn("chat: malformed NDJSON line", line, parseErr); }
        }
      }
    }
    const ms = (performance.now() - t0).toFixed(0);
    console.info(`[claude] turn END (${ms}ms): events=${evCount} text-chars=${textChars} tools=${toolCount}`);
    if (textChars === 0 && toolCount === 0) {
      // Empty assistant turn — surface so the bubble isn't just blank.
      this._appendPlaceholder("(no response — see browser console / webui.log)");
    }
  }

  _appendPlaceholder(msg) {
    if (!this._streamingAssistantBubble) return;
    this._currentTextNode = null;
    const note = el("div", { class: "msg-text msg-empty", text: msg });
    note.style.opacity = "0.6";
    note.style.fontStyle = "italic";
    this._streamingAssistantBubble.appendChild(note);
  }

  _handleEvent(ev) {
    // Any meaningful event ends the pre-first-byte "thinking…" spinner.
    if (ev.type === "text" || ev.type === "tool_use" || ev.type === "tool_result") {
      this._dismissSpinner();
    }
    switch (ev.type) {
      case "text":
        this._setStatus("writing reply…");
        if (this._streamingAssistantBubble) {
          if (!this._currentTextNode) {
            this._currentTextNode = el("div", { class: "msg-text" });
            this._streamingAssistantBubble.appendChild(this._currentTextNode);
          }
          // appendChild a TextNode rather than `+=` to avoid the O(n²) cost
          // of re-serializing/re-parsing the node's contents on every delta.
          this._currentTextNode.appendChild(document.createTextNode(ev.delta));
          this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
        }
        break;
      case "tool_use": {
        const shortName = (ev.name || "").replace(/^mcp__musiq-tools__/, "");
        this._setStatus(`tool: ${shortName}…`);
        if (this._streamingAssistantBubble) {
          // Close the current text run *before* appending the chip so the
          // next text delta starts a fresh node positioned after the chip.
          this._currentTextNode = null;
          this._streamingAssistantBubble.appendChild(this._renderToolChip(ev));
        }
        break;
      }
      case "tool_result":
        this._applyToolResult(ev);
        break;
      case "ui_action":
        this._dispatchUiAction(ev);
        break;
      case "done":
        this._tokens = ev.tokens;
        this._renderTokens();
        this._setStatus("done");
        break;
      case "error":
        this._appendErrorBubble(`${ev.kind || "error"}: ${ev.message}`);
        this._setStatus(`error: ${ev.kind || "?"}`);
        break;
      case "auth_required":
        this._renderAuthRequired();
        this._setStatus("auth required");
        break;
    }
  }

  _dispatchUiAction(ev) {
    const { action, args = {} } = ev;
    switch (action) {
      case "seek_to":           this.engine?.seek(args.time_sec); break;
      case "set_loop_region":   this.viewState?.setLoop(args.start_sec, args.end_sec); break;
      case "set_stem_state":
        if (args.mute   != null) this.engine?.setStemMute(args.stem, args.mute);
        if (args.solo   != null) this.engine?.setStemSolo(args.stem, args.solo);
        if (args.volume != null) this.engine?.setStemVolume(args.stem, args.volume);
        break;
      case "highlight_stem":    if (this.viewState) this.viewState.highlightedStem = args.stem; break;
      case "open_midi":         fetch(`/api/tools/open-midi/${encodeURIComponent(this.slug)}/${encodeURIComponent(args.stem)}`, { method: "POST" }); break;
      case "switch_tab":        this.tabbedSidebar?.bar?.activate(args.tab); break;
      case "highlight_lyric_line": this.lyricsTab?.highlightLineByIndex?.(args.index); break;
      case "reload_lyrics":     this.lyricsTab?._lazyLoad?.(); break;
      default: console.warn("unknown ui_action", action);
    }
  }

  // Enriched view_state — derived entirely from data the client already has
  // loaded. Server-side tools (get_chord_at, etc.) work from the same
  // sources, but having these values right in the prompt prefix means
  // "what's playing now?" answers without a tool round-trip.
  _buildViewState() {
    const playhead = Number(this.engine?.currentTime ?? 0);
    const out = {
      playhead_sec: playhead,
      highlighted_stem: this.viewState?.highlightedStem,
      mutes: this.engine?.muted,
      solos: this.engine?.soloed,
      loop_start_sec: this.viewState?.loopStart,
      loop_end_sec: this.viewState?.loopEnd,
      active_tab: this.tabbedSidebar?.bar?.current(),
    };
    const td = this.trackData;
    if (td) {
      const chord = _findChordAt(td.chords, playhead);
      if (chord) {
        out.current_chord = {
          label: chord.label, roman: chord.roman, function: chord.fn,
          start_sec: chord.start, end_sec: chord.end,
        };
      }
      const bar = _findBarAt(td.downbeats, playhead, td.meta?.timeSig);
      if (bar) out.current_bar = bar;  // {bar_number, beat, beat_count}
    }
    const lt = this.lyricsTab;
    if (lt?.data?.has_sync && lt.activeIndex >= 0 && lt.data.lines[lt.activeIndex]) {
      const line = lt.data.lines[lt.activeIndex];
      out.current_lyric_line = { index: lt.activeIndex, text: line.text, time_sec: line.time_sec };
    }
    return out;
  }

  _renderTokens() {
    if (!this._tokens) { this.tokensEl.textContent = ""; return; }
    const { input = 0, output = 0, cache_read = 0 } = this._tokens;
    this.tokensEl.textContent = `cache ${cache_read} · in ${input} · out ${output}`;
  }

  _appendErrorBubble(msg) {
    this.transcriptEl.appendChild(el("div", { class: "msg msg-error", text: msg }));
    this.transcriptEl.scrollTop = this.transcriptEl.scrollHeight;
  }

  _renderAuthRequired() {
    clear(this.transcriptEl);
    const card = el("div", { class: "auth-card" });
    card.appendChild(el("div", { class: "auth-title", text: "Claude is signed out." }));
    card.appendChild(el("div", { class: "auth-body", text: "Run `claude /login` in a terminal, then click Retry." }));
    const retry = el("button", {
      class: "btn", text: "Retry", attrs: { type: "button" },
      onClick: () => this._restoreHistory(),
    });
    card.appendChild(retry);
    this.transcriptEl.appendChild(card);
  }
}

// Strip a leading <view_state>{...}</view_state> block (followed by an
// optional newline) from a message text. The block is server-side context
// for Claude — see chat.py build_user_message — and shouldn't appear in
// the user-facing transcript.
function _stripViewState(text) {
  if (!text) return text;
  return text.replace(/^<view_state>[\s\S]*?<\/view_state>\n?/, "");
}

function _findChordAt(chords, t) {
  if (!chords?.length) return null;
  // chords is small (a few hundred at most) and unsorted-safe: linear is fine
  // and avoids the edge case of zero-width "N" intervals tripping a bisector.
  for (const c of chords) {
    if (c.start <= t && t < c.end) return c;
  }
  return null;
}

function _findBarAt(downbeats, t, timeSig) {
  if (!downbeats?.length || t < downbeats[0]) return null;
  // Binary search for the largest downbeat <= t.
  let lo = 0, hi = downbeats.length - 1, idx = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (downbeats[mid] <= t) { idx = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  const barStart = downbeats[idx];
  const barEnd = downbeats[idx + 1] ?? (barStart + (downbeats[idx] - (downbeats[idx - 1] ?? barStart)));
  const beatCount = _parseBeatCount(timeSig);
  const beatFrac = (t - barStart) / Math.max(1e-6, barEnd - barStart);
  const beat = Math.min(beatCount, 1 + Math.floor(beatFrac * beatCount));
  return { bar_number: idx + 1, beat, beat_count: beatCount, bar_start_sec: barStart, bar_end_sec: barEnd };
}

function _parseBeatCount(sig) {
  if (typeof sig !== "string") return 4;
  const m = sig.match(/^(\d+)\s*\/\s*\d+$/);
  return m ? Number(m[1]) : 4;
}

function _formatToolArgs(input) {
  try { return JSON.stringify(input ?? {}, null, 2); } catch { return String(input); }
}

// One-line preview for the chip head — strip the outer braces, collapse
// whitespace, truncate. The full pretty-printed input is in the expanded body.
function _compactArgs(jsonStr) {
  const s = (jsonStr || "")
    .replace(/^\{|\}$/g, "")
    .replace(/[\n\s]+/g, " ")
    .trim();
  return s.length > 60 ? s.slice(0, 57) + "…" : s;
}
