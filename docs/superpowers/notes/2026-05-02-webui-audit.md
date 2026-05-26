# webui polish audit — 2026-05-02

Findings from the Playwright-driven audit sweep. Spec at
`docs/superpowers/specs/2026-05-02-webui-polish-design.md`.

**Severity:** P1 broken / P2 refine / P3 nice-to-have
**Category:** bug / refine / ia
**Format:** `- [ ] [Pn] [cat] short title — screenshot ref` then a `notes:` line

## A. Empty state

No true empty state is reachable — first load auto-selects the most recently analyzed track. Documented as expected limitation; no fix needed.

- [x] [P2] [refine] track picker title displays raw filesystem slug, not a human title — screenshot A1-picker-open.png
  notes: the topbar track title and all picker rows show the raw slug (e.g. `gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg`) rather than the parsed human title. Many tracks have proper titles already stored (e.g. "Where Is My Mind_", "Radiohead - creep…") but the Gorillaz track slug was never decorated. Even where human titles exist, the pick-list row typography does not distinguish title from subtitle. Affects first-impressions of every picker open. **Same root cause as B1** (topbar title); fix should populate `display_title` upstream so both surfaces inherit.

- [x] [P2] [refine] picker rows: "sections deferred — no segmenter installed" subtitle is orange/warning-colored for every track — screenshot A1-picker-open.png
  notes: the `.tp-row .nm .warn` style makes this a bright warning color (`.warn { color: #ff8866 }`). For a system-wide status affecting all 22 tracks this feels like screaming at the user; consider a dimmer `--fg-3` or plain italic prose, reserving orange for a real per-track error.

- [x] [P3] [ia] picker panel has no visible header/title — screenshot A1-picker-open.png
  notes: the panel opens straight to a search box with no "Tracks" label or section title. The search placeholder "Search tracks…" carries the context, but the panel lacks hierarchical anchor. Compare: a small "LIBRARY · 22 TRACKS" header in the `--t-micro` caps style would reinforce the editorial system.

## B. Track loaded, idle

- [x] [P1] [bug] track title in topbar is the raw analysis slug, not a display name — screenshot B2-topbar.png
  notes: `gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg` fills the topbar title in 13px weight-600 text, crowding out badges and creating an aggressive first impression. This is a data/metadata gap upstream (no `display_title` field populated for this track), but the UI should fall back gracefully — at minimum, strip the YouTube ID suffix and replace underscores with spaces. **Same root cause as A1** (picker rows show same raw slug); fix in one place.

- [x] [P2] [refine] now-playing card idle state is inert: only "—" and "(no chord)" visible — screenshot B3-sidebar.png
  notes: at t=0 paused, the now-card shows a gold dash (—) as the Roman numeral placeholder, the text "(no chord)", and the time "0:00.00 PLAYHEAD". The card is 110px tall of near-empty space. The editorial direction calls for "deliberate and refined" not "waiting". Consider showing track-level context in this state: key, scale, vocal range, or a small descriptive tagline for the track.

- [x] [P2] [refine] now-card time display "PLAYHEAD" label — screenshot B3-sidebar.png
  notes: the label beneath the time counter reads "PLAYHEAD" in 9px caps. This is ambiguous — it describes the origin of the time, not the meaning. "AT PLAYHEAD" is marginally clearer, or simply drop the label and let the transport bar own the canonical time display. The label also competes with the "playhead" as a concept users know from the canvas.

- [x] [P2] [refine] sidebar section headers (h4) have inconsistent caps: "STEMS · CLICK TO HIGHLIGHT" vs "NOW PLAYING" vs "LOOP · 4 CHORDS · 9 APPEARANCES" — screenshot B3-sidebar.png
  notes: "NOW PLAYING" is plain caps; "STEMS · CLICK TO HIGHLIGHT" embeds an affordance hint inline in the heading; "LOOP · 4 CHORDS · 9 APPEARANCES" embeds data inline. The `h4` selector (`font-size: 9px; text-transform: uppercase; letter-spacing: var(--ls-caps)`) is applied consistently but the copy strategy is inconsistent. The hint "click to highlight" should move to a tooltip or a secondary label, not live inside the heading.

