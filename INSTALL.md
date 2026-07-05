# MusIQ-Lab — Install from scratch on a fresh Windows

This guide takes you from a freshly installed Windows machine to a working
MusIQ-Lab stack: download workflow + webui + music-analysis pipeline.

**Audience:** an agent (or human) following commands top-to-bottom on a
machine where nothing is installed yet beyond Windows itself.

**Run phases in order.** If a phase fails, stop and diagnose — do not skip
ahead. Each phase has explicit success criteria; verify them before moving
on.

---

## Hardware assumptions

| Resource | Minimum | Recommended | Notes |
|---|---|---|---|
| OS | Windows 10 22H2 / Windows 11 | Windows 11 | Earlier builds lack WSL2 GPU passthrough |
| GPU | NVIDIA RTX 20-series, ≥8 GB VRAM | RTX 3090 24 GB | Below 6 GB free VRAM the analyze pipeline silently spills into shared memory and slows ~5–20×; see `docs/research/pipeline.md` § "WSL2 + NVIDIA Sysmem Fallback caveat" |
| RAM | 16 GB | 64+ GB | The spillover ceiling is set by system RAM; 96 GB on the dev machine means VRAM exhaustion is effectively unreachable |
| Disk | 30 GB free | 80 GB free | WSL venv ~10 GB, model cache ~5 GB, WSL itself ~10 GB, plus space for analyzed tracks |
| Network | Steady 50 Mbit | 200+ Mbit | First run downloads ~8 GB of models (settles to ~5 GB resident cache) |

**Total wall time** to follow this guide on a 200 Mbit connection: ~60–90
minutes, dominated by model downloads in Phase 4.

---

## Layout — what gets installed where

The project has three sub-systems with different install footprints:

