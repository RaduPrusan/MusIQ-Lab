# Key/Scale Enharmonic Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD throughout: red → green → commit.

**Goal:** Make the analyzer emit one consistent enharmonic spelling for a track's key everywhere it appears in `summary.json`, so `track.key` and `analysis.scale` (and the `chords_alt_key` block) never disagree on the tonic letter.

**Architecture:** Add a single canonicalization function (`canonical_key_name`) in `analyze/derived/theory.py` that returns the same string `scale_name` produces, and route every human-readable key string through it at the writer boundary. Because `track.key` will adopt the full scale-style spelling (`"E♭ natural minor"`), `parse_key` must first be hardened to round-trip Unicode accidentals (♯/♭) and quality words (`natural`/`harmonic`/`melodic`) — without that, `compute_agreement`'s `_keys_equivalent` (which `parse_key`s `track.key`) silently returns `ok=False` for every flat-minor track.

**Tech Stack:** Python 3.11, pytest. Pure-logic change — no new deps, no Torch/lockfile changes, no JS changes.

**Decisions locked (2026-06-13, user-confirmed):**
- **`track.key` format:** full scale string, byte-identical to `analysis.scale` (e.g. `"E♭ natural minor"`, `"F♯ major"`). → requires `parse_key` hardening (Task 1).
- **Cache migration:** re-run `analyze` per track (cached stages skip; only `summary.json` re-derives). No migration script, no summary schema bump.

**Spec source:** `prompts/fix-key-scale-enharmonic-coherence.md`. Deviations from that prompt: (a) tests live in `tests/unit/`, not the prompt's nonexistent `analyze/tests/`; (b) no schema bump (no summary-level `SCHEMA_VERSION` exists) — migration is a documented re-run.

---

## File Structure

- `analyze/derived/theory.py` — **modify.** Harden `parse_key` (Unicode + quality words); add `canonical_key_name`; optionally factor a shared `_canonical_tonic` helper used by both `scale_name` and `canonical_key_name`.
- `analyze/writers/summary_writer.py` — **modify** line 134: route `track.key` through `canonical_key_name(parse_key(...))`.
- `analyze/derived/alt_key.py` — **modify** line 85: `key` field through `canonical_key_name(alt_key)` instead of raw `alt_key_str`.
- `tests/unit/test_key_scale_coherence.py` — **create.** Round-trip, idempotency, spelling rule, writer-boundary coherence, alt-key coherence.
- `tests/unit/test_essentia_agreement.py` — **modify:** add one regression test that `compute_agreement` works when `pipeline_key` is the canonical scale-string form.
- `tests/unit/test_writers.py` — **modify if needed:** update any assertion that reads the pre-fix raw `track.key`.

---

## Task 1: Harden `parse_key` for Unicode accidentals + quality words

**Files:**
- Modify: `analyze/derived/theory.py:26-43` (the `_KEY_RE` regex + `parse_key` body)
- Test: `tests/unit/test_key_scale_coherence.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_key_scale_coherence.py`:

```python
import json
from pathlib import Path

from analyze.derived.theory import Key, parse_key


class TestParseKeyHardening:
    def test_parses_unicode_sharp(self):
        assert parse_key("F♯ major") == Key(tonic_pc=6, mode="major")

    def test_parses_unicode_flat_with_natural_word(self):
        # scale_name emits this exact form; parse_key must round-trip it.
        assert parse_key("E♭ natural minor") == Key(tonic_pc=3, mode="minor")

    def test_parses_harmonic_and_melodic_qualifiers(self):
        assert parse_key("A harmonic minor") == Key(tonic_pc=9, mode="minor")
        assert parse_key("A melodic minor") == Key(tonic_pc=9, mode="minor")

    def test_still_parses_legacy_forms(self):
        assert parse_key("D# minor") == Key(tonic_pc=3, mode="minor")
        assert parse_key("F#:major") == Key(tonic_pc=6, mode="major")
        assert parse_key("F minor") == Key(tonic_pc=5, mode="minor")
        assert parse_key("C major") == Key(tonic_pc=0, mode="major")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestParseKeyHardening -v`
Expected: FAIL — `test_parses_unicode_sharp`, `test_parses_unicode_flat_with_natural_word`, `test_parses_harmonic_and_melodic_qualifiers` raise `ValueError: unparseable key` (legacy-form test passes).

- [ ] **Step 3: Harden `parse_key`**

In `analyze/derived/theory.py`, replace the regex (lines 26-29):

```python
_KEY_RE = re.compile(
    r"^\s*([A-G][#b]?)\s*[:\s]?\s*(major|maj|minor|min)\s*$",
    re.IGNORECASE,
)
```
with:

