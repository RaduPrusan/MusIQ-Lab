# AGENTS.md

Entry-point file for any AI coding agent working on this repo (Claude CLI, OpenAI Codex CLI, Cursor, Aider, etc.). Read this **first**, then jump to the more specific docs as needed.

> If you are Claude Code specifically, **also** read [`CLAUDE.md`](CLAUDE.md) — it contains Claude-targeted instructions including the YouTube-download conversational triggers and a detailed chronological summary of every shipped feature arc.

## What this repo is

**MusIQ-Lab** — a local music-analysis + practice toolkit. Three loosely-coupled halves:

1. **Download workflow** — `yt-dlp.exe` wrapper for grabbing YouTube audio/video. Triggered conversationally (see [`CLAUDE.md`](CLAUDE.md) § "Download workflow").
2. **Music-analysis stack** (`analyze/`) — MIR pipeline producing stems, beats, key, chords, MIDI, vocal F0 from an MP3. Runs in WSL2 (Ubuntu 24.04, Python 3.11, Torch 2.7+cu126). Entrypoint `python -m analyze <mp3>`.
3. **Web UI** (`webui/`) — FastAPI + claude-agent-sdk app at `127.0.0.1:8765` for browsing analyzed tracks, live-mic overlay, and in-app chat about the current track. Runs on the Windows host (Python 3.13).

See [`README.md`](README.md) for the user-facing pitch + capability list.

## Quick orientation by file

| Need to know… | Read |
|---|---|
| What the project does, capabilities, scope, limits | [`README.md`](README.md) |
| Claude-Code-specific instructions, download workflow triggers, feature chronology | [`CLAUDE.md`](CLAUDE.md) |
| Fresh-machine install runbook (10 phases, success criteria each) | [`INSTALL.md`](INSTALL.md) |
| Analyze-stack architecture + per-stage docs | [`docs/README.md`](docs/README.md) |
| Phase-by-phase project chronology (what changed and why) | [`docs/history.md`](docs/history.md) |
| Validated executable runbook (truth-of-record for install + per-stage commands) | [`prompts/test-stack-torch27.md`](prompts/test-stack-torch27.md) |
| Production driver (analyze CLI) | [`analyze/README.md`](analyze/README.md) |
| webui FastAPI surface, setup, lifecycle helper | [`webui/README.md`](webui/README.md) |
| What's been validated, with metrics | [`install-logs/batch-test-results.md`](install-logs/batch-test-results.md) |
| Design specs for shipped features | [`docs/superpowers/specs/`](docs/superpowers/specs/) |
| Per-feature ship reports (bugs caught, lessons learned) | [`install-logs/`](install-logs/) |

## Setup on a fresh machine

The canonical install runbook is [`INSTALL.md`](INSTALL.md) — 10 phases, ~60–90 minutes wall time, dominated by ~8 GB of model downloads. **Follow it top-to-bottom; do not skip phases.**

Condensed sequence (each line maps to a phase in INSTALL.md):

```text
0. Windows prereqs: Git, Python 3.13, NVIDIA driver ≥555, ffmpeg
1. WSL2 + Ubuntu 24.04, verify wsl -- nvidia-smi works
2. Pick <PROJECT_PATH> (Windows path, no emoji / non-ASCII)
3. git clone https://github.com/RaduPrusan/MusIQ-Lab.git <PROJECT_PATH>
4. wsl -- bash <WSL_PATH>/scripts/bootstrap-wsl.sh          (analyze venv + Torch 2.7 + ~5 GB models)
5. Optional: install-bytedance-piano.sh, install-htdemucs-ft.sh, install-adtof.sh, install-larsnet.sh
6. cd webui && uv venv .venv && uv pip install -r requirements.txt
7. claude /login                                            (claude-agent-sdk auth via Claude CLI)
8. Set up yt-dlp.exe at C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe
9. End-to-end smoke test: download → analyze → view in webui
```

If you are an agent doing this install: at each phase, run the verify-command from INSTALL.md and **only continue if it passes**. The runbook's failure tables tell you what to do if it doesn't.

### AcoustID API key

The `identify` stage needs an AcoustID **Application** API key (not the personal user key — common confusion, see memory `acoustid_app_key_vs_user_key`). Register an application at https://acoustid.org/applications and set `ACOUSTID_API_KEY` in the project-root `.env` file (read by `analyze/keys.py`; `analyze/clients/acoustid.py` resolves it via `keys.get_acoustid_key()`). The `--no-identify` CLI flag disables this stage if you don't want to bother.