| Sub-system | Runs on | Python env | Path |
|---|---|---|---|
| analyze stack | WSL2 (Linux) | Python 3.11 + Torch 2.7/cu126 in `.venv/` (project root) | `/mnt/<drive>/path/to/MusIQ-Lab/.venv/` |
| webui | Windows (host) | Python 3.13 + claude-agent-sdk in `webui/.venv/` | `…\MusIQ-Lab\webui\.venv\` |
| download workflow | Windows (host) | yt-dlp.exe binary, no venv | `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe` |

You will set up all three in this guide.

---

## Phase 0 — Windows-side prerequisites

Install these on Windows before touching WSL. **All require admin.**

### 0.1 Git for Windows

Download from https://git-scm.com/download/win and install with defaults.
Verify in PowerShell:

```powershell
git --version
```

Success: prints `git version 2.x.x` or higher.

### 0.2 Python 3.13 (for the webui)

Download from https://www.python.org/downloads/ and install **with "Add
python.exe to PATH" checked**. The installer's standard "for all users"
+ pip + py launcher options are correct.

Verify:

```powershell
python --version
pip --version
```

Success: Python 3.13.x and pip both report.

### 0.3 NVIDIA driver

If you don't already have a recent NVIDIA driver (Game Ready Driver
≥555 or Studio Driver ≥555 — anything from 2024 onwards is fine), download
from https://www.nvidia.com/Download/index.aspx and install.

Verify in PowerShell:

```powershell
nvidia-smi
```

Success: the table shows your GPU, driver version, and CUDA version (the
"CUDA Version" column shows the *driver-supported* CUDA, not what's
installed — that's normal). The driver supplies WSL2's CUDA passthrough;
you do NOT need to install CUDA Toolkit on Windows.

### 0.4 ffmpeg (system-wide PATH)

The webui's reanalyze button stages MP3s through ffmpeg. Easiest install
via winget (built into Windows 11):

```powershell
winget install Gyan.FFmpeg
```

Then **restart your PowerShell session** (or sign out/in) so the new PATH
is picked up. Verify:

```powershell
ffmpeg -version
```

Success: prints `ffmpeg version N-XXXXX-...`.

---

## Phase 1 — Install WSL2 + Ubuntu 24.04

Open PowerShell **as Administrator**:

```powershell
wsl --install --distribution Ubuntu-24.04
```

This single command:
- Enables the WSL feature
- Installs the WSL2 kernel
- Downloads and installs Ubuntu 24.04
- Drops you into the Ubuntu setup at first login

You will be prompted to **reboot** after the kernel installs. Reboot, then
re-open PowerShell as Administrator and run the install command again to
finish if it didn't complete on the first pass.

After reboot, Ubuntu's first-run wizard asks for a UNIX username and
password. Pick anything; this account is local to the WSL distribution.

Verify from Windows PowerShell (no admin needed after install):

```powershell
wsl -l -v
```

Success: shows `Ubuntu-24.04` with `STATE: Running` and `VERSION: 2`.

### 1.1 Verify GPU passthrough into WSL

From Windows PowerShell:

```powershell
wsl -- nvidia-smi
```

Success: same table as Phase 0.3, but reported from inside Ubuntu. If this
fails but `nvidia-smi` works on the Windows side, your driver is too old —
install the latest from https://www.nvidia.com/Download/index.aspx.

---

## Phase 2 — Decide where the project lives

The repo will be cloned to a Windows path. Pick a location on a
non-system drive if possible (the analyze cache will grow to a few GB
per analyzed track). The dev machine used a project-local `.venv`,
but any path works as long as you are consistent.

**Constraint:** the path should NOT contain WSL-incompatible characters.
Spaces, parentheses, and ASCII punctuation are fine (WSL exposes them via
`/mnt/<drive>/<path>` with literal characters preserved). Avoid emoji or
non-ASCII characters.

For the rest of this guide, the placeholder `<PROJECT_PATH>` means the
Windows path you chose, and `<WSL_PATH>` means the same path translated to
WSL. Examples:

| Windows path | WSL path |
|---|---|
| `F:\Projects\MusIQ-Lab` | `/mnt/f/Projects/MusIQ-Lab` |
| `D:\Code\MusIQ-Lab` | `/mnt/d/Code/MusIQ-Lab` |
| `C:\Users\me\repos\MusIQ-Lab` | `/mnt/c/Users/me/repos/MusIQ-Lab` |

---

## Phase 3 — Clone the repository

From Windows PowerShell:

```powershell
cd <parent of where you want the repo>
git clone https://github.com/RaduPrusan/MusIQ-Lab.git
```

(The repo is public per the project's notes; no auth needed.)

Verify:

```powershell
cd MusIQ-Lab
ls
```

Success: see `analyze\`, `webui\`, `scripts\`, `prompts\`, `docs\`,
`README.md`, `CLAUDE.md`, `requirements.lock`, `requirements-linux-cu126.txt`,
`constraints-torch27-cu126.txt`. **The presence of `requirements.lock`
and `constraints-torch27-cu126.txt` is essential** — the bootstrap script
expects them and will refuse to run without them. If they're absent, your
clone is incomplete; re-clone.

---

## Phase 4 — Bootstrap the analyze stack (WSL)

This is the heaviest phase. Wall time: ~30–45 minutes (~8 GB of
downloads).

The repo's `scripts/bootstrap-wsl.sh` is **idempotent** and wraps Phases 1,
2, 3, and 4 of `prompts/test-stack-torch27.md` in one runnable script:

- **Phase 1 inside the script:** apt deps (build-essential, ffmpeg,
  libsndfile, vamp-plugin-sdk, …). Will sudo and prompt for your WSL user
  password.
- **Phase 2 inside the script:** uv installer + Python 3.11 via uv.
- **Phase 3 inside the script:** Torch 2.7.1+cu126 + the MIR stack
  (delegated to `setup-venv.sh`). Writes `requirements.lock`.
- **Phase 4 inside the script:** pre-warm model checkpoints (audio-separator
  for BS-RoFormer + htdemucs_6s, beat-this `final0`, torchfcpe bundled,
  basic-pitch).

**Run from Windows PowerShell** (the `wsl` command auto-routes into your
default Ubuntu distribution):

```powershell
wsl -- bash "<WSL_PATH>/scripts/bootstrap-wsl.sh"
```

Or, equivalently, from inside WSL (`wsl` in PowerShell drops you into a
shell):

```bash
cd <WSL_PATH>
./scripts/bootstrap-wsl.sh
```

You will be prompted for your WSL user's password once (sudo for apt). The
rest is non-interactive. Output is verbose; expect to see Torch wheels
download, then a hundred or so other packages, then the model pre-warm
section.

### 4.1 Verify

After the script finishes, from Windows PowerShell:

```powershell
wsl -- bash -lc "cd <WSL_PATH> && source .venv/bin/activate && python -c 'import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))'"
```

Success: prints something like `2.7.1+cu126 True NVIDIA GeForce RTX 3090`.

Then verify the analyze package itself imports:

```powershell
wsl -- bash -lc "cd <WSL_PATH> && source .venv/bin/activate && python -m analyze --help"
```

Success: prints the analyze CLI's help output (positional `mp3_path`, `--stems-quality`, `--from-stage`, `--stages-only`, `--params-json`, `--force`).

### 4.2 If the bootstrap fails

Common failure modes and where to look:

| Symptom | Diagnosis | Fix |
|---|---|---|
| `apt-get install` hangs at "Reading package lists" | Ubuntu mirror unreachable | `sudo apt-get update` manually, or change mirror in `/etc/apt/sources.list` |
| `uv: command not found` after install | uv didn't add itself to PATH | `source $HOME/.local/bin/env` then re-run |
| Torch downloads but `cuda.is_available()` is False | Wrong wheel pulled (CPU-only) | Wipe `.venv/` and re-run with `--force`; verify `--index-url https://download.pytorch.org/whl/cu126` is present in the install log |
| `madmom` build fails with Cython errors | Python wheel build env incomplete | Confirm `build-essential` is installed via apt; the script handles this but if it's been clobbered, `sudo apt-get install build-essential cython3` |
| `lv-chordia` complains about `pumpp` or `mir-eval` | Older deps need force-reinstall | `pip install --upgrade --no-cache-dir lv-chordia mir-eval pumpp` inside the venv |
| Phase 4 model pre-warm fails on a single model | Network blip during HF/GitHub download | Re-run `bootstrap-wsl.sh`; idempotent, will skip already-installed bits and retry just the failed download |

