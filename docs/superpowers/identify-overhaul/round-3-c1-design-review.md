# Round 3 C1 Design Review

**Reviewer:** R3 Pass 1 (feature-dev:code-reviewer)
**Date:** 2026-05-12
**Verdict:** **REVISE DESIGN** — two critical blockers must be fixed before C2 starts.

Reviewing: `docs/superpowers/identify-overhaul/round-3-c1-silence-strip-design.md`
Source files read: `analyze/stages/identify.py`, `analyze/clients/acoustid.py`, `analyze/sidecar.py`, `webui/webui/stage_manifest.py`, plus round-1 corpus probe + round-2 delta.

---

## 1. ffmpeg Parameter Scrutiny

### Finding 1A (CRITICAL): `silencedetect` reads the entire file — C1's performance claim is wrong.

C1 §8 states "ffmpeg stops processing after the first non-silent event is found." **This is factually incorrect.** `af_silencedetect.c` uses `filter_frame()` → `ff_filter_frame()` which passes every frame downstream unconditionally. `-f null` discards output but does not terminate the decode chain. For a 300s MP3 the probe decodes all 300 s, not ~7 s.

Revised estimate without `-t 30`:
- `_detect_leading_silence` probe on a 300 s MP3 at 15–25× realtime: **12–20 s wall time** (not 0.3–0.5 s)
- Total overhead per gated track: **12–21 s** (blows the <2 s budget by 6–10×)

**Fix:** add `-t 30` to the probe command (must appear BEFORE `-i` to apply as an input duration limit, not an output filter):

```
ffmpeg -t 30 -i /path/to/track.mp3 -af "silencedetect=noise=-50dB:d=0.3" -f null -
```

Also add `-t 150` to the silenceremove command, since `fpcalc` only reads the first 120 s of audio (`g_max_duration = 120`). 150 s gives 30 s of headroom for stripping plus 120 s for fingerprinting. Halves the temp WAV size and the encode time:

```
ffmpeg -t 150 -y -i /path/to/track.mp3 -af "silenceremove=..." -ar 44100 -ac 1 -c:a pcm_s16le /tmp/x.wav
```

### Finding 1B (Important): `detection=peak` justification is weak but the choice is correct.

C1 justifies `detection=peak` on "consistency with the probe." Not a strong architectural reason. The real factors:
- `peak` triggers on instantaneous amplitude (vinyl-rip transients could miss strips with peak)
- `rms` integrates energy over a 20 ms window — more robust against transients

For YouTube slates at -30 to -45 dB (continuous near-silence), both are fine. The -50 dB threshold's conservatism makes detection mode low-risk. **Accept `peak`; correct the justification.**

### Finding 1C (Minor): `-ac 1` (mono) is harmless.

`fpcalc` mixes to mono internally before the Chromaprint pipeline. Mono input saves one arithmetic step and halves WAV size — irrelevant since fpcalc only reads 120 s anyway. **No change needed.**

### Finding 1D (Minor): `-ar 44100` is correct but overstated.

Chromaprint resamples to 11 025 Hz internally. Input sample rate doesn't matter for fingerprint output. 44.1 kHz is fine; justification can be tightened.

### Finding 1E (Minor): `start_duration=0.3` and `start_threshold=-50dB` justified for this corpus.

The N=0.3 s gate captures all 6 measured-leading-silence tracks including the marginal charlie_puth case at 0.45 s. The -50 dB threshold protects intentional intros (most are above -30 dB). Edge case: a quiet swell from -55 dB → -30 dB over 2 s would have its first ~0.8 s stripped. Document as known limitation.

---

## 2. Query Strategy: RAW FIRST, STRIPPED FALLBACK

### Finding 2A: Correct for the 24 already-identified tracks.

All currently-identified tracks match on raw fingerprint. RAW FIRST preserves zero regression. ✓

### Finding 2B: Wastes one AcoustID call per gated Bucket-A track. Acceptable.

6 extra calls × 0.33 s per call ≈ 2 s of total rate-limit consumption. Within budget. ✓

### Finding 2C (Critical-Theoretical, Low-Risk in practice): RAW FIRST can accept a wrong match.

If the AcoustID DB ever gains a fingerprint for a *different* song that matches the raw fingerprint (including the leading silence), RAW FIRST accepts the wrong match. The B1 duration selector mitigates this (`recording.duration` filter) but doesn't eliminate it. Current corpus has zero false-positive instances. Document as a known assumption rather than design to defeat.

### Finding 2D: The `match is None` trigger is correct.

Strip-fallback fires on `match is None` (empty results OR all results unlinked-or-below-threshold). The bucket-B-with-silence case wastes one strip + one extra AcoustID call but doesn't break correctness.

---

## 3. Test Plan Completeness

### Finding 3A (Important): Only 3 of 6 gated Bucket-A slugs have integration tests.

