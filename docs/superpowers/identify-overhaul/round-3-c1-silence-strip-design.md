# Round 3 C1 — Silence-Strip Preprocessing Design

**Author:** C1 (architecture)
**Date:** 2026-05-12
**Status:** Design only — no source changes

## Executive Summary

Strip leading silence from the source MP3 via ffmpeg `silenceremove` before handing the audio to fpcalc, gated on a cheap `silencedetect` probe that must return > 0.3s of leading silence at -50 dB to trigger preprocessing. The recommended query strategy is RAW fingerprint first, then STRIPPED fingerprint as a fallback only when the raw lookup returns zero results, to minimize AcoustID rate-limit spend while correctly targeting the 6 Bucket-A tracks that carry measurable leading silence. The honest ceiling for this corpus is 3–4 additional identifications from the 11 Bucket-A tracks — the remaining 5 have zero measured leading silence and are fingerprint-not-in-DB cases that silence-strip cannot address.

---

## Pre-design Note: Chromaprint's Internal SilenceRemover

Chromaprint Algorithm 2 (the default, `CHROMAPRINT_ALGORITHM_TEST2`) includes an internal `SilenceRemover` in its audio processing chain (pipeline: AudioProcessor -> SilenceRemover -> FFT -> Chroma -> FingerprintCalculator). However, `chromaprint.h` explicitly documents: **"DO NOT USE `chromaprint_set_option(silence_threshold)` IF YOU ARE PLANNING TO USE THE GENERATED FINGERPRINTS WITH THE ACOUSTID SERVICE."**

The internal threshold targets digital near-silence (PCM values at or near 0), not -50 dB near-silence from YouTube label slates. This is why fpcalc on the raw MP3 still fails for Bucket-A: Chromaprint's internal remover does not catch -50 dB "quiet but non-zero" YouTube intros.

The correct approach is ffmpeg preprocessing in the audio domain before fpcalc sees the file. This is AcoustID-compatible.

---

## 1. Architecture

```
analyze/stages/identify.py  run()
         |
         v
  [_detect_leading_silence(mp3)]
   silencedetect probe, ~0.2s
         |
  leading_sec > gate_sec (0.3s)?
         |
     YES |                          NO
         v                          |
  [_strip_leading_silence(mp3)]     |
   silenceremove to temp WAV        |
   strip_tmp = Path("/tmp/x.wav")   |
         |                          |
   audio_path = strip_tmp      audio_path = mp3
         \                         /
          \-----------+-----------/
                      v
        [_run_fpcalc(mp3)]  <-- always raw fingerprint first
                      |
        [acoustid_client.lookup(fp_raw, mp3_dur)]
                      |
           match is None AND strip_tmp is not None?
                      |
           YES        |              NO
                      v              |
         [_run_fpcalc(strip_tmp)]    |
         [acoustid_client.lookup(    |
           fp_stripped, strip_dur)]  |
                      \             /
                       \-----------/
                            v
              [existing MB lookup, _preserve_or_write,
               _log_outcome]  -- unchanged
                            |
                    finally: strip_tmp.unlink()
```

### Cache artifacts

The stripped WAV is written to a `tempfile.NamedTemporaryFile(suffix=".wav", delete=False)` in the same directory as `mp3` (to avoid cross-volume NTFS issues). It is deleted in a `finally` block after fpcalc returns. No new permanent files are added to `cache/<slug>/`.

### Schema version

Round 3 bumps `SCHEMA_VERSION` from 2 to 3. Rationale in §11.

---

## 2. ffmpeg Commands

### 2a. Silencedetect probe (cheap gate check)

```bash
ffmpeg -i /path/to/track.mp3 \
  -af "silencedetect=noise=-50dB:d=0.3" \
  -f null - 2>&1
```

Parse stderr for the first `silence_end: <T>` line. If `T <= 30.0`, the silence is at the track head and the strip is appropriate. If no `silence_end` line appears, leading silence is absent and the gate does not cross.

Wall time: approximately 0.2–0.4s. ffmpeg stops processing after the first non-silent event is found; it does not decode the entire file.

### 2b. Silenceremove (strip and encode WAV)

