# Batch test of `analyze` on 5 mixed-genre MP3s — 2026-04-29

Driven by `install-logs/batch-test.sh`. Full log in `install-logs/batch-test.log`. Total wall time: ~33 minutes for all 5 tracks (sequential — they share the GPU).

Skipped: `Sequence 01.mp3` (30:44, paired with a `.srt` sidecar — clearly an interview/video export, not music).

## Results

| # | Track | Key | Tempo | Loop (Roman) | Modal interchange | Vocal range | Run time |
|---|-------|-----|-------|--------------|-------------------|-------------|----------|
| 1 | Chet Baker · *Autumn Leaves* (jazz duet, 7:08) | F min | 187.5 ⚠️ (½×) | v7-i7 (Cm7→Fm7) | 45 | D♯2–G7 ⚠️ | 500 s |
| 2 | Charlie Puth · *Attention* (~5:01) | D♯ min | 100.0 | i7-♭VII-v7-♭III-♭VImaj7 | 46 | C♯3–G6 | 331 s |
| 3 | Lou Reed · *Perfect Day* (3:42) | **B♭ Maj** ✓ | **73.2** ✓ | **vi-V-IV** (Gm→F→E♭) ✓ | 18 | D♯2–E6 ✓ | 324 s |
| 4 | Bach · *Air on G String* (cello quintet, 5:26) | A Maj | 107.1 | IV-ii-♭VIImaj7-♭VII-I-vi-vi°-i/5 | 15 | D♯2–F♯7 ⚠️ | 400 s |
| 5 | *Autumn Leaves Gm 130bpm Backing Track* (5:13) | **G min** ✓✓ | **130.4** ✓✓ | **i7-iv7-♭VII7** ✓✓ | 36 | G2–E5 | 387 s |

✓ = matches ground truth (filename label or well-known harmony). ⚠️ = upstream-model limit, not pipeline bug.

## Headline findings

**Pipeline-level bug found and fixed.** Track 2 (Charlie Puth) initially reported `duration_sec = 1711.96` for a 5:01 track. Root cause was `librosa.get_duration(path=…)` trusting the MP3's malformed Xing/VBR header. Replaced with an `ffprobe` wrapper in `analyze/pipeline.py`. Re-run with `--force` produced 301.73 s. See `docs/history.md` Phase I for the full diagnosis.

**Best-case validation: track 5.** The filename literally says "Gm 130bpm" and the pipeline returned `G minor / 130.4 BPM` with the canonical Autumn-Leaves changes (`Gm7 → Cm7 → F7` = `i7 - iv7 - ♭VII7`). This is the standard ii-V-i in the relative major (B♭) — exactly what Autumn Leaves is built on.

**Strong cross-validation: track 3.** *Perfect Day* is in B♭ major; the pipeline matched key, tempo, and the well-known `vi-V-IV` (Gm-F-E♭) progression without any hint from the filename.

## Upstream-model limits (not pipeline bugs)

Re-running these with the same models gives bit-identical outputs (modulo basic-pitch's CUDA-reduction-order non-determinism in the per-stem note count).

**Jazz tempo doubling (track 1).** Both `madmom` and `beat-this` lock onto the 8th-note swing pulse and report 187.5 BPM. Real tempo ≈93. Classic MIR failure mode on swing material.

**Instrumental "vocals" stems (tracks 1 & 4).** `htdemucs_6s` always emits a `vocals` stem. On purely instrumental pieces (Bach's cello quintet) and saxophone-led tracks (Chet Baker / Paul Desmond), the misclassified content originally yielded nonsensical vocal ranges (Bach reached F♯7; Chet Baker reached G7 from sax). **Fixed 2026-04-30** by adding `is_instrumental()` to `analyze/derived/vocal_range.py`: when the BS-RoFormer vocals stem RMS is < 15% of its instrumental stem RMS, `vocal_range` is suppressed and a warning is recorded. After the fix all three instrumental tracks (Bach, Chet Baker, the Gm backing track) report `vocal_range = null`; all three vocal tracks (Charlie Puth, Lou Reed, Gorillaz reference) keep their `vocal_range`. See `docs/history.md` Phase J for the full diagnosis (htdemucs leaks too much voice-band content; BS-RoFormer is a much cleaner discriminator with a ~10× ratio gap between vocal and instrumental tracks on the validation set).

**Long chord loops (track 4).** Bach's chromatic harmony defeats `loop_detect`'s "predominant" heuristic — it returned an 8-chord "loop" because no 2-bar pattern dominated. Probably correct given the heuristic; the song just doesn't loop.

## Re-running

```bash
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
bash install-logs/batch-test.sh > install-logs/batch-test.log 2>&1
```

To re-analyze a single track with the duration-bug fix applied:

```bash
python -m analyze --force "/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/MP3/<track>.mp3"
```
