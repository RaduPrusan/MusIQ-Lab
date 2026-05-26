# MusIQ-Lab — Music Analysis Documentation

> ⚠️ **Read [`history.md`](history.md) before this document.** The original design documents were partially superseded after a validation run in April 2026: `allin1` was dropped (NATTEN ABI + RPB removal incompatibilities), `madmom` from git replaced its downbeat/tempo role, `beat-this` is now the canonical beat tracker (not a cross-check), and section detection is deferred. The truth-of-record for the install + per-stage commands is `../prompts/test-stack-torch27.md`. The per-task pages under [`research/tasks/`](research/tasks/) have now been retrofitted to match the validated stack (each carries its own dated banner); the higher-level design pages under [`research/`](research/) (`pipeline.md`, `recommended-stack.md`, `installation.md`, `output-format.md`, `cross-validation.md`) remain frozen at design time and are kept for the *why* behind each choice, not as install instructions.

This documentation describes the music-analysis pipeline of the Youtube project: a script that takes an MP3 (typically downloaded via `yt-dlp`) and produces a structured analysis suitable for **educational study and practice** — chord progressions with timestamps, beat/downbeat grids, tempo, key, ~~section structure~~ (deferred), per-instrument note transcriptions, and vocal melody pitch contours.

The pipeline is designed for use **on this machine specifically** (WSL2 Ubuntu 24.04, RTX 3090, project at `<PROJECT_PATH>`). Output is intentionally **Claude-CLI readable** so you can converse about songs (e.g. "what scale does the vocal use in the chorus?", "compare the harmony of these two songs") without needing a DAW.

## Reading order

The docs are organised so you can read top-down (concept → implementation) or jump to a specific task.

- [`history.md`](history.md) — chronology of what changed since the initial design; **start here** if revisiting after April 2026
- [`../prompts/test-stack-torch27.md`](../prompts/test-stack-torch27.md) — the executable, validated runbook (install + per-stage commands)

### Higher-level design pages (`research/`) — frozen at design time

These pages reflect the pre-validation design and still reference `allin1` throughout. They are kept for the *why* behind each architectural choice, not as install instructions. Per-task pages (`research/tasks/0X-*.md`) have been retrofitted separately and lead with the actual current stack.

1. [`research/pipeline.md`](research/pipeline.md) — overall architecture, design principles, data flow
2. [`research/recommended-stack.md`](research/recommended-stack.md) — the recommended toolset with rationale, what was rejected and why (allin1 entry is now historical)
3. [`research/installation.md`](research/installation.md) — original system + Python environment setup. **Use the runbook above instead** for the validated install.
4. [`research/output-format.md`](research/output-format.md) — JAMS file structure + `summary.json` schema
5. [`research/cross-validation.md`](research/cross-validation.md) — how Claude orchestrates and reconciles tool outputs

## Per-task references

Each pipeline stage has its own detailed page with options, install commands, usage examples, accuracy notes, and caveats. Each starts with the **recommended pick** and then lists alternatives.

> Two production stages added after the original design — **`identify`** (AcoustID + MusicBrainz canonical identity, May 2026, overhauled across five rounds; spec [`superpowers/specs/2026-05-12-identify-pipeline-overhaul.md`](superpowers/specs/2026-05-12-identify-pipeline-overhaul.md)) and **`essentia_extract`** (Essentia second-opinion on tempo / key / loudness) — have no entries under `research/tasks/`. Their truth-of-record is the analyze code + `history.md` Phase Q.

- [`research/tasks/01-stem-separation.md`](research/tasks/01-stem-separation.md) — vocals / drums / bass / other (or 6-stem)
- [`research/tasks/02-beats-downbeats-tempo.md`](research/tasks/02-beats-downbeats-tempo.md) — `madmom` (downbeats/tempo) + `beat-this` (beats); historical `allin1` rationale preserved at the bottom of the page
- [`research/tasks/03-key-detection.md`](research/tasks/03-key-detection.md) — Deezer S-KEY (self-supervised, ICASSP 2024). Entry point is `skey.key_detection.detect_key(audio, device='cuda', cli=False)`.
- [`research/tasks/04-chord-recognition.md`](research/tasks/04-chord-recognition.md) — `lv-chordia` (170–600 chord vocabulary). Kwarg is `chord_dict_name=`; no `python -m` CLI.
- [`research/tasks/05-polyphonic-transcription.md`](research/tasks/05-polyphonic-transcription.md) — Basic Pitch per stem
- [`research/tasks/06-vocal-f0.md`](research/tasks/06-vocal-f0.md) — FCPE primary, PESTO cross-check; Phase 0c (May 2026) layered an 8-state Viterbi consensus smoother on top with per-frame agreement_strength for confidence-bucketed UI rendering. See [`superpowers/specs/2026-05-05-vocal-consensus-improvements.md`](superpowers/specs/2026-05-05-vocal-consensus-improvements.md) and [`../install-logs/phase-0c-results-2026-05-05.md`](../install-logs/phase-0c-results-2026-05-05.md)
- [`research/tasks/07-section-analysis.md`](research/tasks/07-section-analysis.md) — **deferred**: candidate replacements ranked (librosa recurrence → MSAF → revived allin1 → SongFormer)

## References

- [`research/references.md`](research/references.md) — papers, GitHub repos, citations

## Conventions

- **Recommended** picks are prefixed with ✅ and listed first.
- **Alternative** picks marked ↳ with notes on when to prefer them.
- **Experimental / research-quality** picks marked 🧪 (use at your own risk; packaging immature).
- All install commands assume the project's project-local `.venv/` is activated and you're inside WSL.
- Paths in commands use the WSL view (`/mnt/f/...`); the same files appear under `F:\...` from Windows.

## Quick start

```bash
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
python -m analyze "/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/<song>.mp3"
```

This produces `cache/<slug>/<slug>.jams` (full multi-track annotation, ~9 MB for a 3.5-min track) and `cache/<slug>/<slug>.summary.json` (compact educational digest with Roman numerals, scale, chord loop, per-note role/in_chord/scale_deg enrichment, vocal range), where `<slug>` is auto-derived from the MP3 filename. On purely instrumental tracks `vocal_range` is `null` and a `"vocal_range suppressed"` warning is recorded — see [`install-logs/batch-test-results.md`](../install-logs/batch-test-results.md) for the validation that drove that detector. Pass `--slug NAME` to override the slug; `--force` to ignore cache; `--quiet` to suppress per-stage progress.

Stage outputs are cached per-song under `cache/<slug>/`. Re-running on the same MP3 reuses cached intermediates (~10-30 seconds total, dominated by per-note enrichment) unless you pass `--force` (~10 minutes for a fresh run on the RTX 3090).

For the validated end-to-end example, see `cache/gorillaz_silent_running/`. Design spec: [`docs/superpowers/specs/2026-04-29-analyze-py-design.md`](superpowers/specs/2026-04-29-analyze-py-design.md). Implementation plan: [`docs/superpowers/plans/2026-04-29-analyze-py.md`](superpowers/plans/2026-04-29-analyze-py.md).