C1 §9 tests 14-16 cover charlie_puth, ren_x_chinchilla, balthazar. The other 4 gated slugs (jamel_debbouze_stromae, sting_rijksmuseum, it_could_happen_to_you, submotion_orchestra) are absent. The 3-track set covers the range (short / long / zero silence) which is defensible — but the design must STATE this rather than leaving the reader to infer it.

### Finding 3B (Important): No explicit test for AcoustID 429 / rate-limit.

C1 §9 test 7 covers `AcoustIDError` generically. AcoustID 429 raises `AcoustIDError` per `acoustid.py:94-108`. The `strip_tmp` cleanup fires in the `finally` block IF the `finally` is placed correctly (see Finding 5A — this is exactly the case where vague `finally` placement bites).

### Finding 3C (Important — recommend ADD): No `source=acoustid_stripped` distinction in the structured log.

C1's design has `_log_outcome` emit `source=acoustid` regardless of whether the match came from raw or stripped fingerprint. For Round 3 observability — and for the Round 3 delta report — we need to distinguish "identified via raw" from "identified via stripped." 

**Fix:** introduce `source="acoustid_stripped"` for matches from the stripped-fingerprint path. Add a test asserting this is logged when the stripped fallback succeeds.

### Finding 3D (Important): `.acoustid_raw.json` write in the stripped-fallback block isn't specified.

C1 §3 pseudo-code shows the AcoustID call in the stripped fallback but no `_cache_raw_acoustid` call. The raw-cache contract from B1 is: cache the response on every successful query. C2 must call `_cache_raw_acoustid` in the stripped-fallback block too. The `fingerprint_hash` field will differ from the raw fingerprint's hash, which is correct behavior (the hash identifies WHICH fingerprint produced WHICH response).

### Finding 3E (Minor): No test for `silence_end > 30 s` returning 0.0.

The 30 s anchor check is load-bearing (prevents stripping mid-track gaps). Needs a dedicated unit test.

---

## 4. Risks Adequately Addressed

### Finding 4A (Important): Intentional pre-roll risk understated.

The 30 s anchor check protects against internal gaps, NOT against long leading atmospheric passages (e.g. 15 s of sparse intro at -52 dB). The -50 dB threshold is the actual protection. Document explicitly.

### Finding 4B: VBR MP3 timestamp imprecision is a non-issue.

silencedetect and silenceremove decode the same demuxer; both operate on PCM samples after demux. Output WAV is uncompressed so its duration is sample-exact. No risk.

### Finding 4C: Cumulative latency on `/analyze-stale` is small AFTER Finding 1A is fixed.

With `-t 30`, probe overhead is 0.3–0.5 s. For 24 identified tracks, legacy bridge in `cached()` returns True without invoking `run()` so ffmpeg is never called. **Concern resolved by Finding 1A fix.**

### Finding 4D: Legacy bridge correctly handles BOTH schema and params-hash changes.

Verified by reading `identify.py:42-61` and `sidecar.py:73-74`. `sidecar.matches()` returns False on ANY of: missing sidecar, schema mismatch, params mismatch. Bridge fires whenever `matches()` is False AND `identified=true`. The synthesized v3 sidecar contains the new DEFAULT_PARAMS so subsequent `cached()` calls return True without bridge intervention. **C1's claim is correct.**

### Finding 4E: Demotion protection is airtight.

`_preserve_or_write` preserves existing `identified=true` regardless of which path (raw or stripped) was attempted in `run()`. No new risk.

---

## 5. Wire-in Correctness

### Finding 5A (CRITICAL): `finally` placement spec is dangerously vague.

C1 §3 says "C2: put the finally at the outermost try level, not just around _run_fpcalc." This is insufficient — current `run()` has TWO separate try/except blocks (lines 130-147 for fpcalc, lines 149-171 for AcoustID), no outermost wrapper. C2 must:

1. Add a new outer `try/finally` wrapping BOTH existing inner try/except blocks
2. Keep the inner `try/except` blocks intact (they handle specific error classes and have early returns)
3. Put `strip_tmp.unlink(missing_ok=True)` in the outer `finally`

Required code skeleton (C2 must follow exactly):

```python
def run(mp3, cache_dir, **params):
    p = {**DEFAULT_PARAMS, **params}
    slug = cache_dir.name
    
    # Preprocessing
    strip_tmp: Path | None = None
    if p.get("silence_strip_enabled", True):
        try:
            leading_sec = _detect_leading_silence(mp3, ...)
            if leading_sec > p.get("silence_strip_gate_sec", 0.3):
                strip_tmp = _strip_leading_silence(mp3, ...)
        except Exception as exc:
            log.warning(...)
            strip_tmp = None
    
    try:
        # Existing try/except for fpcalc + AcoustID + MB + _preserve_or_write
        # ...all existing logic, plus stripped-fallback block...
        return result
    finally:
        if strip_tmp is not None:
            strip_tmp.unlink(missing_ok=True)
```