```bash
ffmpeg -y -i /path/to/track.mp3 \
  -af "silenceremove=start_periods=1:start_threshold=-50dB:start_duration=0.3:detection=peak" \
  -ar 44100 -ac 1 -c:a pcm_s16le \
  /tmp/stripped_<slug>.wav
```

Parameter justification:

- `start_periods=1` — remove exactly the first contiguous silent region; do not touch any subsequent silent passages
- `start_threshold=-50dB` — conservative; YouTube label slates are typically -30 to -45 dB. A genuine quiet piano intro at -40 dB WOULD be stripped, but most musical intros are above -30 dB
- `start_duration=0.3` — silence must persist for 0.3s continuously before the strip fires; a single quiet transient that briefly dips below -50 dB does not trigger
- `detection=peak` — uses peak amplitude, matching R1's silencedetect probe configuration (consistency: what the probe detects is what the remover strips)
- `-ar 44100 -ac 1` — 44.1 kHz matches canonical CD master fingerprints in the AcoustID DB; mono halves the I/O size
- `-c:a pcm_s16le` — uncompressed PCM; fpcalc reads it natively without a second decode step

### 2c. Empirical validation against 3 corpus tracks

The Round 1 A2 probe already ran `silencedetect=noise=-50dB:d=0.3` against all 30 corpus tracks, providing ground truth for these three cases:

| Track | R1 measured leading silence | Expected post-strip duration | Gate action |
|---|---|---|---|
| `charlie_puth_attention` | 0.45s | ~301.25s (from 301.7s) | Strips 0.45s intro |
| `ren_x_chinchilla_chalk_outlines` | 6.47s | ~338.23s (from 344.7s) | Strips 6.47s intro |
| `balthazar-changes_official_video-p3jb998acqo` | 0.00s | No-op | Gate not crossed |

These projected output durations are derived from R1 data. C2 must run the actual commands (specified verbatim in the C2 prompt §14) and record actual wall times and output durations before committing. If any step exceeds 2s or the stripped durations differ by more than ±0.1s from projected, report to the orchestrator before committing.

---

## 3. Wire-in Plan

Integration point: **BEFORE** the existing `fp = _run_fpcalc(mp3)` at `identify.py:131`.

Choosing BEFORE over INSIDE `_run_fpcalc`: the existing function has no awareness of silence preprocessing and its signature is `(mp3: Path) -> dict`. Adding the preprocessing BEFORE preserves the function's single responsibility and keeps it independently testable. A piped-stdin approach inside `_run_fpcalc` would couple two concerns with no benefit.

Pseudo-code for the integration (line numbers relative to the current `identify.py`):

```python
def run(mp3: Path, cache_dir: Path, **params) -> dict:
    p = {**DEFAULT_PARAMS, **params}
    slug = cache_dir.name

    # --- NEW: Silence-strip preprocessing (insert before line 131) ---
    strip_tmp: Path | None = None
    if p.get("silence_strip_enabled", True):
        try:
            leading_sec = _detect_leading_silence(
                mp3,
                threshold_db=p.get("silence_strip_threshold_db", -50),
                min_duration_sec=p.get("silence_strip_min_duration_sec", 0.3),
            )
            if leading_sec > p.get("silence_strip_gate_sec", 0.3):
                strip_tmp = _strip_leading_silence(
                    mp3,
                    threshold_db=p.get("silence_strip_threshold_db", -50),
                    min_duration_sec=p.get("silence_strip_min_duration_sec", 0.3),
                )
                log.debug("silence-strip: %s stripped %.2fs", slug, leading_sec)
        except Exception as exc:
            log.warning("silence-strip preprocessing failed for %s, using raw: %s", slug, exc)
            strip_tmp = None  # ensure clean state
    # --- END NEW ---

    try:
        fp_raw = _run_fpcalc(mp3)          # always fingerprint raw first
    except (FileNotFoundError, ...) as e:
        # existing error handling, unchanged
        ...

    # Existing AcoustID lookup (line ~150):
    try:
        match = acoustid_client.lookup(fp_raw["fingerprint"], fp_raw["duration"])
    except acoustid_client.AcoustIDError as e:
        ...  # unchanged

    # --- NEW: Stripped fallback if raw returned nothing ---
    if match is None and strip_tmp is not None:
        try:
            fp_stripped = _run_fpcalc(strip_tmp)
            match = acoustid_client.lookup(fp_stripped["fingerprint"], fp_stripped["duration"])
        except Exception as exc:
            log.warning("silence-strip AcoustID fallback failed for %s: %s", slug, exc)
            match = None
    # --- END NEW ---

    # existing match-is-None handling, MB lookup, _preserve_or_write, _log_outcome
    # all unchanged from here
```