- [x] [P2] [refine] sidebar SHORTCUTS section duplicates the shortcuts modal — screenshot B3-sidebar.png
  notes: the sidebar always shows the shortcuts list, and clicking "?" opens a modal with the same (expanded) list. The sidebar section is redundant once the modal exists. It takes up ~150px of sidebar real estate that could show more useful track context. Consider removing the sidebar section or condensing it to a single "? keyboard shortcuts" link row.

- [x] [P3] [refine] stem note counts displayed as bare integers with no unit — screenshot B3-sidebar.png
  notes: "1098", "564", "917", "295", "913" appear in `--font-mono` next to stem names. No unit label. New users cannot interpret these numbers. Even a tooltip ("1098 notes detected") or a micro-label ("notes") would clarify. Drums shows "2067 hits" which is better — that pattern should apply to all stems.

- [x] [P3] [refine] sidebar section dividers are `border-bottom: 1px solid #1f1f24` (hardcoded, not a token) — screenshot B3-sidebar.png (track.css line 99)
  notes: not visible as a bug but the color is not from `--bg-3` (which is used for dividers elsewhere). Minor consistency gap flagged during Phase 0 refactor.

## C. Track playing

- [x] [P2] [refine] now-card chord display: Roman numeral and chord name lack visual hierarchy — screenshot C2-now-card-filled.png
  notes: the now-card shows "v" (36px serif, amber) stacked over "C:min" (13px mono, white) with a "dominant" tag below. The "C:min" label is formatted as a chord name (colon separator) which is non-standard notation; conventional would be "Cm" or "C min". The tag "dominant" is a harmonic function label, styled as a rounded pill in a warm-muted background — function label is useful but the color (`#3a2a1a` background, `var(--accent)` text) makes it look like a third Roman numeral tag rather than a separate concept.

- [ ] [P2] [refine] playhead on canvas is white with white glow — barely distinguishable from bright notes on saturated tracks — screenshot C1-playing.png
  notes: `#roll-frame .playhead` is `background: white; box-shadow: 0 0 8px rgba(255,255,255,.7)`. Against a canvas full of multi-color notes the white line can get lost. The accent color (`--accent: #ffb86b`) or a contrasting color like `#6cf` would be more legible. The minimap playhead uses `var(--accent)` correctly; the roll playhead does not.

- [x] [P3] [refine] auto-scroll badge ("▶ AUTO") at bottom-left of canvas uses canvas-space position — screenshot C1-playing.png
  notes: the `.auto-badge` is positioned `bottom: 8px; left: 10px` inside `#roll-frame`, overlapping notes at the bottom of the pitch range. When playing, the badge competes with drum hits at the bottom rows. Consider moving it to the transport bar (next to zoom controls) or the topbar.

## D. Hover states