If any failure is unrecoverable: wipe `.venv/`, `requirements.lock`, and
`install-logs/` and start Phase 4 over with `bootstrap-wsl.sh --force`.

---

## Phase 5 — Optional analyze components

These three components are not required for the core pipeline but enable
specific stages (piano transcription, finer drum stems, drum onsets).
**Install them now** if you want the full analyze surface; skip if you
only need basic separation + chords + beats.

### 5.1 ByteDance HR-Piano (recommended)

Required for the piano-stem transcription stage. Without it, piano
transcription falls back to basic-pitch (~80% F1 on MAPS vs HR-Piano's
~96.7%). Wall time: ~3 minutes (~165 MB weights download).

```powershell
wsl -- bash "<WSL_PATH>/scripts/install-bytedance-piano.sh"
```

Success: prints `OK: ByteDance HR-Piano loaded and ran on 1s silence.`

### 5.2 htdemucs_ft pre-warm (recommended)

Pre-downloads the htdemucs_ft 4-stem model so the first analyze run isn't
dominated by a 100+ MB download. The model is part of the default stem
ensemble for `--stems-quality normal` and `best`; without it, analyze will
download it on first run (~3 min one-time delay).

```powershell
wsl -- bash "<WSL_PATH>/scripts/install-htdemucs-ft.sh"
```

Success: prints `OK: htdemucs_ft is installed and produces all 4 stems
(Vocals/Drums/Bass/Other).`

### 5.3 ADTOF (optional — drum onset detection)

Required for the drum onset detection sub-stage. Skip if you don't care
about drum analysis. Wall time: ~5 minutes.

```powershell
wsl -- bash "<WSL_PATH>/scripts/install-adtof.sh"
```

Success: prints `OK: ADTOF is installed, importable, and Torch 2.7 is intact.`