The `finally` block placement is critical: C2 must ensure `strip_tmp.unlink()` fires even if the AcoustID call raises. The cleanest approach is to move the unlink into the outermost `try/finally` that wraps all of `run()`.

---

## 4. Conditional Gating

Gate threshold: **N = 0.3s**

Corpus data drives this choice:

| Track | Leading silence | Gate 0.1s | Gate 0.3s | Gate 0.5s | Gate 1.0s |
|---|---|---|---|---|---|
| `ren_x_chinchilla` | 6.47s | yes | yes | yes | yes |
| `jamel_debbouze_stromae` | 1.94s | yes | yes | yes | yes |
| `sting_rijksmuseum` | 1.49s | yes | yes | yes | yes |
| `it_could_happen_to_you` | 0.82s | yes | yes | yes | NO |
| `submotion_orchestra` | 0.78s | yes | yes | yes | NO |
| `charlie_puth_attention` | 0.45s | yes | yes | NO | NO |

At N=0.3s: 6 tracks preprocessed (all with measured leading silence).
At N=0.5s: 5 tracks preprocessed (charlie_puth missed).
At N=1.0s: 3 tracks preprocessed.

N=0.3s captures the marginal charlie_puth case at 0.45s. The silencedetect probe is cheap (~0.2s) even when it returns "gate not crossed" for zero-silence tracks. Setting N=0.1s would increase probe false-positive rate on tracks with very brief room-noise tails at the head; N=0.3s aligns with R1's silencedetect `d=0.3` parameter (consistency: the probe and the gate use the same minimum-duration concept).

The probe also applies a 30-second anchor check: if `silence_end > 30.0`, the silence is not a head-of-track slate but an internal gap — skip preprocessing.

---

## 5. Sidecar Params

New keys to add to `DEFAULT_PARAMS` in `identify.py:31`:

```python
DEFAULT_PARAMS: dict = {
    "silence_strip_enabled": True,
    "silence_strip_threshold_db": -50,
    "silence_strip_min_duration_sec": 0.3,
    "silence_strip_gate_sec": 0.3,
}
```

`sidecar.matches()` at `analyze/sidecar.py:73-74` compares `data.get("params") == expected_params`. Old sidecars with `params={}` will not equal the new DEFAULT_PARAMS, so all schema_version=2 caches fail `matches()` and trigger re-runs. The legacy bridge in `cached()` (identify.py:52-60) handles `identified=True` caches by synthesizing a v3 sidecar with the new defaults and returning True without re-querying AcoustID. This is safe because the bridge only fires when `identified=True`, per R2's analysis.

Changing `silence_strip_threshold_db` from -50 to -40 also invalidates the sidecar (params-hash changes), which is the desired invalidation for any tuning change.

---

## 6. Query Strategy: RAW FIRST, STRIPPED FALLBACK

Recommended: **query raw fingerprint first; if zero results AND strip was triggered, query stripped fingerprint as fallback.**

| Strategy | AcoustID calls | Strengths | Weaknesses |
|---|---|---|---|
| STRIPPED ONLY | 1 per gated track | Simple; one AcoustID call | Misses CD-rip tracks that happen to match raw (no regression protection) |
| RAW FIRST, STRIPPED FALLBACK | 1 normally; 2 if raw=None and strip triggered | No regression on existing matches; rate-limit efficient | Slightly higher latency for Bucket-A silence cases |
| STRIPPED FIRST, RAW FALLBACK | 1 normally; 2 if stripped=None | Fastest for Bucket-A | Wastes a strip call on future zero-silence tracks; ordering harder to reason about |