### Vendored components with license attention

- **LarsNet** (drum sub-stems) ships separately under CC BY-NC 4.0 — non-commercial use only. Install opt-in via `scripts/install-larsnet.sh`. See [`analyze/vendor/README.md`](analyze/vendor/README.md).
- **Chromaprint `fpcalc`** (AcoustID fingerprinting) is vendored under LGPL 2.1+. Already in [`analyze/vendor/`](analyze/vendor/).

## Daily-use commands

Once installed, the daily flow is three commands. Treat these as the canonical operations — many memory entries and the spec docs refer to them by name.

```powershell
# 1. Download (conversational in CLAUDE.md; under the hood:)
& "C:\`$WinSoft\`$tools\yt-dlp\yt-dlp.exe" `
  -x --audio-format mp3 --audio-quality 0 --no-update `
  -o 'C:/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/%(title)s-%(id)s.%(ext)s' `
  '<URL>'

# 2. Analyze (must use absolute path — see memory analyze_relative_path_bug)
wsl -- bash -lc "cd <WSL_PATH> && source .venv/bin/activate && python -m analyze '<ABSOLUTE_MP3_PATH>'"

# 3. Browse
cd <PROJECT_PATH>\webui
.\webui.ps1 start    # idempotent, logs to webui.log + webui.log.err
# or .\run.bat       # foreground, blocks the shell
# then open http://127.0.0.1:8765/
```

### webui lifecycle

```powershell
.\webui.ps1 start | stop | restart | kill | status | logs | monitor
```

The lifecycle script is the headless-control entrypoint. **Use it from agent sessions** instead of `.\run.bat` so you can keep the shell free for follow-up commands and the agent can read `webui.log` to debug.

### Re-analyzing

Two paths:
1. **From the webui's Tools → Reanalyze** button — selectively re-runs stale stages (detected via per-stage schema-version + params manifest in `webui/webui/stage_manifest.py`). Single-flight per server.
2. **From the CLI** — `python -m analyze <mp3> --from-stage <name>` or `--force` to rebuild from scratch.

## Where context lives (for an agent joining mid-project)

This codebase has accumulated multi-month context in three places:

1. **`docs/history.md`** — phase-by-phase chronology. Each major arc (vocal consensus, WASAPI engine, identify overhaul, theme tokens, live mic, etc.) has a dated section explaining what was built, what was rejected, and why.
2. **`docs/superpowers/specs/`** — design specs for shipped features. Frozen at design time + post-ship deltas appended at the bottom. Refer to these when extending a feature; do not "fix" things the spec explicitly chose.
3. **`install-logs/`** — ship reports, per-arc bug-and-lesson logs, batch-test results. Read the relevant one before touching a shipped feature's code.

If you are Claude Code specifically, the auto-memory at `~/.claude/projects/.../memory/` also contains 30+ named entries (`MEMORY.md` is the index). Common ones agents reach for:
- `live_mic_layer_shipped` — architecture of the live mic-pitch layer + the layout integration done 2026-05-24
- `theme_audit_2026_05_24` — cross-theme audit rules (stem↔fn hue pairing, drum colour theme adaptation, opacity tier patterns)
- `mic_overlay_color_buckets` — the 4-bucket colour scheme + theme integration for the mic overlay
- `wasapi_engine_v1_shipped` — Windows audio engine details
- `identify_demotion_protection` — never demote `identified=true` on transient error

## Conventions you should follow

### Code style

- **Surgical edits** are preferred over large refactors. The memory entry `feedback_surgical_changes_no_tests` notes that single-token recolors, text→icon swaps, attribute renames don't warrant a `node --test` pass — just restart the webui and let the user eyeball. **Bigger changes do warrant tests.**
- **No comments explaining WHAT** — well-named identifiers do that. Comments are for non-obvious WHYs (a hidden constraint, a workaround for a specific bug, behaviour that would surprise a reader). The preset files (`webui/static/js/theme/presets.js`) are the gold standard — every token change carries a dated comment with the *why*.
- **Theme-portability:** never hardcode hex/rgba in new CSS or inline JS — use the design tokens (`tokens.css`, `presets.js`). The audit `theme_audit_2026_05_24` shows what happens when you don't. Acceptable exception: literals already documented in `install-logs/ui-polish-2026-05-09-token-audit.md` as deliberately kept.
- **Don't bump Torch off 2.7.** `deezer/skey` pins `torch = "~2.7.0"`. Don't try to revive `allin1`. See `docs/history.md` for the rabbit hole.

### Git workflow

- **The user commits straight to `main`** on this project (no feature branches/PRs for routine work). See memory `branching_workflow`.
- **Conventional-commits style with scope** — recent commits show the convention: `feat(webui/mic): ...`, `style(webui): ...`, `fix(webui/mic): ...`, `docs(claude.md): ...`, `tweak(webui/mic): ...`.
- **Co-Authored-By trailer** for agent-made commits: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (substitute your agent's identity).
- **Commit messages explain WHY**, not WHAT — the diff shows what.

### Testing

- **Python tests:** `pytest` from the analyze venv (in WSL) or the webui venv (Windows). ~1060 tests total (~570 analyze + ~490 webui); these drift upward — `pytest --collect-only -q | tail -1` is the source of truth. On the Windows webui venv expect ~424 collected plus 4 collection errors: the `test_identify_round3/4/5` files import the analyze/WSL runtime — that's the known baseline, not a breakage you introduced.
- **Node pure-logic tests:** `cd webui && node --test tests-js/` for the JS that doesn't need a browser.
- **Playwright e2e:** `cd webui/tests-e2e && npm test` (the Playwright config + package.json live in `tests-e2e/`) — these are the visual-review and contrast-audit specs. Selectors may need updating after UI renames (e.g. today's "Claude" → "Assistant" tab rename touched `visual-review.spec.js`).

### When in doubt

- **Read before writing.** This codebase has a lot of "this was tried, here's why we don't do it that way" context. The history.md + memory entries will save you from reverting fixes.
- **Verify before claiming.** When a memory entry names a file/function/flag, grep for it before recommending. Memories are point-in-time observations; code moves on.
- **Ask the user, don't guess on irreversible or shared-state actions** (git push, force-push, destructive cache deletes, posting to external services).

## Common pitfalls (from accumulated memory)

These are the failure modes that have actually bitten in this codebase. Worth knowing before you encounter them:

| Pitfall | Memory entry |
|---|---|
| `wsl -- bash 'cd /mnt/...'` mangles the path through msys2 | `wsl_bash_dollar_quoting` |
| Passing a relative MP3 path to `python -m analyze` breaks the chords stage | `analyze_relative_path_bug` |
| ffprobe MP3 duration is byte_size÷bitrate, not decoded — cross-check via stream-copy + `soundfile.info()` if it disagrees with the player | `ffprobe_mp3_duration_not_authoritative` |
| Demucs preserves source title in every stem WAV — match `_(Stem)_` token, not free substring | `stem_filename_title_collision` |
| Low VRAM doesn't OOM on WSL2 — it silently spills to system memory and wall-time blows up 5–20× | `wsl2_sysmem_fallback` |
| `MusicExtractor(highlevel=...)` fails because PyPI Essentia is built without gaia2; low-level path works | `essentia_gaia2_gotcha` |
| AcoustID `/v2/lookup` needs the **Application** API key, NOT the personal user account key | `acoustid_app_key_vs_user_key` |
| Never demote cached `identified=true` on transient AcoustID/MB error — see `_preserve_or_write()` in `analyze/stages/identify.py` | `identify_demotion_protection` |
| The webui binds `127.0.0.1:8765`, not 8000 — don't port-scan, just hit 8765 | `webui_dev_server_port` |
| Ring-buffer pitch must be `Float32`, not `Uint8` (Uint quantizes to semitones; invisible in tests, painfully visible in the rendered contour) | `live_mic_layer_shipped` |
| Inline arrow `addEventListener` on a long-lived singleton + per-mount consumer = listener leak (mount-count subscribers) | `listener_leak_singleton_pattern` |
| EMA/IIR in `render()` re-seeds from the visible window's leftmost sample each frame — pan-shimmer. Smooth at write time or use median/FIR | `recursive_smoother_render_window` |

## Verify-before-completion

Before claiming work is done, **especially UI work**, verify the actual behaviour:
- Restart the webui (`.\webui.ps1 restart`), hard-refresh the browser (`Ctrl+Shift+R`), and *visually check* the change. The harness can't see the rendered UI; you can't either, but the user can.
- For backend work, run the relevant `pytest` subset. The full suite is slow; target the module you touched.
- For type-checking and tests pass ≠ feature works. Say so explicitly if you can't visually confirm.

This convention is logged in memory as `feedback_surgical_changes_no_tests` (the inverse: when NOT to bother running tests) — single-token swaps don't need a test pass, but anything substantive does.

## Operating the in-app chat

The webui's right-sidebar **Assistant** tab (formerly "Claude") wraps `claude-agent-sdk.ClaudeSDKClient` and exposes in-process MCP tools that let the model:
- `set_loop_region(start_sec, end_sec)`
- `highlight_stem(stem)`
- `seek_to(time_sec)`
- a dozen more — see `make_mcp_server()` in `webui/webui/chat.py`

When extending this, follow the pattern in `chat.py` (each tool is an `SdkMcpTool` entry — name, description, input schema, async handler — returning the JSON response shape the UI expects). The chat actor (`webui/webui/chat_actor.py`) speaks to the SDK via a long-lived per-track client; the tool calls render as compact chips in the chat output.

`claude-agent-sdk` bundles its own `claude.exe` per-platform — there is **no separate Claude Code install needed for the webui to chat**. See memory `claude_agent_sdk_bundled_cli`. The bundled CLI is in the wheel; you can see "Using bundled Claude Code CLI" in the runtime log.

## The repo layout in one screen

```
<PROJECT_PATH>\
├─ README.md                 ← user-facing pitch + capability list
├─ AGENTS.md                 ← (this file) agent entry point
├─ CLAUDE.md                 ← Claude-Code-specific instructions + feature chronology
├─ INSTALL.md                ← fresh-machine 10-phase runbook
├─ analyze/                  ← MIR pipeline (WSL2 venv)
│  ├─ __main__.py            ←   python -m analyze <mp3>
│  ├─ stages/                ←   per-stage modules
│  ├─ vendor/                ←   fpcalc + LarsNet weights
│  └─ README.md
├─ webui/                    ← FastAPI app (Windows venv)
│  ├─ webui/                 ←   Python package
│  │  ├─ __main__.py         ←     python -m webui (uvicorn entry)
│  │  ├─ server.py           ←     FastAPI app (webui.server:app)
│  │  ├─ chat.py             ←     MCP tool definitions (make_mcp_server)
│  │  ├─ chat_actor.py       ←     claude-agent-sdk ClaudeSDKClient actor
│  │  ├─ audio_backend/      ←     WASAPI engine
│  │  └─ stage_manifest.py   ←     stale-detection for Reanalyze
│  ├─ static/                ←   JS modules + CSS tokens + presets
│  ├─ tests-js/              ←   Node pure-logic tests
│  ├─ tests-e2e/             ←   Playwright specs
│  ├─ webui.ps1              ←   start/stop/restart/kill/status/logs/monitor
│  ├─ run.bat                ←   foreground launcher
│  └─ README.md
├─ scripts/
│  ├─ bootstrap-wsl.sh       ← idempotent analyze-stack setup
│  ├─ install-*.sh           ← optional component installers
│  └─ ...
├─ prompts/
│  └─ test-stack-torch27.md  ← THE validated runbook
├─ docs/
│  ├─ README.md              ← analyze-stack architecture
│  ├─ history.md             ← phase-by-phase chronology
│  ├─ research/              ← original design pages (frozen at design time)
│  └─ superpowers/specs/     ← per-feature design specs
├─ install-logs/             ← ship reports + batch test results
├─ tests/                    ← analyze Python tests
├─ cache/<slug>/             ← analyze output, per-track
├─ requirements.lock         ← analyze stack lock file (~150 pkgs)
└─ constraints-torch27-cu126.txt
```

## TL;DR for an agent dropping in cold

1. Read this file (you are here), then `README.md`, then `CLAUDE.md`.
2. If setting up: follow `INSTALL.md` top-to-bottom.
3. If extending a shipped feature: find the spec in `docs/superpowers/specs/` + the ship report in `install-logs/`, read both.
4. If debugging: grep memory entries for keywords related to the symptom, and check `docs/history.md` for the relevant phase.
5. Be honest about what you can't visually verify (UI changes especially). Tell the user "I changed X; please hard-refresh and confirm."
6. The user's email is `<maintainer-email>`. The repo is `https://github.com/RaduPrusan/MusIQ-Lab`. Daily work goes straight to `main`.

Welcome aboard. Make some music.