- [x] [P2] [refine] track row hover background (#1c1c22) is nearly indistinguishable from default row background — screenshot D1-hover-track-row.png
  notes: `.track-row:hover { background: #1c1c22 }` is only ~2 luminance steps above the sidebar background (`--bg-1`). The Vocals row is "highlighted" (`#1f1f28`) which is itself barely different from hover. A user cannot easily tell which row they're about to click. Consider a more distinct hover treatment — e.g., `--bg-3` or a slight left-border accent on hover (similar to the selected state).

- [x] [P2] [refine] transport play button has no visible hover state — screenshot D4-hover-play.png
  notes: `.play-btn` has no `:hover` CSS. It's a 28px white circle on dark background. Moving the cursor over it produces no feedback. This is the most-clicked interactive element. At minimum add `filter: brightness(0.85)` on hover.

- [x] [P2] [refine] topbar menu items hover is `background: var(--bg-3); color: white` — adequate but no transition — screenshot D2-hover-tools.png
  notes: the hover state snaps instantly. Adding `transition: background .12s` would align with the track-picker chevron which already has `transition: transform .15s`.

- [x] [P3] [refine] zoom +/− buttons in transport zoomgrp have no hover/focus ring visible — screenshot D4-hover-play.png
  notes: `.zoomgrp button:hover` is not defined. The `background: var(--bg-2)` buttons get no feedback on hover. Minor but part of the hover-coverage gap.

- [x] [P3] [refine] canvas hover tooltip note format "D#4 29.49s" uses D#/Eb notation inconsistently — screenshot D5-hover-canvas.png
  notes: the tooltip in `D5-hover-canvas.png` shows `D#4 29.49s` while the gutter labels show `D4` / `E4` etc. The track key is F natural minor (no sharps), yet the tooltip uses `#` notation. The gutter uses `♭` for tonic-aligned rows. Notation should be consistent with the key context.

## E. Mute / solo

- [x] [P2] [refine] M (mute) active state: `background: #4a1a1a; color: #ff8a8a` — S (solo) active: `background: #4a3a1a; color: #ffb86b` — visually similar at a glance — screenshot E1-mute-solo-active.png
  notes: both active states use warm-colored text on dark warm backgrounds. In a quick scan, a muted stem and a soloed stem look similar. Mute is conventionally a destructive/off state (grey or red); solo is a highlighting/on state (yellow or blue). The current colors are both "warm" with low contrast difference. Consider making M active state more clearly "dimming" (cool grey or desaturated red) while S active state is "brightening" (amber accent matches the logo).

- [x] [P3] [refine] M and S buttons are 18×18px with 10px font — small click target — screenshot E1-mute-solo-active.png
  notes: at 18×18px these are below the WCAG 44×44px touch target guideline (not a strict web requirement here, but still small). The adjacent volume slider is also 5px tall. Both are hard to interact with precisely.

## F. Track picker

- [x] [P2] [refine] picker search input has no visible focus ring — screenshot F2-picker-filter.png
  notes: `.tp-search input:focus { border-color: #6cf }` changes only the border color. On dark backgrounds the `#6cf` border is legible, but there's no outline/ring outside the element. This is a focus visibility gap (WCAG 2.4.11). Consider adding `outline: 2px solid rgba(102, 204, 255, 0.4)` on focus.

- [x] [P2] [refine] picker footer "↑↓ navigate · ↵ open · esc close" is 10px on `--bg-0` background — screenshot F1-picker-open.png
  notes: `.tp-footer` uses `font-size: var(--t-micro)` (10px) and `color: var(--fg-3)`. On the `--bg-0` background the contrast is very low for small text. The keyboard hint is useful but near-invisible at first glance.

- [x] [P3] [refine] filter pills (SORT / FILTER controls) have `.lbl` in 10px uppercase separated from the pills — screenshot F1-picker-open.png
  notes: "SORT" and "FILTER" labels float to the left of pill groups in the controls bar. The label–pill pairing is not visually grouped (no bounding box, just proximity). The active pill (`background: #3a2a4a`) has good contrast; the inactive pill is `--bg-2` which is close to the controls background `--bg-0`.

## G. Modals (Settings, Tools, Shortcuts, Reanalyze)

- [x] [P1] [bug] reanalyze flow invokes a native browser `confirm()` dialog instead of a custom modal — screenshot G4-reanalyze-modal.png (shows the Tools modal one click away from the trigger; native confirm itself cannot be captured by Playwright)
  notes: confirmed via Playwright's `browser_handle_dialog` handler — clicking "Reanalyze (clear cache + re-run pipeline)" in the Tools modal triggers `window.confirm()`, which Playwright detected and auto-dismissed. The captured G4 screenshot shows the Tools modal (the precondition to the trigger), not the dialog itself, because Playwright cannot screenshot a blocking native dialog. The native dialog is unstyled, breaks the dark UI, has no log area, and cannot be themed. Replace with a custom modal matching Settings/Tools/Shortcuts. Note: commit 6f0155b mentions "enlarged the reanalyze modal" — the in-codebase modal exists at the source level (see `tests/screenshots/reanalyze-modal-bigger.png`), but is evidently not wired into the click path; investigate which code path runs vs. which was enlarged.

- [x] [P2] [refine] Settings modal: extremely sparse content — only "AUDIO ENGINE" with two radio buttons — screenshot G1-settings-modal.png
  notes: the modal has a good header ("Settings"), adequate padding, and dark backdrop. But the content is a single radio group with one real option (ASIO is "coming r1"). The empty space below the radio buttons is ~150px of void. At minimum, add a modal close button (×) in the top-right corner; currently only Escape closes it.

- [ ] [P2] [refine] Tools modal: "Open *.mid in default Windows handler" items have no icon or grouping — screenshot G2-tools-modal.png
  notes: the five MIDI open links are visually identical plain text rows, separated from "Reveal cache… in Explorer" and "Reanalyze…" only by a horizontal margin. No grouping headers (e.g., "Export / Open", "Cache"), no icons. The "Reanalyze (clear cache + re-run pipeline)" row is in red (`color: #ff6b6b` or similar) — appropriate for destructive action, but the visual scanning path through the modal is unguided.

- [ ] [P2] [refine] Shortcuts modal: lists more shortcuts than the sidebar section (more complete) — screenshot G3-shortcuts-modal.png
  notes: the sidebar "SHORTCUTS" section is an abbreviated list; the modal has Home/End/Numpad entries that don't appear in the sidebar. This difference in content reinforces that the sidebar section is redundant — the modal is the authoritative reference. The modal is well-structured (key–action two-column layout) but the dividing line between navigation/playback shortcuts and stem shortcuts is not visually marked.

- [x] [P3] [refine] Tools and Shortcuts modals also lack explicit close buttons — screenshots G2, G3
  notes: scope-limited follow-up to G1 (which already covers the Settings modal close-button gap). The Settings, Tools, and Shortcuts modals all rely on Escape-only dismissal. Mouse-only users may find them "sticky". Apply the same close-button affordance from G1 across all three modals.

- [x] [P3] [refine] the `?` keyboard shortcut to open shortcuts modal requires `Shift+/` — sidebar hint says `? / Esc shortcuts modal / close` — screenshot G3-shortcuts-modal.png
  notes: pressing bare `?` in the main window does nothing (the key is captured by Shift). The sidebar hint `? / Esc` is technically accurate (? = Shift+/) but visually ambiguous. The shortcuts modal lists `Shift+/` which is correct. The sidebar copy should say `Shift+?` or `Shift+/` to match.

## H. Toasts / errors

- [x] [P2] [bug] error toast cannot be triggered via fetch-to-invalid-endpoint — no toast UI visible — screenshot H1-error-toast-attempt.png
  notes: **unconfirmed via this audit path** — fetching `/api/tracks/__nonexistent__` produced a 404 (console error logged) but no toast appeared. This may mean (a) no toast UI exists at all, or (b) toasts only fire from specific user-action error paths not exercised here (e.g., reanalyze failures, autoplay rejection). Needs deliberate error injection from a real user-action path before classifying as confirmed missing UI. If confirmed, consider adding `showToast('error', message)` in the fetch error path in `webui/static/js/`.

## I. Suppressed / missing stems

- [ ] [P2] [refine] suppressed stem row opacity (0.4) makes it almost invisible in the stems list — screenshot I1-suppressed-stems.png
  notes: `.track-row.stem-suppressed { opacity: 0.4 }` reduces the Piano row to 40% opacity. The italic name and grayed count are readable but the row feels broken/dead rather than "intentionally quiet". Consider 0.55–0.6 opacity, or a more explicit "suppressed" badge/pill on the row rather than just opacity reduction.

- [x] [P2] [refine] suppressed footer link "1 stem suppressed — click to show" uses `text-decoration: underline dotted` which is 10px and barely visible — screenshot I2-suppressed-footer.png
  notes: `.stems-suppressed-footer` is `font-size: var(--t-micro); color: var(--fg-3)` with a dotted underline. At 10px on a dark background the dotted underline is nearly invisible. The click target is also just the text width, not a full-width row. This is an affordance gap — users may not notice the suppressed stem or know how to reveal it.

- [x] [P3] [refine] "show suppressed" link in the stems section header is top-right-aligned, small — screenshot I1-suppressed-stems.png
  notes: the "show suppressed" toggle in the `h4` heading is `color: var(--fg-3)` at 9px. It competes with neither of the other h4 patterns (NOW PLAYING, LOOP info), and is the smallest interactive element in the sidebar. Increase font-size to `--t-body` (11px) minimum and ensure the click target covers the full label.

## J. Narrow viewport (1280×800)

- [x] [P2] [refine] sidebar scrolls off-screen bottom at 800px height — SHORTCUTS section not visible without scroll — screenshot J3-sidebar-1280.png
  notes: the sidebar overflows at 800px. The SHORTCUTS section (which should arguably be removed per finding B) is pushed below the visible area. Even without shortcuts, the HARMONY STATS section barely fits. The sidebar is `overflow-y: auto` so scrolling works, but there is no scroll indicator and important harmony data may be hidden at this height. Consider removing the sidebar SHORTCUTS section (see B) to recover ~150px.

- [x] [P3] [refine] track picker panel (480px wide) covers ~38% of canvas at 1280px while open — screenshot J5-picker-1280.png
  notes: at 1280×800 the 480px picker panel opens at `left: 0` of the `.track-picker` element. The panel correctly stays within the viewport but covers the first ~480px of canvas behind it. This is expected behavior — the picker is a transient overlay and the user is looking at the picker, not the canvas, while it's open. **No fix recommended; informational.** Documented in case future viewport-aware behavior is desired (e.g., shrink panel to 360px on narrow viewports).

- [x] [P2] [refine] topbar title has no overflow protection — will clip on longer slugs or at narrower widths — screenshot J2-topbar-1280.png
  notes: the full Gorillaz slug fits at 1280px today (~630px wide), but only barely. After badges (~240px) and menu (~120px), the remaining topbar space is ~820px. No `max-width`, `overflow: hidden`, or `text-overflow: ellipsis` is set on `.track-picker .title`. A longer slug (or browser zoom) will overflow with no graceful fallback. This is a defensive hardening gap, not a current visible defect — downgraded from P1 since the screenshot shows no actual overflow. Recommended fix: `.track-picker .title { max-width: 40ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }`.

- [x] [P2] [refine] transport zoom controls label text ("ctrl+wheel", "⇧wheel") is truncated at 1280px — screenshot J4-transport-1280.png
  notes: the `ctrl+wheel` and `⇧wheel` labels inside the zoom groups are `font-size: 9px` and appear clipped at narrow width. The `min-width: 90px` on `.time` and the `flex: 1` scrub bar absorb the squeeze well, but the zoomgrp hint labels are purely decorative and could be hidden below 1400px.

## K. Token-refactor near-misses (from Phase 0)

Carry-overs flagged during the foundation pass:

- `font-size: 9px` occurrences (7 sites in track.css) — no token; consider `--t-tiny: 9px` or rebase callers to `--t-micro: 10px`.
- `font-size: 12px` occurrences (3 sites: `#topbar`, `.tp-search input`, `#transport .time`, `.track-row .name`) — between `--t-body: 11px` and `--t-prose: 13px`; consider `--t-ui: 12px` if the size is intentional, or rebase to `--t-body`/`--t-prose`.
- `font-size: 14px` one-off (`#loading`) — likely intentional one-off; document but do not fix.
- `font-size: 16px` (`.now-card .now-time .time-num`) — promote to `--t-prose-lg` if reused.
- `font-size: 36px` (`.now-card .rn`) — promote to `--t-display-lg` if reused.
- `letter-spacing` literals at `.06em`, `.05em`, `.08em` (5 sites) — close to `--ls-caps: 0.07em` but not exact; per-context tracking. Decide: unify to one token, add a small set, or leave as design choice.
- JS canvas font hardcodes in `webui/static/js/render/pianoroll.js` (lines 166, 290, 328, 334) — Canvas 2D `ctx.font` does not accept CSS variables, so these can't be tokenized without a JS helper. Pre-existing, not from Phase 0 refactor.
- JS inline-style font hardcodes in `webui/static/js/ui/shortcuts.js:54` and `webui/static/js/ui/sidebar.js:294` — these COULD use CSS vars via `element.style.font` resolution; pre-existing.

## Triage

(user fills this section after audit complete; mark items as included/deferred)

## Deferred

(items not chosen for Phase 2 cut land here as future work)