RAW FIRST wins. It preserves the existing behavior for the 24 already-identified tracks (raw fingerprint still matches, no second call). The extra call fires only for Bucket-A tracks with zero-results-on-raw AND measured leading silence — at most 6 in this corpus.

On AcoustID rate limit: 6 extra calls across a full corpus reanalyze takes 2s of additional query time at 3 req/s. Well within budget.

Note on fpcalc call count: with RAW FIRST, fpcalc is called ONCE on the raw MP3 (always). If the AcoustID raw lookup returns None AND a strip_tmp was created, fpcalc is called a SECOND time on strip_tmp. Total fpcalc overhead per Bucket-A silence track: two fpcalc calls. Each fpcalc on a 300s MP3 takes ~2–3s (it reads the first 120s by default). This is acceptable.

---

## 7. Soft-Fail Behavior

All preprocessing failures leave `audio_path = mp3` and `strip_tmp = None`. The existing `_run_fpcalc` path runs unchanged.

| Failure mode | Exception class | Catch location | Fallback |
|---|---|---|---|
| ffmpeg not on PATH | `FileNotFoundError` | broad `except Exception` in preprocessing block | raw MP3 |
| ffmpeg nonzero exit (codec error, corrupt input) | `subprocess.CalledProcessError` | same | raw MP3 |
| Disk full writing temp WAV | `OSError` | same | raw MP3 |
| silencedetect output parse error | `ValueError`, `IndexError` | same | gate not crossed = raw MP3 |
| Stripped WAV created but 0 bytes | `FpcalcError` in `_run_fpcalc(strip_tmp)` | inner `except Exception` in stripped-fallback block | match stays None; existing "no AcoustID match above threshold" result |

The broad `except Exception` in the preprocessing block is intentional — preprocessing is an enhancement, not a correctness requirement. Narrow catches would risk leaving unexpected exceptions (e.g., `MemoryError`) unhandled and causing the identify stage to fail entirely.

The temp WAV is always cleaned up in the outermost `finally` block, even on exceptions after preprocessing succeeds.

---

## 8. Performance Budget

Target: < 2s overhead per track.

Components on JINN (Threadripper PRO 3945WX, NVMe):

- `_detect_leading_silence` (silencedetect): reads the first non-silent event then exits. For a 6.47s head-silence track, ffmpeg decodes ~7s of audio. At 15–25x realtime: **0.3–0.5s wall time**.
- `_strip_leading_silence` (silenceremove + PCM encode): full file decode for a 300s MP3 at 44.1 kHz mono. Output size ~300s × 44100 × 2 bytes = 26 MB. At 15x realtime for combined decode+filter+write: **0.5–1.0s wall time**.

Total overhead when gate is crossed: **0.8–1.5s**. Within budget.

When gate is NOT crossed (zero-silence tracks, 5 of 11 Bucket-A tracks): only the silencedetect probe runs. Overhead: **0.2–0.4s**.

If the combined overhead exceeds 2s on C2's measurement: pre-cache the silencedetect result as `cache_dir/.silence_probe.json` (written after first probe, valid until sidecar params change). This allows subsequent `identify --stages-only identify` re-runs to skip the probe on already-probed tracks. C2 should measure first and only implement the cache if needed.

---

## 9. Test Plan

### Unit tests (mocked subprocess) — `webui/tests/test_identify_round3.py`