```python
# Note token, optional colon/space, optional scale-quality word
# (natural/harmonic/melodic — emitted by scale_name), then the mode.
_KEY_RE = re.compile(
    r"^\s*([A-G][#b]?)\s*:?\s*(?:(?:natural|harmonic|melodic)\s+)?(major|maj|minor|min)\s*$",
    re.IGNORECASE,
)
```

and add Unicode normalization as the first line of `parse_key` (currently line 33), so the function head becomes:

```python
def parse_key(s: str) -> Key:
    # Normalize Unicode music accidentals to ASCII so scale_name output
    # (e.g. "E♭ natural minor", "F♯ major") round-trips.
    s = s.replace("♯", "#").replace("♭", "b")
    m = _KEY_RE.match(s)
    if not m:
        raise ValueError(f"unparseable key: {s!r}")
```

(Leave the rest of the body unchanged — `m.group(1)` is still the note, `m.group(2)` is still the mode, because the quality word is a non-capturing group.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestParseKeyHardening -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_key_scale_coherence.py
git commit -m @'
feat(analyze): harden parse_key for Unicode accidentals + quality words

parse_key now round-trips scale_name's own output (Unicode ♯/♭ and the
natural/harmonic/melodic qualifier). Prereq for canonicalizing track.key
to the scale-string form: compute_agreement._keys_equivalent parse_keys
track.key, so without this it would silently report ok=False for flat-
minor tracks. Legacy forms ("D# minor", "F#:major") still parse.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## Task 2: Add `canonical_key_name`

**Files:**
- Modify: `analyze/derived/theory.py:416-430` (`scale_name`; factor `_canonical_tonic`, add `canonical_key_name`)
- Test: `tests/unit/test_key_scale_coherence.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_key_scale_coherence.py`:

```python
from analyze.derived.theory import canonical_key_name, scale_name


class TestCanonicalKeyName:
    def test_roundtrips_all_pcs_and_modes(self):
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                assert parse_key(canonical_key_name(k)) == k

    def test_idempotent(self):
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                once = canonical_key_name(k)
                assert canonical_key_name(parse_key(once)) == once

    def test_flat_minor_spelling_rule(self):
        # PCs 1,3,6,8,10 in minor come out flat (Db/Eb/Gb/Ab/Bb).
        assert canonical_key_name(Key(tonic_pc=3, mode="minor")) == "E♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=1, mode="minor")) == "D♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=6, mode="minor")) == "G♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=8, mode="minor")) == "A♭ natural minor"
        assert canonical_key_name(Key(tonic_pc=10, mode="minor")) == "B♭ natural minor"

    def test_major_keys_use_sharp_letter_spelling(self):
        assert canonical_key_name(Key(tonic_pc=6, mode="major")) == "F♯ major"
        assert canonical_key_name(Key(tonic_pc=3, mode="major")) == "D♯ major"

    def test_byte_identical_to_scale_name(self):
        # track.key must equal analysis.scale, so the two functions agree.
        for pc in range(12):
            for mode in ("major", "minor"):
                k = Key(tonic_pc=pc, mode=mode)
                assert canonical_key_name(k) == scale_name(k)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestCanonicalKeyName -v`
Expected: FAIL — `ImportError: cannot import name 'canonical_key_name'`.

- [ ] **Step 3: Factor `_canonical_tonic` and add `canonical_key_name`**

In `analyze/derived/theory.py`, replace `scale_name` (lines 416-430):

```python
def scale_name(key: Key) -> str:
    """Return a human-readable scale name, e.g. 'C major' or 'F natural minor'.

    For major keys, always use sharp spellings (F♯ major, not G♭ major).
    For minor keys, prefer flat spellings for conventionally flat-notated tonics
    (Bb, Eb, Ab, Db, Gb minor → B♭, E♭, A♭, D♭, G♭ natural minor).
    """
    pc = key.tonic_pc
    if key.mode == "minor" and pc in _PREFER_FLAT_PCS:
        tonic = _PC_TO_FLAT_NAME[pc]
    else:
        tonic = _PC_TO_NOTE[pc]
    if key.mode == "major":
        return f"{tonic} major"
    return f"{tonic} natural minor"
```
with:

