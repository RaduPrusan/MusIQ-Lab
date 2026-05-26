# Cross-validation & LLM orchestration (Stage 8)

Stage 8 of the pipeline takes raw outputs from all upstream stages and produces:
1. A single canonical track per question (chord progression, beats, etc.) by reconciling multiple tools
2. Derived analysis (Roman numerals, chord-tone tags, scale degrees) using **musical reasoning**
3. The `summary.json` digest

This is where Claude becomes useful as an orchestrator — and where the "best of all worlds truth" you asked about emerges.

## The two reconciliation modes

### Mode 1 — Pure-algorithmic reconciliation (no LLM)

Done by `lib/reconcile.py` in pure Python. No model calls, deterministic, fast.

| Field | Reconciliation |
|---|---|
| **Beats** | `allin1` primary; `beat_this` cross-checks with ±50 ms tolerance. Disagreements > 50 ms recorded in JAMS as `beat_disagreement` annotations. |
| **Downbeats** | `allin1` only (it's the joint task; `beat_this` doesn't always emit downbeats reliably). |
| **Tempo** | Median of inter-beat intervals from the reconciled beat track. |
| **Sections** | `allin1` only. |
| **Key** | `skey` primary; if confidence < 0.5, fall back to librosa K-S and emit a warning. |
| **Chord boundaries** | Snap each chord's `start` and `end` to the nearest downbeat (from `allin1`). Chord boundary error < 100 ms is the typical wobble; downbeat-snapping fixes it deterministically. |
| **Vocal f0** | Average FCPE and PESTO frame-by-frame where both are voiced; mark unvoiced where one says voiced and the other says unvoiced (uncertainty signal). |

This mode is enough to produce a clean JAMS file. The summary.json gets richer with Mode 2 below.

### Mode 2 — LLM-orchestrated reconciliation (Claude)

For analyses that require **musical reasoning**, not just algorithm. Done by Claude reading the post-Mode-1 JAMS file and emitting structured corrections / annotations.

This is where the "ChordCoT pattern" (LLM Chain-of-Thought for ACR) lives. The pattern:

1. Mode 1 produces a JAMS with a chord track that's been beat-snapped but otherwise raw.
2. Claude is given that track plus the detected key, melody notes, and bass-stem MIDI.
3. Claude reasons over inconsistencies: "If the key is G minor and the chord recognizer says C# dim here, that's a tritone sub for V → I — but the bass plays D for two beats followed by G. So this is more likely D7/F#." (Or it might preserve the original prediction with a confidence note.)
4. Claude emits a corrected chord track AND a per-chord explanation.

Strict guardrail: **Claude does not invent missing chords or notes.** Claude's role is reconciliation, not transcription. If the audio model didn't see a chord, Claude doesn't add one. Claude can:

- Re-label a chord (with explanation)
- Lower confidence on an ambiguous chord
- Add Roman numeral / function tags
- Tag melody notes as chord-tone / non-chord-tone
- Compute scale degrees relative to detected key
- Flag interesting moments ("modal interchange", "secondary dominant", "tritone substitution", "borrowed chord", "passing chord")

## The cross-validation matrix

For each pairwise tool combination, what gets cross-checked:

| Source A | Source B | Validation |
|---|---|---|
| `lv-chordia` chords | `basic-pitch` bass-stem notes | Bass note should match chord's `bass` (or `root` if no slash). Disagreement → flag |
| `lv-chordia` chords | `skey` key | Compute Roman numeral; flag chords outside diatonic set as modal interchange or secondary |
| `basic-pitch` notes per stem | `lv-chordia` chord at that time | Note within active chord triad → `chord_tone`; note outside → `passing_tone` / `non_chord_tone` |
| `basic-pitch` notes per stem | `skey` key | Compute scale degree; notes outside scale → flag (could be chromatic embellishment) |
| `torchfcpe` vocal f0 | `pesto-pitch` vocal f0 | Frame-by-frame agreement; large disagreement → mark frame as low-confidence |
| `torchfcpe` vocal f0 | `basic-pitch` vocals notes | f0 contour should pass through MIDI note pitches; large deviation → flag (vibrato, slide, error) |
| `allin1` beats | `beat_this` beats | ±50 ms tolerance; disagreement → flag |
| `allin1` downbeats | `lv-chordia` chord boundaries | Chord changes should land near downbeats; misalignment > 100 ms → snap, log original |
| `allin1` sections | repeated chord progressions | If a chord progression repeats with same length but different section labels → flag (likely section labelling weak point) |

## Why this matters pedagogically

The user's stated goal is **understanding music**, not just "having a chord chart". The cross-validation produces signals that are themselves educational:

| Signal | Educational meaning |
|---|---|
| Chord-tone vs passing-tone tags on melody | Voice leading lessons; melodic contour analysis; understanding why a melody sounds tense or resolved |
| Roman numeral + function tags on chords | Harmonic analysis; cadence recognition; predicting the next chord |
| Modal interchange flags | Mode mixture; "borrowed chord" recognition; modal vs tonal thinking |
| Tools-disagree-here flags | Real harmonic ambiguity, often where suspensions, sus chords, or modal pivots live — the *actually interesting* moments to study |
| Vocal-f0 vs vocal-MIDI deviation | Vibrato, melisma, scoops, fall-offs — the expressive content |
| Repeated-progression detection | Identifying the song's harmonic skeleton; recognizing common patterns (I-V-vi-IV, ii-V-I, etc.) across a library |

## The orchestrator prompt template

When `lib/reconcile.py` invokes Claude (CLI), the structured prompt is roughly:

```
You are reconciling music analysis outputs for {song.file}.

KEY: {key}  (confidence {key_conf})
TEMPO: {tempo_bpm}
TIME SIGNATURE: 4/4
DOWNBEATS: {first_8_downbeats}...

RAW CHORD TRACK from lv-chordia (post-beat-snap):
{chord_table}

BASS-STEM NOTES (basic-pitch on isolated bass stem):
{bass_notes_at_each_chord}

For each chord above, produce a JSON record with:
- the original label (preserve unless clearly wrong given bass)
- the Roman numeral relative to the key
- the diatonic function (tonic / predominant / dominant / modal_interchange / secondary)
- a confidence in [0, 1]
- an agreement marker (consensus / split / corrected)
- if you correct or split, a one-sentence explanation

Do NOT add chords not in the input. Do NOT remove chords from the input.
You may re-label, lower confidence, or annotate.

Output: a JSON array, one record per input chord, same length.
```

This is Stage-8 work — it's not a free-form conversation, it's a structured reconciliation call with strict input/output contracts.

## What if Claude isn't available

The pipeline must work without Claude (e.g. on a fresh machine, no auth). Mode 1 reconciliation alone produces a complete JAMS file and a viable `summary.json` — the only fields that go missing are:

- `roman`, `function` per chord (computed via simpler library: chord-against-key-template lookup)
- `role` (chord_tone / passing_tone) per note (computed via simpler library: note-in-chord-triad check)
- `notes` (free-text explanation per chord)
- The whole `analysis` section's free-text fields

So the fallback algorithmic version is workable. The LLM version adds **judgement** to ambiguous cases. Both work.