1. `test_silence_gate_not_crossed` — silencedetect returns 0.1s; fpcalc called with original MP3 path, no temp WAV
2. `test_silence_gate_crossed_strips` — silencedetect returns 0.45s; temp WAV created; first fpcalc call uses MP3, second uses WAV (two-call pattern)
3. `test_silence_strip_disabled` — `silence_strip_enabled=False`; ffmpeg never called; fpcalc called with raw MP3
4. `test_soft_fail_ffmpeg_not_found` — silencedetect raises `FileNotFoundError`; fpcalc still called with raw MP3; no exception propagated
5. `test_soft_fail_ffmpeg_nonzero` — silenceremove returns exit code 1; fpcalc called with raw MP3
6. `test_temp_wav_cleaned_up_after_fpcalc_error` — fpcalc raises `FpcalcError`; temp WAV is deleted (assert `strip_tmp.exists() is False`)
7. `test_temp_wav_cleaned_up_after_acoustid_error` — AcoustID raises `AcoustIDError`; temp WAV is deleted
8. `test_raw_first_stripped_fallback_fires` — raw AcoustID returns None; strip_tmp exists; second AcoustID call uses stripped fingerprint; match returned
9. `test_raw_first_no_second_call_if_raw_matches` — raw AcoustID returns a match; `_run_fpcalc` called exactly once, AcoustID called exactly once
10. `test_raw_first_no_strip_if_gate_not_crossed` — zero-silence track; raw AcoustID returns None; no stripped fallback attempted (strip_tmp is None)
11. `test_silence_strip_params_reach_sidecar` — run() with default params produces sidecar containing all 4 `silence_strip_*` keys
12. `test_schema_v2_sidecar_invalidated_by_new_params` — sidecar with `schema_version=2, params={}` does not satisfy `sidecar.matches()` against new DEFAULT_PARAMS

### Sidecar / schema drift test

13. `test_stage_manifest_in_sync` (already exists) — verify it passes after SCHEMA_VERSION = 3 is set in both files

### Integration tests (real ffmpeg + real fpcalc, mocked AcoustID) — skip in CI

14. `test_integration_charlie_puth_silence_strip` — verify fpcalc returns `duration ≈ 301.25` (not 301.7) when called with stripped WAV
15. `test_integration_ren_x_chinchilla_silence_strip` — verify fpcalc returns `duration ≈ 338.23` (not 344.7)
16. `test_integration_balthazar_no_strip` — verify gate not crossed; fpcalc called with original MP3; duration ≈ 200.1 unchanged

---

## 10. Risks

### Risk 1: Stripping too much intro identifies the wrong song

Scenario: a track has 6.47s of near-silence followed by audio that accidentally fingerprints as a different commercial track.

Mitigations:
- **Post-strip minimum duration guard**: if `fp_stripped["duration"] < 30.0`, abort the stripped lookup. fpcalc accuracy degrades below 30s and the AcoustID DB rejects short fingerprints.
- **Duration selector in acoustid.py**: B1's recording-by-duration selector prefers recordings whose `recording.duration` is closest to the fingerprinted audio duration. The raw MP3 duration (344.7s for ren_x_chinchilla) is passed when using the raw fingerprint, and the stripped duration (338.23s) when using the stripped fingerprint. AcoustID's DB typically has recordings listed at the canonical release duration (~344s for the album track). A wrong match would need both: (a) a song whose recording duration is ~338s AND (b) fingerprint content that matches the stripped audio. This double coincidence is extremely unlikely for a 5-minute track with a 6s strip.
- **Conservative -50 dB threshold**: we strip only audio that is essentially inaudible by music standards. The risk of stripping recognizable musical content at -50 dB is very low.

### Risk 2: Chromaprint anchor-time shift and AcoustID matching tolerance

Chromaprint generates an ordered sequence of 32-bit integers, one per ~0.37s frame. Stripping 0.45s shifts the entire sequence by ~1 frame; stripping 6.47s shifts by ~17 frames. AcoustID's server-side matching compares these sequences and does NOT perform time-shift invariant search.

The stripped fingerprint only matches if the AcoustID DB contains a fingerprint that also starts at the music content — which is true for commercial releases submitted from CD rips. The YouTube-source fingerprint started at the label slate; after stripping, our fingerprint aligns with the CD-rip fingerprint in the DB.

AcoustID supports partial fingerprint matching (you can submit just the first 120s of audio). Large offsets (17 frames for ren_x_chinchilla) may fall outside the server's matching tolerance window. This is the primary uncertainty. The RAW FIRST strategy ensures we never regress; if the stripped fingerprint fails to match despite our stripping, the result is still `no AcoustID match above threshold` — identical to the current behavior.

---

## 11. SCHEMA_VERSION Decision

Bump from 2 to 3.