```python
def _canonical_tonic(key: Key) -> str:
    """Tonic letter spelling per the canonical rule: major → sharp letters;
    minor → flat for the conventionally flat-notated pitch classes
    ({C♯/D♭, D♯/E♭, F♯/G♭, G♯/A♭, A♯/B♭})."""
    pc = key.tonic_pc
    if key.mode == "minor" and pc in _PREFER_FLAT_PCS:
        return _PC_TO_FLAT_NAME[pc]
    return _PC_TO_NOTE[pc]


def scale_name(key: Key) -> str:
    """Return a human-readable scale name, e.g. 'C major' or 'F natural minor'.

    For major keys, always use sharp spellings (F♯ major, not G♭ major).
    For minor keys, prefer flat spellings for conventionally flat-notated tonics
    (Bb, Eb, Ab, Db, Gb minor → B♭, E♭, A♭, D♭, G♭ natural minor).
    """
    tonic = _canonical_tonic(key)
    if key.mode == "major":
        return f"{tonic} major"
    return f"{tonic} natural minor"


def canonical_key_name(key: Key) -> str:
    """Canonical human-readable key string for writer boundaries.

    Identical to `scale_name`'s output so `track.key` and `analysis.scale`
    always agree on enharmonic spelling. Round-trips with `parse_key`:
    parse_key(canonical_key_name(k)) == k. Use this at every summary-writer
    boundary that emits a human-readable key string.
    """
    return scale_name(key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestCanonicalKeyName -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_key_scale_coherence.py
git commit -m @'
feat(analyze): add canonical_key_name (scale-string form for key strings)

canonical_key_name returns the same string scale_name produces, via a
shared _canonical_tonic helper. Round-trips through the hardened parse_key.
This is the single canonicalization point for human-readable key strings.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## Task 3: Route `track.key` through `canonical_key_name` in the summary writer

**Files:**
- Modify: `analyze/writers/summary_writer.py` (import + line 134)
- Test: `tests/unit/test_key_scale_coherence.py`; verify `tests/unit/test_writers.py`

- [ ] **Step 1: Write the failing writer-coherence test**

Append to `tests/unit/test_key_scale_coherence.py`:

```python
from analyze.writers.summary_writer import write_summary


class TestWriterBoundaryCoherence:
    def _minimal_results(self, raw_key: str) -> dict:
        return {
            "beats": {"bpm": 120.0, "downbeats": [0.5, 2.5], "time_signature": "4/4"},
            "key": {"key": raw_key, "confidence": 1.0},
            "chords": [],
        }

    def test_track_key_matches_analysis_scale(self, tmp_path):
        # Raw skey output is sharp ("D# minor"); analysis.scale is flat.
        out = tmp_path / "song.summary.json"
        mp3 = tmp_path / "song.mp3"
        mp3.write_bytes(b"")
        results = self._minimal_results("D# minor")
        derived = {"scale": scale_name(parse_key("D# minor"))}
        write_summary(out, mp3, results, derived, warnings=[], duration_sec=200.0)

        data = json.loads(out.read_text())
        track_key = data["track"]["key"]
        scale = data["analysis"]["scale"]
        # Same Key object…
        assert parse_key(track_key) == parse_key(scale)
        # …and same tonic letter spelling (the actual bug).
        assert track_key.split()[0] == scale.split()[0] == "E♭"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestWriterBoundaryCoherence -v`
Expected: FAIL — `track.key` is `"D# minor"` (raw), `scale` is `"E♭ natural minor"`; tonic letters `"D#"` ≠ `"E♭"`.

- [ ] **Step 3: Route `track.key` through the canonicalizer**

In `analyze/writers/summary_writer.py`, add the import near the top (after the `import analyze` line, ~line 47):

```python
from analyze.derived.theory import canonical_key_name, parse_key
```

Change line 134 from:

```python
            "key": results["key"]["key"],
```
to:

```python
            "key": canonical_key_name(parse_key(results["key"]["key"])),
```

(`compute_agreement(summary["track"], ...)` at line 168 reads this canonicalized value automatically, satisfying Goal #2 — `essentia_agreement.key.analyze` stays byte-identical to `track.key`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestWriterBoundaryCoherence -v`
Expected: PASS.

- [ ] **Step 5: Repair any existing writer test that asserted the raw spelling**

Run: `python -m pytest tests/unit/test_writers.py -v`
Expected: any test that asserts `summary["track"]["key"] == "F minor"` (the `fake_results` fixture uses `"F minor"`) now sees `"F natural minor"`. If such an assertion exists, update its expected value to `"F natural minor"` — the test was reading the pre-fix raw layer (the prompt explicitly authorizes fixing such drifted assertions). If no test asserts `track.key`, no change is needed.

To find them: `grep -n '\["key"\]' tests/unit/test_writers.py` and inspect each hit under `summary["track"]`.

- [ ] **Step 6: Commit**

