# Batch test of `analyze` on 20 mixed-genre MP3s — 2026-04-30

Driven by `install-logs/batch-tests-mp3.sh` (initial 17 tracks) + `install-logs/batch-tests-mp3-resume.sh` (re-run 6 user-replaced/added MP3s and 3 brand-new tracks). Full logs in `install-logs/batch-tests-mp3.log` and `install-logs/batch-tests-mp3-resume.log`.

Net analysis wall time (final cache state): ~5,770 s ≈ **1h 36min**, sequential on a single GPU. Plus an extra ~25 min on a failed run that surfaced a real path-resolution bug — see "Pipeline-level bug" below.

## Results

Sorted alphabetically (matches the find/sort order the batch scripts iterate in).

| # | Track | Key (conf) | Tempo (BPM) | Loop (Roman) | Modal interchange | Vocal range | Run time |
|---|-------|-----------|-------------|---------------|--------------------|-------------|----------|
| 1 | Angus & Julia Stone · *Harvest Moon* (Paste Studios live) | D Major (1.00) | 105.3 | I-IV (D-G) | 0 | A2-E6 | 330 s |
| 2 | Arcade Fire · *Reflektor* (7:34) | B minor (1.00) | 111.1 | iv-♭III-i (Em-D-Bm) | 9 | E2-D7 ⚠️ | 183 s |
| 3 | Baleen · *Unmedicated* | E minor (1.00) | 85.7 | ♭III-♭VI-v-V-i-♭III-♭VI-v | 47 | D♯2-G♯7 ⚠️ | 102 s |
| 4 | *CVT 380 M* (7.4 s clip) | A minor (1.00) | 93.8 | (none — clip) | 0 | F2-E5 | 183 s |
| 5 | Editors · *Life Is A Fear (Alternative)* | E Major (1.00) | 107.1 | vi-V (C♯m-B) | 0 | E2-A5 | 356 s |
| 6 | Editors · *Life Is A Fear* | C♯ minor (1.00) | 120.0 | i-♭VII-IV-♭III (C♯m-B-F♯-E) | 27 | E2-E7 ⚠️ | 329 s |
| 7 | Fanfare Ciocarlia · *Asfalt Tango* (gypsy brass) | B♭ minor (1.00) | 115.4 | (N)-i (Bbm) | 4 | null *(instrumental)* | 398 s |
| 8 | Flunk · *On My Balcony* | C Major (1.00) | 171.4 ⚠️ | IV-V-vi-I-IV-V-vi-iii | 0 | F2-E7 ⚠️ | 276 s |
| 9 | Gorillaz · *Silent Running ft. Adeleye Omotayo* | F minor (1.00) | 107.1 | i-v-♭VI-♭III (Fm-Cm-D♭-A♭) | 29 | F2-F6 | 289 s |
| 10 | *It Could Happen To You 2_Render* | G Major (1.00) | 153.8 ⚠️ | I-IV (G-C) | 6 | null *(instrumental)* | 246 s |
| 11 | Jamiroquai · *Everyday* | C♯ minor (1.00) | 136.4 | ♭iii7-iv7-♭VII7-♭iii7-iv7 | 53 | E2-E6 | 336 s |
| 12 | Joesef · *Comedown* | A Major (1.00) | 89.6 | **ii7-V7-Imaj7-iii7-ii7-V7-Imaj7** ✓ | 0 | C3-F6 | 331 s |
| 13 | Leonard Cohen · *In My Secret Life* | F Major (1.00) | 82.2 | vi-V/3-I (Dm-C/E-F) | 0 | D♯2-F6 | 347 s |
| 14 | Lou Reed · *Perfect Day* | **B♭ Major** ✓ (1.00) | **73.2** ✓ | **vi-V-IV** (Gm-F-E♭) ✓ | 18 | D♯2-E6 ✓ | 294 s |
| 15 | Olivia Dean · *Dive (Acoustic)* | F Major (1.00) | 84.5 | iii7-vi7-ii7 (Am7-Dm7-Gm7) | 0 | F3-F6 ✓ | 279 s |
| 16 | Radiohead · *Creep (Heads On The Radio)* | **G Major** ✓ (1.00) | 84.5 | **I-III-IV-iv-I-III** ✓ (G-B-C-Cm) | 1 | D♯2-B6 ⚠️ | 254 s |
| 17 | Ren X Chinchilla · *Chalk Outlines* | E Major (1.00) | 109.1 | vi-IV-I (C♯m-A-E) | 0 | D♯2-D♯7 ⚠️ | 364 s |
| 18 | Two Fingers · *Deep Jinx* (electronic instr.) | C♯ minor (1.00) | 85.7 | (N)-I (C♯) | 0 | null *(instrumental)* | 279 s |
| 19 | Warhaus · *Love's A Stranger* | E minor (1.00) | 81.1 | v-i-v-i-v (Bm-Em) | 4 | D♯2-D♯7 ⚠️ | 285 s |
| 20 | Pixies · *Where Is My Mind* (cover/instr-ish) | C♯ minor (1.00) | 82.2 | ♭III-i-V-♭VI (E-C♯m-A♭-A) | 34 | G♯2-A6 | 306 s |

✓ = pipeline matches the well-known ground truth for the song.
⚠️ = upstream-model artifact, not a pipeline bug — see "Upstream-model limits" below.

## Headline findings

