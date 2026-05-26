# MusIQ-Lab — Roadmap to a serious music-analysis stack

**Date:** 2026-05-03
**Status:** Roadmap. Phase A+B has a full design spec; later phases are scoped sketches that will get full specs when their turn comes.

## Why this roadmap exists

The current pipeline (validated April 2026, batch-tested on 5 mixed-genre tracks) is **competent across the board, best-in-class at none of it**. Every stage uses a generalist model where a specialist exists, and three components people expect from a serious music-analysis app are simply absent (sections, modulations, real exports).

This roadmap describes the path from "competent prototype" to "serious app a working musician can rely on."

## North star

A musician opens a song and gets:

- Stems they can solo and trust.
- A beat/downbeat grid they can quantize against, with per-bar tempo.
- Key + per-section modulations.
- Chord progression at chorus-vs-verse granularity.
- **Per-stem MIDI that sounds like the song when re-synthesized.**
- Drum pattern with realistic velocities.
- Vocal melody as both F0 curve *and* snapped notes.
- Structural sections (intro / verse / chorus / bridge / outro).
- Confidence indicators per stage so the UI can flag "trust this" vs "double-check this."
- Exports usable in a DAW: per-instrument MIDI, optional MusicXML lead sheet, sectional clips.

## The six phases

| Phase | Theme | Effort | Status |
|---|---|---|---|
| [**A**](phase-a-specialist-models.md) | Specialist models everywhere it matters | ≈2 weeks | **Shipped May 2026** ([`docs/history.md`](../../docs/history.md) Phases L + M); WI-7 vocals specialist reverted to basic-pitch after post-ship correction arc |
| [**B**](phase-b-pipeline-architecture.md) | Per-stage params + selective re-run | ≈1 week | **Shipped May 2026** (combined with A; `--stages-only` / `--from-stage` / `--params-json` flags) |
| [**C**](phase-c-structural-layer.md) | Sections, modulations, time signatures, tempo curves | ≈2 weeks | Sketch — sections deferred since allin1 drop; remains the largest open gap |
| [**D**](phase-d-confidence-signals.md) | Per-detection confidence + cross-validation | ≈1 week | Sketch — partial: Phase 0c added per-frame `agreement_strength` for vocal F0; Essentia second-opinion (May 2026) added tempo/key cross-check |
| [**E**](phase-e-control-surface.md) | Advanced settings modal + presets + A/B compare | ≈1.5 weeks | Sketch |
| [**F**](phase-f-exports.md) | Per-instrument MIDI, MusicXML, sectional bundle | ≈1 week | Sketch |

> **Update (2026-05-13):** Two non-roadmap arcs landed in May 2026 outside the original six phases — the **identify pipeline overhaul** (5-round AcoustID + MusicBrainz canonical identity overhaul, ship report in `docs/history.md` Phase Q) and **WASAPI audio engine v1** (selectable Windows audio engine in the webui, Phase P). Phase Q in particular subsumes part of what Phase D ("cross-validation") was meant to cover for the metadata layer.

Total: **≈8–9 focused weeks** to a complete serious pipeline. Each phase ships independently and unlocks the next.

## Order of execution

**Bundle A+B first** (covered by the single Phase A+B spec). Reasons:

1. A is the quality lift the user immediately feels.
2. B is what makes A's iteration cycle livable — without selective re-run, every transcription tweak rewinds 5 minutes of stems work.
3. They share enough cache + pipeline-driver work that splitting them costs more than combining them.
4. Phase E's modal lands meaningfully better with A+B done; the knobs are wider and faster to feel.

After A+B ships:

- **C and D can run in parallel** (no shared files, no shared concepts) — two independent tracks.
- **E follows D** so the modal can surface confidence signals.
- **F follows C** so exports can be section-aware.

```
            ┌────────────────────────┐
            │   A+B (one spec)       │  ≈3 weeks
            │   specialists +        │
            │   selective re-run     │
            └───────────┬────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
┌──────────────────────┐   ┌──────────────────────┐
│ C: structural layer  │   │ D: confidence        │
│ ≈2 weeks             │   │ ≈1 week              │
└──────────┬───────────┘   └──────────┬───────────┘
           │                          │
           ▼                          ▼
┌──────────────────────┐   ┌──────────────────────┐
│ F: exports           │   │ E: control surface   │
│ ≈1 week              │   │ ≈1.5 weeks           │
└──────────────────────┘   └──────────────────────┘
```

## How each phase is written and executed

Every phase follows the same shape:

1. **Sketch** lives in `prompts/next/phase-X-*.md` (this directory). Captures goal, scope, deliverables, dependencies, validation criteria.
2. **Full spec** lives in `docs/superpowers/specs/YYYY-MM-DD-phase-X-*.md`. Implementation-ready: file-level changes, interfaces, tests, migration.
3. **Implementation plan** lives in `docs/superpowers/plans/YYYY-MM-DD-phase-X-*.md`. Generated from the spec via the `superpowers:writing-plans` skill. Sequential, reviewable, with checkpoints.
4. **Execution** is via `claude-agent-sdk` ralph loops with reviewer subagents (see Phase A+B spec for the canonical pattern). Loops iterate until the reviewer agent signs off on every acceptance criterion.

## What to do next

- Read the [Phase A+B spec](../../docs/superpowers/specs/2026-05-03-phase-ab-pipeline-upgrade-design.md).
- If approved, generate the implementation plan via `superpowers:writing-plans`.
- Open a fresh session to execute it (the spec is self-contained — no prior conversation context required).