If the install fails with a dependency conflict, the script exits cleanly
with a `BLOCKED` diagnostic — see the script's stderr for the conflict
details. ADTOF is TensorFlow-based, not Torch-based, so it should not
conflict with the Torch 2.7 pin.

### 5.4 LarsNet (optional — drum sub-stem separation)

Required for the per-drum-piece sub-stems (kick/snare/toms/hihat/cymbals)
shown in the webui's drum lane. Skip if you don't need the visualization.
Wall time: ~2 minutes (~562 MB weights download from Google Drive).

**License note:** LarsNet weights are CC BY-NC 4.0 — non-commercial use
only.

```powershell
wsl -- bash "<WSL_PATH>/scripts/install-larsnet.sh"
```

Success: prints `LarsNet installed: <size> at <path>`.

If the Google Drive download fails (the script extracts a confirm token
from a warning page that occasionally rotates), the script reports the
manual download URL — fetch the zip, place it at
`<WSL_PATH>/analyze/vendor/larsnet/larsnet_weights.zip`, and re-run the
script.

---

## Phase 6 — Set up the webui (Windows side)

The webui has its own Python venv on the **Windows side** (Python 3.13).
It is not the same venv as the analyze stack — keep them separate.

### 6.1 Install uv on Windows (if not already)

uv is the fastest way to set up the webui venv. From PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After install, **restart your PowerShell session** so the new PATH is
picked up. Verify:

```powershell
uv --version
```

If you prefer not to install uv, the manual `python -m venv` + `pip
install` path also works — substitute accordingly below.

### 6.2 Create the webui venv

From PowerShell, in the project root:

```powershell
cd <PROJECT_PATH>\webui
uv venv .venv
uv pip install -r requirements.txt
uv pip freeze > requirements.lock
```

Wall time: ~2 minutes.

Success: `.venv\` exists, `.venv\Scripts\python.exe` runs, `requirements.lock`
is written.

### 6.3 First boot

```powershell
.\run.bat
```

This launches the FastAPI server bound to `127.0.0.1:8765` and opens your
default browser to it.

Success: the browser opens to a "Tracks" page. If you have no analyzed
tracks yet, the page will be empty — that's expected (smoke test in Phase
9 will populate one).

If the browser doesn't auto-open, navigate manually to
http://127.0.0.1:8765/.

Stop the server with `Ctrl+C` in the PowerShell window where you launched
it, or use the lifecycle manager:

```powershell
.\webui.ps1 stop
```

---

## Phase 7 — Authenticate claude-agent-sdk for the Assistant tab

The webui's "Assistant" sidebar tab (renamed from "Claude" 2026-05-24; tab id is still `claude` internally for backwards compatibility with persisted state) uses `claude-agent-sdk` to talk to the Claude API. It authenticates via your existing Claude Code login (Pro/Max
subscription); **no API key required**.

### 7.1 Install Claude Code (if not already)

If you don't already have Claude Code installed (the CLI for chatting
with Claude that this guide is being followed inside), install per
https://docs.claude.com/en/docs/claude-code/getting-started.

### 7.2 Log in

From any PowerShell window:

```powershell
claude /login
```

Follow the browser-based OAuth flow. The credentials persist to your
user profile and are picked up automatically by the webui's
`claude-agent-sdk` integration.

### 7.3 Verify

Boot the webui again (`.\run.bat` from `webui\`), open any analyzed
track (if you have one), and click the **Assistant** tab in the sidebar
(the right-most tab). It should show a chat input rather than a
"signed out" message.

If it shows "signed out" despite a successful `claude /login`, click
**Retry** — the SDK occasionally needs a nudge to re-read credentials.

---

## Phase 8 — yt-dlp for the download workflow

The download workflow uses a standalone `yt-dlp.exe` binary. The dev
machine keeps it at `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe` — that path is
hardcoded in `CLAUDE.md`. **Match that exact path** so the project's
download instructions work without modification.

### 8.1 Create the directory

From PowerShell **as Administrator**:

```powershell
New-Item -ItemType Directory -Path "C:\`$WinSoft\`$tools\yt-dlp" -Force
```

(The backticks escape the literal `$` characters for PowerShell.)

### 8.2 Download yt-dlp.exe

```powershell
Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile "C:\`$WinSoft\`$tools\yt-dlp\yt-dlp.exe"
```

### 8.3 Verify

```powershell
& "C:\`$WinSoft\`$tools\yt-dlp\yt-dlp.exe" --version
```

Success: prints a date-coded version string like `2026.05.10`.

### 8.4 Create the default download folder

```powershell
New-Item -ItemType Directory -Path "C:\Users\$env:USERNAME\Videos\Any Video Converter Ultimate\Youtube" -Force
```

(This is the folder yt-dlp will write to per the `CLAUDE.md` defaults.
The "Any Video Converter Ultimate" subdirectory naming is historical;
keeping it preserves consistency with the existing project setup.)

---

## Phase 9 — End-to-end smoke test

Now verify the three sub-systems work together on a real track.

### 9.1 Download a short test track

Pick a short YouTube video (under 1 minute is ideal). Use yt-dlp's
project-default invocation. From any shell on Windows that supports
single-quoting (PowerShell or Git Bash):

```powershell
& "C:\`$WinSoft\`$tools\yt-dlp\yt-dlp.exe" `
  -x --audio-format mp3 --audio-quality 0 `
  --no-update `
  -o 'C:/Users/$env:USERNAME/Videos/Any Video Converter Ultimate/Youtube/%(title)s-%(id)s.%(ext)s' `
  '<YOUTUBE_URL>'
