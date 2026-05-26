# UI Polish — Independent Playwright Verification (2026-05-09)

## Verdict

✅ Promise delivered

All four promises — professional polish, full themability via Settings, localStorage persistence under `musiq.theme`, and four distinct presets — are confirmed delivered by live browser testing against the running webui at `127.0.0.1:8765`. Every check in the checklist passed. The console was completely clean (zero errors, zero warnings) across the entire session.

## Test summary

| # | Check | Outcome |
|---|---|---|
| 1 | Default Classic Dark loads cleanly | ✅ |
| 2 | Settings → Appearance exists (4 preset cards + Customize button) | ✅ |
| 3 | All 4 presets switch live (Classic Dark, Midnight, Studio Light, High Contrast) | ✅ |
| 4 | Color picker + alpha slider apply live | ✅ |
| 5 | Customizations persist across reload (`localStorage["musiq.theme"]`) | ✅ |
| 6 | Copy theme JSON works (clipboard contains valid preset/tokens/locks) | ✅ |
| 7 | Reset to preset works | ✅ |
| 8 | Console clean (no Uncaught / red errors) | ✅ |

## Findings

- **Classic Dark (default):** Dark surfaces with an orange (#ffb86b) accent. Coherent dark music UI with piano roll, mixer sidebar, chord panel all visually unified. No mismatched borders or off-color edges observed. `localStorage["musiq.theme"]` is null on a clean first load, which is correct (default applies without touching storage).

- **Midnight:** Noticeably different from Classic Dark — the modal background shifts to a cooler dark-navy tone and the overall surface hue becomes slightly bluer. The difference is real but subtle; both are dark themes, which is appropriate.

- **Studio Light:** Genuinely light — white modal background, dark text, light-grey piano roll canvas. The full sidebar panel renders dark text on light surfaces. Not just a tinted dark theme; it is a real light theme inversion. Confirmed distinct from all dark variants.

- **High Contrast:** Near-black canvas background with aggressively saturated stem colors and bright chip labels (cyan, yellow, green). The Function bar and chord tags render with high-saturation fills. Clearly distinct from all other presets.

- **Accent color picker (magenta test):** Setting accent to `#ff00ff` via programmatic `input` event caused immediate live repainting across the topbar, piano roll pitch ruler, octave markers, the selection border on the Classic Dark preset card, and the SRC playback button. The entire CSS custom property cascade updated without a page reload.

- **Alpha-scrim slider:** Raising `alpha-scrim` from 0.55 to 0.9 visibly darkened the backdrop behind the Settings modal, confirming the transparency tokens are wired to live CSS variables.

- **Persistence confirmed:** After closing Settings with accent=#ff00ff and alpha-scrim=0.9, `localStorage["musiq.theme"]` contained valid JSON: `{"v":1,"preset":"custom","_basePreset":"classic-dark","tokens":{...,"accent":"#ff00ff","alpha-scrim":"0.9",...},"locks":{...}}`. On full page reload the magenta accent was already applied with no flash of Classic Dark — persistence is seamless.

- **Copy theme JSON:** The button calls `navigator.clipboard.writeText` with 2,625-character JSON containing `preset`, `tokens`, and `locks` fields. **Minor caveat:** the copied JSON does not include the `v` version field (present in localStorage but omitted from the clipboard payload). This does not break functionality but is a minor inconsistency worth noting.

- **Reset to preset:** Clicking "Reset to Classic Dark" immediately reverted all tokens — `accent` snapped back to `#ffb86b`, `alpha-scrim` back to `0.55`, and `preset` changed from `"custom"` to `"classic-dark"`. Visual repaint was instant.

- **Console:** Zero console errors and zero warnings captured across the full session (all preset switches, customize panel interactions, reload, reset).

## Caveats / things you couldn't test

- **Clipboard readback in headless mode:** `navigator.clipboard.readText()` returned stale data from the test harness (a screenshot filename), not the theme JSON. The Copy theme JSON test was verified by intercepting `navigator.clipboard.writeText` before the button click instead of reading back after. The button does call `writeText` with correct JSON; whether it reaches the OS clipboard in a non-headless context could not be independently confirmed in this environment.

- **ASIO audio engine:** The ASIO option in Settings is greyed out ("coming r1") — not testable.

- **WebAudio playback:** Audio playback (play button, MIX/SRC switching) was not exercised as it is out of scope for the UI polish verification.

- **Midnight vs Classic Dark visual delta:** The two dark themes look similar in screenshots. Both are intentionally dark; Midnight applies a cooler hue/surface palette. The distinction is real but not dramatic — considered correct design behaviour, not a bug.
