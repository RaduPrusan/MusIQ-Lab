# MusIQ-Lab

A personal music-analysis + practice tool. Drop in a track (or grab one off YouTube), and see what's happening inside it on a single timeline: the chord progression, the stems, the vocal pitch contour, the rhythmic grid — all synced and ready to loop, mute, solo, or sing along with.

![Piano-roll overview — chord strip on top with Roman numerals + Solfège chord names; piano-roll canvas underneath with per-stem MIDI fills (vocals yellow, guitar/bass/drums coloured); a white line tracing the song's vocal pitch (F0); a magenta line tracing the user's live microphone pitch as they sing along; right sidebar with Now Playing chord, harmony stats, function distribution, cross-check across analyzers](docs/screenshots/piano-roll-overview.png)

*Billie Eilish — Billie Bossa Nova. Sol minor (G minor), 111.1 BPM, 4/4. The chord strip on top shows the progression in Roman numerals (`i7 iv7 i ♭III iv7 …`) with chord names underneath in your chosen notation system (Solfège here: Solm7, Dom7, Sib, …). The piano-roll canvas shows every transcribed note, coloured by stem. **Two pitch lines are layered on top of the canvas: the white line is the song's vocal F0 (the singer's own pitch contour, extracted offline); the magenta line is the user singing along live into their microphone, drawn in real time as the track plays.** Compare the two and you can see your intonation against the original — where they overlap you're in tune, where the magenta drifts above or below the white you're sharp or flat. The right sidebar tells you what chord is playing right now (Dom7, function: pre-dominant), where the looped section sits in the song's harmonic geography (54% tonic / 37% pre-dom / 9% modal), the vocal range (Do₂–La₆), and where the analyzers agree or disagree (here: tempo matches at ~111 BPM, key analysis disagrees — Sol minor active vs Do minor candidate).*

---

## For musicians, ear-trainers, and curious listeners

If any of these describe you, this tool was built with you in mind:

- **You want to *see* what's happening in a track.** Where the chord changes, where the drums lean, where the bass turns over. A piano-roll view of every instrument, separated.
- **You want to analyze a song musically.** What key is this in, what scale degrees does the vocal use, what's the function of each chord, where are the modal interchange moments, how does the harmonic rhythm relate to the bar structure.
- **You want to train your voice.** Sing along to the song and watch your pitch get drawn live in real time against a reference stem, coloured by how many cents off you are. The piano-roll's gutter shows you what note you're sitting on; the F0 contour shows you the singer's line.
- **You want to train your ear.** Mute the vocal, solo the bass, loop a four-bar phrase, and try to sing the bass line. Watch what you sang light up on the piano roll. Compare against the actual bass MIDI. Internalize the relationship between what you hear and where it sits on the keyboard.
- **You want to understand rhythm.** The bar grid is locked to the song. Every beat and downbeat is annotated. The drum lane shows kick / snare / toms / hi-hat / cymbals as separate streams so you can read the pattern, loop a bar, and feel where the groove lives.
- **You want to converse about songs.** Ask "what scale does the vocal use in the bridge", "loop bars 17–24 and solo guitar", "compare this chord progression to the previous track" — and the in-app assistant answers using the same analysis data you're looking at.