```

Success: an MP3 file appears under
`C:\Users\<you>\Videos\Any Video Converter Ultimate\Youtube\` named
`<title>-<11-char-video-id>.mp3`.

If yt-dlp errors with `403 Forbidden` or "older than 90 days", run
`yt-dlp.exe -U` first then retry.

### 9.2 Analyze the track

From Windows PowerShell:

```powershell
wsl -- bash -lc "cd <WSL_PATH> && source .venv/bin/activate && python -m analyze '/mnt/c/Users/$env:USERNAME/Videos/Any Video Converter Ultimate/Youtube/<TRACK>.mp3'"
```

(Adjust the path to match what yt-dlp produced. The literal `<TRACK>.mp3`
should be the actual filename including the `-<id>` suffix.)

Wall time: typically **10–20 minutes** for a 3–5 minute song on an RTX
3090 (a sub-1-minute clip lands closer to 3–5 minutes since several
stages have fixed overhead). It scales roughly linearly with track
duration once stem separation completes. Variance comes from GPU
availability, free VRAM (drops below 6 GB and the pipeline silently
spills into shared memory — see the memory note in
`MEMORY.md:wsl2_sysmem_fallback`), and how many of Phase 5's optional
components you installed.

The pipeline streams stage progress as it runs (`==> Stage stems:
running`, etc.). Watch for any stage that reports `Stage <name>
soft-failed` — the pipeline will continue but the corresponding output
will be missing or stubbed.

Success criteria:
- Process exits with code 0
- `cache/<slug>/` exists under the project root
- `cache/<slug>/<slug>.summary.json` is present and parseable JSON
- `cache/<slug>/midi/` contains at least `vocals.mid`, `bass.mid`,
  `guitar.mid`, `other.mid` (and `piano.mid` if HR-Piano is installed)

### 9.3 View the track in the webui

Boot the webui:

```powershell
cd <PROJECT_PATH>\webui
.\run.bat
```

The browser should open to the Tracks page and show the track you just
analyzed. Click it.

Success criteria:
- Piano-roll renders with notes per stem
- Transport plays audio (click anywhere on the canvas)
- Stems list shows mute/solo controls
- Sidebar tabs (Track / Lyrics / Assistant) all switch correctly
- Assistant tab shows a chat input (not "signed out")

If anything is off, check `webui\webui.log` and `webui\webui.log.err` for
the FastAPI server's output.

---

## Phase 10 — What's done

Once Phase 9 passes, you have:

- A working analyze pipeline at `<PROJECT_PATH>\.venv\` (Linux side, via
  WSL2)
- A working webui at `<PROJECT_PATH>\webui\.venv\` (Windows side, on
  127.0.0.1:8765)
- A working download workflow at
  `C:\$WinSoft\$tools\yt-dlp\yt-dlp.exe`
- All required model checkpoints cached locally (~5 GB across
  `~/.cache/audio-separator/`, `~/.cache/torch/`,
  `~/.cache/huggingface/`, `~/piano_transcription_inference_data/`,
  and `<PROJECT_PATH>\analyze\vendor\larsnet\` if Phase 5.4 ran)

Daily-use pattern:

```powershell
# 1. Download
& "C:\`$WinSoft\`$tools\yt-dlp\yt-dlp.exe" -x --audio-format mp3 --audio-quality 0 --no-update -o '...' '<URL>'