```bash
git add analyze/writers/summary_writer.py tests/unit/test_key_scale_coherence.py tests/unit/test_writers.py
git commit -m @'
fix(analyze): canonicalize track.key so it matches analysis.scale

summary.track.key now routes through canonical_key_name(parse_key(...)) at
the writer boundary, so it carries the same enharmonic spelling as
analysis.scale (both "E♭ natural minor", not "D# minor" vs "E♭ natural
minor"). essentia_agreement.key.analyze echoes the canonical form for free.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## Task 4: Canonicalize the `chords_alt_key` block

**Files:**
- Modify: `analyze/derived/alt_key.py:84-85` (the returned `key` field)
- Test: `tests/unit/test_key_scale_coherence.py`

- [ ] **Step 1: Write the failing alt-key coherence test**

Append to `tests/unit/test_key_scale_coherence.py`:

```python
from analyze.derived.alt_key import derive_alt_key_block


class TestAltKeyCoherence:
    def test_alt_block_key_matches_scale(self):
        # Essentia consensus arrives in colon form ("F#:major").
        block = derive_alt_key_block(
            chords_enriched=[{"label": "F#:maj"}],
            predominant_loop=None,
            alt_key_str="F#:major",
        )
        assert parse_key(block["key"]) == parse_key(block["scale"])
        assert block["key"].split()[0] == block["scale"].split()[0] == "F♯"

    def test_alt_block_flat_minor_consensus(self):
        block = derive_alt_key_block(
            chords_enriched=[],
            predominant_loop=None,
            alt_key_str="Eb:minor",
        )
        assert block["key"] == block["scale"] == "E♭ natural minor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestAltKeyCoherence -v`
Expected: FAIL — `block["key"]` is the raw `"F#:major"` / `"Eb:minor"` echo; `"F#:major".split()[0]` is `"F#:major"`, not `"F♯"`.

- [ ] **Step 3: Build the alt-key `key` field canonically**

In `analyze/derived/alt_key.py`, add `canonical_key_name` to the import (lines 26-32):

```python
from analyze.derived.theory import (
    canonical_key_name,
    function_for,
    parse_chord,
    parse_key,
    roman_for,
    scale_name,
)
```

Change the returned `key` field (line 85) from:

```python
        "key": alt_key_str,
```
to:

```python
        "key": canonical_key_name(alt_key),
```