Early returns inside the inner except blocks STILL trigger the outer `finally` (Python guarantee). This is the only correct placement.

### Finding 5B (Minor): `mp3.parent` for temp WAV is fine on NTFS via WSL.

The cache dir is read-write on both Windows and WSL. No permission issue.

### Finding 5C (Important): `_detect_leading_silence` parse logic — take FIRST `silence_end` match.

silencedetect prints all silence regions; we want only the FIRST. C1's spec is correct ("Parse stderr for the FIRST line matching `silence_end:`"). Both `re.search` (first match in string) and line-by-line iteration work.

---

## 6. SCHEMA_VERSION Decision

### Finding 6A: Dual-path invalidation correctly handled.

`sidecar.matches()` fails on either schema OR params mismatch. Bridge fires in both cases when `identified=true`. C1's choice of bumping SCHEMA_VERSION=3 is correct (explicit versioning) but the params change alone would also invalidate. **Accept SCHEMA_VERSION=3.**

### Finding 6B: `stage_manifest.py` test is the only drift guard.

`test_stage_manifest_in_sync` uses `ast.literal_eval` (no analyze.* import — works on Windows). C2 must update both `analyze/stages/identify.py:30` and `webui/webui/stage_manifest.py` identify entry. Run pytest after.

---

## 7. R2 Fold-ins

### Finding 7A: D3 (`source=acoustid_unenriched`) correctly scoped.

3-line change. Update the `_log_outcome` docstring to list ALL valid sources: `acoustid | acoustid_stripped | acoustid_unenriched | none` (note: `acoustid_stripped` per Finding 3C).

### Finding 7B: Recording tie-break determinism correctly scoped.

1-line change: secondary sort by `recording.id` (lexicographic, deterministic).

---

## 8. Additional Risks C1 Missed

### Finding 8A (Important): Stripped duration must be passed to AcoustID, not raw duration.

C1 §3 pseudo-code correctly uses `fp_stripped["duration"]` for the stripped lookup. Document explicitly: passing `fp_raw["duration"]` to a stripped-fingerprint lookup would invalidate AcoustID's duration-based recording selection.

### Finding 8B (RESOLVED — orchestrator did pre-design check): fpcalc version.

R2 §6-A required this check. The orchestrator confirmed: fpcalc 1.5.1 (Chromaprint 1.5.1, the AcoustID-canonical version). **Not a blocker.**

### Finding 8C (Minor): No test for post-strip duration < 30s guard.

C1 §10 mentions the guard but it's absent from the pseudo-code and test plan. If C2 implements it, add a test: stripped fingerprint with duration < 30 s → abort the stripped lookup; identify returns the raw-result outcome.

---

## Summary of Required Changes

**MUST FIX (blockers before C2 starts):**

1. **Finding 1A** — Add `-t 30` to the probe command and `-t 150` to the strip command. Update §2a, §2b, §8 accordingly. Without this, the probe takes 12-20 s per track and Round 3 is infeasible.

2. **Finding 5A** — Replace the vague "outermost try/finally" instruction with the explicit code skeleton above. C2's prompt at the end of C1 must include this skeleton verbatim.

3. **Finding 3C** — Add `source=acoustid_stripped` as a distinct log value when the match comes from the stripped path. Update `_log_outcome` docstring and test plan.

**SHOULD FIX (recommended; can be C2 notes if design is otherwise stable):**

4. **Finding 3A** — Justify 3-track integration coverage explicitly.
5. **Finding 3D** — Specify `_cache_raw_acoustid` call in stripped-fallback block.
6. **Finding 3E** — Add unit test for `silence_end > 30s` returning 0.0.
7. **Finding 4A** — Document quiet-swell as a known limitation explicitly.
8. **Finding 8A** — Document the stripped-duration-passes-to-AcoustID requirement.
9. **Finding 8C** — Add the post-strip minimum-duration guard to pseudo-code + test plan.

---

## Recommendation: REVISE DESIGN

The architecture is sound. The query strategy is correct. The SCHEMA_VERSION decision is correct. The legacy bridge interaction is correctly analyzed.

Two blockers must be fixed in the C1 design before C2 implements:

- **Blocker 1 (Finding 1A):** silencedetect probe duration limit — without `-t 30`, the probe blows the <2 s budget by 6-10×, making Round 3 latency unacceptable.
- **Blocker 2 (Finding 5A):** explicit code skeleton for the outer `try/finally` — C2 will get it wrong without an explicit pattern, leaving temp WAVs uncleaned in error paths.

The orchestrator's choice: revise C1's design doc to incorporate these fixes (small edits) and proceed to C2 with the revised doc, OR relaunch C1 with these notes. Given the small scope of the revisions, the former is recommended.

The R2-required fpcalc version check (Finding 8B) was already done by the orchestrator (fpcalc 1.5.1, Chromaprint 1.5.1, AcoustID-canonical). Not a blocker.