# 2. Analyze
wsl -- bash -lc "cd <WSL_PATH> && source .venv/bin/activate && python -m analyze '<MP3_PATH>'"

# 3. Browse
cd <PROJECT_PATH>\webui
.\webui.ps1 start
# (or .\run.bat for foreground)
```

The webui can also kick off re-analysis from its **⚒ Tools → Reanalyze**
button — it shells into WSL automatically and streams stage progress into
a modal.

---

## Reproducibility

`<PROJECT_PATH>\requirements.lock` (analyze stack, ~150 packages) and
`<PROJECT_PATH>\webui\requirements.lock` (webui, smaller) are checked into
the repo. To reproduce a known-good install on a different machine, you
can replace the requirements file content with these locks and re-run the
bootstrap.

For the analyze stack specifically, do **not** bump Torch off 2.7 —
`deezer/skey` pins `torch = "~2.7.0"` and the resolver will fight any
attempt to move. See `prompts/test-stack-torch27.md` § "Compatibility
decisions" for the full list of pins that must not be touched.

---

## Troubleshooting cross-reference

| Issue | Where to look |
|---|---|
| Analyze stage fails with CUDA OOM (Linux) | Won't happen on WSL2 — see `docs/research/pipeline.md` § "WSL2 + NVIDIA Sysmem Fallback caveat". On WSL2, low VRAM produces 5–20× wall-time inflation, not crashes |
| Analyze stage takes 10× longer than documented | Almost certainly WSL2 sysmem-fallback spillover. Check Windows Task Manager → Performance → GPU → "Shared GPU memory". Close other GPU consumers (browser hardware accel, ComfyUI with model loaded) |
| `audio-separator` model truncates output mid-track | Known libsndfile MP3-header bug; the pipeline transcodes to clean WAV via ffmpeg first to avoid it. If you bypass the pipeline and call audio-separator directly, this can bite you |
| `python -m analyze` errors with "no piano stem in routing" | Stems stage may have failed silently. Re-run with `--from-stage stems` to force regeneration |
| webui shows blank tracks page | Tracks scanner couldn't find any analyzed tracks. Confirm the analyze run wrote to `<PROJECT_PATH>\cache\<slug>\<slug>.summary.json` |
| webui's Reanalyze button hangs | The WSL subprocess is single-flight per server — only one reanalysis at a time. If a previous run hung, restart the webui (`.\webui.ps1 restart`) |
| Assistant tab (formerly "Claude") shows "signed out" after `claude /login` | Click the Retry button in the chat panel; the SDK occasionally needs a re-read of credentials |
| yt-dlp fails on signed-in / age-gated content | This guide covers public videos only; signed-in content needs cookies — see yt-dlp's `--cookies-from-browser` option |

---

## Updating the install in the future

The bootstrap script is idempotent. To pull the latest version of the
project:

```powershell
cd <PROJECT_PATH>
git pull
wsl -- bash "<WSL_PATH>/scripts/bootstrap-wsl.sh"
cd webui
uv pip install -r requirements.txt
```

If the analyze stack's requirements have meaningfully changed (lock-file
diff is large), force a clean rebuild:

```powershell
wsl -- bash "<WSL_PATH>/scripts/bootstrap-wsl.sh" --force
```

The `--force` flag wipes `.venv/` and rebuilds from scratch — about 30
minutes wall time, but guaranteed-clean.