(`"scale": scale_name(alt_key)` on line 86 stays — it now equals `key` byte-for-byte. `alt_key` is the `parse_key(alt_key_str)` object already built at line 68.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_key_scale_coherence.py::TestAltKeyCoherence -v`
Expected: PASS.

- [ ] **Step 5: Verify no alt_key test asserted the raw echo**

Run: `python -m pytest tests/unit -k alt_key -v`
Expected: PASS. If a pre-existing test asserts `block["key"] == "Bb:major"` (raw echo), update it to `canonical_key_name(parse_key("Bb:major"))` → `"B♭ major"` — same drifted-layer rationale as Task 3 Step 5.

- [ ] **Step 6: Commit**

```bash
git add analyze/derived/alt_key.py tests/unit/test_key_scale_coherence.py
git commit -m @'
fix(analyze): canonicalize chords_alt_key.key to match its scale field

The alt-key block echoed the raw consensus string ("F#:major") as `key`
while `scale` used scale_name; they now both route through the canonical
spelling so the webui Key toggle shows a coherent alt key.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## Task 5: Regression guard — agreement works with canonical `track.key`

**Files:**
- Modify: `tests/unit/test_essentia_agreement.py` (add one test)

This guards the `compute_agreement → _keys_equivalent → parse_key(track.key)` path now that `track.key` is the scale-string form.

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_essentia_agreement.py`:

```python
def test_key_agreement_with_canonical_scale_string_pipeline_key():
    """track.key now arrives as 'E♭ natural minor' (canonical form). The
    cross-check must still parse it and compute equivalence — not fall into
    _keys_equivalent's except→False path. Eb minor's relative major is Gb
    major; an Eb-major consensus is parallel (NOT equivalent)."""
    pipeline = {"key": "E♭ natural minor"}
    essentia = {
        "extracted": True,
        "tempo": {"bpm": 120.0},
        "key": {
            "krumhansl": ["Gb", "major", 0.80],
            "temperley": ["Gb", "major", 0.78],
            "edma": ["B", "major", 0.40],
        },
    }
    agreement = compute_agreement(pipeline, essentia)
    # Gb major is the relative major of Eb minor → equivalent → ok.
    assert agreement["key"]["ok"] is True
    assert agreement["key"]["analyze"] == "E♭ natural minor"
```

- [ ] **Step 2: Run test to verify it passes (parse_key already hardened in Task 1)**

Run: `python -m pytest tests/unit/test_essentia_agreement.py::test_key_agreement_with_canonical_scale_string_pipeline_key -v`
Expected: PASS. (If Task 1 were skipped, this would fail with `ok=False` — that's the silent regression this guard exists to catch.)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_essentia_agreement.py
git commit -m @'
test(analyze): guard compute_agreement against canonical track.key form

Regression guard: track.key is now "E♭ natural minor"; ensure
_keys_equivalent parses it (not the except→False path) so the Essentia
cross-check stays correct for flat-minor tracks.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
'@
```

---

## Task 6: Full-suite verification + pipeline smoke + migration note

**Files:** none (verification only)

- [ ] **Step 1: Run the targeted suite**

Run: `python -m pytest tests/unit -k "key or scale or theory or coherence or agreement or writer" -v`
Expected: PASS, no skips for these.

- [ ] **Step 2: Run the broader analyze unit suite for regressions**

Run: `python -m pytest tests/unit -q`
Expected: PASS (same count as before plus the new tests). Investigate any failure that reads a key/scale string — it's a drifted-layer assertion to update, not a logic break.

- [ ] **Step 3: Pipeline smoke (user-invoked, WSL)**

The pipeline runs in WSL2 with the project venv. On a sharp/flat-ambiguous track already in cache (e.g. Charlie Puth — Attention), re-run analyze — cached stages skip; only the summary re-derives:

Run (in WSL): `python -m analyze "<path-to-attention.mp3>"`
Then inspect: `cache/charlie_puth-attention_official_video-nfs8nyg7yqm/summary.json` — confirm `track.key` and `analysis.scale` are byte-identical, and `essentia_agreement.key.analyze` matches `track.key`.

- [ ] **Step 4: Migration — re-run analyze across cached tracks**

Per the locked decision, there is no migration script. Old `summary.json` files keep their inconsistent spelling until re-derived. To migrate the whole cache, re-run analyze on each cached track (cached stages skip, so this is cheap and GPU-light). The webui picks up the new values on next page reload — no JS or static-asset change. Note this in the final summary to the user so they know to re-run on the tracks they care about.

- [ ] **Step 5: Final confirmation**

No extra commit needed — Tasks 1-5 already committed their work. Confirm `git status` is clean and `git log --oneline -6` shows the five feat/fix/test commits.

---

## Self-review

**1. Spec coverage (vs `prompts/fix-key-scale-enharmonic-coherence.md`):**
- Goal #1 (`track.key` & `analysis.scale` same `Key` + same tonic spelling) → Task 3.
- Goal #2 (`essentia_agreement.key.analyze` == `track.key`) → free via Task 3 (compute_agreement reads the canonicalized dict) + guarded in Task 5.
- Goal #3 (`chords_alt_key.key`/`.scale` coherent) → Task 4.
- Goal #4 (`skey.json` keeps raw) → respected; we canonicalize only at the writer boundary, never mutate `results["key"]["key"]`.
- Goal #5 (round-trip stable) → Task 2 tests (round-trip + idempotent).
- "What to test" 1-6 → Tasks 2 (1,2,3), 3 (4), 4 (5), 3 Step 5 (6).
- Cache migration → Task 6 Step 4 (re-run, per locked decision).
- Boundaries (don't touch `scale_name` output, chord labels, `skey.json`, JS, lockfile) → respected; `scale_name`'s *output* is unchanged (only refactored to share `_canonical_tonic`).

**2. Placeholder scan:** every code step shows the exact before/after; every test step shows full test bodies; commands are exact. No TBD/TODO.

**3. Type/name consistency:** `canonical_key_name`, `_canonical_tonic`, `parse_key`, `scale_name`, `Key(tonic_pc=…, mode=…)`, `derive_alt_key_block`, `compute_agreement`, `write_summary` — all used consistently with their real signatures verified against the current source. `write_summary(summary_path, mp3_path, results, derived, warnings, duration_sec, …)` matches `summary_writer.py:99`. `_KEY_RE` group indices preserved (quality word is non-capturing, so `m.group(2)` is still the mode).

**Note on parse_key hardening risk:** `parse_key` is used at `pipeline.py:607`, `alt_key.py:68`, `summary_writer.py` (new), `essentia_extract.py:174-175`, and likely elsewhere. The change is strictly *additive* (accepts more forms; still parses all old forms) — verified against legacy-form test in Task 1. Task 6 Step 2 is the regression backstop.
