# webui Polish Fixes (Phase 2) Implementation Plan

> **Status: SHIPPED 2026-05-02** — all 12 area-scoped fix tasks landed as 13 commits between `8cf4bb3` (T1 backend) and `dfc110a` (T12 badge relocation). Per-task commit map: T1 `8cf4bb3` + follow-up `956010d`, T2 `b885be5`, T3 `79f5401`, T4 `8b4f11d`, T5 `94422de`, T6 `960f7e7`, T7 `fc7eacd`, T8 `a3cf432`, T9 `ff87b7b`, T10 `cec26a6`, T11 `6144877`, T12 `dfc110a`. Subagent-driven execution; one implementer per task with inline Playwright spec-compliance checks instead of full reviewer-subagent loops. **Lessons recorded in memory `webui_polish_session_state.md`.** **Plan body retained as historical narrative.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the 33 audit findings the user triaged from `docs/superpowers/notes/2026-05-02-webui-audit.md` (sections A-J) as a sequence of cohesive, area-scoped fix commits, each with before/after screenshot evidence.

**Architecture:** Twelve tasks, each producing exactly one commit. Tasks are batched by **area** (display title, picker, sidebar, now-card, hover, mute/solo, modals, reanalyze, toast, suppressed stems, narrow viewport, auto-scroll badge) rather than by severity, so each commit is a coherent reviewable visual unit. Most tasks are CSS-heavy with small JS where DOM markup or behavior changes. Two tasks (Task 8 reanalyze modal, Task 9 error toast) involve real component work, not just CSS. Each task ends with a Playwright screenshot saved to `tests/screenshots/polish-after/` and a regression run if functional code changed.

**Tech Stack:** Vanilla JS modules + hand-authored CSS (no framework). Server: FastAPI on `127.0.0.1:8765` (already running, managed by `webui/webui.ps1`). Browser automation: Playwright MCP tools. Tests: `webui/.venv\Scripts\python -m pytest`, `node --test webui/tests-js/*.test.js`, `cd webui/tests-e2e && npm test`.

**Spec:** `docs/superpowers/specs/2026-05-02-webui-polish-design.md`
**Audit:** `docs/superpowers/notes/2026-05-02-webui-audit.md`
**Phase 0+1 plan:** `docs/superpowers/plans/2026-05-02-webui-polish.md`

**JS conventions:** This codebase constructs DOM via `document.createElement` + `textContent` / `appendChild`, NOT `innerHTML`. All JS in this plan follows that convention to avoid XSS hazards even though current consumers are first-party data.

---

## File map

**Create:**
- `tests/screenshots/polish-after/` (directory + per-task PNGs)

**Modify (per task — see each task for which files):**
- `webui/webui/tracks.py` — display-title fallback derivation (Task 1)
- `webui/static/css/track.css` — most CSS edits across tasks
- `webui/static/css/tokens.css` — adding 1-2 new tokens if audit calls for them
- `webui/static/js/ui/track-picker.js` — picker chrome (Task 2)
- `webui/static/js/ui/sidebar.js` — sidebar IA + now-card (Tasks 3, 4)
- `webui/static/js/ui/topbar.js` — topbar overflow handling (Task 11)
- `webui/static/js/ui/menus.js` — reanalyze confirm replacement (Task 8)
- `webui/static/js/ui/reanalyze.js` — confirmation flow (Task 8)
- `webui/static/js/render/pianoroll.js` — auto-scroll badge relocation (Task 12), tooltip notation (Task 5 step 6)

**Out of scope:**
- The 4 deferred audit items (C2 playhead color, G3 Tools modal grouping, G4 shortcuts duplication, I1 suppressed-stem opacity) stay in the audit doc's `## Deferred` section.
- Any changes to the canvas piano-roll renderer beyond auto-scroll badge position and tooltip notation.

---

# Task 1: Display title fallback (audit A1, B1)

Strip the YouTube ID suffix and replace underscores with spaces when no `display_title` is populated. Both the picker rows and topbar inherit from the same data source so this fixes A1 and B1 in one place.

**Files:**
- Modify: `webui/webui/tracks.py`
- Test: existing `webui/tests/test_tracks.py` (add a case)

- [ ] **Step 1: Read the current title-derivation logic**

`Read` the entire `webui/webui/tracks.py` and locate where each track's title is constructed. The picker and topbar both consume the API output, so the field name returned to the frontend (likely `title` or `display_title`) is the single fix point. Confirm via `Grep`:

```
Grep pattern: title|display
File: webui/webui/tracks.py
Output mode: content with line numbers
```

If a `display_title` field exists already and is just empty for some slugs, the fix is to populate it from the slug. If the field doesn't exist, add one.

- [ ] **Step 2: Write a failing test**

Add to `webui/tests/test_tracks.py`:

```python
def test_display_title_fallback_strips_youtube_id_and_underscores():
    from webui.tracks import derive_display_title
    assert derive_display_title("gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg") == "Gorillaz Silent Running Ft Adeleye Omotayo Official Video"
    assert derive_display_title("simple_track_aBcDeFgHiJk") == "Simple Track"
    # if no 11-char trailing token, return as-is with underscores → spaces
    assert derive_display_title("no_id_here") == "No Id Here"
```