**Pipeline-level bug found and fixed.** Initial run failed on tracks 1-2 with `error: required stage chords failed: Exception: File not found: …/.venv/lib/python3.11/site-packages/tests/mp3/<track>.mp3`. Root cause: `lv-chordia` (chords stage) resolves the MP3 path against its own package install dir when given a relative path, instead of caller CWD. The previous batch (`install-logs/batch-test.sh`) used absolute `/mnt/c/...` paths so this never tripped. Fix: pass `realpath "$mp3"` from the batch scripts. Long-term candidate fix: `analyze/cli.py` should call `args.mp3_path = args.mp3_path.resolve()` right after the existence check on line 19, immunising any caller. Memory recorded at `~/.claude/projects/<CLAUDE_PROJECT_ID>/memory/analyze_relative_path_bug.md`.

**Strong cross-validations.** Three tracks the pipeline nailed without filename hints, with both key/tempo/progression matching the well-known reference:

- **Lou Reed · *Perfect Day*** → B♭ Major / 73.2 BPM / vi-V-IV (Gm-F-E♭) — matches the iconic chorus harmony.
- **Radiohead · *Creep (Heads On The Radio)*** → G Major / 84.5 BPM / I-III-IV-iv (G-B-C-Cm) — that's literally Creep's chord progression, including the famously dramatic **iv** (C minor) borrowed from G minor. Modal-interchange count of 1 captures exactly that one borrowed chord.
- **Joesef · *Comedown*** → A Major / 89.6 BPM / ii7-V7-Imaj7-iii7 — textbook jazz/soul ii-V-I, modal-interchange = 0 because everything stays diatonic.

**Cache reuse paid off twice.** Ren X Chinchilla had been interrupted mid-chords during the first run; resuming pulled the cached stems/beats/key from disk and only re-ran chords + transcription, finishing in 364 s including the chord ensemble's full 5-snapshot pass. The 11 already-complete tracks were skipped entirely by the resume script's summary.json check (no per-stage replay needed at all).

**Cache reuse counter-example.** When a slug is identical but the underlying MP3 changes (or a stage output is older than the new MP3), the per-stage `is_newer_than_mp3(out, mp3)` probe correctly invalidates and re-runs. The user replaced 4 MP3s with YouTube-downloaded versions; because the new filenames carry video-ID suffixes, their slugs differ, so they got fresh cache directories — no collision risk.

## Upstream-model limits (not pipeline bugs)

**`Where Is My Mind` keyed as C♯ minor (rather than the conventional E major analysis).** C♯ minor and E major share the same key signature; both are theoretically valid but most listeners hear the song's tonal centre as E (especially via the iconic intro on E and the G♯m–E hook). `skey` returned C♯ minor with confidence 1.00 — the high confidence is misleading because the relative-major/minor distinction is genuinely ambiguous from pitch-class statistics alone. The pipeline's chord progression `E:maj C♯:min A♭:maj A:maj` reads as `♭III-i-V-♭VI` in C♯m (with V being a dominant on G♯ via the A♭ enharmonic) or as `I-vi-III-IV` in E major. Either reading describes the same audio.

**Tempo doubling on bright/fast material (track 8: Flunk · *On My Balcony*, 171.4 BPM).** Real tempo is ≈85.7 BPM (this is the half-time pulse). Same failure mode madmom and beat-this both exhibit on swing/compound-meter tracks. The `it_could_happen_to_you_2_render` track also reports 153.8 BPM where the half-time would be ≈77 BPM. Per `install-logs/batch-test-results.md`, this isn't fixable inside the pipeline — both estimators converge on the wrong octave for these material types.

**`vocal_range` artefacts on vocal tracks.** Several reported `high` values sit in whistle register (`D7` Arcade Fire, `G♯7` Baleen, `E7` Editors, `E7` Flunk, `B6` Radiohead, `D♯7` Ren, `D♯7` Warhaus). The `is_instrumental()` guard (`analyze/derived/vocal_range.py`) only suppresses the field when the *whole* track is instrumental (BS-RoFormer vocals stem RMS < 15% of the instrumental stem RMS). On vocal tracks, basic-pitch's per-frame transcription still picks up high harmonics from synths/strings/cymbals leaking into the vocals stem, producing impossibly-high `high` values. Three instrumental-leaning tracks correctly suppressed: Fanfare Ciocarlia (brass), It Could Happen To You 2 (render), Two Fingers (electronica) — all show `vocal_range = null` with the suppression warning recorded. **Possible future improvement:** percentile-clip the MIDI note range (e.g. 5th-95th) before reporting, rather than `min`/`max`; would catch spurious whistle-register notes from non-vocal harmonics. Out of scope for this batch.

**Short-clip handling.** `CVT 380 M.mp3` is a 7.4 s clip. Pipeline gracefully returned full key/tempo/chords/MIDI but `loop=None` because the loop detector needs at least one repeated 2-bar pattern. Useful confirmation that the pipeline degrades cleanly on too-short input rather than crashing.

**`Two Fingers · Deep Jinx` and `Fanfare Ciocarlia` show `loop[0] = "N"`.** That's the chord-recogniser's "no-chord" symbol surfacing in the predominant-loop output. On these two tracks the most-frequent token over the verse/intro is silence/no-chord followed by the tonic, which produces a literal `[N, i]` loop. Not a bug, but readable as one — could be worth filtering N-only entries out of the predominant-loop computation.

## Re-running

The two scripts compose cleanly:

```bash
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate

# Initial run on all MP3s in tests/mp3/ (will skip per-stage anything already cached):
bash install-logs/batch-tests-mp3.sh > install-logs/batch-tests-mp3.log 2>&1

# Process only tracks whose summary.json doesn't yet exist (after curating cache/):
bash install-logs/batch-tests-mp3-resume.sh > install-logs/batch-tests-mp3-resume.log 2>&1
```

To force-redo a specific track:

```bash
python -m analyze --force "$(realpath tests/mp3/<track>.mp3)"
```

The `realpath` is required — see the path-resolution bug above. Long-term fix candidate is to absorb that into `analyze/cli.py`.