It is **not** a streaming service replacement (you supply the audio). It is **not** a DAW (you can't record / produce). It is **not** an automatic sheet-music transcription service (MIDI is the output format, not engraved notation). It is a **practice and analysis surface** that sits between your library and your ears.

---

## What you can actually do with it (concrete capabilities)

### Visualize what happens in a track

- **Piano-roll canvas** showing every transcribed note per stem (Vocals / Drums / Bass / Guitar / Piano / Other), coloured and rendered with semi-transparent fills so overlapping voices are still readable.
- **Chord strip** locked to the bar grid above the piano roll, in Roman numerals + your chosen notation system (Scientific or Solfège-Romance).
- **F0 overlay** showing the singer's pitch contour as a smooth line over the vocal MIDI, with confidence-bucketed rendering (high-confidence frames bold, uncertain frames faint).
- **Drum lane** with per-piece sub-stems (kick / snare / toms / hi-hat / cymbals as separate horizontal streams).
- **Now Playing card** in the sidebar that updates as you scrub — current chord (Dom7), current Roman numeral (iv7), harmonic function (pre-dominant / dominant / tonic / modal), and time position.

### Analyze musically

- **Key + scale** detection with cross-check between two analyzers (Deezer S-KEY primary + Essentia second-opinion). When they disagree, the sidebar shows both so you can decide.
- **Chord recognition** with 170–600-chord vocabularies (`lv-chordia`), Roman-numeral analysis against the detected key, and a function-distribution summary (% tonic / pre-dom / dominant / modal) for any loop region.
- **Tempo + beats + downbeats** with two-source cross-check (`madmom` for downbeats/tempo + `beat-this` for beats) so the bar grid is locked to where the song actually feels the one.
- **Vocal range** measurement and **modal interchange** detection (which chords sit outside the diatonic set and how often).
- **Per-stem MIDI** export so you can drop the vocal line into a DAW, generate a chord chart, or compare your performance to the original.

### Train your voice

- **Live mic overlay**: enable your microphone, sing along, and your pitch gets drawn live on the same canvas — coloured in 4 buckets (in-tune within 100¢ / off by more / matched-to-stem-but-silent / no reference selected).
- **Per-user latency offset** slider compensates for whatever delay your browser + audio interface introduces (Web Audio doesn't expose it, so it's tunable per setup).
- **Reference stem picker** — sing against the vocal, the bass, or any stem; the colouring reflects how far off you are from that stem's pitch at the current song time.
- **EMA-smoothed contour** so YIN's frame-to-frame shimmer doesn't make held notes look noisy.

### Train your ear

- **Mute and solo per stem** with a single click; volume sliders per stem.
- **Loop regions** — drag-to-set on the canvas; play the loop, sing it, check your transcription, repeat.
- **Sample-accurate looping** on Windows via the WASAPI engine (loops are bit-perfect at the loop boundary; no click).
- **Two notation systems** — switch globally between Scientific (C♯4) and Solfège (Do♯4) depending on what your training uses. (Enharmonic spelling — sharp vs flat — is decided upstream from the detected key, not a separate display toggle.)
- **Settings → Pitch lines** lets you tune the F0 and mic line widths + colours per theme, so visual ergonomics match how you actually study.

### Understand rhythmic structure

- **Bar numbers** painted at every downbeat on the canvas.
- **Beat ticks** at every beat under the chord strip.
- **Drum sub-stems** as separate horizontal lanes (kick row, snare row, toms, hi-hat, cymbals) so you can read the pattern visually instead of listening through them stacked.
- **Loop snapping to bar boundaries** so it's easy to grab "bars 17–24" cleanly.

### Converse about songs

- **In-app Assistant tab** (right sidebar) — chat about the current track. The model can read the chord progression, current loop, vocal range, current playhead position, and the analysis JSON. It can also call back into the UI: "set the loop to bars 17–24", "solo the guitar", "seek to 1:30" — these execute as tool calls and the UI responds.
- Powered by `claude-agent-sdk` — uses your Claude subscription (no API key needed).

---

## A typical session

1. **Find a song you want to study.** Either drop an MP3 into the project's cache folder, or use the download workflow: just paste a YouTube link to your agent and say "grab the audio from this". The tool fetches it as MP3 and stores it in your downloads folder.
2. **Analyze it.** One command (`python -m analyze <mp3>`), typically **10–20 minutes** for a 3–5 minute song on an RTX 3090 (longer for longer songs; the pipeline is roughly linear in duration once stems land). The pipeline produces stems, beats, key, chords, per-stem MIDI, vocal F0, and a reconciled summary — all stored under `cache/<slug>/`. You only pay this cost once per track; the webui reads cached artifacts instantly thereafter.
3. **Open the webui.** It shows your library; click the track. The piano-roll view loads with everything synced to the bar grid.
4. **Explore.** Mute the vocal, sing it. Loop a four-bar phrase. Switch to the Assistant tab and ask "what's the function of the chord at bar 38?" — it'll tell you it's pre-dominant moving to tonic. Enable the live mic and watch your intonation get drawn next to the singer's. Change the notation system to Solfège if you study that way.
5. **Move on to the next song.** The cache persists; you can swap between analyzed tracks instantly. The Assistant tab carries context per track.

That's the loop. Practice surface. Analysis surface. Ear-training surface. All on one timeline.

---

## A note on accuracy — what the analysis can and can't tell you

Automatic transcription of recorded music is **ill-posed** in the literal mathematical sense. When two instruments share harmonics, separating them is underdetermined; when a producer EQs information out of the mix, no model can recover it. The underlying models (htdemucs, beat-this, madmom, S-KEY, lv-chordia, FCPE, basic-pitch, …) were optimised broadly for Western pop/rock from the last 50 years — anything outside that distribution (rubato, 7/8, non-Western tunings, double-tracked or heavily processed vocals) drifts toward "best guess."

Concretely:

- **Stems bleed.** Vocals leak into Other; heavily distorted guitar ends up in Bass; "Piano" catches anything piano-shaped including Rhodes and pad synths.
- **Beat tracking falters on rubato** — ballads with elastic timing and songs that drop the "1" yield bar grids locally off by half a beat.
- **Key detection is opinion.** S-KEY and Essentia regularly disagree — the hero screenshot above shows this exact case (Sol minor vs Do minor).
- **Chord recognition hallucinates** phantom 7ths and missed inversions in dense mixes; chord boundaries drift from where the change actually happens.
- **MIDI is approximate.** HR-Piano is ~96.7% F1 on *clean isolated piano*; on a stem bleeding bass and guitar, worse. Basic Pitch misses fast passages.
- **Vocal F0** has octave errors and breath gaps; whispered, growled, or heavily processed vocals confuse all three F0 backends.
- **Drum onsets drop** in busy fills. **Identify** fails on covers, remixes, and live recordings by design — they're acoustically different works.

**What to do:**

- Trust your ear over the algorithm when they disagree — the tool is a study aid.
- Read the sidebar's CROSS-CHECK disagreements as "look here, listen harder" signals, not as bugs. Those spots are usually the musically interesting ones.
- Be sceptical at song boundaries and around tempo / time-signature changes — models do worst at edges and transitions.

This tool will not match a careful human transcription. It gives you a good first pass — usually 80–95% right — surfaced on one timeline with the audio synced to it. That's the value: **useful approximation paired with the audio it came from**, so you can verify and correct as you go.

---

## Status & honest limits

- **Validated April 2026** on 5 mixed-genre tracks (Gorillaz, Charlie Puth, NIN piano cover, etc. — see [`install-logs/batch-test-results.md`](install-logs/batch-test-results.md)). Active personal use; the live-mic, chord, key, and chat surfaces all work as advertised on the dev machine.
- **Section detection is deferred.** `allin1` (the original section-detection plan) was dropped after a NATTEN ABI incompatibility; candidate replacements are ranked in [`docs/research/tasks/07-section-analysis.md`](docs/research/tasks/07-section-analysis.md) but not yet picked.
- **Single-track pipeline.** Batch analysis is a shell loop, not a parallel scheduler. Fine for personal use; not what you'd use to crawl a 10,000-track library.
- **Offline analysis only.** The live-mic layer is the only real-time surface; the MIR pipeline itself runs offline (analyze → cache → browse).
- **Studio Light theme** has two known minor visual notes (piano-roll fills muted on cream; HC minimap overlay strength) — see [`install-logs/ui-polish-2026-05-09-results.md`](install-logs/ui-polish-2026-05-09-results.md).
- **Tuned for one machine.** Windows 11 + WSL2 Ubuntu 24.04 + RTX 3090, project at `<PROJECT_PATH>`. It's reproducible elsewhere (see the next section), but it's not packaged as a generic library.

---

# Technical stack & reproduction

The rest of this document is for someone who wants to **install the tool on their own machine** or **understand how it's built under the hood**. If you're just exploring whether the tool might be useful for you, you can stop reading here — the canvas screenshot above is what it looks like in practice.

## Architecture (three halves)

The codebase has three loosely-coupled sub-systems. You can run any one without the others; most users want all three.

| Half | What it is | Lives at | Runs on |
|---|---|---|---|
| **Download workflow** | `yt-dlp.exe` wrapper for grabbing YouTube audio/video. Triggered conversationally ("grab the audio from this link"). | Standalone binary; instructions in [`CLAUDE.md`](CLAUDE.md) | Windows host |
| **Music-analysis stack** (`analyze/`) | MIR pipeline taking an MP3 and producing stems, beats, key, chords, MIDI, vocal F0. Entry point `python -m analyze <mp3>`. | `analyze/` package | WSL2 Ubuntu 24.04, Python 3.11 + Torch 2.7+cu126, project-local `.venv/` |
| **Web UI** (`webui/`) | FastAPI app at `127.0.0.1:8765` — browsing analyzed tracks, live-mic overlay, in-app chat. | `webui/`, FastAPI + claude-agent-sdk + in-process MCP | Windows host, Python 3.13, `webui/.venv/` |

```
YouTube URL
    │  (download workflow, Windows host)
    ▼
MP3 in ~/Videos/.../Youtube/
    │  (python -m analyze, WSL2)
    ▼
cache/<slug>/
  ├─ <slug>.summary.json        ← key, tempo, chord progression, sections
  ├─ identify.json              ← AcoustID / MusicBrainz identity
  ├─ stems_6s/ (+ stems_*/)     ← 6× WAV per stem + drum sub-stems
  ├─ midi/                      ← per-stem .mid files
  ├─ madmom_downbeats.json      ← beats + downbeats + bar grid
  ├─ chords.json                ← chord timestamps + Roman-numeral analysis
  ├─ vocal_consensus.npz        ← consensus F0 contour + per-frame agreement
  └─ essentia.json              ← Essentia features
    │  (webui, Windows host; .\webui.ps1 start)
    ▼
http://127.0.0.1:8765/  ← browse, mute/solo, loop, mic, chat
```

## Technology stack

The MIR pipeline assembles a stack of specialized open-source models, each picked for the task it does best:

| Stage | Tool | Why |
|---|---|---|
| Source separation (6-stem) | **htdemucs_6s** + **BS-RoFormer** (`audio-separator`) | Best-in-class separation quality; 6 stems out (V/D/B/G/P/O). |
| Drum sub-separation | **LarsNet** (optional, CC BY-NC) | Per-piece separation for the drum lane. |
| Beats | **beat-this** | High-accuracy beat tracker. |
| Downbeats + tempo | **madmom** (from git) | Mature downbeat + tempo detector. |
| Key | **Deezer S-KEY** | Self-supervised, ICASSP 2024. CUDA. |
| Chords | **lv-chordia** | 170–600-chord vocabularies with Roman-numeral analysis. |
| Per-stem MIDI | **basic-pitch** (ONNX) | Fast, multi-instrument-capable. |
| Piano MIDI (recommended) | **ByteDance HR-Piano** (optional) | ~96.7% F1 on MAPS vs basic-pitch's ~80%. |
| Drum onsets | **ADTOF** (optional, TensorFlow) | Typed onset detection per drum piece. |
| Vocal F0 (primary) | **FCPE** (torchfcpe) | Modern transformer-based pitch tracker. |
| Vocal F0 (cross-check) | **PESTO** | Independent second opinion. |
| Vocal F0 (third opinion) | **basic-pitch** | Fused via 8-state Viterbi consensus smoother with per-frame agreement signal. |
| Acoustic identity | **Chromaprint** (`fpcalc`) + **AcoustID** + **MusicBrainz** | Canonical track ID; text-search fallback for low-quality fingerprints. |
| Audio features | **Essentia** | Tempo / key / loudness second-opinion + acoustic profile. |

The webui is FastAPI + a hand-written canvas renderer in plain JS (no React/Vue). The audio engine is WASAPI on Windows (via PortAudio + `soxr` for HQ resampling) with WebAudio fallback. The Assistant tab uses `claude-agent-sdk` with an in-process MCP server exposing UI tool calls (`set_loop_region`, `highlight_stem`, `seek_to`, etc.) so the model can drive the UI in response to natural-language requests.

The vendored model weights live at `~/.cache/audio-separator/`, `~/.cache/torch/`, `~/.cache/huggingface/`, `~/piano_transcription_inference_data/`, and `analyze/vendor/larsnet/` for LarsNet specifically. Total ~5 GB of model cache after a complete install.

## Reproducing the stack — let an agent do it

The install has multiple moving parts (WSL2 + Torch 2.7+cu126 from a specific index URL + model weights from HuggingFace + GitHub + Google Drive + `claude-agent-sdk` auth + `yt-dlp.exe` + an AcoustID API key for the `identify` stage). It is reproducible but it is not a `pip install` one-liner.

**Recommended:** hand the repo to an AI coding agent and let it follow the runbook. The cleanest install path looks like this:

1. Install **[Claude CLI](https://claude.com/claude-code)** (the CLI version of the same agent that the webui's Assistant tab uses).
2. Clone this repo and `cd` into it.
3. Open `claude` and prompt it:

   > *"Read AGENTS.md and INSTALL.md, then set up MusIQ-Lab from scratch on this machine. Stop and ask me if anything is ambiguous."*

4. The agent will follow [`INSTALL.md`](INSTALL.md) (10 phases, success-criteria at each step, idempotent bootstrap script), diagnose failures as they happen, walk you through `claude /login` for the in-app Assistant, install the optional components you want (HR-Piano for better piano MIDI, LarsNet for drum sub-stems), and run an end-to-end smoke test on a short YouTube clip.

Wall time: **~60–90 minutes** on a 200 Mbit connection, dominated by ~8 GB of model downloads. Active install time (your attention) is closer to ~15 minutes — the rest is the script downloading and verifying.

**Other agents that work:** [OpenAI Codex CLI](https://github.com/openai/codex) (`codex exec`), Cursor, Aider, any agent that respects the `AGENTS.md` convention. The runbook is agent-agnostic.

**Manual / human path:** [`INSTALL.md`](INSTALL.md) is the same content as a human-readable runbook. It assumes you can follow PowerShell + WSL commands.

## Hardware

| Resource | Minimum | Recommended | Notes |
|---|---|---|---|
| OS | Windows 10 22H2 / Windows 11 | Windows 11 | Earlier builds lack WSL2 GPU passthrough |
| GPU | NVIDIA RTX 20-series, ≥8 GB VRAM | RTX 3090 24 GB | Below 6 GB free VRAM the analyze pipeline silently spills into shared memory and slows ~5–20× — see memory entry `wsl2_sysmem_fallback` |
| RAM | 16 GB | 64+ GB | The spillover ceiling is set by system RAM |
| Disk | 30 GB free | 80 GB free | WSL venv ~10 GB, model cache ~5 GB, WSL itself ~10 GB, plus per-track cache (~50–200 MB) |
| Network | 50 Mbit | 200+ Mbit | First run downloads ~8 GB of models |

A non-NVIDIA setup is not supported — the MIR pipeline uses Torch + CUDA throughout, and Torch 2.7 is pinned by `deezer/skey`.

## Reading order for understanding the codebase

1. [`AGENTS.md`](AGENTS.md) — entry point for any AI coding agent (cross-vendor convention)
2. [`CLAUDE.md`](CLAUDE.md) — Claude-Code-specific instructions + chronological feature arcs
3. [`INSTALL.md`](INSTALL.md) — 10-phase fresh-machine setup runbook
4. [`docs/README.md`](docs/README.md) — analyze-stack architecture
5. [`docs/history.md`](docs/history.md) — phase-by-phase chronology of what changed and why
6. [`prompts/test-stack-torch27.md`](prompts/test-stack-torch27.md) — the executable, validated runbook (truth-of-record for the install)
7. [`analyze/README.md`](analyze/README.md) — production driver entrypoint
8. [`webui/README.md`](webui/README.md) — UI setup, FastAPI surface, lifecycle helper

## License

MusIQ-Lab is licensed under the **GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [`LICENSE`](LICENSE) for the full text.

Practical summary (not a substitute for the license itself):

- You may use, study, modify, and redistribute MusIQ-Lab freely.
- If you distribute a modified version, or if you make a modified version available to users over a network (the AGPL's distinguishing clause), you must make the corresponding source available under the same AGPL-3.0-or-later terms.
- The project ships **loopback-only by design** (`127.0.0.1:8765`) — see [`SECURITY.md`](SECURITY.md). The AGPL network-service clause only triggers if you choose to expose it to remote users; running it locally for yourself imposes no obligations beyond the standard GPL ones.

The vendored / pulled-in third-party dependencies carry their own licenses, listed below. None of them are redistributed through this repository — the install scripts pull them from their original sources at install time.

## Attribution

The vendored / pulled-in dependencies carry their own licenses — the ones with non-trivial terms:

- **LarsNet** drum sub-stem separation (optional) — weights are **CC BY-NC 4.0** (non-commercial only). Excluded from the install by default; opt in via `scripts/install-larsnet.sh`. See [`analyze/vendor/README.md`](analyze/vendor/README.md).
- **ByteDance HR-Piano** (optional) — recommended for the piano stem; ~96.7% F1 vs basic-pitch's ~80%.
- **htdemucs_6s / htdemucs_ft** (Demucs by Facebook AI Research) — MIT.
- **BS-RoFormer** (audio-separator project) — Apache 2.0.
- **beat-this**, **madmom**, **basic-pitch**, **FCPE**, **PESTO**, **Essentia**, **deezer/skey**, **lv-chordia**, **ADTOF**, **acoustid + MusicBrainz client libs** — each carries its own permissive license; the install pulls them from PyPI / git per `requirements.lock`.
- **Chromaprint `fpcalc`** (vendored binary for AcoustID fingerprinting) — LGPL 2.1+. See [`analyze/vendor/`](analyze/vendor/).

The full transitive dependency tree is captured in [`requirements.lock`](requirements.lock) (analyze stack, ~150 packages) and [`webui/requirements.lock`](webui/requirements.lock).