Run: `cd webui && .venv\Scripts\python -m pytest webui/tests/test_tracks.py::test_display_title_fallback_strips_youtube_id_and_underscores -v`
Expected: FAIL with `ImportError` (function doesn't exist yet).

- [ ] **Step 3: Implement `derive_display_title`**

Add to `webui/webui/tracks.py` (top-level function, before any class/route that uses it):

```python
import re

_YT_ID_SUFFIX = re.compile(r"_[A-Za-z0-9_-]{11}$")

def derive_display_title(slug: str) -> str:
    """Fallback display title from a slug.
    Strips a trailing 11-char YouTube ID if present, then replaces
    underscores with spaces and title-cases each word."""
    base = _YT_ID_SUFFIX.sub("", slug)
    return base.replace("_", " ").title()
```

- [ ] **Step 4: Verify the unit test passes**

Run: `cd webui && .venv\Scripts\python -m pytest webui/tests/test_tracks.py::test_display_title_fallback_strips_youtube_id_and_underscores -v`
Expected: PASS.

- [ ] **Step 5: Wire the fallback into the API**

Find the function/method that builds each track's API payload (likely the `/api/tracks` route or a `Track.to_dict()` equivalent). Add the fallback so the returned `title` (or `display_title`) is `track.display_title or derive_display_title(track.slug)`. Use the actual existing field names you found in Step 1.

- [ ] **Step 6: Verify in browser via Playwright**

`mcp__plugin_playwright_playwright__browser_navigate` to `http://127.0.0.1:8765`. Confirm the topbar shows `Gorillaz Silent Running Ft Adeleye Omotayo Official Video` instead of the raw slug. Open the picker, confirm rows display human titles. Take screenshot to `tests/screenshots/polish-after/T1-display-title.png`.

- [ ] **Step 7: Run regressions and commit**

```powershell
cd "<PROJECT_PATH>/webui"
.\.venv\Scripts\python -m pytest
```

Expected: all pass.

```powershell
cd "<PROJECT_PATH>"
git add webui/webui/tracks.py webui/tests/test_tracks.py tests/screenshots/polish-after/T1-display-title.png
git commit -m @'
fix(webui): display-title fallback strips YouTube ID and underscores (A1, B1)

derive_display_title() in webui/tracks.py applies the fallback when a
track has no upstream display_title. Topbar and picker rows both inherit
the API field, so one fix covers both surfaces (audit A1 + B1, same root
cause).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 2: Picker chrome polish (audit A2, A3, F1, F2, F3)

Demote the orange "sections deferred" warn color to neutral, add a panel header, add a focus ring to search input, raise footer contrast, and tighten the filter pill grouping.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/track-picker.js`

- [ ] **Step 1: Capture before-state screenshot**

`browser_navigate` to webui, click topbar title to open picker. `browser_take_screenshot` to `tests/screenshots/polish-after/T2-picker-before.png`.

- [ ] **Step 2: Demote `.tp-row .nm .warn` color (A2)**

In `webui/static/css/track.css`, find `.tp-row .nm .warn` and change `color` from `#ff8866` to `var(--fg-3)` and add `font-style: italic` to differentiate from regular subtext.

```
old: .tp-row .nm .warn { color: #ff8866; font-size: 9px; display: block; }
new: .tp-row .nm .warn { color: var(--fg-3); font-style: italic; font-size: 9px; display: block; }
```

- [ ] **Step 3: Add picker panel header (A3)**

Locate where `.tp-panel` is constructed in `webui/static/js/ui/track-picker.js`. Above the `.tp-search` element, insert a header row using DOM-construction (no innerHTML):

```js
function buildHeader(trackCount) {
  const header = document.createElement("div");
  header.className = "tp-header";
  const label = document.createTextNode("LIBRARY · ");
  const count = document.createElement("span");
  count.className = "tp-count";
  count.textContent = String(trackCount);
  const trail = document.createTextNode(" TRACKS");
  header.appendChild(label);
  header.appendChild(count);
  header.appendChild(trail);
  return header;
}

// Where the panel is built:
const header = buildHeader(tracks.length);
panel.insertBefore(header, panel.firstChild);
```

In `track.css`, add:

```css
.tp-header {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--t-micro);
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: var(--ls-caps);
  background: var(--bg-0);
  border-bottom: 1px solid var(--bg-3);
}
.tp-header .tp-count { color: var(--fg-1); font-family: var(--font-mono); }
```

- [ ] **Step 4: Add focus ring to picker search input (F1)**

Edit `.tp-search input:focus` rule in `track.css`:

```
old: .tp-search input:focus { border-color: #6cf; }
new: .tp-search input:focus { border-color: #6cf; outline: 2px solid rgba(102, 204, 255, 0.35); outline-offset: 1px; }
```

- [ ] **Step 5: Raise footer contrast (F2)**

Edit `.tp-footer` rule in `track.css`:

```
old: .tp-footer { padding: 6px 12px; font-size: 10px; color: var(--fg-3); background: var(--bg-0); border-top: 1px solid #1f1f24; display: flex; justify-content: space-between; }
new: .tp-footer { padding: 6px 12px; font-size: var(--t-micro); color: var(--fg-2); background: var(--bg-1); border-top: 1px solid var(--bg-3); display: flex; justify-content: space-between; }
```

- [ ] **Step 6: Group filter pills with bounding box (F3)**

Edit `.tp-controls .lbl` and `.tp-controls .pill` in `track.css`:

```
old: .tp-controls .lbl { color: var(--fg-3); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; margin-right: 2px; }
new: .tp-controls .lbl { color: var(--fg-3); text-transform: uppercase; letter-spacing: var(--ls-caps); font-weight: 600; margin-right: var(--sp-1); padding: 3px 0; border-right: 1px solid var(--bg-3); padding-right: var(--sp-2); }
```

```
old: .tp-controls .pill { background: var(--bg-2); padding: 3px 8px; border-radius: 10px; color: var(--fg-1); cursor: pointer; display: flex; align-items: center; gap: 4px; }
new: .tp-controls .pill { background: var(--bg-3); padding: 3px 8px; border-radius: 10px; color: var(--fg-1); cursor: pointer; display: flex; align-items: center; gap: var(--sp-1); }
```

- [ ] **Step 7: Reload + after-state screenshot**

`browser_evaluate` `() => location.reload()`. Open picker again. `browser_take_screenshot` to `tests/screenshots/polish-after/T2-picker-after.png`. Visually compare to the before-state.

- [ ] **Step 8: Run regressions and commit**

```powershell
cd "<PROJECT_PATH>"
node --test webui/tests-js/*.test.js
```

Expected: pass.

```powershell
git add webui/static/css/track.css webui/static/js/ui/track-picker.js tests/screenshots/polish-after/T2-picker-before.png tests/screenshots/polish-after/T2-picker-after.png
git commit -m @'
feat(webui): picker chrome polish (A2, A3, F1, F2, F3)

- Demote .warn subtitle color to fg-3 italic (A2)
- Add panel header "LIBRARY · N TRACKS" in micro caps (A3)
- Add focus ring outline to search input (F1)
- Raise footer contrast: bg-1 surface, fg-2 text (F2)
- Group filter pills under separated label (F3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 3: Now-card refinements (audit B2, B3, C1)

Now-card idle state shows track-level context instead of "(no chord)"; PLAYHEAD label dropped; chord display gets typographic hierarchy.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/sidebar.js`

- [ ] **Step 1: Capture before-state**

Reload webui, paused at t=0. `browser_take_screenshot` of `#viewer-side` to `tests/screenshots/polish-after/T3-now-card-idle-before.png`. Then press Space, wait 8 seconds, `browser_take_screenshot` of `#viewer-side` to `T3-now-card-playing-before.png`. Press Space to pause again.

- [ ] **Step 2: Idle-state copy and content (B2)**

Find the now-card render function in `webui/static/js/ui/sidebar.js`. When `currentChord === null` (idle), replace the placeholder block with track-level context. Use existing element refs and `textContent` (no `innerHTML`):

```js
// Pseudocode — adapt to actual element refs in the file:
function renderNowCardIdle(refs, trackData) {
  refs.rn.textContent = trackData.scale.tonic_pc_name || "—";
  refs.rn.style.fontSize = "var(--t-prose)";
  refs.rn.style.color = "var(--fg-1)";
  refs.lab.textContent = trackData.scale.full_name || "";

  // Build the meta strip with createElement:
  refs.meta.replaceChildren(); // clear
  if (trackData.vocal_range_low && trackData.vocal_range_high) {
    const tag = document.createElement("span");
    tag.className = "tag fn-tonic";
    tag.textContent = `vocal range ${trackData.vocal_range_low}–${trackData.vocal_range_high}`;
    refs.meta.appendChild(tag);
  }
}

function renderNowCardPlaying(refs, chord) {
  refs.rn.style.fontSize = ""; // restore var(--t-display)/36px from CSS
  refs.rn.style.color = "";
  // ... existing chord-rendering logic stays
}
```

Confirm field names by reading the actual `trackData` shape (likely from `webui/static/js/data/track-data.js`).

- [ ] **Step 3: Drop the "PLAYHEAD" label (B3)**

In the same now-card render path, find the `.time-lbl` element. Set its text to empty:

```js
refs.timeLbl.textContent = ""; // was "PLAYHEAD"
```

In `track.css`, soften the rule so an empty label collapses cleanly:

```
old: .now-card .now-time .time-lbl { font-size: 9px; color: var(--fg-3); text-transform: uppercase; letter-spacing: .06em; margin-top: 4px; }
new: .now-card .now-time .time-lbl { font-size: 9px; color: var(--fg-3); text-transform: uppercase; letter-spacing: var(--ls-caps); margin-top: 4px; }
.now-card .now-time .time-lbl:empty { display: none; }
```

- [ ] **Step 4: Chord typography hierarchy (C1)**

Restructure the now-card playing state to a clear three-tier hierarchy:
1. Roman numeral (display, serif) — biggest
2. Chord name (prose, mono) — secondary
3. Function tag (micro, label-style pill) — accent

In `webui/static/js/ui/sidebar.js`, change the chord-name format from `C:min` to `Cm` (collapse the colon to standard chord shorthand). Use a small helper:

```js
function formatChordShorthand(name) {
  return name
    .replace(":maj", "")
    .replace(":min", "m")
    .replace(":dim", "°")
    .replace(":aug", "+");
}

// At the chord-name render site:
refs.lab.textContent = formatChordShorthand(chord.name);
```

In `track.css`, give the function tags a less Roman-numeral-like treatment:

```
old: .tag.rn { background: #3a2a1a; color: var(--accent); font-family: ui-serif, Georgia, serif; padding: 4px 9px; }
new: .tag.rn { background: #3a2a1a; color: var(--accent); font-family: var(--font-numeral); padding: 4px 9px; }
```

For the function tags `.tag.fn-tonic` etc., reduce visual weight — outlined micro caps:

```
old: .tag.fn-tonic { background: var(--fn-tonic-bg); color: var(--fn-tonic-fg); }
new: .tag.fn-tonic { background: transparent; color: var(--fn-tonic-fg); border: 1px solid var(--fn-tonic-fg); padding: 2px 6px; font-size: 9px; letter-spacing: var(--ls-caps); }
```

Apply the same `transparent + 1px border + smaller-caps` treatment to `.tag.fn-dominant`, `.tag.fn-predominant`, `.tag.fn-modal_interchange`. The Roman-numeral pill stays solid; function pills become outlined for clear separation.

- [ ] **Step 5: After-state screenshots**

Reload. Idle-state: screenshot `#viewer-side` to `T3-now-card-idle-after.png`. Press Space, wait 8s, screenshot to `T3-now-card-playing-after.png`. Pause.

- [ ] **Step 6: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/css/track.css webui/static/js/ui/sidebar.js tests/screenshots/polish-after/T3-now-card-*.png
git commit -m @'
feat(webui): now-card refinements — idle context, drop PLAYHEAD label, chord hierarchy (B2, B3, C1)

- Idle now-card shows tonic + scale + vocal range instead of "(no chord)" (B2)
- "PLAYHEAD" caption removed; hidden when empty (B3)
- Chord name format: ":min" → "m", ":dim" → "°", colons collapsed (C1)
- Function tags switched from solid pills to outlined micro-caps so the
  Roman numeral remains the primary visual anchor (C1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 4: Sidebar IA (audit B4, B5, B6, B7)

Move STEMS-section affordance hint out of the heading, remove the redundant SHORTCUTS sidebar section, add unit labels to stem note counts, switch divider to `--bg-3` token.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/sidebar.js`
- Possibly modify: `webui/static/js/ui/shortcuts.js`

- [ ] **Step 1: Capture before screenshot**

Reload, screenshot `#viewer-side` to `T4-sidebar-before.png`.

- [ ] **Step 2: STEMS heading cleanup (B4)**

In `webui/static/js/ui/sidebar.js`, find the line that builds the STEMS heading. Remove the `· CLICK TO HIGHLIGHT` suffix from the h4 text. Add a tooltip on the section instead:

```js
// before:
h4.textContent = "STEMS · CLICK TO HIGHLIGHT";

// after:
h4.textContent = "STEMS";
sectionEl.title = "Click a row to highlight that stem on the canvas";
```

Apply the same pattern to other h4s if they embed affordance hints.

- [ ] **Step 3: Remove SHORTCUTS sidebar section (B5)**

Find where the SHORTCUTS section is constructed in `sidebar.js`. Remove the entire section block (the `.side-section` wrapping the shortcuts list). Users still get the shortcuts modal via `?` (covered in Task 7's hint copy fix).

If the section build is in a separate file (`webui/static/js/ui/shortcuts.js`), remove the call-site that injects it into the sidebar; leave the modal-only export intact.

- [ ] **Step 4: Stem note unit label (B6)**

In the stem-row builder, add the unit suffix as a separate child element with `createElement` + `textContent`:

```js
// where the count cell is built:
function buildCountCell(stem) {
  const cell = document.createElement("div");
  cell.className = "count";
  cell.textContent = String(stem.count);
  const unit = document.createElement("span");
  unit.className = "count-unit";
  unit.textContent = stem.name === "drums" ? " hits" : " notes";
  cell.appendChild(unit);
  return cell;
}
```

Adapt this if the existing build pattern differs; the key is to use `createElement` + `textContent`, never `innerHTML`.

In `track.css`, style the unit suffix small and dim:

```css
.track-row .count-unit { color: var(--fg-3); font-size: 9px; font-family: var(--font-sans); margin-left: 2px; }
```

- [ ] **Step 5: Sidebar divider color (B7)**

In `track.css`, find:
```
.side-section { padding: 12px 14px; border-bottom: 1px solid #1f1f24; }
```
Change to:
```
.side-section { padding: var(--sp-3) 14px; border-bottom: 1px solid var(--bg-3); }
```

(Padding-left of 14px stays a literal — 14 is not a token, and the spec said only swap when ALL values match.)

- [ ] **Step 6: After screenshot**

Reload, screenshot `T4-sidebar-after.png`. Visually compare.

- [ ] **Step 7: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
cd webui/tests-e2e && npm test
```

(Note: e2e may surface pre-existing slug-match failure unrelated to this work — that's the same failure documented in Phase 0.)

```powershell
git add webui/static/css/track.css webui/static/js/ui/sidebar.js webui/static/js/ui/shortcuts.js tests/screenshots/polish-after/T4-sidebar-*.png
git commit -m @'
refactor(webui): sidebar IA — affordance hints out of headings, drop redundant shortcuts section, stem-count units (B4, B5, B6, B7)

- h4 headings no longer embed affordance hints; section gets title attr (B4)
- SHORTCUTS sidebar section removed; modal remains the canonical reference (B5)
- Stem counts show "N notes" / "N hits" suffix (B6)
- Section dividers use --bg-3 token instead of hardcoded #1f1f24 (B7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 5: Hover/focus coverage (audit D1, D2, D3, D4, D5)

Make hover states more distinct, add transitions, fill focus gaps, fix tooltip notation.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/render/pianoroll.js` (D5 only)

- [ ] **Step 1: Capture before screenshots**

Reload. Hover over the Vocals row in sidebar; screenshot `T5-hover-row-before.png`. Hover over Tools menu item; screenshot `T5-hover-tools-before.png`. Hover over canvas at a note position; screenshot `T5-hover-canvas-before.png`.

- [ ] **Step 2: Track-row hover (D1)**

Edit `.track-row:hover` in `track.css`:

```
old: .track-row:hover { background: #1c1c22; }
new: .track-row:hover { background: var(--bg-3); transition: background 0.12s; }
```

- [ ] **Step 3: Play button hover (D2)**

Add `:hover` rule for `.play-btn`:

```css
#transport .play-btn { transition: filter 0.12s, background 0.12s; }
#transport .play-btn:hover { filter: brightness(0.9); }
```

Insert near the `.play-btn` definition in `track.css`.

- [ ] **Step 4: Topbar menu transition (D3)**

Edit `#topbar .menu .item` to add a transition. Find the existing rule and append `transition: background 0.12s, color 0.12s`:

```
old: #topbar .menu .item { padding: 5px 10px; border-radius: 4px; font-size: var(--t-body); color: var(--fg-1); cursor: pointer; display: flex; align-items: center; gap: 5px; }
new: #topbar .menu .item { padding: 5px 10px; border-radius: 4px; font-size: var(--t-body); color: var(--fg-1); cursor: pointer; display: flex; align-items: center; gap: 5px; transition: background 0.12s, color 0.12s; }
```

- [ ] **Step 5: Zoom button hover (D4)**

Add a hover rule for the zoom group buttons:

```css
#transport .zoomgrp button { transition: background 0.12s, color 0.12s; }
#transport .zoomgrp button:hover { background: var(--bg-3); color: white; }
```

- [ ] **Step 6: Canvas tooltip notation (D5)**

In `webui/static/js/render/pianoroll.js`, find the tooltip text-build (look for usages of the hovered MIDI note → name conversion). The tooltip currently uses sharps regardless of key context. Make the function key-aware: when the track key has flat accidentals, prefer flats; otherwise sharps.

```js
const FLAT_KEYS = new Set(["F", "Bb", "Eb", "Ab", "Db", "Gb"]);
function midiToContextualName(midi, keyTonic) {
  const useFlats = FLAT_KEYS.has(keyTonic) || (typeof keyTonic === "string" && keyTonic.endsWith("b"));
  const sharpNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const flatNames  = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
  const names = useFlats ? flatNames : sharpNames;
  const oct = Math.floor(midi / 12) - 1;
  return names[midi % 12] + oct;
}
```

Then in the tooltip-building call site, pass the current track's key tonic in. Confirm the F-natural-minor Gorillaz track now shows `Eb4` instead of `D#4` for that pitch.

- [ ] **Step 7: After screenshots**

Reload. Hover each element again; screenshot `T5-hover-row-after.png`, `T5-hover-tools-after.png`, `T5-hover-canvas-after.png`. Verify the canvas tooltip now uses key-appropriate accidentals.

- [ ] **Step 8: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/css/track.css webui/static/js/render/pianoroll.js tests/screenshots/polish-after/T5-hover-*.png
git commit -m @'
fix(webui): hover/focus coverage and tooltip key-context (D1, D2, D3, D4, D5)

- Track row hover bumped to --bg-3 with 0.12s transition (D1)
- Play button gets brightness hover (D2)
- Topbar menu items transition symmetrically on hover (D3)
- Zoom +/− buttons get explicit hover bg (D4)
- Canvas pitch tooltip uses flats for flat-side keys (D5)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 6: Mute/solo button polish (audit E1, E2)

Recolor the active states so M and S read as opposite intents at a glance, and bump button size for easier targeting.

**Files:**
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Before screenshot**

Click M on Vocals row, S on Bass row. Screenshot `T6-mute-solo-before.png`. Click each off again to restore.

- [ ] **Step 2: M (mute) — desaturate to "off" feel**

Edit `.track-row .btn.m.on`:

```
old: .track-row .btn.m.on { background: #4a1a1a; color: #ff8a8a; }
new: .track-row .btn.m.on { background: var(--bg-3); color: var(--fg-3); text-decoration: line-through; }
```

The line-through reinforces "this stem is silenced." The desaturated grey reads as "off" rather than competing with the warm S accent.

- [ ] **Step 3: S (solo) — keep amber, raise weight**

Edit `.track-row .btn.s.on`:

```
old: .track-row .btn.s.on { background: #4a3a1a; color: #ffb86b; }
new: .track-row .btn.s.on { background: var(--accent); color: var(--bg-0); }
```

Inverting (amber background, dark text) makes solo read as "this stem is the focus" — like a highlight.

- [ ] **Step 4: Bump button size (E2)**

Edit `.track-row .btn`:

```
old: .track-row .btn { width: 18px; height: 18px; border-radius: 3px; background: var(--bg-2); color: var(--fg-2); font-size: 10px; display: flex; align-items: center; justify-content: center; font-weight: 700; cursor: pointer; }
new: .track-row .btn { width: 22px; height: 22px; border-radius: 4px; background: var(--bg-2); color: var(--fg-2); font-size: var(--t-body); display: flex; align-items: center; justify-content: center; font-weight: 700; cursor: pointer; transition: background 0.12s, color 0.12s; }
```

The track-row grid template uses fixed columns; if the row layout breaks, adjust `.track-row` `grid-template-columns` to widen the M/S group cell from `42px` to `52px`. Apply the same change to `.track-row.highlighted`.

- [ ] **Step 5: After screenshot**

Click M Vocals + S Bass; screenshot `T6-mute-solo-after.png`. Restore.

- [ ] **Step 6: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/css/track.css tests/screenshots/polish-after/T6-mute-solo-*.png
git commit -m @'
feat(webui): mute/solo visual disambiguation and larger targets (E1, E2)

- M active: desaturated --bg-3/--fg-3 + line-through (off feel)
- S active: --accent inverted (amber bg, dark fg) — clear "focus" feel
- Buttons 18px → 22px, font 10px → 11px (--t-body)
- Track-row grid widened to fit, transitions added

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 7: Modal close buttons + shortcut hint copy (audit G2, G5, G6)

Add explicit close (×) affordances to the three modals and fix the ambiguous `?` shortcut hint in the sidebar.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/menus.js` (or wherever modals are built)
- Modify: `webui/static/js/ui/shortcuts.js`

- [ ] **Step 1: Locate modal markup**

Use `Grep` to find the modal-build pattern:

```
Grep pattern: class=.modal|className.*modal|backdrop
File: webui/static/js/
Output mode: files with matches
```

Confirm in which file (`menus.js`?) the Settings, Tools, Shortcuts modals' DOM is constructed. Most likely a shared helper.

- [ ] **Step 2: Add `.modal-close` element to each modal header**

In the modal-build helper(s), insert a close button using `createElement` + `textContent`:

```js
function addCloseButton(modalEl, onClose) {
  const closeBtn = document.createElement("button");
  closeBtn.className = "modal-close";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", onClose);
  modalEl.appendChild(closeBtn);
}
```

Call `addCloseButton(modalEl, () => modalEl.remove())` (or whatever the existing close path is) in each modal build site. If modals are constructed independently in `menus.js` (Settings/Tools) and `shortcuts.js` (Shortcuts), do it in both places.

- [ ] **Step 3: Style `.modal-close` in `track.css`**

Add (after existing modal rules; if no modal rules exist, add at end of file):

```css
.modal-close {
  position: absolute;
  top: var(--sp-2);
  right: var(--sp-2);
  width: 28px;
  height: 28px;
  background: transparent;
  border: none;
  color: var(--fg-2);
  font-size: 22px;
  font-weight: 300;
  line-height: 1;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.12s, color 0.12s;
}
.modal-close:hover { background: var(--bg-3); color: white; }
```

Verify the modal container has `position: relative` so the absolute positioning anchors correctly; if not, add it.

- [ ] **Step 4: Fix sidebar shortcut hint copy (G6)**

This applies even though the sidebar SHORTCUTS section was removed in Task 4. Confirm — search for `? / Esc` or similar string in `webui/static/js/`:

```
Grep pattern: \? / Esc|Shift\+\/
File: webui/static/js/
Output mode: content
```

If the string is gone (Task 4 removed it), this step is a no-op. Otherwise, replace `?` with `Shift+/` in the hint copy.

- [ ] **Step 5: Verify in browser**

Reload. Open Settings — confirm × in top-right; click closes. Open Tools — same. Press `?` for Shortcuts modal — confirm × visible. Screenshot `T7-modal-close-buttons.png` (Settings modal with × visible).

- [ ] **Step 6: Run regressions and commit**

```powershell
cd webui/tests-e2e && npm test
```

```powershell
git add webui/static/css/track.css webui/static/js/ui/menus.js webui/static/js/ui/shortcuts.js tests/screenshots/polish-after/T7-modal-close-buttons.png
git commit -m @'
feat(webui): modal close affordances + shortcut hint copy (G2, G5, G6)

- × close button on Settings/Tools/Shortcuts modals (G2, G5)
- Sidebar shortcut hint clarified (G6) — covers any remaining instance
  if Task 4 missed one

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 8: Custom reanalyze modal (audit G1)

Replace the native `confirm()` in `webui/static/js/ui/menus.js` with a confirmation step inside the existing `showReanalyzeModal` flow (which already streams progress and shows a final stats panel — confirmed by `webui/static/js/ui/reanalyze.js`).

**Files:**
- Modify: `webui/static/js/ui/menus.js`
- Modify: `webui/static/js/ui/reanalyze.js`
- Modify: `webui/static/css/track.css` (small)

- [ ] **Step 1: Read both files**

`Read` `webui/static/js/ui/menus.js` (around line 53) and the full `webui/static/js/ui/reanalyze.js`. Note the current confirm-then-call pattern in `menus.js`:

```js
const ok = confirm("Reanalyze ...?");
if (ok) showReanalyzeModal(slug);
```

`showReanalyzeModal` opens a modal that already has a log area, stage badge, etc. The fix: add a confirmation pre-state inside the modal — modal opens immediately, shows a warning + Cancel/Reanalyze buttons; on Reanalyze click, transitions to the existing streaming UI.

- [ ] **Step 2: Capture before-state**

Open Tools modal, click "Reanalyze". The native confirm dialog will appear. Use `mcp__plugin_playwright_playwright__browser_handle_dialog` with `accept: false` to dismiss. Then screenshot the Tools modal (no native dialog visible) to `T8-reanalyze-before.png`.

- [ ] **Step 3: Modify `menus.js` to remove `confirm()` and call modal directly**

```
old: const ok = confirm(`Reanalyze ${slug}?\n\nThis will wipe cache/${slug}/ and re-run the full pipeline (~minutes).`);
     if (ok) showReanalyzeModal(slug);
new: showReanalyzeModal(slug);
```

The confirmation now lives inside the modal.

- [ ] **Step 4: Add a confirmation pre-state to `reanalyze.js`**

In `webui/static/js/ui/reanalyze.js`, refactor `showReanalyzeModal(slug)` to start in a "confirmation" state. Build all DOM with `createElement` + `textContent` (NO innerHTML, NO template strings into innerHTML):

```js
export function showReanalyzeModal(slug) {
  const modal = buildModal(); // existing helper that creates the .modal element
  renderConfirmationState(modal, slug, () => startReanalyzePipeline(modal, slug));
  document.body.appendChild(modal);
}

function renderConfirmationState(modal, slug, onConfirm) {
  const body = modal.querySelector(".modal-body");
  body.replaceChildren(); // clear

  const warn = document.createElement("p");
  warn.className = "reanalyze-warn";
  const lead = document.createTextNode("This will wipe ");
  const slugCode = document.createElement("code");
  slugCode.textContent = `cache/${slug}/`;
  const tail = document.createTextNode(" and re-run the full pipeline (~minutes). The original source will be staged so the in-cache MP3 is safe to lose.");
  warn.appendChild(lead);
  warn.appendChild(slugCode);
  warn.appendChild(tail);
  body.appendChild(warn);

  const actions = document.createElement("div");
  actions.className = "reanalyze-actions";

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "btn-cancel";
  cancelBtn.textContent = "Cancel";
  cancelBtn.addEventListener("click", () => modal.remove());

  const confirmBtn = document.createElement("button");
  confirmBtn.className = "btn-confirm";
  confirmBtn.textContent = "Reanalyze";
  confirmBtn.addEventListener("click", onConfirm);

  actions.appendChild(cancelBtn);
  actions.appendChild(confirmBtn);
  body.appendChild(actions);
}

function startReanalyzePipeline(modal, slug) {
  // Move the existing implementation (stream NDJSON from
  // /api/tools/reanalyze/{slug}, populate stage badge + log area + stats)
  // into this function. It replaces the modal body's confirmation UI
  // with the streaming UI.
  // Preserve all current behaviors:
  // - single-reanalysis-at-a-time guard
  // - log streaming
  // - final stats panel
}
```

- [ ] **Step 5: CSS for confirmation state**

In `track.css`, add:

```css
.reanalyze-warn { color: var(--fg-1); margin-bottom: var(--sp-3); line-height: 1.5; }
.reanalyze-warn code { background: var(--bg-3); padding: 1px 5px; border-radius: 3px; font-family: var(--font-mono); font-size: var(--t-body); }
.reanalyze-actions { display: flex; gap: var(--sp-2); justify-content: flex-end; }
.reanalyze-actions button { padding: var(--sp-2) var(--sp-3); border-radius: 4px; border: 1px solid var(--bg-3); cursor: pointer; transition: background 0.12s; }
.reanalyze-actions .btn-cancel { background: var(--bg-2); color: var(--fg-1); }
.reanalyze-actions .btn-cancel:hover { background: var(--bg-3); }
.reanalyze-actions .btn-confirm { background: #4a1a1a; color: #ff8a8a; border-color: #5a2a2a; }
.reanalyze-actions .btn-confirm:hover { background: #5a2a2a; color: white; }
```

The destructive button is warm-red, matching the existing destructive-action color in the Tools modal.

- [ ] **Step 6: Verify**

Reload. Tools → Reanalyze. The custom modal opens with the confirmation copy and Cancel / Reanalyze buttons. **Click Cancel** to dismiss. **Do NOT click Reanalyze** — that would actually run the pipeline. Screenshot `T8-reanalyze-after.png` showing the confirmation state.

- [ ] **Step 7: Run regressions and commit**

```powershell
cd webui/tests-e2e && npm test
```

The e2e test for reanalyze (if any) may need updating — check the suite. If it expected `confirm()`, update it to interact with the new modal buttons. If no specific test exercises the reanalyze flow, skip.

```powershell
git add webui/static/js/ui/menus.js webui/static/js/ui/reanalyze.js webui/static/css/track.css tests/screenshots/polish-after/T8-reanalyze-*.png
git commit -m @'
feat(webui): replace native confirm() with in-modal confirmation for reanalyze (G1)

The Tools → Reanalyze flow used to fire window.confirm(), breaking the
dark UI and bypassing the existing streaming modal. Now the custom modal
opens directly with a confirmation pre-state (Cancel / Reanalyze buttons)
that transitions to the streaming UI on confirm.

The existing single-reanalysis-at-a-time guard, NDJSON streaming, and
post-run stats panel all preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 9: Error toast investigation + minimal toast UI (audit H1)

The audit could not confirm whether a toast UI exists. Investigate first; if missing, build a minimal toast component for fetch errors.

**Files:**
- Modify or Create: `webui/static/js/ui/toast.js`
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/api.js` (or wherever fetch wrappers live)

- [ ] **Step 1: Investigate**

```
Grep pattern: toast|notification|showError
File: webui/static/js/
Output mode: files with matches
```

Two outcomes:

**A) Toast UI exists already.** Read the file. The fix is wiring: ensure fetch error paths in `api.js` (or wherever) call the toast. Skip to Step 4.

**B) Toast UI doesn't exist.** Continue to Step 2 to build it.

- [ ] **Step 2: Build a minimal toast component**

Create `webui/static/js/ui/toast.js`. Use `createElement` + `textContent`, never `innerHTML`:

```js
// Minimal toast notification surface.
// Toasts append to a container at #toast-stack, auto-dismiss after 5s,
// or on click. Multiple toasts stack; max 4 visible (older drop).

const MAX_TOASTS = 4;
const DISMISS_MS = 5000;

let stack = null;

function ensureStack() {
  if (stack) return stack;
  stack = document.createElement("div");
  stack.id = "toast-stack";
  document.body.appendChild(stack);
  return stack;
}

export function showToast(level, message) {
  const el = document.createElement("div");
  el.className = `toast toast-${level}`;
  el.textContent = message; // textContent, not innerHTML
  el.addEventListener("click", () => el.remove());
  const root = ensureStack();
  root.appendChild(el);
  while (root.children.length > MAX_TOASTS) root.firstElementChild.remove();
  setTimeout(() => el.remove(), DISMISS_MS);
}
```

- [ ] **Step 3: Style in `track.css`**

Add at end of file:

```css
#toast-stack {
  position: fixed;
  top: var(--sp-3);
  right: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  z-index: 100;
  pointer-events: none;
}
.toast {
  padding: var(--sp-2) var(--sp-3);
  border-radius: 6px;
  background: var(--bg-2);
  color: var(--fg-0);
  font-size: var(--t-body);
  box-shadow: var(--el-3);
  pointer-events: auto;
  cursor: pointer;
  max-width: 400px;
  animation: toast-slide 0.18s ease-out;
}
.toast-error { background: #2a0e0e; color: #ff8a8a; border: 1px solid #5a2a2a; }
.toast-info  { background: var(--bg-2); color: var(--fg-1); border: 1px solid var(--bg-3); }
@keyframes toast-slide { from { transform: translateY(-12px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
```

- [ ] **Step 4: Wire into fetch errors**

Locate the central fetch wrapper (likely `webui/static/js/api.js`). Import `showToast` and surface errors:

```js
import { showToast } from "./ui/toast.js";

export async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    showToast("error", `Request failed: ${res.status} ${res.statusText} — ${url}`);
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}
```

Adapt to actual existing wrapper signature. If there's no central wrapper, wrap the most-touched fetch sites (track loading, reanalyze) and skip the rest.

- [ ] **Step 5: Verify**

Reload. Trigger via `browser_evaluate`:

```js
() => import("/static/js/ui/toast.js").then(m => m.showToast("error", "Test error toast"))
```

A red toast should appear top-right. Click to dismiss, or wait 5s. Screenshot `T9-toast.png`.

- [ ] **Step 6: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/js/ui/toast.js webui/static/js/api.js webui/static/css/track.css tests/screenshots/polish-after/T9-toast.png
git commit -m @'
feat(webui): minimal toast for fetch errors (H1)

Adds webui/static/js/ui/toast.js with a stack-based toast surface
(max 4 visible, 5s auto-dismiss, click-to-dismiss). Wired into the
central fetch wrapper so 4xx/5xx responses surface as user-visible
red toasts. Resolves the H1 audit gap where backend errors were
silent in the UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 10: Suppressed stems polish (audit I2, I3)

Make the "show suppressed" affordances more visible and clickable.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/sidebar.js`

- [ ] **Step 1: Before screenshot**

Switch to a track with a suppressed stem (use the same one the audit found). Screenshot `#viewer-side` to `T10-suppressed-before.png`.

- [ ] **Step 2: Suppressed footer affordance (I2)**

Edit `.stems-suppressed-footer` in `track.css`:

```
old: .stems-suppressed-footer { font-size: 10px; color: var(--fg-3); padding: 4px 0 0 0; cursor: pointer; text-decoration: underline dotted; }
new: .stems-suppressed-footer { font-size: var(--t-body); color: var(--fg-2); padding: var(--sp-2) 0 var(--sp-1) 0; cursor: pointer; text-decoration: none; border-top: 1px solid var(--bg-3); margin-top: var(--sp-1); display: block; transition: color 0.12s; }
.stems-suppressed-footer::before { content: "▸ "; color: var(--fg-3); }
.stems-suppressed-footer:hover { color: var(--fg-0); }
.stems-suppressed-footer:hover::before { color: var(--fg-1); }
```

The footer becomes a chevron-led full-width row instead of a dotted-underline link.

- [ ] **Step 3: "Show suppressed" header link (I3)**

If the stems section header has a "show suppressed" link inside the h4 (per audit I3 — verify in `sidebar.js`), increase its font-size and target. Move it OUT of the h4 to a sibling element on the right side of the heading row. Build with `createElement`:

```js
function buildStemsHeader(hasSuppressed, showingSuppressed, onToggle) {
  const headerRow = document.createElement("div");
  headerRow.className = "side-section-header";

  const h4 = document.createElement("h4");
  h4.textContent = "STEMS";
  headerRow.appendChild(h4);

  if (hasSuppressed) {
    const toggle = document.createElement("button");
    toggle.className = "show-suppressed-btn";
    toggle.textContent = showingSuppressed ? "hide" : "show suppressed";
    toggle.addEventListener("click", onToggle);
    headerRow.appendChild(toggle);
  }
  return headerRow;
}
```

In `track.css`:

```css
.side-section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.side-section-header h4 { margin: 0; }
.show-suppressed-btn {
  background: transparent;
  border: 1px solid var(--bg-3);
  color: var(--fg-1);
  font-size: var(--t-micro);
  letter-spacing: var(--ls-caps);
  padding: 2px 8px;
  border-radius: 10px;
  cursor: pointer;
  text-transform: uppercase;
  transition: background 0.12s, color 0.12s;
}
.show-suppressed-btn:hover { background: var(--bg-3); color: white; }
```

- [ ] **Step 4: After screenshot**

Reload, switch to suppressed-stem track, screenshot `T10-suppressed-after.png`.

- [ ] **Step 5: Run regressions and commit**

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/css/track.css webui/static/js/ui/sidebar.js tests/screenshots/polish-after/T10-suppressed-*.png
git commit -m @'
fix(webui): suppressed-stem affordance visibility (I2, I3)

- Suppressed footer: chevron-led full-width row, --t-body size,
  --bg-3 top border (I2)
- "Show suppressed" pill button moved out of h4 heading into a
  flex sibling, --t-micro caps style (I3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 11: Narrow-viewport hardening (audit J1, J2, J3, J4)

Add overflow protection on the topbar title, condense transport zoom labels at narrow widths, and verify sidebar scroll behavior.

**Files:**
- Modify: `webui/static/css/track.css`

- [ ] **Step 1: Resize to narrow viewport and capture before**

`browser_resize` `{width: 1280, height: 800}`. Reload. Screenshot full viewport `T11-narrow-before.png`.

- [ ] **Step 2: Topbar title overflow (J2/J3)**

Edit `.track-picker .title`:

```
old: .track-picker .title { font-weight: 600; color: white; font-size: 13px; }
new: .track-picker .title { font-weight: 600; color: white; font-size: var(--t-prose); max-width: 40ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

(13px → `--t-prose` since they're equal; the size token doesn't change rendering.)

- [ ] **Step 3: Transport zoom hint labels (J4)**

The `.zoomgrp .zlbl` labels (`ctrl+wheel`, `⇧wheel`) become decorative noise at narrow widths. Hide them below 1400px:

```css
@media (max-width: 1399px) {
  #transport .zoomgrp .zlbl { display: none; }
}
```

Insert near the existing `.zoomgrp` rules.

- [ ] **Step 4: Sidebar scroll affordance (J1)**

The audit notes the sidebar overflows at 800px and has no scroll indicator. Now that Task 4 removed the SHORTCUTS section, less content lives in the sidebar — verify whether it still overflows. If it does, add a subtle scroll affordance:

```css
#viewer-side {
  /* existing rules ... */
  scrollbar-width: thin;
  scrollbar-color: var(--bg-3) transparent;
}
#viewer-side::-webkit-scrollbar { width: 8px; }
#viewer-side::-webkit-scrollbar-thumb { background: var(--bg-3); border-radius: 4px; }
#viewer-side::-webkit-scrollbar-track { background: transparent; }
```

If the sidebar no longer overflows after Task 4, skip the scrollbar styling and document in the commit message that J1 was resolved by Task 4's removal of SHORTCUTS.

- [ ] **Step 5: After screenshot at 1280×800**

Reload at narrow viewport. Screenshot `T11-narrow-after.png`. Verify topbar title shows ellipsis, zoom labels hidden, sidebar scrolls cleanly.

- [ ] **Step 6: Restore default viewport, run regressions, commit**

`browser_resize` `{width: 1600, height: 1000}`.

```powershell
node --test webui/tests-js/*.test.js
```

```powershell
git add webui/static/css/track.css tests/screenshots/polish-after/T11-narrow-*.png
git commit -m @'
feat(webui): narrow-viewport hardening (J1, J2, J3, J4)

- Topbar title gets max-width: 40ch + ellipsis (J2, J3)
- Transport zoom hint labels hide below 1400px (J4)
- Sidebar gets thin custom scrollbar styling (J1; partially mitigated
  by Task 4's removal of SHORTCUTS section reducing sidebar content)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Task 12: Auto-scroll badge relocation (audit C3)

Move `.auto-badge` out of the canvas and into the transport bar.

**Files:**
- Modify: `webui/static/css/track.css`
- Modify: `webui/static/js/ui/transport.js`
- Modify: `webui/static/js/render/pianoroll.js`

- [ ] **Step 1: Before screenshot**

Reload at 1600×1000, press Space, wait 3 seconds. Screenshot `T12-badge-before.png` (badge visible in canvas bottom-left). Pause.

- [ ] **Step 2: Read current badge logic**

`Read` the auto-badge state code in `pianoroll.js` (CSS class `.auto-badge`, `.auto-badge.off`). Note: the badge has two states (`edge` mode = visible default, `off` = manual scroll). It also has a click handler to re-engage auto-scroll when off.

- [ ] **Step 3: Remove badge from canvas DOM**

In `pianoroll.js`, find where the badge is created and appended inside `#roll-frame`. Remove that DOM creation. Leave the auto-scroll state machine intact (the model — edge-pinning vs center-pinning vs off — doesn't change).

Expose the auto-scroll state via a public hook:

```js
// in pianoroll.js, near the state model:
let autoScrollListener = null;
export function onAutoScrollChange(cb) { autoScrollListener = cb; }
function setAutoScrollState(state) {
  currentState = state;
  if (autoScrollListener) autoScrollListener(state); // 'edge' | 'center' | 'off'
}
```

- [ ] **Step 4: Add badge to transport**

In `webui/static/js/ui/transport.js`, after the play button is built, insert the badge using `createElement` + `textContent`:

```js
import { onAutoScrollChange, reengageAutoScroll } from "../render/pianoroll.js";

// ... after play button is built:
const badge = document.createElement("button");
badge.className = "auto-badge";
badge.textContent = "▶ AUTO";
badge.addEventListener("click", () => reengageAutoScroll());
transportEl.insertBefore(badge, scrubEl); // position between play and scrub

onAutoScrollChange((state) => {
  badge.classList.toggle("off", state === "off");
  badge.textContent = state === "off" ? "○ MANUAL" : "▶ AUTO";
});
```

- [ ] **Step 5: Update CSS**

Remove the `#roll-frame .auto-badge` rules from `track.css`. Add new rules for the transport-positioned badge:

```css
#transport .auto-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: var(--ls-caps);
  background: white;
  color: var(--bg-0);
  padding: 3px 8px;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  box-shadow: var(--el-1);
}
#transport .auto-badge.off {
  background: var(--bg-2);
  color: var(--fg-2);
  box-shadow: none;
}
#transport .auto-badge:hover { filter: brightness(0.9); }
```

- [ ] **Step 6: After screenshot**

Reload, press Space, wait 3s. Screenshot `T12-badge-after.png` (badge now in transport, no longer overlapping canvas notes). Pause.

- [ ] **Step 7: Run regressions and commit**

```powershell
cd webui/tests-e2e && npm test
```

The e2e test suite has tests that interact with the auto-badge (search for `.auto-badge` selectors). Update those to target `#transport .auto-badge` if they currently expect the badge inside `#roll-frame`.

```powershell
git add webui/static/css/track.css webui/static/js/ui/transport.js webui/static/js/render/pianoroll.js webui/tests-e2e/ tests/screenshots/polish-after/T12-badge-*.png
git commit -m @'
refactor(webui): relocate auto-scroll badge from canvas to transport (C3)

Badge was inside #roll-frame at bottom-left, overlapping notes at low
pitch rows. Moves to #transport between play button and scrub bar.
State machine unchanged; pianoroll.js exposes onAutoScrollChange()
hook for transport.js to subscribe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

# Done criteria (Phase 2)

- 12 commits land, each addressing the audit IDs listed in the task title.
- Before/after screenshot pairs in `tests/screenshots/polish-after/` cover every task that produced visible change (all 12).
- All three regression suites green at session end:
  - `cd webui && .venv\Scripts\python -m pytest`
  - `node --test webui/tests-js/*.test.js`
  - `cd webui/tests-e2e && npm test` (note: pre-existing slug-match failure may persist; if so, document)
- No findings from the triage cut remain unaddressed unless explicitly deferred during execution (with a note in the audit doc).
- Audit doc's `## Triage` section gets a final pass updating each `[x]` checkbox to `[done]` (or similar) once its task lands, plus a `## Deferred` section update with anything we couldn't ship.

# Pause / resume

This plan is large. The user can pause execution at any commit boundary; resume by reading the plan and continuing from the first un-checked task. Each task is self-contained; later tasks do not depend on earlier ones except through shared file edits (most edits are to `track.css` and a handful of JS files — no merge-order constraints).