The new `DEFAULT_PARAMS` dict (`{"silence_strip_enabled": True, ...}`) does not equal the old `{}`. Since `sidecar.matches()` compares params directly, all existing schema_version=2 sidecars would fail regardless of whether the schema version changes. The params-hash change alone is sufficient for invalidation.

However, bumping to SCHEMA_VERSION=3 is still the right call because:
1. Client-picking behavior changes materially (silence-strip is a new fingerprint derivation step)
2. Explicit version numbers are easier for operators to grep and reason about
3. The bump trigger list in `sidecar.py:8-14` explicitly includes "Client picking logic or behavior changes — even if the cached payload shape is unchanged"

Cost: triggers staleness for all 24 currently-identified caches. The legacy bridge handles `identified=True` cases by synthesizing a v3 sidecar and returning True, so no AcoustID re-queries occur for those tracks. The staleness chip in the UI will show briefly but reanalyze is a no-op.

Update both: `analyze/stages/identify.py:30` (SCHEMA_VERSION = 3) and `webui/webui/stage_manifest.py` (identify entry schema_version: 3). The `test_stage_manifest_in_sync` test will catch any drift.

---

## 12. R2 Fold-ins (Bundle with Round 3 Implementation)

Both are small enough to land in the same Round 3 commit:

### D3: `source=acoustid_unenriched`

In `identify.py`, the `_log_outcome` call at lines 180–183 (MusicBrainz error path) logs `source="none"`. Change to `source="acoustid_unenriched"`. This is a 3-line change: the `source=` argument, the docstring of `_log_outcome`, and a new test `test_log_outcome_mb_error_uses_acoustid_unenriched`.

### Recording tie-break determinism

In `analyze/clients/acoustid.py`, the `min(candidates_with_dur, ...)` call in the recording-by-duration selector. Add `recording.id` as the secondary sort key per R2's recommendation:

```python
chosen_rec = min(candidates_with_dur, key=lambda rd: (rd[1], rd[0].get("id", "")))[0]
```

This is a 1-line change with no schema or sidecar impact.

---

## C2 Implementation Prompt

```
You are Subagent C2 for Round 3 of the MusIQ-Lab identify-pipeline overhaul.
Implement the silence-strip preprocessing layer designed by C1.

Working directory (worktree):
  <PROJECT_PATH>/.claude/worktrees/identify-overhaul
Branch: worktree-identify-overhaul

FIRST, read these files before writing a single line of code:
  1. docs/superpowers/identify-overhaul/round-3-c1-silence-strip-design.md  (your spec)
  2. analyze/stages/identify.py  (current state, SCHEMA_VERSION=2)
  3. analyze/clients/acoustid.py  (recording selector tie-break change goes here)
  4. analyze/sidecar.py  (to understand params-hash invalidation)
  5. webui/webui/stage_manifest.py  (SCHEMA_VERSION must be bumped here too)
  6. webui/tests/test_stage_manifest_in_sync.py  (drift test)
  7. docs/superpowers/identify-overhaul/round-2-review.md  (R2 fold-ins context)

## Files to create or modify

### A. analyze/stages/identify.py

1. Change DEFAULT_PARAMS (line 31) to:
   DEFAULT_PARAMS: dict = {
       "silence_strip_enabled": True,
       "silence_strip_threshold_db": -50,
       "silence_strip_min_duration_sec": 0.3,
       "silence_strip_gate_sec": 0.3,
   }

2. Change SCHEMA_VERSION (line 30) to 3.

3. Add new imports at top (if not already present): `import tempfile`

4. Add two new private functions ABOVE `_run_fpcalc`:

   `_detect_leading_silence(mp3, threshold_db, min_duration_sec) -> float`:
   - Command: ["ffmpeg", "-i", str(mp3), "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration_sec}", "-f", "null", "-"]
   - capture_output=True, text=True (stderr has the events)
   - Parse stderr for the FIRST line matching `silence_end: <float_val>`
   - If that value <= 30.0: return it
   - Otherwise: return 0.0
   - Any exception from subprocess: raise it (caller catches with broad except)

   `_strip_leading_silence(mp3, threshold_db, min_duration_sec) -> Path`:
   - Create temp file: tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=mp3.parent)
   - Command: ["ffmpeg", "-y", "-i", str(mp3), "-af", f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_duration={min_duration_sec}:detection=peak", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(Path(tmp.name))]
   - capture_output=True, check=True
   - Return Path(tmp.name)
   - On failure: unlink the temp file before re-raising

5. Modify run() following the pseudo-code in the C1 design §3 and §6.
   CRITICAL: the `finally` block that unlinks `strip_tmp` must wrap the ENTIRE
   processing pipeline (fpcalc + AcoustID + MB), not just the fpcalc call.

6. D3 fold-in: change source="none" to source="acoustid_unenriched" in the
   MusicBrainz error path. Update _log_outcome docstring.

### B. analyze/clients/acoustid.py

Recording tie-break: change min() key lambda to:
   lambda rd: (rd[1], rd[0].get("id", ""))

### C. webui/webui/stage_manifest.py

Find the identify entry and change "schema_version": 2 to "schema_version": 3.

### D. webui/tests/test_identify_round3.py  (new file)

Write the 16 tests listed in C1 design §9. Use monkeypatch for subprocess.
Integration tests (14-16) gated by @pytest.mark.skipif on corpus MP3 presence.
AcoustID calls always mocked.

## Verification steps before committing

1. Run via WSL (timing on real corpus MP3s):
   time ffmpeg -i "/mnt/f/.../charlie_puth_attention.mp3" -af "silencedetect=noise=-50dB:d=0.3" -f null - 2>&1 | grep -E "silence_end|real"
   time ffmpeg -y -i "/mnt/f/.../ren_x_chinchilla.mp3" -af "silenceremove=start_periods=1:..." -ar 44100 -ac 1 -c:a pcm_s16le /tmp/test.wav 2>&1 | tail -5
   ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1 /tmp/test.wav

   Expected:
   - charlie_puth: silence_end ~0.45, wall time <0.5s
   - ren_x_chinchilla: wall time <2s, stripped duration 338.2 ± 0.5s
   - balthazar: no silence_end output

   If any deviation: report before committing.

2. Run pytest:
   cd webui && python -m pytest tests/ -x -q

3. Verify test_stage_manifest_in_sync passes.

## Commit message

feat(identify): silence-strip preprocessing + SCHEMA_VERSION=3 (Round 3)

- Strips leading silence (> 0.3s at -50 dB) via ffmpeg silenceremove
  before fpcalc fingerprinting
- Query strategy: raw fingerprint first; stripped fallback on zero AcoustID
  results
- DEFAULT_PARAMS now contains 4 silence_strip_* keys; all schema_version=2
  caches stale (legacy bridge protects identified=true caches)
- Also lands R2 fold-ins: source=acoustid_unenriched (D3); recording
  tie-break determinism (secondary sort by recording.id)

ffmpeg timing on JINN (filled in from verification):
  - charlie_puth silencedetect: Xs
  - ren_x_chinchilla silenceremove: Xs, output duration: Xs
  - balthazar: no leading silence

Corpus ceiling: 3-4 additional identifications from 6 gated Bucket-A tracks;
5 zero-silence Bucket-A tracks are fingerprint-not-in-DB (Round 4).

Refs: docs/superpowers/specs/2026-05-12-identify-pipeline-overhaul.md §C1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Hard rules
- Edit only: analyze/stages/identify.py, analyze/clients/acoustid.py,
  webui/webui/stage_manifest.py, and the new test file
- DO NOT modify _preserve_or_write, _atomic_write_text, or sidecar.py
- DO NOT edit webui/tests/test_paths.py (deferred per R2 §5)
- DO NOT commit if pytest reports any failures
- DO NOT commit if ffmpeg timing exceeds 2s on either step
```

---

## Sources

- [Chromaprint | AcoustID](https://acoustid.org/chromaprint)
- [How does Chromaprint work?](https://oxygene.sk/2011/01/how-does-chromaprint-work/)
- [chromaprint/src/chromaprint.h](https://github.com/acoustid/chromaprint/blob/master/src/chromaprint.h)
- [chromaprint/src/cmd/fpcalc.cpp](https://github.com/acoustid/chromaprint/blob/master/src/cmd/fpcalc.cpp)
