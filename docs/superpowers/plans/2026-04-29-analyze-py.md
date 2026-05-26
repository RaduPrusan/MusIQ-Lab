# `analyze.py` Implementation Plan

> **Status: SHIPPED late April 2026** via the subagent-driven build documented in [`docs/history.md`](../../history.md) Phase H ("`analyze` package landed"). The `analyze/` package is the production driver — `python -m analyze <mp3>` produces JAMS + `summary.json` under `cache/<slug>/`. Post-ship fixes layered on (CUDA tensor release `02cc19d`, presence-gate thresholds `0f31b05`, per-stem presence gate `804dc2c`); Phase A+B (May 2026) added task-specialist models on top — see `2026-05-03-phase-ab-pipeline-upgrade.md`. **Plan body retained as historical narrative; current code is at `analyze/`.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the production driver for the validated MIR pipeline — `python -m analyze <mp3>` produces JAMS + summary.json under `cache/<slug>/`, with full music-theory derivations (Roman numerals, scale, per-note role/in_chord/scale_deg, predominant chord loop, vocal range).

**Architecture:** `analyze/` Python package with stages/, derived/, writers/ subpackages. Each stage/module has one job, can run standalone via `python -m analyze.<module>`. Pipeline orchestrator hard-fails on foundational stages (stems, downbeats, key, chords, transcription), soft-fails on cross-checks (beat-this, vocal_f0). Cache reuse by default; `--force` recomputes.

**Tech Stack:** Python 3.11 (project venv at `.venv/`), Torch 2.7+cu126, jams 0.3.5, pretty_midi 0.2.11, librosa 0.11.0, numpy 2.2.6, pytest. WSL2 Ubuntu 24.04. RTX 3090.

**Reference docs:**
- Spec: `docs/superpowers/specs/2026-04-29-analyze-py-design.md`
- Stage source-of-truth: `prompts/test-stack-torch27.md` Phase 6, also captured in `install-logs/rerun-mp3.sh`
- Output format spec (allin1-era, partially superseded): `docs/research/output-format.md`
- Validated reference cache: `cache/gorillaz_silent_running/`

**Execution environment for every step:**
```bash
# All commands assume WSL bash with the venv activated:
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
```

When invoking from the Claude Code Bash tool (Git Bash on Windows / msys2), use `MSYS_NO_PATHCONV=1` and escape `$VAR` as `\$VAR` in single-quoted args. See `~/.claude/projects/.../memory/wsl_bash_dollar_quoting.md`.

**Git note:** This project is not currently a git repo. The `git add` / `git commit` steps below are advisory checkpoints. If you want them to take effect, run `git init` once before Task 1.

---

## File structure

```
analyze/
├── __init__.py            # __version__ = "0.1.0", public API surface (Task 2)
├── __main__.py            # python -m analyze entry point → cli.main() (Task 20)
├── cli.py                 # argparse, --force, --quiet, --slug; dispatches to pipeline (Task 20)
├── pipeline.py            # required/optional stage orchestration, error policy (Task 19)
├── cache.py               # slug derivation, cache_dir creation, is_done() probes, clear() (Task 1)
├── stages/
│   ├── __init__.py        # (Task 12)
│   ├── stems.py           # Stage 1: audio-separator subprocess (Task 12)
│   ├── beats.py           # Stage 2a: madmom downbeats + tempo (Task 13)
│   ├── beats_xcheck.py    # Stage 3: beat-this (Task 14)
│   ├── key.py             # Stage 4: skey + librosa K-S fallback (Task 15)
│   ├── chords.py          # Stage 5: lv-chordia (Task 16)
│   ├── transcription.py   # Stage 6: basic-pitch per stem (Task 17)
│   └── vocal_f0.py        # Stage 7: torchfcpe + pesto (Task 18)
├── derived/
│   ├── __init__.py        # (Task 3)
│   ├── theory.py          # key parsing, chord parsing, Roman numerals, function, scale (Tasks 3-7)
│   ├── note_enrichment.py # per-note role / in_chord / scale_deg (Task 9)
│   ├── loop_detect.py     # predominant_chord_loop + appearances (Task 8)
│   └── vocal_range.py     # low/high from vocals MIDI (Task 10)
└── writers/
    ├── __init__.py        # (Task 11)
    ├── jams_writer.py     # all 8+ JAMS annotations (Task 11)
    └── summary_writer.py  # summary.json assembly (Task 11)

tests/
├── __init__.py
├── unit/
│   ├── __init__.py
│   ├── test_cache.py            # (Task 1)
│   ├── test_theory_key.py       # (Task 3)
│   ├── test_theory_chord.py     # (Task 4)
│   ├── test_theory_roman.py     # (Task 5)
│   ├── test_theory_function.py  # (Task 6)
│   ├── test_theory_scale.py     # (Task 7)
│   ├── test_loop_detect.py      # (Task 8)
│   ├── test_note_enrichment.py  # (Task 9)
│   └── test_vocal_range.py      # (Task 10)
└── integration/
    ├── __init__.py
    └── test_gorillaz.py         # full-pipeline test against validated cache (Task 21)

requirements-dev.txt           # pytest pin (Task 0)
```

---

## Task 0: Add pytest to dev requirements

**Files:**
- Create: `requirements-dev.txt`

- [ ] **Step 1: Create `requirements-dev.txt`**

```
# Test-time only; not constrained by constraints-torch27-cu126.txt
pytest>=8,<9
```

- [ ] **Step 2: Install pytest into the venv**

Run:
```bash
python -m pip install -r requirements-dev.txt
```

Expected: pytest installs cleanly. If it pulls in conflicting versions of anything, stop and investigate — the runtime venv is a known-good lock.

- [ ] **Step 3: Verify pytest works**

Run:
```bash
pytest --version
```

Expected: `pytest 8.x.y`

- [ ] **Step 4: Commit**

```bash
git add requirements-dev.txt
git commit -m "chore: add pytest dev dependency"
```

---

## Task 1: cache.py — slug derivation, cache layout, is_done probes

**Files:**
- Create: `analyze/__init__.py`
- Create: `analyze/cache.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_cache.py`

- [ ] **Step 1: Create `analyze/__init__.py`**

```python
"""MusIQ-Lab music analysis pipeline driver."""
__version__ = "0.1.0"
```

- [ ] **Step 2: Create empty test packages**

Create `tests/__init__.py`:
```python
```

Create `tests/unit/__init__.py`:
```python
```

- [ ] **Step 3: Write failing tests for `cache.py`**

Create `tests/unit/test_cache.py`:

```python
from pathlib import Path

import pytest

from analyze import cache


def test_slug_for_strips_punctuation_and_lowercases():
    p = Path("Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3")
    assert cache.slug_for(p) == "gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg"


def test_slug_for_collapses_runs_and_strips_edges():
    p = Path("___Hello---World___.mp3")
    assert cache.slug_for(p) == "hello_world"


def test_slug_for_handles_unicode():
    p = Path("Beyoncé - Halo.mp3")
    # non-alnum (incl. é) collapses to _; result is ascii
    assert cache.slug_for(p) == "beyonc_halo"


def test_ensure_dir_creates_under_project_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d = cache.ensure_dir("my_song")
    assert d == tmp_path / "cache" / "my_song"
    assert d.is_dir()


def test_ensure_dir_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d1 = cache.ensure_dir("my_song")
    d2 = cache.ensure_dir("my_song")
    assert d1 == d2
    assert d1.is_dir()


def test_clear_removes_contents_preserves_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PROJECT_ROOT", tmp_path)
    d = cache.ensure_dir("my_song")
    (d / "stuff.json").write_text("{}")
    (d / "subdir").mkdir()
    (d / "subdir" / "file.wav").write_bytes(b"data")
    cache.clear(d)
    assert d.is_dir()
    assert list(d.iterdir()) == []


def test_is_newer_than_mp3_true_when_file_newer(tmp_path):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    out = tmp_path / "out.json"
    out.write_text("{}")
    # touch out to be slightly newer
    import os, time
    time.sleep(0.01)
    out.touch()
    assert cache.is_newer_than_mp3(out, mp3) is True


def test_is_newer_than_mp3_false_when_mp3_newer(tmp_path):
    out = tmp_path / "out.json"
    out.write_text("{}")
    import time
    time.sleep(0.01)
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    assert cache.is_newer_than_mp3(out, mp3) is False


def test_is_newer_than_mp3_false_when_out_missing(tmp_path):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"x")
    out = tmp_path / "missing.json"
    assert cache.is_newer_than_mp3(out, mp3) is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_cache.py -v
```

Expected: All 9 tests FAIL with `ModuleNotFoundError: No module named 'analyze.cache'` or attribute errors.

- [ ] **Step 5: Implement `analyze/cache.py`**

Create `analyze/cache.py`:

```python
"""Cache layout, slug derivation, staleness probes.

Cache layout:
    <PROJECT_ROOT>/cache/<slug>/
        stems_6s/*.wav              (Stage 1)
        stems_bsroformer/*.wav      (Stage 1)
        madmom_downbeats.json       (Stage 2a)
        sections.json               (Stage 2b — placeholder)
        beat_this.json              (Stage 3)
        skey.json                   (Stage 4)
        chords.json                 (Stage 5)
        midi/{vocals,bass,guitar,piano,other}.mid  (Stage 6)
        transcription_summary.json  (Stage 6)
        vocal_f0.npz                (Stage 7)
        vocal_f0_summary.json       (Stage 7)
        reconciliation_preview.json (Stage 8)
        <slug>.jams                 (final)
        <slug>.summary.json         (final)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_for(mp3_path: Path) -> str:
    stem = mp3_path.stem.lower()
    s = _SLUG_RE.sub("_", stem)
    return s.strip("_")


def ensure_dir(slug: str) -> Path:
    d = PROJECT_ROOT / "cache" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear(cache_dir: Path) -> None:
    for child in cache_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def is_newer_than_mp3(out_path: Path, mp3_path: Path) -> bool:
    if not out_path.exists():
        return False
    return out_path.stat().st_mtime >= mp3_path.stat().st_mtime
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_cache.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add analyze/__init__.py analyze/cache.py tests/__init__.py tests/unit/__init__.py tests/unit/test_cache.py
git commit -m "feat(cache): slug derivation + cache layout + staleness probes"
```

---

## Task 2: Public API stub

**Files:**
- Modify: `analyze/__init__.py`

- [ ] **Step 1: Add public API surface to `analyze/__init__.py`**

Replace `analyze/__init__.py` with:

```python
"""MusIQ-Lab music analysis pipeline driver."""
__version__ = "0.1.0"

# Public API — populated as modules are added.
# from analyze.pipeline import analyze, AnalyzeResult, PipelineError
```

(The import line stays commented until Task 19; this file just declares the version.)

- [ ] **Step 2: Commit**

```bash
git add analyze/__init__.py
git commit -m "chore(analyze): version stub for public API"
```

---

## Task 3: derived/theory.py — key parsing

**Files:**
- Create: `analyze/derived/__init__.py`
- Create: `analyze/derived/theory.py`
- Create: `tests/unit/test_theory_key.py`

- [ ] **Step 1: Write failing tests for key parsing**

Create `tests/unit/test_theory_key.py`:

```python
import pytest

from analyze.derived.theory import Key, parse_key


def test_parse_key_space_form_major():
    assert parse_key("C major") == Key(tonic_pc=0, mode="major")
    assert parse_key("F major") == Key(tonic_pc=5, mode="major")


def test_parse_key_space_form_minor():
    assert parse_key("F minor") == Key(tonic_pc=5, mode="minor")
    assert parse_key("A minor") == Key(tonic_pc=9, mode="minor")


def test_parse_key_colon_form():
    assert parse_key("F:min") == Key(tonic_pc=5, mode="minor")
    assert parse_key("G:maj") == Key(tonic_pc=7, mode="major")


def test_parse_key_sharp_and_flat():
    assert parse_key("F# minor") == Key(tonic_pc=6, mode="minor")
    assert parse_key("Gb major") == Key(tonic_pc=6, mode="major")
    assert parse_key("Bb minor") == Key(tonic_pc=10, mode="minor")
    assert parse_key("A# major") == Key(tonic_pc=10, mode="major")


def test_parse_key_strips_whitespace():
    assert parse_key("  C major  ") == Key(tonic_pc=0, mode="major")


def test_parse_key_case_insensitive_mode():
    assert parse_key("C MAJOR") == Key(tonic_pc=0, mode="major")
    assert parse_key("F Minor") == Key(tonic_pc=5, mode="minor")


def test_parse_key_invalid_raises():
    with pytest.raises(ValueError):
        parse_key("nonsense")
    with pytest.raises(ValueError):
        parse_key("H major")  # H is not a valid note letter
    with pytest.raises(ValueError):
        parse_key("C dorian")  # only major/minor supported in v1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_theory_key.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'analyze.derived'`.

- [ ] **Step 3: Create `analyze/derived/__init__.py`**

```python
```

- [ ] **Step 4: Implement `analyze/derived/theory.py` (key parsing only)**

Create `analyze/derived/theory.py`:

```python
"""Music-theory primitives: key parsing, chord parsing, Roman numerals,
diatonic function, scale name. All pure functions; no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Pitch class indices: C=0, C#/Db=1, D=2, D#/Eb=3, E=4, F=5,
# F#/Gb=6, G=7, G#/Ab=8, A=9, A#/Bb=10, B=11.
_NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
    "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

Mode = Literal["major", "minor"]


@dataclass(frozen=True)
class Key:
    tonic_pc: int  # 0..11
    mode: Mode


_KEY_RE = re.compile(
    r"^\s*([A-G][#b]?)\s*[:\s]?\s*(major|maj|minor|min)\s*$",
    re.IGNORECASE,
)


def parse_key(s: str) -> Key:
    m = _KEY_RE.match(s)
    if not m:
        raise ValueError(f"unparseable key: {s!r}")
    note = m.group(1).capitalize()
    # canonicalize: 'C#' stays 'C#', 'cb' → 'Cb' but only valid letters reach here
    note = note[0].upper() + note[1:].lower() if len(note) > 1 else note
    if note not in _NOTE_TO_PC:
        raise ValueError(f"unknown note letter: {note!r}")
    mode_raw = m.group(2).lower()
    mode: Mode = "major" if mode_raw.startswith("maj") else "minor"
    return Key(tonic_pc=_NOTE_TO_PC[note], mode=mode)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_theory_key.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add analyze/derived/__init__.py analyze/derived/theory.py tests/unit/test_theory_key.py
git commit -m "feat(theory): key parsing"
```

---

## Task 4: derived/theory.py — chord parsing

**Files:**
- Modify: `analyze/derived/theory.py` (add `Chord`, `parse_chord`)
- Create: `tests/unit/test_theory_chord.py`

- [ ] **Step 1: Write failing tests for chord parsing**

Create `tests/unit/test_theory_chord.py`:

```python
import pytest

from analyze.derived.theory import Chord, parse_chord


def test_parse_chord_simple_minor():
    c = parse_chord("F:min")
    assert c.root_pc == 5
    assert c.bass_pc == 5  # no inversion → bass = root
    assert c.quality == "min"
    assert c.extensions == []
    assert c.is_no_chord is False


def test_parse_chord_simple_major():
    c = parse_chord("C:maj")
    assert c.root_pc == 0
    assert c.bass_pc == 0
    assert c.quality == "maj"
    assert c.extensions == []


def test_parse_chord_sharp_root():
    c = parse_chord("C#:maj")
    assert c.root_pc == 1
    assert c.quality == "maj"


def test_parse_chord_flat_root():
    c = parse_chord("Eb:maj")
    assert c.root_pc == 3
    assert c.quality == "maj"


def test_parse_chord_dominant_seventh():
    c = parse_chord("D:7")
    assert c.root_pc == 2
    # "X:7" means major triad + minor 7th (= dominant 7); we treat as quality="maj" with ext "7"
    assert c.quality == "maj"
    assert c.extensions == ["7"]


def test_parse_chord_inversion_bass_third():
    c = parse_chord("Eb:maj/3")
    assert c.root_pc == 3
    # /3 → bass is 4 semitones up from Eb (major third) = G (pc=7)
    assert c.bass_pc == 7
    assert c.quality == "maj"


def test_parse_chord_inversion_bass_fifth():
    c = parse_chord("F:min/5")
    assert c.root_pc == 5
    # /5 → bass is 7 semitones up from F = C (pc=0)
    assert c.bass_pc == 0


def test_parse_chord_no_chord():
    c = parse_chord("N")
    assert c.is_no_chord is True
    assert c.quality == "N"


def test_parse_chord_unknown_label_returns_unknown():
    c = parse_chord("X")
    assert c.quality == "unknown"
    assert c.root_pc is None


def test_parse_chord_letter_form_minor():
    # alt notation lv-chordia sometimes uses
    c = parse_chord("Fm")
    assert c.root_pc == 5
    assert c.quality == "min"


def test_parse_chord_letter_form_maj7():
    c = parse_chord("Cmaj7")
    assert c.root_pc == 0
    assert c.quality == "maj"
    assert "7" in c.extensions  # spec says: extension list — exact representation is implementation choice


def test_parse_chord_unparseable_returns_unknown_with_raw_label():
    c = parse_chord("???garbage???")
    assert c.quality == "unknown"
    assert c.raw_label == "???garbage???"


def test_parse_chord_diminished():
    c = parse_chord("B:dim")
    assert c.root_pc == 11
    assert c.quality == "dim"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_theory_chord.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Chord'` or similar.

- [ ] **Step 3: Add `Chord` and `parse_chord` to `analyze/derived/theory.py`**

Append to `analyze/derived/theory.py`:

```python
from typing import Optional

# Inversion bass intervals from chord root, in semitones.
# "/3" means a major third above root; "/b3" means minor third; etc.
_INVERSION_INTERVALS = {
    "1": 0,
    "b2": 1, "2": 2,
    "b3": 3, "3": 4,
    "4": 5,
    "b5": 6, "5": 7, "#5": 8,
    "b6": 8, "6": 9,
    "b7": 10, "7": 11,
}

# Harte-style quality tokens we recognize.
_QUALITY_TOKENS = {
    "maj", "min", "dim", "aug", "sus2", "sus4", "maj7", "min7", "7", "dim7", "hdim7", "minmaj7",
}


@dataclass(frozen=True)
class Chord:
    root_pc: Optional[int]    # 0..11, or None for N/unknown
    bass_pc: Optional[int]    # 0..11, or None for N/unknown
    quality: str              # "maj"/"min"/"dim"/"aug"/"sus2"/"sus4"/"N"/"unknown"
    extensions: list[str]     # e.g. ["7"], ["b9", "#11"]
    raw_label: str
    is_no_chord: bool = False


# Harte-style: ROOT[:QUALITY[(EXTENSIONS)]][/BASS]
_HARTE_RE = re.compile(
    r"^\s*([A-G][#b]?)"
    r"(?::([a-zA-Z0-9]+)"
    r"(?:\(([^)]*)\))?)?"
    r"(?:/([#b]?\d+))?\s*$"
)
# Letter-form: ROOT[QUALITY_LETTER][EXTENSIONS][/BASS]
_LETTER_RE = re.compile(
    r"^\s*([A-G][#b]?)"
    r"(maj|min|m|M|dim|aug|sus[24]?)?"
    r"(\d+)?"
    r"([#b]\d+)?"
    r"(?:/([A-G][#b]?))?\s*$"
)


def _normalize_note(s: str) -> str:
    return s[0].upper() + (s[1:].lower() if len(s) > 1 else "")


def _quality_to_extensions(qtoken: str) -> tuple[str, list[str]]:
    """Split a quality+extension token like 'maj7' or 'min7' into (quality, [extensions])."""
    qtoken = qtoken.lower()
    if qtoken in {"maj", "min", "dim", "aug", "sus2", "sus4"}:
        return qtoken, []
    if qtoken == "7":
        # bare "7" = dominant 7 = major triad + b7
        return "maj", ["7"]
    if qtoken == "maj7":
        return "maj", ["maj7"]
    if qtoken in {"min7", "m7"}:
        return "min", ["7"]
    if qtoken == "dim7":
        return "dim", ["7"]
    if qtoken == "hdim7":  # half-diminished
        return "dim", ["7"]
    if qtoken == "minmaj7":
        return "min", ["maj7"]
    return qtoken, []


def parse_chord(label: str) -> Chord:
    label = label.strip()
    if label in {"N", "n"}:
        return Chord(root_pc=None, bass_pc=None, quality="N", extensions=[], raw_label=label, is_no_chord=True)
    if label in {"X", "x"}:
        return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)

    m = _HARTE_RE.match(label)
    if m:
        root = _normalize_note(m.group(1))
        if root not in _NOTE_TO_PC:
            return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)
        root_pc = _NOTE_TO_PC[root]
        qtoken = (m.group(2) or "maj").lower()
        ext_inside = m.group(3) or ""
        bass_token = m.group(4)
        quality, exts = _quality_to_extensions(qtoken)
        if ext_inside:
            exts = exts + [e.strip() for e in ext_inside.split(",") if e.strip()]
        bass_pc = root_pc
        if bass_token:
            interval = _INVERSION_INTERVALS.get(bass_token)
            if interval is not None:
                bass_pc = (root_pc + interval) % 12
        return Chord(root_pc=root_pc, bass_pc=bass_pc, quality=quality, extensions=exts, raw_label=label)

    # Try letter-form (Cmaj7, Fm, F#m7b5/A)
    m = _LETTER_RE.match(label)
    if m:
        root = _normalize_note(m.group(1))
        if root not in _NOTE_TO_PC:
            return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)
        root_pc = _NOTE_TO_PC[root]
        qletter = m.group(2)
        digit = m.group(3)
        accidental = m.group(4)
        bass_letter = m.group(5)

        if qletter in {"m", "min"}:
            quality = "min"
        elif qletter in {"M", "maj"}:
            quality = "maj"
        elif qletter == "dim":
            quality = "dim"
        elif qletter == "aug":
            quality = "aug"
        elif qletter and qletter.startswith("sus"):
            quality = qletter
        else:
            quality = "maj"

        exts: list[str] = []
        if digit:
            if digit == "7" and quality == "maj":
                exts.append("7")
            elif digit == "7" and quality == "min":
                exts.append("7")
            elif digit == "7":
                exts.append("7")
            else:
                exts.append(digit)
        if accidental:
            exts.append(accidental)

        bass_pc = root_pc
        if bass_letter:
            bass_norm = _normalize_note(bass_letter)
            if bass_norm in _NOTE_TO_PC:
                bass_pc = _NOTE_TO_PC[bass_norm]

        return Chord(root_pc=root_pc, bass_pc=bass_pc, quality=quality, extensions=exts, raw_label=label)

    return Chord(root_pc=None, bass_pc=None, quality="unknown", extensions=[], raw_label=label)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_theory_chord.py -v
```

Expected: All 13 tests PASS. If `test_parse_chord_letter_form_maj7` fails because `extensions` doesn't contain `"7"`, ensure `_quality_to_extensions` is also applied to letter-form chords — adjust if needed.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_theory_chord.py
git commit -m "feat(theory): chord parsing (Harte + letter forms, inversions, extensions)"
```

---

## Task 5: derived/theory.py — Roman numeral derivation

**Files:**
- Modify: `analyze/derived/theory.py` (add `roman_for`)
- Create: `tests/unit/test_theory_roman.py`

- [ ] **Step 1: Write failing tests for Roman numerals**

Create `tests/unit/test_theory_roman.py`:

```python
import pytest

from analyze.derived.theory import Key, parse_chord, roman_for


# Helper
def r(chord_label: str, key_str: str) -> str | None:
    from analyze.derived.theory import parse_key
    return roman_for(parse_chord(chord_label), parse_key(key_str))


# === Major key diatonic ===
def test_major_diatonic():
    assert r("C:maj", "C major") == "I"
    assert r("D:min", "C major") == "ii"
    assert r("E:min", "C major") == "iii"
    assert r("F:maj", "C major") == "IV"
    assert r("G:maj", "C major") == "V"
    assert r("A:min", "C major") == "vi"
    assert r("B:dim", "C major") == "vii°"


def test_major_dominant_seventh():
    assert r("G:7", "C major") == "V7"


# === Minor key diatonic (natural minor) ===
def test_minor_diatonic_natural():
    assert r("F:min", "F minor") == "i"
    assert r("G:dim", "F minor") == "ii°"
    assert r("Ab:maj", "F minor") == "♭III"
    assert r("Bb:min", "F minor") == "iv"
    assert r("C:min", "F minor") == "v"
    assert r("Db:maj", "F minor") == "♭VI"
    assert r("Eb:maj", "F minor") == "♭VII"


def test_minor_raised_leading_tone_dominant():
    # In F minor, E:7 is the harmonic-minor V (raised leading tone).
    # Interval E - F = 11 (or -1 mod 12). We mark this as V (uppercase, dominant).
    assert r("E:7", "F minor") == "V7"


# === Modal interchange in major ===
def test_modal_interchange_in_major():
    # In C major: bIII, bVI, bVII (borrowed from parallel minor)
    assert r("Eb:maj", "C major") == "♭III"
    assert r("Ab:maj", "C major") == "♭VI"
    assert r("Bb:maj", "C major") == "♭VII"


# === Modal interchange in minor (Neapolitan, etc.) ===
def test_neapolitan_in_minor():
    # In F minor, the bII is Gb (root pc 6, F=5, interval 1) — major chord.
    assert r("Gb:maj", "F minor") == "♭II"


# === Inversions ===
def test_inversion_first_inversion_third_in_bass():
    assert r("C:maj/3", "C major") == "I/3"


def test_inversion_second_inversion_fifth_in_bass():
    assert r("C:maj/5", "C major") == "I/5"


def test_inversion_minor_chord_first_inversion():
    # F:min/3 — bass is Ab (minor third)
    assert r("F:min/3", "F minor") == "i/♭3"


# === Unparseable / no-chord ===
def test_no_chord_returns_none():
    assert r("N", "C major") is None


def test_unknown_chord_returns_none():
    assert r("???", "C major") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_theory_roman.py -v
```

Expected: FAIL with `ImportError: cannot import name 'roman_for'`.

- [ ] **Step 3: Add `roman_for` to `analyze/derived/theory.py`**

Append:

```python
# Diatonic interval → Roman numeral mapping.
# Major: I ii iii IV V vi vii°  (intervals 0 2 4 5 7 9 11)
# Minor: i ii° ♭III iv v ♭VI ♭VII  (intervals 0 2 3 5 7 8 10)
# Off-diatonic intervals get ♭/♯ prefix and case from chord quality.

_MAJOR_DIATONIC = {
    0: ("I", True),   # uppercase = major-typed degree
    2: ("II", False), # lowercase if chord is minor; "ii"
    4: ("III", False),
    5: ("IV", True),
    7: ("V", True),
    9: ("VI", False),
    11: ("VII", False),
}

_MINOR_DIATONIC = {
    0: ("I", False),    # i
    2: ("II", False),   # ii°
    3: ("III", True),   # ♭III but uppercase prefix
    5: ("IV", False),   # iv
    7: ("V", False),    # v (or V if dominant — natural vs harmonic minor)
    8: ("VI", True),    # ♭VI
    10: ("VII", True),  # ♭VII
}

# In minor, off-diatonic intervals
_MINOR_OFF_DIATONIC = {
    1: "♭II",
    4: "♯III",
    6: "♯IV",
    9: "♯VI",
    11: "VII",  # raised leading tone (treated as dominant when chord is major/dom7)
}

# In major, off-diatonic intervals (borrowed from parallel minor + chromatic)
_MAJOR_OFF_DIATONIC = {
    1: "♭II",
    3: "♭III",
    6: "♯IV",
    8: "♭VI",
    10: "♭VII",
}

# Bass-interval → suffix for inversion notation.
_INVERSION_SUFFIX = {
    0: "",     # root position
    1: "/♭2",
    2: "/2",
    3: "/♭3",
    4: "/3",
    5: "/4",
    6: "/♭5",
    7: "/5",
    8: "/♯5",
    9: "/6",
    10: "/♭7",
    11: "/7",
}


def _case_for_quality(numeral_upper: str, quality: str) -> str:
    if quality == "min":
        return numeral_upper.lower()
    if quality == "dim":
        return numeral_upper.lower() + "°"
    if quality == "aug":
        return numeral_upper + "+"
    if quality in {"sus2", "sus4"}:
        return numeral_upper + quality
    # maj or unknown-but-major-ish: uppercase
    return numeral_upper


def _add_extensions(roman_str: str, extensions: list[str]) -> str:
    if not extensions:
        return roman_str
    # Single-purpose: append "7" / "maj7" / extensions verbatim
    return roman_str + "".join(extensions)


def roman_for(chord, key) -> Optional[str]:
    if chord.is_no_chord or chord.root_pc is None or chord.quality == "unknown":
        return None

    interval = (chord.root_pc - key.tonic_pc) % 12

    # Step 1: scale-degree numeral + accidental
    if key.mode == "major":
        if interval in _MAJOR_DIATONIC:
            numeral_upper, _ = _MAJOR_DIATONIC[interval]
            base = _case_for_quality(numeral_upper, chord.quality)
        else:
            off = _MAJOR_OFF_DIATONIC[interval]
            # off has accidental prefix like "♭III"; case stays as-is for major chord, lowercase for min
            if chord.quality == "min":
                base = off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()
            elif chord.quality == "dim":
                base = (off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()) + "°"
            elif chord.quality == "aug":
                base = off + "+"
            else:
                base = off
    else:  # minor
        if interval in _MINOR_DIATONIC:
            numeral_upper, has_flat_prefix = _MINOR_DIATONIC[interval]
            base = _case_for_quality(numeral_upper, chord.quality)
            if has_flat_prefix:
                base = "♭" + base
        else:
            off = _MINOR_OFF_DIATONIC[interval]
            if chord.quality == "min":
                base = off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()
            elif chord.quality == "dim":
                base = (off[0] + off[1:].lower() if off[0] in "♭♯" else off.lower()) + "°"
            elif chord.quality == "aug":
                base = off + "+"
            else:
                base = off

    # Step 2: extensions
    base = _add_extensions(base, chord.extensions)

    # Step 3: inversion suffix
    if chord.bass_pc is not None and chord.bass_pc != chord.root_pc:
        bass_interval = (chord.bass_pc - chord.root_pc) % 12
        base = base + _INVERSION_SUFFIX[bass_interval]

    return base
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_theory_roman.py -v
```

Expected: All ~14 tests PASS. If a specific case (like inversion notation) renders subtly differently than the test asserts (`/♭3` vs `/b3`), update the test or implementation to agree — but pick the unicode `♭`/`♯` convention everywhere for consistency.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_theory_roman.py
git commit -m "feat(theory): Roman numeral derivation (diatonic + modal interchange + inversions)"
```

---

## Task 6: derived/theory.py — diatonic function classification

**Files:**
- Modify: `analyze/derived/theory.py` (add `function_for`)
- Create: `tests/unit/test_theory_function.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_theory_function.py`:

```python
from analyze.derived.theory import function_for, parse_chord, parse_key, roman_for


def f(chord_label: str, key_str: str) -> str | None:
    chord = parse_chord(chord_label)
    key = parse_key(key_str)
    rom = roman_for(chord, key)
    if rom is None:
        return None
    return function_for(rom, key.mode)


def test_function_tonic_major():
    assert f("C:maj", "C major") == "tonic"
    assert f("A:min", "C major") == "tonic"  # vi is also tonic-functional
    assert f("E:min", "C major") == "tonic"  # iii sometimes tonic


def test_function_predominant_major():
    assert f("D:min", "C major") == "predominant"  # ii
    assert f("F:maj", "C major") == "predominant"  # IV


def test_function_dominant_major():
    assert f("G:maj", "C major") == "dominant"
    assert f("G:7", "C major") == "dominant"
    assert f("B:dim", "C major") == "dominant"  # vii°


def test_function_modal_interchange_major():
    assert f("Eb:maj", "C major") == "modal_interchange"  # bIII
    assert f("Ab:maj", "C major") == "modal_interchange"  # bVI
    assert f("Bb:maj", "C major") == "modal_interchange"  # bVII


def test_function_tonic_minor():
    assert f("F:min", "F minor") == "tonic"


def test_function_predominant_minor():
    assert f("Bb:min", "F minor") == "predominant"  # iv
    assert f("G:dim", "F minor") == "predominant"  # ii°


def test_function_dominant_minor_natural_v_is_minor():
    # In natural minor, "v" (lowercase) is technically not a strong dominant.
    # We classify it as dominant anyway because that's its scale-position role.
    assert f("C:min", "F minor") == "dominant"


def test_function_dominant_minor_raised_v():
    # Harmonic-minor V — the major V chord
    assert f("E:7", "F minor") == "dominant"


def test_function_modal_interchange_minor_neapolitan():
    assert f("Gb:maj", "F minor") == "modal_interchange"  # bII / Neapolitan


def test_function_none_for_no_chord():
    assert f("N", "C major") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_theory_function.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add `function_for` to `analyze/derived/theory.py`**

Append:

```python
Function = Literal["tonic", "predominant", "dominant", "modal_interchange", "secondary"]

# Map base Roman numeral (no accidental, no extension, no inversion) → function.
# Mode-aware: i in minor is tonic, I in major is tonic; both use the same lookup.
_FUNCTION_MAP_MAJOR = {
    "I": "tonic", "i": "tonic",
    "ii": "predominant", "ii°": "predominant",
    "iii": "tonic",  # mediant — weak tonic
    "IV": "predominant", "iv": "predominant",
    "V": "dominant", "v": "dominant",
    "vi": "tonic",  # submediant — substitute tonic
    "vii°": "dominant",
}

_FUNCTION_MAP_MINOR = {
    "i": "tonic", "I": "tonic",
    "ii°": "predominant", "ii": "predominant",
    "♭III": "tonic",  # relative major in minor key — tonic-functional
    "iv": "predominant", "IV": "predominant",
    "v": "dominant", "V": "dominant",
    "♭VI": "modal_interchange",  # actually diatonic in minor; v1 calls it tonic-substitute
    "♭VII": "modal_interchange",
    "vii°": "dominant",
}


def _strip_extensions_inversion(roman: str) -> str:
    """Strip extensions and inversion to get bare numeral for function lookup."""
    # Remove inversion (everything from "/" on)
    if "/" in roman:
        roman = roman.split("/")[0]
    # Remove trailing digits + accidentals (extensions like "7", "b9")
    # but keep "°" and "+" which are part of the numeral itself
    # AND keep leading "♭"/"♯" accidental prefix
    base = re.match(r"^([♭♯]?[IiVv]+[°+]?)", roman)
    return base.group(1) if base else roman


def function_for(roman_str: str, mode: Mode) -> Optional[Function]:
    if not roman_str:
        return None
    bare = _strip_extensions_inversion(roman_str)

    # Off-diatonic accidentals → modal_interchange
    if bare.startswith("♭") or bare.startswith("♯"):
        # In minor, ♭III ♭VI ♭VII are diatonic — handle via mode map below first
        table = _FUNCTION_MAP_MINOR if mode == "minor" else _FUNCTION_MAP_MAJOR
        if bare in table:
            return table[bare]  # type: ignore[return-value]
        return "modal_interchange"

    table = _FUNCTION_MAP_MINOR if mode == "minor" else _FUNCTION_MAP_MAJOR
    if bare in table:
        return table[bare]  # type: ignore[return-value]
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_theory_function.py -v
```

Expected: All ~10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_theory_function.py
git commit -m "feat(theory): diatonic function classification"
```

---

## Task 7: derived/theory.py — scale name + helpers

**Files:**
- Modify: `analyze/derived/theory.py` (add `scale_name`, `pc_to_note_name`, `scale_degree_for`)
- Create: `tests/unit/test_theory_scale.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_theory_scale.py`:

```python
import pytest

from analyze.derived.theory import (
    parse_key,
    pc_to_note_name,
    scale_degree_for,
    scale_name,
)


def test_scale_name_major():
    assert scale_name(parse_key("C major")) == "C major"
    assert scale_name(parse_key("F# major")) == "F♯ major"


def test_scale_name_minor():
    assert scale_name(parse_key("F minor")) == "F natural minor"
    assert scale_name(parse_key("Bb minor")) == "B♭ natural minor"


def test_pc_to_note_name_naturals():
    assert pc_to_note_name(0) == "C"
    assert pc_to_note_name(5) == "F"
    assert pc_to_note_name(11) == "B"


def test_pc_to_note_name_sharps_or_flats():
    # We use sharps as canonical for unicode clarity.
    assert pc_to_note_name(1) == "C♯"
    assert pc_to_note_name(6) == "F♯"
    assert pc_to_note_name(8) == "G♯"


def test_scale_degree_for_in_C_major():
    # Note pc 0 (C) in C major = "1"; pc 7 (G) = "5"
    key = parse_key("C major")
    assert scale_degree_for(0, key) == "1"
    assert scale_degree_for(7, key) == "5"
    assert scale_degree_for(11, key) == "7"


def test_scale_degree_for_chromatic_in_C_major():
    key = parse_key("C major")
    assert scale_degree_for(1, key) == "♭2"
    assert scale_degree_for(3, key) == "♭3"
    assert scale_degree_for(6, key) == "♯4"
    assert scale_degree_for(8, key) == "♭6"
    assert scale_degree_for(10, key) == "♭7"


def test_scale_degree_uses_major_scale_relative_regardless_of_mode():
    # spec says: "Always relative to the major scale of the tonic, regardless of mode"
    minor_key = parse_key("F minor")  # tonic_pc=5
    # The note Ab (pc=8) is the "♭3" relative to F major (a minor third up)
    assert scale_degree_for(8, minor_key) == "♭3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_theory_scale.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add `scale_name`, `pc_to_note_name`, `scale_degree_for` to `analyze/derived/theory.py`**

Append:

```python
# Canonical sharp-spelled note names per pitch class (unicode ♯ for clarity).
_PC_TO_NOTE = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]

# Scale-degree label per chromatic interval from tonic, relative to MAJOR scale.
_INTERVAL_TO_DEGREE = {
    0: "1", 1: "♭2", 2: "2", 3: "♭3", 4: "3", 5: "4",
    6: "♯4", 7: "5", 8: "♭6", 9: "6", 10: "♭7", 11: "7",
}


def pc_to_note_name(pc: int) -> str:
    return _PC_TO_NOTE[pc % 12]


def _ascii_to_unicode_accidental(name: str) -> str:
    return name.replace("#", "♯").replace("b", "♭") if len(name) > 1 else name


def scale_name(key: Key) -> str:
    tonic = pc_to_note_name(key.tonic_pc)
    if key.mode == "major":
        return f"{tonic} major"
    return f"{tonic} natural minor"


def scale_degree_for(note_pc: int, key: Key) -> str:
    interval = (note_pc - key.tonic_pc) % 12
    return _INTERVAL_TO_DEGREE[interval]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_theory_scale.py -v
```

Expected: All 7 tests PASS. If `pc_to_note_name(1)` returns `"C#"` instead of `"C♯"`, ensure `_PC_TO_NOTE` uses the unicode `♯` character.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/theory.py tests/unit/test_theory_scale.py
git commit -m "feat(theory): scale name + scale-degree mapping"
```

---

## Task 8: derived/loop_detect.py — predominant chord loop

**Files:**
- Create: `analyze/derived/loop_detect.py`
- Create: `tests/unit/test_loop_detect.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_loop_detect.py`:

```python
import pytest

from analyze.derived.loop_detect import predominant_chord_loop


def make_chords(labels_with_times: list[tuple[float, float, str]]) -> list[dict]:
    """Helper to build chord dicts."""
    return [{"start": s, "end": e, "label": l} for (s, e, l) in labels_with_times]


def test_simple_two_chord_loop():
    chords = make_chords([
        (0.0, 1.0, "F:min"),
        (1.0, 2.0, "C:min"),
        (2.0, 3.0, "F:min"),
        (3.0, 4.0, "C:min"),
        (4.0, 5.0, "F:min"),
        (5.0, 6.0, "C:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
    assert len(appearances) == 3  # three full passes
    assert appearances[0] == {"start": 0.0, "end": 2.0}
    assert appearances[1] == {"start": 2.0, "end": 4.0}
    assert appearances[2] == {"start": 4.0, "end": 6.0}


def test_collapses_consecutive_duplicates():
    chords = make_chords([
        (0.0, 1.0, "F:min"),
        (1.0, 2.0, "F:min"),
        (2.0, 3.0, "C:min"),
        (3.0, 4.0, "F:min"),
        (4.0, 5.0, "C:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
    assert len(appearances) == 2  # [F:min, C:min] appears twice (with the run of F:min collapsed)


def test_longer_loop_wins_when_score_higher():
    # 4-chord loop appearing 3 times = score 12
    # 2-chord loop appearing 6 times = score 12 (tie — longer loop wins by tie-breaker)
    chords = make_chords([
        (i * 1.0, (i + 1) * 1.0, label)
        for i, label in enumerate(["F:min", "C:min", "Ab:maj", "Eb:maj"] * 3)
    ])
    loop, _ = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min", "Ab:maj", "Eb:maj"]


def test_no_repeating_loop_returns_none():
    chords = make_chords([
        (0.0, 1.0, "C:maj"),
        (1.0, 2.0, "G:maj"),
        (2.0, 3.0, "F:maj"),
        (3.0, 4.0, "Am:min"),
    ])
    loop, appearances = predominant_chord_loop(chords)
    assert loop is None
    assert appearances == []


def test_handles_single_chord():
    chords = make_chords([(0.0, 1.0, "C:maj")])
    loop, appearances = predominant_chord_loop(chords)
    assert loop is None
    assert appearances == []


def test_skips_no_chord_spans():
    # "N" entries collapse into the sequence; the loop algorithm operates on labels.
    # Per spec, we leave N in place — loop just won't include them as part of any meaningful pattern.
    chords = make_chords([
        (0.0, 1.0, "N"),
        (1.0, 2.0, "F:min"),
        (2.0, 3.0, "C:min"),
        (3.0, 4.0, "F:min"),
        (4.0, 5.0, "C:min"),
    ])
    loop, _ = predominant_chord_loop(chords)
    assert loop == ["F:min", "C:min"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_loop_detect.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `analyze/derived/loop_detect.py`**

Create:

```python
"""Predominant chord loop detection.

Scores all sliding windows of length 2..8 over the chord label sequence
(with consecutive duplicates collapsed). Score = count × length. Returns
the highest-scoring window, or None if no length-≥2 window appears ≥2 times.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional


def _collapse_runs(chords: list[dict]) -> list[dict]:
    """Collapse consecutive identical labels, keeping the first chord's start
    and the last chord's end for each run."""
    if not chords:
        return []
    out = [dict(chords[0])]
    for c in chords[1:]:
        if c["label"] == out[-1]["label"]:
            out[-1]["end"] = c["end"]
        else:
            out.append(dict(c))
    return out


def _find_appearances(chords: list[dict], loop: list[str]) -> list[dict]:
    """Find every contiguous run in `chords` (after collapsing) matching the loop pattern.
    Returns appearances as {start, end}."""
    appearances = []
    L = len(loop)
    n = len(chords)
    i = 0
    while i + L <= n:
        if [c["label"] for c in chords[i:i + L]] == loop:
            appearances.append({
                "start": chords[i]["start"],
                "end": chords[i + L - 1]["end"],
            })
            i += L  # non-overlapping
        else:
            i += 1
    return appearances


def predominant_chord_loop(
    chords: list[dict],
) -> tuple[Optional[list[str]], list[dict]]:
    collapsed = _collapse_runs(chords)
    labels = [c["label"] for c in collapsed]

    best_loop: Optional[list[str]] = None
    best_score = 3  # require score > 3 (i.e. at least 2 repeats × length 2 = 4)
    best_length = 0

    for L in range(2, 9):
        if L > len(labels):
            break
        windows = [tuple(labels[i:i + L]) for i in range(len(labels) - L + 1)]
        counts = Counter(windows)
        for window, count in counts.items():
            if count < 2:
                continue
            score = count * L
            if score > best_score or (score == best_score and L > best_length):
                best_loop = list(window)
                best_score = score
                best_length = L

    if best_loop is None:
        return None, []
    appearances = _find_appearances(collapsed, best_loop)
    return best_loop, appearances
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_loop_detect.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/loop_detect.py tests/unit/test_loop_detect.py
git commit -m "feat(derived): predominant chord loop detection"
```

---

## Task 9: derived/note_enrichment.py — per-note role/in_chord/scale_deg

**Files:**
- Create: `analyze/derived/note_enrichment.py`
- Create: `tests/unit/test_note_enrichment.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_note_enrichment.py`:

```python
import pytest

from analyze.derived.note_enrichment import (
    chord_intervals,
    enrich_note,
    find_chord_at,
)
from analyze.derived.theory import parse_chord, parse_key


def test_chord_intervals_major_triad():
    assert chord_intervals(parse_chord("C:maj")) == {0, 4, 7}


def test_chord_intervals_minor_triad():
    assert chord_intervals(parse_chord("F:min")) == {0, 3, 7}


def test_chord_intervals_dominant_seventh():
    assert chord_intervals(parse_chord("G:7")) == {0, 4, 7, 10}


def test_chord_intervals_no_chord_returns_empty():
    assert chord_intervals(parse_chord("N")) == set()


def test_find_chord_at_returns_active_chord():
    chords = [
        {"start": 0.0, "end": 2.0, "label": "F:min"},
        {"start": 2.0, "end": 4.0, "label": "C:min"},
        {"start": 4.0, "end": 6.0, "label": "Ab:maj"},
    ]
    assert find_chord_at(0.5, chords)["label"] == "F:min"
    assert find_chord_at(2.5, chords)["label"] == "C:min"
    assert find_chord_at(5.9, chords)["label"] == "Ab:maj"


def test_find_chord_at_returns_none_outside_range():
    chords = [{"start": 0.0, "end": 2.0, "label": "F:min"}]
    assert find_chord_at(-1.0, chords) is None
    assert find_chord_at(5.0, chords) is None


def test_enrich_note_chord_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "F:min"}]
    key = parse_key("F minor")
    # MIDI 53 = F3 (root of F:min) — chord tone
    enriched = enrich_note({"t": 0.5, "midi": 53}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] == "F:min"
    assert enriched["role"] == "chord_tone"
    assert enriched["scale_deg"] == "1"


def test_enrich_note_passing_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # C maj chord tones are C, E, G (pc 0, 4, 7)
    # MIDI 60 (C4) → 62 (D4) → 64 (E4): D is passing tone between C and E
    prev = {"t": 0.1, "midi": 60}
    cur = {"t": 0.2, "midi": 62}
    next_ = {"t": 0.3, "midi": 64}
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["in_chord"] == "C:maj"
    assert enriched["role"] == "passing_tone"
    assert enriched["scale_deg"] == "2"


def test_enrich_note_neighbor_tone():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # C → D → C: D is neighbor tone above C
    prev = {"t": 0.1, "midi": 60}
    cur = {"t": 0.2, "midi": 62}
    next_ = {"t": 0.3, "midi": 60}
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["role"] == "neighbor_tone"


def test_enrich_note_non_chord_tone_when_isolated():
    chords = [{"start": 0.0, "end": 2.0, "label": "C:maj"}]
    key = parse_key("C major")
    # F (pc 5) jumping in/out, not stepwise
    prev = {"t": 0.1, "midi": 60}  # C
    cur = {"t": 0.2, "midi": 65}  # F (not chord tone, not stepwise from C)
    next_ = {"t": 0.3, "midi": 60}  # back to C
    enriched = enrich_note(cur, prev=prev, next_=next_, chords=chords, key=key)
    assert enriched["role"] == "non_chord_tone"


def test_enrich_note_outside_any_chord():
    chords = [{"start": 1.0, "end": 2.0, "label": "F:min"}]
    key = parse_key("F minor")
    enriched = enrich_note({"t": 0.5, "midi": 53}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] is None
    assert enriched["role"] is None


def test_enrich_note_in_no_chord_span():
    chords = [{"start": 0.0, "end": 2.0, "label": "N"}]
    key = parse_key("C major")
    enriched = enrich_note({"t": 1.0, "midi": 60}, prev=None, next_=None, chords=chords, key=key)
    assert enriched["in_chord"] is None
    assert enriched["role"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_note_enrichment.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `analyze/derived/note_enrichment.py`**

Create:

```python
"""Per-note enrichment: in_chord (which chord covers note's t), role
(chord_tone / passing_tone / neighbor_tone / non_chord_tone), scale_deg
(scale degree relative to key tonic, major-scale relative regardless of mode)."""
from __future__ import annotations

import bisect
from typing import Optional

from analyze.derived.theory import (
    Chord,
    Key,
    parse_chord,
    scale_degree_for,
)


def chord_intervals(chord: Chord) -> set[int]:
    """The set of pitch-class intervals (relative to chord root) that count as chord tones."""
    if chord.is_no_chord or chord.root_pc is None:
        return set()
    intervals: set[int] = {0}
    if chord.quality == "maj":
        intervals.update({4, 7})
    elif chord.quality == "min":
        intervals.update({3, 7})
    elif chord.quality == "dim":
        intervals.update({3, 6})
    elif chord.quality == "aug":
        intervals.update({4, 8})
    elif chord.quality == "sus2":
        intervals.update({2, 7})
    elif chord.quality == "sus4":
        intervals.update({5, 7})
    else:
        intervals.update({4, 7})  # default to major triad
    for ext in chord.extensions:
        if ext == "7":
            intervals.add(10)  # b7 (dominant 7 / minor 7)
        elif ext == "maj7":
            intervals.add(11)
        elif ext.startswith("9"):
            intervals.add(2)
        elif ext.startswith("b9"):
            intervals.add(1)
        elif ext.startswith("11"):
            intervals.add(5)
        elif ext.startswith("#11"):
            intervals.add(6)
        elif ext.startswith("13"):
            intervals.add(9)
    return intervals


def find_chord_at(t: float, chords: list[dict]) -> Optional[dict]:
    """Binary-search the chords array for the chord active at time t.
    Chords are assumed non-overlapping and sorted by start."""
    if not chords:
        return None
    starts = [c["start"] for c in chords]
    idx = bisect.bisect_right(starts, t) - 1
    if idx < 0:
        return None
    chord = chords[idx]
    if chord["end"] <= t:
        return None
    return chord


def _classify_role(
    cur_pc: int,
    prev: Optional[dict],
    next_: Optional[dict],
    chord_tone_intervals: set[int],
    chord_root_pc: int,
) -> str:
    cur_interval = (cur_pc - chord_root_pc) % 12
    if cur_interval in chord_tone_intervals:
        return "chord_tone"
    if prev is None or next_ is None:
        return "non_chord_tone"
    prev_pc = prev["midi"] % 12
    next_pc = next_["midi"] % 12
    prev_interval = (prev_pc - chord_root_pc) % 12
    next_interval = (next_pc - chord_root_pc) % 12
    prev_is_chord_tone = prev_interval in chord_tone_intervals
    next_is_chord_tone = next_interval in chord_tone_intervals

    # neighbor: prev == next, both chord tones, current is ±1 or ±2 semitones from them
    if (
        prev_is_chord_tone
        and next_is_chord_tone
        and prev["midi"] == next_["midi"]
        and abs(cur_pc - prev_pc) in {1, 2}
    ):
        return "neighbor_tone"

    # passing: prev and next both chord tones, current is between them stepwise (≤2 semitones each side, monotonic direction)
    if prev_is_chord_tone and next_is_chord_tone:
        d1 = next_["midi"] - prev["midi"]
        if abs(d1) in {2, 3, 4}:
            # check current is between them and stepwise
            d_prev = cur_pc - prev_pc
            d_next = next_pc - cur_pc
            if 1 <= abs(d_prev) <= 2 and 1 <= abs(d_next) <= 2 and (d_prev * d_next) > 0:
                return "passing_tone"

    return "non_chord_tone"


def enrich_note(
    note: dict,
    *,
    prev: Optional[dict],
    next_: Optional[dict],
    chords: list[dict],
    key: Key,
) -> dict:
    """Return note dict augmented with in_chord, role, scale_deg."""
    out = dict(note)
    chord_dict = find_chord_at(note["t"], chords)
    out["scale_deg"] = scale_degree_for(note["midi"] % 12, key)
    if chord_dict is None or chord_dict["label"] in {"N", "n"}:
        out["in_chord"] = None
        out["role"] = None
        return out
    chord = parse_chord(chord_dict["label"])
    if chord.root_pc is None:
        out["in_chord"] = chord_dict["label"]
        out["role"] = None
        return out
    intervals = chord_intervals(chord)
    out["in_chord"] = chord_dict["label"]
    out["role"] = _classify_role(
        cur_pc=note["midi"] % 12,
        prev=prev,
        next_=next_,
        chord_tone_intervals=intervals,
        chord_root_pc=chord.root_pc,
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_note_enrichment.py -v
```

Expected: All ~12 tests PASS. The role-classification rules are heuristic; if a specific test fails because the rubric is overly strict (e.g. test_enrich_note_passing_tone fails because `d1 = 4` not in `{2, 3, 4}`), expand the allowed interval set in `_classify_role`.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/note_enrichment.py tests/unit/test_note_enrichment.py
git commit -m "feat(derived): per-note role/in_chord/scale_deg enrichment"
```

---

## Task 10: derived/vocal_range.py — vocal range from MIDI

**Files:**
- Create: `analyze/derived/vocal_range.py`
- Create: `tests/unit/test_vocal_range.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_vocal_range.py`:

```python
from pathlib import Path

import pretty_midi
import pytest

from analyze.derived.vocal_range import midi_number_to_pitch_name, vocal_range_from_midi


def test_midi_to_pitch_name_middle_c():
    assert midi_number_to_pitch_name(60) == "C4"


def test_midi_to_pitch_name_a440():
    assert midi_number_to_pitch_name(69) == "A4"


def test_midi_to_pitch_name_low_octave():
    assert midi_number_to_pitch_name(36) == "C2"


def test_midi_to_pitch_name_with_sharp():
    assert midi_number_to_pitch_name(61) == "C♯4"


def test_vocal_range_from_midi_synthetic(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    # add notes spanning G3 (55) to D5 (74)
    for pitch in [55, 60, 67, 72, 74]:
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    pm.instruments.append(inst)
    midi_path = tmp_path / "vocals.mid"
    pm.write(str(midi_path))

    rng = vocal_range_from_midi(midi_path)
    assert rng == {"low": "G3", "high": "D5"}


def test_vocal_range_from_empty_midi_returns_none(tmp_path):
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    pm.instruments.append(inst)
    midi_path = tmp_path / "vocals_empty.mid"
    pm.write(str(midi_path))
    assert vocal_range_from_midi(midi_path) is None


def test_vocal_range_from_missing_midi_returns_none(tmp_path):
    midi_path = tmp_path / "absent.mid"
    assert vocal_range_from_midi(midi_path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_vocal_range.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `analyze/derived/vocal_range.py`**

Create:

```python
"""Vocal range derivation from a stem MIDI file."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pretty_midi

_PITCH_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]


def midi_number_to_pitch_name(midi_num: int) -> str:
    """MIDI 60 = C4 (middle C). Octave naming follows pretty_midi convention."""
    octave = (midi_num // 12) - 1
    pc = midi_num % 12
    return f"{_PITCH_NAMES[pc]}{octave}"


def vocal_range_from_midi(midi_path: Path) -> Optional[dict]:
    if not midi_path.exists():
        return None
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    pitches = [n.pitch for inst in pm.instruments for n in inst.notes]
    if not pitches:
        return None
    return {
        "low": midi_number_to_pitch_name(min(pitches)),
        "high": midi_number_to_pitch_name(max(pitches)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_vocal_range.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add analyze/derived/vocal_range.py tests/unit/test_vocal_range.py
git commit -m "feat(derived): vocal range from stems MIDI"
```

---

## Task 11: writers/ — JAMS + summary.json (skeleton with stage outputs)

This task creates the writer modules with no derivation integration yet — the derivation outputs will be wired in via Task 19's pipeline. We test by feeding pre-baked stage outputs and asserting file shape.

**Files:**
- Create: `analyze/writers/__init__.py`
- Create: `analyze/writers/jams_writer.py`
- Create: `analyze/writers/summary_writer.py`
- Create: `tests/unit/test_writers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_writers.py`:

```python
import json
from pathlib import Path

import jams
import pytest

from analyze.writers.jams_writer import write_jams
from analyze.writers.summary_writer import write_summary


@pytest.fixture
def fake_results():
    return {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {
            "bpm": 107.14,
            "beats": [0.5, 1.0, 1.5, 2.0],
            "downbeats": [0.5, 2.5],
            "n_beats": 4,
            "n_downbeats": 2,
        },
        "beats_xcheck": {
            "beats": [0.51, 1.01, 1.51, 2.01],
            "downbeats": [0.51, 2.51],
            "n_beats": 4,
            "n_downbeats": 2,
        },
        "key": {"key": "F minor", "confidence": 1.0, "source": "skey.detect_key", "errors": []},
        "chords": [
            {"start": 0.0, "end": 1.0, "label": "F:min"},
            {"start": 1.0, "end": 2.0, "label": "C:min"},
            {"start": 2.0, "end": 3.0, "label": "F:min"},
        ],
        "transcription": {
            "vocals": {"notes": 100, "midi": "midi/vocals.mid"},
            "bass": {"notes": 50, "midi": "midi/bass.mid"},
        },
        "vocal_f0": {
            "fcpe_frames": 1000,
            "pesto_frames": 1000,
            "agreement_50c": 0.80,
        },
    }


@pytest.fixture
def fake_derived():
    return {
        "scale": "F natural minor",
        "predominant_chord_loop": ["F:min", "C:min"],
        "loop_roman": ["i", "v"],
        "loop_appearances": [{"start": 0.0, "end": 2.0}],
        "modal_interchange_count": 0,
        "vocal_range": {"low": "G3", "high": "D5"},
        "chords_enriched": [
            {"start": 0.0, "end": 1.0, "label": "F:min", "root": "F", "bass": "F",
             "type": "min", "roman": "i", "function": "tonic", "confidence": 1.0,
             "agreement": "single_source"},
            {"start": 1.0, "end": 2.0, "label": "C:min", "root": "C", "bass": "C",
             "type": "min", "roman": "v", "function": "dominant", "confidence": 1.0,
             "agreement": "single_source"},
            {"start": 2.0, "end": 3.0, "label": "F:min", "root": "F", "bass": "F",
             "type": "min", "roman": "i", "function": "tonic", "confidence": 1.0,
             "agreement": "single_source"},
        ],
        "stems_enriched": {
            "vocals": {"notes": []},  # no per-note enrichment in this synthetic test
            "bass": {"notes": []},
        },
    }


def test_write_summary_produces_valid_json(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.summary.json"
    warnings = ["sections deferred — no segmenter installed"]

    write_summary(out, mp3, fake_results, fake_derived, warnings, duration_sec=215.0)

    data = json.loads(out.read_text())
    assert data["track"]["file"] == "song.mp3"
    assert data["track"]["key"] == "F minor"
    assert data["track"]["tempo_bpm"] == 107.14
    assert data["track"]["duration_sec"] == 215.0
    assert data["sections"] == []
    assert data["downbeats"] == [0.5, 2.5]
    assert len(data["chords"]) == 3
    assert data["chords"][0]["roman"] == "i"
    assert data["chords"][1]["roman"] == "v"
    assert data["analysis"]["scale"] == "F natural minor"
    assert data["analysis"]["predominant_chord_loop"] == ["F:min", "C:min"]
    assert data["analysis"]["vocal_range"] == {"low": "G3", "high": "D5"}
    assert "sections deferred" in data["provenance"]["warnings"][0]


def test_write_jams_produces_valid_file(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"

    write_jams(out, mp3, fake_results, fake_derived, warnings=[], duration_sec=215.0)

    j = jams.load(str(out))
    # Required JAMS structure
    assert j.file_metadata.duration == 215.0
    # at least one beat, one chord, one key annotation
    assert len(j.search(namespace="beat")) >= 1
    assert len(j.search(namespace="chord")) >= 1
    assert len(j.search(namespace="key_mode")) >= 1


def test_write_jams_skips_missing_stages(tmp_path, fake_derived):
    """If beats_xcheck and vocal_f0 are absent (None), the JAMS still writes — those annotations just aren't included."""
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    results_minimal = {
        "stems": {"stems_6s": "stems_6s/", "stems_bsroformer": "stems_bsroformer/"},
        "beats": {"bpm": 107.0, "beats": [0.5, 1.0], "downbeats": [0.5], "n_beats": 2, "n_downbeats": 1},
        "key": {"key": "F minor", "confidence": 1.0, "source": "skey.detect_key", "errors": []},
        "chords": [{"start": 0.0, "end": 1.0, "label": "F:min"}],
        "transcription": {"vocals": {"notes": 0, "midi": "midi/vocals.mid"}},
        # beats_xcheck and vocal_f0 are missing
    }
    write_jams(out, mp3, results_minimal, fake_derived, warnings=[], duration_sec=215.0)
    j = jams.load(str(out))
    # only one beat annotation (from madmom), no beat_this
    annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="beat")]
    assert "madmom" in annotators
    assert "beat_this" not in annotators
    # no pitch_contour annotations
    assert len(j.search(namespace="pitch_contour")) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/unit/test_writers.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create empty `analyze/writers/__init__.py`**

```python
```

- [ ] **Step 4: Implement `analyze/writers/jams_writer.py`**

Create:

```python
"""JAMS file writer.

Maps validated-stack stage outputs onto JAMS annotations following the
spec in docs/superpowers/specs/2026-04-29-analyze-py-design.md (JAMS
structure section). Each stage's output becomes one or more JAMS
annotations with explicit annotator metadata for downstream filtering.
"""
from __future__ import annotations

from importlib import metadata as importlib_metadata
from pathlib import Path

import jams


def _annotator_meta(name: str, module: str) -> dict:
    try:
        version = importlib_metadata.version(name)
    except Exception:
        version = "unknown"
    return {
        "annotator": {"name": name, "version": version},
        "annotation_tools": f"[script: {module}]",
        "data_source": "machine",
        "corpus": "user_library",
    }


def _build_beat_annotation(beats: list[float], annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="beat", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for t in beats:
        ann.append(time=float(t), duration=0.0, value=1, confidence=None)
    return ann


def _build_chord_annotation(chords: list[dict], annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="chord", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for c in chords:
        ann.append(
            time=float(c["start"]),
            duration=float(c["end"]) - float(c["start"]),
            value=str(c["label"]),
            confidence=None,
        )
    return ann


def _build_key_annotation(key_str: str, source: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="key_mode", duration=duration)
    annotator_name = "skey" if source == "skey.detect_key" else source
    meta = _annotator_meta(annotator_name, "analyze.stages.key")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    # Normalize "F minor" → "F:minor" per JAMS key_mode namespace convention.
    parts = key_str.split()
    jams_key = f"{parts[0]}:{parts[1].lower()}" if len(parts) == 2 else key_str
    ann.append(time=0.0, duration=duration, value=jams_key, confidence=None)
    return ann


def write_jams(
    jams_path: Path,
    mp3_path: Path,
    results: dict,
    derived: dict,
    warnings: list[str],
    duration_sec: float,
) -> None:
    j = jams.JAMS()
    j.file_metadata.duration = float(duration_sec)
    j.file_metadata.title = mp3_path.stem
    j.file_metadata.artist = ""

    # beats (madmom canonical)
    if "beats" in results:
        j.annotations.append(
            _build_beat_annotation(results["beats"]["beats"], "madmom", "analyze.stages.beats", duration_sec)
        )
    # beats_xcheck (beat-this; only if present)
    if "beats_xcheck" in results:
        j.annotations.append(
            _build_beat_annotation(results["beats_xcheck"]["beats"], "beat_this", "analyze.stages.beats_xcheck", duration_sec)
        )
    # chord (raw lv-chordia)
    if "chords" in results:
        j.annotations.append(
            _build_chord_annotation(results["chords"], "lv_chordia", "analyze.stages.chords", duration_sec)
        )
    # key
    if "key" in results:
        j.annotations.append(
            _build_key_annotation(results["key"]["key"], results["key"].get("source", "skey.detect_key"), duration_sec)
        )

    # Validate but don't crash — if invalid, append warning
    try:
        j.validate(strict=True)
    except Exception as e:
        warnings.append(f"JAMS validation failed (writing anyway): {e}")

    j.save(str(jams_path))
```

**Note:** This first cut handles only beats, chords, key — the smallest set needed to pass `test_write_jams_produces_valid_file`. Stage 6 (note_midi per stem), Stage 7 (pitch_contour for FCPE/PESTO), tempo, and the snapped chord track will be added in Task 19 when the full pipeline wires the writer up. (Documented in module docstring.)

- [ ] **Step 5: Implement `analyze/writers/summary_writer.py`**

Create:

```python
"""summary.json writer.

Assembles the compact educational digest from stage outputs + derivation.
Schema mirrors docs/superpowers/specs/2026-04-29-analyze-py-design.md
(summary.json section), with v1 deltas (sections=[], single_source agreement,
drums-not-transcribed marker)."""
from __future__ import annotations

import json
from importlib import metadata as importlib_metadata
from pathlib import Path

import analyze


def _model_versions() -> dict[str, str]:
    versions = {}
    for tool in [
        "audio-separator", "madmom", "beat-this", "skey", "lv-chordia",
        "basic-pitch", "torchfcpe", "pesto", "jams", "pretty_midi", "librosa",
    ]:
        try:
            versions[tool] = importlib_metadata.version(tool)
        except Exception:
            versions[tool] = "unknown"
    return versions


def write_summary(
    summary_path: Path,
    mp3_path: Path,
    results: dict,
    derived: dict,
    warnings: list[str],
    duration_sec: float,
) -> None:
    chords_enriched = derived.get("chords_enriched", [])
    stems_enriched = derived.get("stems_enriched", {})

    # Convert MP3 path to both Windows and WSL views.
    abs_path = mp3_path.resolve()
    wsl_path = str(abs_path)
    if wsl_path.startswith("/mnt/"):
        # /mnt/c/... → C:/...
        parts = wsl_path.split("/", 3)
        if len(parts) >= 4:
            drive = parts[2].upper()
            windows_path = f"{drive}:\\" + parts[3].replace("/", "\\")
        else:
            windows_path = wsl_path
    else:
        windows_path = wsl_path

    summary = {
        "track": {
            "file": mp3_path.name,
            "windows_path": windows_path,
            "wsl_path": wsl_path,
            "duration_sec": float(duration_sec),
            "tempo_bpm": float(results["beats"]["bpm"]),
            "key": results["key"]["key"],
            "key_confidence": float(results["key"]["confidence"]),
            "time_signature": "4/4",
        },
        "sections": [],
        "downbeats": [round(float(t), 3) for t in results["beats"]["downbeats"]],
        "chords": chords_enriched,
        "stems": stems_enriched,
        "analysis": {
            "scale": derived.get("scale"),
            "modal_interchange_count": derived.get("modal_interchange_count", 0),
            "predominant_chord_loop": derived.get("predominant_chord_loop"),
            "loop_roman": derived.get("loop_roman"),
            "loop_appearances": derived.get("loop_appearances", []),
            "vocal_range": derived.get("vocal_range"),
        },
        "provenance": {
            "pipeline_version": analyze.__version__,
            "models": _model_versions(),
            "warnings": list(warnings),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2))
```

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
pytest tests/unit/test_writers.py -v
```

Expected: All 3 tests PASS. If `test_write_jams_produces_valid_file` fails inside `j.save()` due to JAMS schema strictness, the writer should still complete; expand the validation try/except to also catch `jams.SchemaError` / `jams.ParameterError`.

- [ ] **Step 7: Commit**

```bash
git add analyze/writers/__init__.py analyze/writers/jams_writer.py analyze/writers/summary_writer.py tests/unit/test_writers.py
git commit -m "feat(writers): JAMS + summary.json writers (skeleton)"
```

---

## Tasks 12-18: Stage modules (port-and-verify pattern)

These tasks port each Phase 6 bash body from `prompts/test-stack-torch27.md` (also captured in `install-logs/rerun-mp3.sh`) into a Python module with the contract described in the spec. They do NOT use classical TDD — instead, "verify" means run against the validated MP3 and diff the output JSON byte shape against `cache/gorillaz_silent_running/`'s reference artifacts.

**Common contract for every stage module:**

```python
def cached(cache_dir: Path) -> bool: ...
def load(cache_dir: Path) -> dict: ...
def run(mp3: Path, cache_dir: Path) -> dict: ...

if __name__ == "__main__":
    # CLI: python -m analyze.stages.<name> <mp3>
    ...
```

The reference cache is at `<PROJECT_WSL_PATH>/cache/gorillaz_silent_running/`.

---

### Task 12: stages/stems.py

**Files:**
- Create: `analyze/stages/__init__.py`
- Create: `analyze/stages/stems.py`

- [ ] **Step 1: Create empty `analyze/stages/__init__.py`**

```python
```

- [ ] **Step 2: Implement `analyze/stages/stems.py`**

Create:

```python
"""Stage 1: stem separation via audio-separator.

Runs htdemucs_6s and BS-RoFormer in sequence. Both are CLI tools (no clean
Python API) so we shell out via subprocess.

Outputs:
    cache_dir/stems_6s/<basename>_(Vocals)_htdemucs_6s.wav
    cache_dir/stems_6s/<basename>_(Drums)_htdemucs_6s.wav
    cache_dir/stems_6s/<basename>_(Bass)_htdemucs_6s.wav
    cache_dir/stems_6s/<basename>_(Guitar)_htdemucs_6s.wav
    cache_dir/stems_6s/<basename>_(Piano)_htdemucs_6s.wav
    cache_dir/stems_6s/<basename>_(Other)_htdemucs_6s.wav
    cache_dir/stems_bsroformer/<basename>_(Vocals)_model_bs_roformer_ep_317_sdr_12.wav
    cache_dir/stems_bsroformer/<basename>_(Instrumental)_model_bs_roformer_ep_317_sdr_12.wav
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


STEMS_6S_COUNT = 6
STEMS_BSROFORMER_COUNT = 2


def cached(cache_dir: Path) -> bool:
    s6 = cache_dir / "stems_6s"
    sbr = cache_dir / "stems_bsroformer"
    if not (s6.is_dir() and sbr.is_dir()):
        return False
    n6 = sum(1 for _ in s6.glob("*.wav"))
    nbr = sum(1 for _ in sbr.glob("*.wav"))
    return n6 == STEMS_6S_COUNT and nbr == STEMS_BSROFORMER_COUNT


def load(cache_dir: Path) -> dict:
    return {
        "stems_6s": str(cache_dir / "stems_6s"),
        "stems_bsroformer": str(cache_dir / "stems_bsroformer"),
        "stems_6s_files": sorted(str(p) for p in (cache_dir / "stems_6s").glob("*.wav")),
        "stems_bsroformer_files": sorted(str(p) for p in (cache_dir / "stems_bsroformer").glob("*.wav")),
    }


def run(mp3: Path, cache_dir: Path) -> dict:
    s6 = cache_dir / "stems_6s"
    sbr = cache_dir / "stems_bsroformer"
    s6.mkdir(exist_ok=True)
    sbr.mkdir(exist_ok=True)

    subprocess.run(
        [
            "audio-separator", str(mp3),
            "--model_filename", "htdemucs_6s.yaml",
            "--output_dir", str(s6) + "/",
            "--output_format", "WAV",
        ],
        check=True,
    )
    subprocess.run(
        [
            "audio-separator", str(mp3),
            "--model_filename", "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "--output_dir", str(sbr) + "/",
            "--output_format", "WAV",
        ],
        check=True,
    )
    return load(cache_dir)


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(f"stems_6s: {len(result['stems_6s_files'])} files")
    print(f"stems_bsroformer: {len(result['stems_bsroformer_files'])} files")
```

- [ ] **Step 3: Verify against the validated cache**

The reference cache already has stems. Skip the run, just verify the `cached()` and `load()` functions agree:

```bash
python -c "
from pathlib import Path
from analyze.stages import stems
cd = Path('cache/gorillaz_silent_running')
print('cached:', stems.cached(cd))
result = stems.load(cd)
print('stems_6s files:', len(result['stems_6s_files']))
print('stems_bsroformer files:', len(result['stems_bsroformer_files']))
"
```

Expected output:
```
cached: True
stems_6s files: 6
stems_bsroformer files: 2
```

- [ ] **Step 4: Commit**

```bash
git add analyze/stages/__init__.py analyze/stages/stems.py
git commit -m "feat(stages): stem separation (htdemucs_6s + BS-RoFormer)"
```

---

### Task 13: stages/beats.py

**Files:**
- Create: `analyze/stages/beats.py`

- [ ] **Step 1: Implement `analyze/stages/beats.py`**

Create:

```python
"""Stage 2a: madmom downbeats and tempo.

Uses madmom's RNNDownBeatProcessor + DBNDownBeatTrackingProcessor. Runs on CPU
(custom inference path, not torch). Plenty fast for offline analysis.

Output: cache_dir/madmom_downbeats.json with bpm, beats, downbeats, n_beats,
n_downbeats, first_8_downbeats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


CANONICAL = "madmom_downbeats.json"


def cached(cache_dir: Path) -> bool:
    return (cache_dir / CANONICAL).exists()


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path) -> dict:
    from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor

    activations = RNNDownBeatProcessor()(str(mp3))
    tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
    beats_with_pos = tracker(activations)
    beats = [float(t) for t, _ in beats_with_pos]
    downbeats = [float(t) for t, pos in beats_with_pos if int(pos) == 1]

    if len(beats) >= 2:
        diffs = np.diff(beats)
        median_ibi = float(np.median(diffs))
        bpm = 60.0 / median_ibi if median_ibi > 0 else 0.0
    else:
        bpm = 0.0

    out = {
        "bpm": float(bpm),
        "beats": beats,
        "downbeats": downbeats,
        "n_beats": len(beats),
        "n_downbeats": len(downbeats),
        "first_8_downbeats": [round(t, 3) for t in downbeats[:8]],
    }
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(f"bpm: {result['bpm']:.2f}, beats: {result['n_beats']}, downbeats: {result['n_downbeats']}")
```

- [ ] **Step 2: Verify against the validated cache**

Run:
```bash
python -c "
from pathlib import Path
from analyze.stages import beats
cd = Path('cache/gorillaz_silent_running')
print('cached:', beats.cached(cd))
r = beats.load(cd)
print(f\"bpm={r['bpm']:.2f}, beats={r['n_beats']}, downbeats={r['n_downbeats']}\")
"
```

Expected:
```
cached: True
bpm=107.14, beats=379, downbeats=95
```

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/beats.py
git commit -m "feat(stages): madmom downbeats + tempo"
```

---

### Task 14: stages/beats_xcheck.py

**Files:**
- Create: `analyze/stages/beats_xcheck.py`

- [ ] **Step 1: Implement**

Create `analyze/stages/beats_xcheck.py`:

```python
"""Stage 3: beat-this (canonical beat tracker, also serves as cross-check).

Output: cache_dir/beat_this.json with beats, downbeats, n_beats, n_downbeats,
first_8_beats, first_8_downbeats.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CANONICAL = "beat_this.json"


def cached(cache_dir: Path) -> bool:
    return (cache_dir / CANONICAL).exists()


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path) -> dict:
    from beat_this.inference import File2Beats
    model = File2Beats(checkpoint_path="final0", device="cuda")
    beats, downbeats = model(str(mp3))
    out = {
        "beats": [float(t) for t in beats],
        "downbeats": [float(t) for t in downbeats],
        "n_beats": len(beats),
        "n_downbeats": len(downbeats),
        "first_8_beats": [round(float(t), 3) for t in beats[:8]],
        "first_8_downbeats": [round(float(t), 3) for t in downbeats[:8]],
    }
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(f"beats: {result['n_beats']}, downbeats: {result['n_downbeats']}")
```

- [ ] **Step 2: Verify**

Run:
```bash
python -c "
from pathlib import Path
from analyze.stages import beats_xcheck
cd = Path('cache/gorillaz_silent_running')
r = beats_xcheck.load(cd)
print(f\"beats={r['n_beats']}, downbeats={r['n_downbeats']}\")
"
```

Expected: `beats=374, downbeats=94`

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/beats_xcheck.py
git commit -m "feat(stages): beat-this cross-check beat tracker"
```

---

### Task 15: stages/key.py

**Files:**
- Create: `analyze/stages/key.py`

- [ ] **Step 1: Implement**

Create:

```python
"""Stage 4: key detection via skey, with librosa Krumhansl-Schmuckler fallback.

Output: cache_dir/skey.json with key, confidence, source ('skey.detect_key' or
'librosa_ks'), errors (list).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CANONICAL = "skey.json"


def cached(cache_dir: Path) -> bool:
    return (cache_dir / CANONICAL).exists()


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path) -> dict:
    key = conf = src = None
    errors: list[str] = []

    try:
        from skey.key_detection import detect_key
        result = detect_key(str(mp3), device="cuda", cli=False)
        if result:
            key = result[0] if isinstance(result, list) else str(result)
            conf = 1.0
            src = "skey.detect_key"
    except Exception as exc:
        errors.append(f"skey.detect_key failed: {type(exc).__name__}: {exc}")

    if not key or key == "error":
        import librosa
        import numpy as np
        src = "librosa_ks"
        KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        y, sr = librosa.load(str(mp3), duration=120)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
        best = max(
            [(notes[i] + ":" + mode, np.corrcoef(np.roll(chroma, -i), profile)[0, 1])
             for i in range(12) for mode, profile in [("major", KS_MAJ), ("minor", KS_MIN)]],
            key=lambda row: row[1],
        )
        key, conf = best[0], float(best[1])

    out = {"key": str(key), "confidence": float(conf), "source": src, "errors": errors}
    (cache_dir / CANONICAL).write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    result = run(mp3, cd)
    print(json.dumps(result, indent=2))
```

- [ ] **Step 2: Verify**

```bash
python -c "
from pathlib import Path
from analyze.stages import key
r = key.load(Path('cache/gorillaz_silent_running'))
print(r)
"
```

Expected: `{'key': 'F minor', 'confidence': 1.0, 'source': 'skey.detect_key', 'errors': []}`

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/key.py
git commit -m "feat(stages): skey key detection + librosa K-S fallback"
```

---

### Task 16: stages/chords.py

**Files:**
- Create: `analyze/stages/chords.py`

- [ ] **Step 1: Implement**

Create:

```python
"""Stage 5: chord recognition via lv-chordia.

Output: cache_dir/chords.json — list of {start, end, label} dicts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CANONICAL = "chords.json"


def cached(cache_dir: Path) -> bool:
    return (cache_dir / CANONICAL).exists()


def load(cache_dir: Path) -> list[dict]:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path) -> list[dict]:
    from lv_chordia.chord_recognition import chord_recognition
    raw = chord_recognition(str(mp3), chord_dict_name="submission")
    chords = [
        {
            "start": float(item.get("start_time", item.get("start", 0.0))),
            "end": float(item.get("end_time", item.get("end", 0.0))),
            "label": str(item.get("chord", item.get("label", "N"))),
        }
        for item in raw
    ]
    (cache_dir / CANONICAL).write_text(json.dumps(chords, indent=2))
    return chords


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    chords = run(mp3, cd)
    print(f"{len(chords)} chord events")
    for c in chords[:8]:
        print(f"  {c['start']:6.2f}-{c['end']:6.2f}: {c['label']}")
```

- [ ] **Step 2: Verify**

```bash
python -c "
from pathlib import Path
from analyze.stages import chords
c = chords.load(Path('cache/gorillaz_silent_running'))
print(f'{len(c)} chords; first: {c[0]}; second: {c[1]}')
"
```

Expected: `94 chords; first: {'start': 0.0, 'end': ..., 'label': 'N'}; second: {'start': 2.95, 'end': ..., 'label': 'F:min'}`

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/chords.py
git commit -m "feat(stages): lv-chordia chord recognition"
```

---

### Task 17: stages/transcription.py

**Files:**
- Create: `analyze/stages/transcription.py`

- [ ] **Step 1: Implement**

Create:

```python
"""Stage 6: per-stem polyphonic transcription via basic-pitch (ONNX path).

Skips drums. Per-stem hyperparameters are tuned per the runbook.

Outputs:
    cache_dir/midi/{vocals,bass,guitar,piano,other}.mid
    cache_dir/transcription_summary.json — per-stem note counts + paths
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

CANONICAL = "transcription_summary.json"
MIDI_SUBDIR = "midi"
EXPECTED_STEMS = {"vocals", "bass", "guitar", "piano", "other"}


def cached(cache_dir: Path) -> bool:
    summary = cache_dir / CANONICAL
    if not summary.exists():
        return False
    midi_dir = cache_dir / MIDI_SUBDIR
    return all((midi_dir / f"{s}.mid").exists() for s in EXPECTED_STEMS)


def load(cache_dir: Path) -> dict:
    return json.loads((cache_dir / CANONICAL).read_text())


def run(mp3: Path, cache_dir: Path) -> dict:
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    stems_dir = cache_dir / "stems_6s"
    out_dir = cache_dir / MIDI_SUBDIR
    out_dir.mkdir(exist_ok=True)

    params = {
        "vocals": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
        "bass": dict(onset_threshold=0.4, minimum_note_length=100, minimum_frequency=27.5),
        "guitar": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=80),
        "piano": dict(onset_threshold=0.5, minimum_note_length=58, minimum_frequency=27.5),
        "other": dict(onset_threshold=0.6, minimum_note_length=100, minimum_frequency=80),
    }
    results: dict[str, dict] = {}
    for wav in sorted(glob.glob(str(stems_dir / "*.wav"))):
        name = Path(wav).name.lower()
        matched = next((k for k in params if k in name), None)
        if matched is None or "drum" in name:
            continue
        _, midi_data, note_events = predict(
            wav,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            multiple_pitch_bends=True,
            melodia_trick=True,
            **params[matched],
        )
        midi_path = out_dir / f"{matched}.mid"
        midi_data.write(str(midi_path))
        results[matched] = {"notes": len(note_events), "midi": str(midi_path)}

    (cache_dir / CANONICAL).write_text(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    for stem, info in r.items():
        print(f"{stem}: {info['notes']} notes")
```

- [ ] **Step 2: Verify**

```bash
python -c "
from pathlib import Path
from analyze.stages import transcription
print('cached:', transcription.cached(Path('cache/gorillaz_silent_running')))
r = transcription.load(Path('cache/gorillaz_silent_running'))
for stem, info in r.items(): print(f\"{stem}: {info['notes']}\")
"
```

Expected: `cached: True`; per-stem note counts (bass:554, guitar:922, other:1004, piano:955, vocals:1097).

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/transcription.py
git commit -m "feat(stages): basic-pitch per-stem transcription"
```

---

### Task 18: stages/vocal_f0.py

**Files:**
- Create: `analyze/stages/vocal_f0.py`

- [ ] **Step 1: Implement**

Create:

```python
"""Stage 7: vocal F0 via FCPE primary + PESTO cross-check.

Outputs:
    cache_dir/vocal_f0.npz   — fcpe and pesto arrays (16 kHz frame rate)
    cache_dir/vocal_f0_summary.json — frame counts + agreement_50c
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np

CANONICAL_NPZ = "vocal_f0.npz"
CANONICAL_SUMMARY = "vocal_f0_summary.json"


def cached(cache_dir: Path) -> bool:
    return (cache_dir / CANONICAL_NPZ).exists() and (cache_dir / CANONICAL_SUMMARY).exists()


def load(cache_dir: Path) -> dict:
    summary = json.loads((cache_dir / CANONICAL_SUMMARY).read_text())
    npz = np.load(cache_dir / CANONICAL_NPZ)
    return {**summary, "fcpe_array": npz["fcpe"], "pesto_array": npz["pesto"]}


def run(mp3: Path, cache_dir: Path) -> dict:
    import librosa
    import torch
    from torchfcpe import spawn_bundled_infer_model
    import pesto

    vocals_path = next(
        path for path in glob.glob(str(cache_dir / "stems_6s" / "*.wav"))
        if "vocal" in Path(path).name.lower()
    )
    audio, sr = librosa.load(vocals_path, sr=16000, mono=True)

    audio_cuda = torch.from_numpy(audio).unsqueeze(0).to("cuda")
    fcpe = spawn_bundled_infer_model(device="cuda")
    f0_fcpe = fcpe.infer(
        audio_cuda, sr=16000, decoder_mode="local_argmax",
        threshold=0.006, f0_min=80, f0_max=880, interp_uv=False,
    ).squeeze().detach().cpu().numpy()

    audio_cpu = torch.from_numpy(audio)
    _, f0_pesto, _, _ = pesto.predict(audio_cpu, sr=16000, step_size=10.0, inference_mode="cqt")
    if hasattr(f0_pesto, "detach"):
        f0_pesto = f0_pesto.detach().cpu().numpy()
    else:
        f0_pesto = np.asarray(f0_pesto)

    n = min(len(f0_fcpe), len(f0_pesto))
    fcpe_n, pesto_n = f0_fcpe[:n], f0_pesto[:n]
    both_voiced = (fcpe_n > 0) & (pesto_n > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200 * np.log2(fcpe_n / np.maximum(pesto_n, 1e-6))
    agree_50c = both_voiced & (np.abs(cents) < 50)
    agreement = float(agree_50c.sum() / max(both_voiced.sum(), 1))

    np.savez_compressed(cache_dir / CANONICAL_NPZ, fcpe=f0_fcpe, pesto=f0_pesto)
    summary = {
        "fcpe_frames": int(len(f0_fcpe)),
        "pesto_frames": int(len(f0_pesto)),
        "agreement_50c": agreement,
    }
    (cache_dir / CANONICAL_SUMMARY).write_text(json.dumps(summary, indent=2))
    return {**summary, "fcpe_array": f0_fcpe, "pesto_array": f0_pesto}


if __name__ == "__main__":
    from analyze.cache import ensure_dir, slug_for
    mp3 = Path(sys.argv[1])
    cd = ensure_dir(slug_for(mp3))
    r = run(mp3, cd)
    print(f"FCPE frames: {r['fcpe_frames']}, PESTO frames: {r['pesto_frames']}, agree50c: {r['agreement_50c']:.3f}")
```

- [ ] **Step 2: Verify**

```bash
python -c "
from pathlib import Path
from analyze.stages import vocal_f0
print('cached:', vocal_f0.cached(Path('cache/gorillaz_silent_running')))
r = vocal_f0.load(Path('cache/gorillaz_silent_running'))
print(f\"frames: fcpe={r['fcpe_frames']} pesto={r['pesto_frames']} agree50c={r['agreement_50c']:.3f}\")
"
```

Expected: `cached: True`; `frames: fcpe=21502 pesto=21502 agree50c=0.804`.

- [ ] **Step 3: Commit**

```bash
git add analyze/stages/vocal_f0.py
git commit -m "feat(stages): vocal F0 (FCPE + PESTO)"
```

---

## Task 19: pipeline.py — orchestration

**Files:**
- Create: `analyze/pipeline.py`
- Modify: `analyze/__init__.py` (uncomment public API import)

- [ ] **Step 1: Implement `analyze/pipeline.py`**

Create:

```python
"""Pipeline orchestrator: runs stages 1-8 + derivation, writes JAMS + summary.json.

Required stages (hard-fail): stems, beats, key, chords, transcription.
Optional stages (soft-fail): beats_xcheck, vocal_f0.

Always-on derivations: theory (Roman numerals + function), loop_detect, vocal_range.
Per-note enrichment runs over all transcribed stems.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import librosa

from analyze import cache as cache_mod
from analyze.derived.loop_detect import predominant_chord_loop
from analyze.derived.note_enrichment import enrich_note
from analyze.derived.theory import (
    Chord,
    function_for,
    parse_chord,
    parse_key,
    pc_to_note_name,
    roman_for,
    scale_name,
)
from analyze.derived.vocal_range import vocal_range_from_midi
from analyze.stages import (
    beats,
    beats_xcheck,
    chords as chords_stage,
    key as key_stage,
    stems,
    transcription,
    vocal_f0,
)
from analyze.writers.jams_writer import write_jams
from analyze.writers.summary_writer import write_summary


REQUIRED_STAGES = [
    ("stems", stems),
    ("beats", beats),
    ("key", key_stage),
    ("chords", chords_stage),
    ("transcription", transcription),
]
OPTIONAL_STAGES = [
    ("beats_xcheck", beats_xcheck),
    ("vocal_f0", vocal_f0),
]


class PipelineError(RuntimeError):
    pass


@dataclass
class AnalyzeResult:
    jams_path: Path
    summary_path: Path
    warnings: list[str]


def _log(msg: str, *, quiet: bool) -> None:
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def _enrich_chords(chords_raw: list[dict], key) -> list[dict]:
    """Build the chords[] entries for summary.json with roman/function/decomposition."""
    enriched = []
    for c in chords_raw:
        chord = parse_chord(c["label"])
        roman = roman_for(chord, key)
        function = function_for(roman, key.mode) if roman else None
        out = {
            "start": float(c["start"]),
            "end": float(c["end"]),
            "label": c["label"],
            "root": pc_to_note_name(chord.root_pc) if chord.root_pc is not None else None,
            "bass": pc_to_note_name(chord.bass_pc) if chord.bass_pc is not None else None,
            "type": chord.quality,
            "roman": roman,
            "function": function,
            "confidence": 1.0,
            "agreement": "single_source",
        }
        enriched.append(out)
    return enriched


def _enrich_stems(transcription_result: dict, chords_raw: list[dict], key, cache_dir: Path) -> dict:
    """Build stems.<stem>.notes[] with per-note enrichment for each transcribed stem."""
    import pretty_midi
    out: dict = {}
    for stem_name, info in transcription_result.items():
        midi_path = Path(info["midi"])
        if not midi_path.exists():
            out[stem_name] = {"notes": [], "transcribed": False, "reason": "midi missing"}
            continue
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        notes_raw = sorted(
            (
                {"t": float(n.start), "dur": float(n.end - n.start), "midi": int(n.pitch),
                 "name": pretty_midi.note_number_to_name(n.pitch),
                 "vel": round(float(n.velocity) / 127.0, 3)}
                for inst in pm.instruments for n in inst.notes
            ),
            key=lambda x: x["t"],
        )
        enriched = []
        for i, note in enumerate(notes_raw):
            prev_n = notes_raw[i - 1] if i > 0 else None
            next_n = notes_raw[i + 1] if i + 1 < len(notes_raw) else None
            enriched.append(enrich_note(note, prev=prev_n, next_=next_n, chords=chords_raw, key=key))
        out[stem_name] = {"notes": enriched}
    # Drums stub per spec
    out["drums"] = {"transcribed": False, "reason": "drums skipped per Stage 6"}
    return out


def analyze(mp3_path: Path, *, force: bool = False, quiet: bool = False, slug: Optional[str] = None) -> AnalyzeResult:
    if not mp3_path.exists():
        raise FileNotFoundError(f"MP3 not found: {mp3_path}")

    slug_str = slug if slug else cache_mod.slug_for(mp3_path)
    cache_dir = cache_mod.ensure_dir(slug_str)
    if force:
        cache_mod.clear(cache_dir)

    warnings: list[str] = ["sections deferred — no segmenter installed"]
    results: dict = {}

    for name, module in REQUIRED_STAGES + OPTIONAL_STAGES:
        is_required = (name, module) in REQUIRED_STAGES
        if module.cached(cache_dir):
            _log(f"==> Stage {name}: cached", quiet=quiet)
            results[name] = module.load(cache_dir)
            continue
        _log(f"==> Stage {name}: running", quiet=quiet)
        try:
            results[name] = module.run(mp3_path, cache_dir)
        except Exception as e:
            if is_required:
                raise PipelineError(f"required stage {name} failed: {type(e).__name__}: {e}") from e
            warnings.append(f"stage {name} failed (soft): {type(e).__name__}: {e}")
            _log(f"!!  Stage {name} soft-failed: {e}", quiet=quiet)

    # Derivation
    _log("==> Derivation: theory + loop + vocal range + note enrichment", quiet=quiet)
    key_obj = parse_key(results["key"]["key"])
    chords_raw = results["chords"]
    chords_enriched = _enrich_chords(chords_raw, key_obj)
    loop, loop_appearances = predominant_chord_loop(chords_raw)
    loop_roman = None
    if loop:
        loop_roman = [roman_for(parse_chord(lbl), key_obj) for lbl in loop]
    modal_interchange_count = sum(1 for c in chords_enriched if c["function"] == "modal_interchange")
    vocals_midi = cache_dir / "midi" / "vocals.mid"
    vocal_range = vocal_range_from_midi(vocals_midi)
    if vocal_range is None:
        warnings.append("vocal_range not computable (no vocals MIDI or empty)")
    stems_enriched = _enrich_stems(results["transcription"], chords_raw, key_obj, cache_dir)

    derived = {
        "scale": scale_name(key_obj),
        "predominant_chord_loop": loop,
        "loop_roman": loop_roman,
        "loop_appearances": loop_appearances,
        "modal_interchange_count": modal_interchange_count,
        "vocal_range": vocal_range,
        "chords_enriched": chords_enriched,
        "stems_enriched": stems_enriched,
    }

    # Track duration via librosa (lightweight metadata read)
    duration_sec = float(librosa.get_duration(path=str(mp3_path)))

    jams_path = cache_dir / f"{slug_str}.jams"
    summary_path = cache_dir / f"{slug_str}.summary.json"
    write_jams(jams_path, mp3_path, results, derived, warnings, duration_sec=duration_sec)
    write_summary(summary_path, mp3_path, results, derived, warnings, duration_sec=duration_sec)
    _log(f"==> Wrote {jams_path.name} + {summary_path.name}", quiet=quiet)

    return AnalyzeResult(jams_path=jams_path, summary_path=summary_path, warnings=warnings)
```

- [ ] **Step 2: Update `analyze/__init__.py` to expose public API**

Replace `analyze/__init__.py` with:

```python
"""MusIQ-Lab music analysis pipeline driver."""
__version__ = "0.1.0"

from analyze.pipeline import AnalyzeResult, PipelineError, analyze

__all__ = ["AnalyzeResult", "PipelineError", "analyze", "__version__"]
```

- [ ] **Step 3: Smoke test against the validated cache**

Since all stages are cached, the orchestrator should reuse them and produce the two output files in seconds:

```bash
python -c "
from pathlib import Path
from analyze.pipeline import analyze
mp3 = Path('/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3')
result = analyze(mp3, slug='gorillaz_silent_running')
print('jams:', result.jams_path)
print('summary:', result.summary_path)
print('warnings:', result.warnings)
"
```

Expected: ~5-10 second wall time (cache hits), both files written to `cache/gorillaz_silent_running/`. Summary should contain `key=F minor`, `tempo_bpm≈107.14`, `94 chords`, `analysis.scale="F natural minor"`.

- [ ] **Step 4: Commit**

```bash
git add analyze/pipeline.py analyze/__init__.py
git commit -m "feat(pipeline): orchestration of stages + derivation + writers"
```

---

## Task 20: cli.py + __main__.py — argparse entry point

**Files:**
- Create: `analyze/__main__.py`
- Create: `analyze/cli.py`

- [ ] **Step 1: Implement `analyze/cli.py`**

Create:

```python
"""CLI entry: python -m analyze <mp3> [--force] [--quiet] [--slug NAME]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyze.pipeline import PipelineError, analyze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyze", description="MusIQ-Lab music analysis pipeline")
    parser.add_argument("mp3_path", type=Path, help="path to MP3 file")
    parser.add_argument("--force", action="store_true", help="ignore cache, recompute all stages")
    parser.add_argument("--quiet", action="store_true", help="suppress per-stage progress on stderr")
    parser.add_argument("--slug", type=str, default=None, help="override the auto-derived cache slug")
    args = parser.parse_args(argv)

    if not args.mp3_path.exists():
        print(f"error: MP3 not found: {args.mp3_path}", file=sys.stderr)
        return 2
    try:
        result = analyze(args.mp3_path, force=args.force, quiet=args.quiet, slug=args.slug)
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (OSError, IOError) as e:
        print(f"error: cache/output write failure: {e}", file=sys.stderr)
        return 3

    if not args.quiet:
        print(f"Wrote {result.jams_path}", file=sys.stderr)
        print(f"Wrote {result.summary_path}", file=sys.stderr)
        if result.warnings:
            print("Warnings:", file=sys.stderr)
            for w in result.warnings:
                print(f"  - {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Implement `analyze/__main__.py`**

Create:

```python
"""Entry point for `python -m analyze`."""
from analyze.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke test**

Run with `--help`:
```bash
python -m analyze --help
```
Expected: usage message printed.

Run against the validated cache (should be fast, all stages cached):
```bash
python -m analyze "/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3" --slug gorillaz_silent_running
```

Expected stderr trace:
```
==> Stage stems: cached
==> Stage beats: cached
==> Stage key: cached
==> Stage chords: cached
==> Stage transcription: cached
==> Stage beats_xcheck: cached
==> Stage vocal_f0: cached
==> Derivation: theory + loop + vocal range + note enrichment
==> Wrote gorillaz_silent_running.jams + gorillaz_silent_running.summary.json
Wrote /mnt/f/.../cache/gorillaz_silent_running/gorillaz_silent_running.jams
Wrote /mnt/f/.../cache/gorillaz_silent_running/gorillaz_silent_running.summary.json
Warnings:
  - sections deferred — no segmenter installed
```

Exit code 0.

- [ ] **Step 4: Commit**

```bash
git add analyze/__main__.py analyze/cli.py
git commit -m "feat(cli): python -m analyze entrypoint with --force/--quiet/--slug"
```

---

## Task 21: Integration test against validated cache

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_gorillaz.py`

- [ ] **Step 1: Create empty `tests/integration/__init__.py`**

```python
```

- [ ] **Step 2: Write integration test**

Create `tests/integration/test_gorillaz.py`:

```python
"""End-to-end integration test against the validated Gorillaz cache.

Reuses cache/gorillaz_silent_running/ (must be populated from a prior run, or
will fail). No GPU required — every stage is cache-loaded."""
import json
from pathlib import Path

import jams
import pytest

from analyze.cache import PROJECT_ROOT
from analyze.pipeline import analyze

GORILLAZ_MP3 = Path("/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/"
                    "Gorillaz - Silent Running ft. Adeleye Omotayo (Official Video)-_0Pf48RqSsg.mp3")
GORILLAZ_CACHE = PROJECT_ROOT / "cache" / "gorillaz_silent_running"


@pytest.fixture(scope="module")
def gorillaz_result():
    if not GORILLAZ_MP3.exists():
        pytest.skip(f"reference MP3 not present: {GORILLAZ_MP3}")
    if not GORILLAZ_CACHE.exists():
        pytest.skip(f"reference cache not present: {GORILLAZ_CACHE}")
    return analyze(GORILLAZ_MP3, slug="gorillaz_silent_running", quiet=True)


@pytest.fixture(scope="module")
def gorillaz_summary(gorillaz_result):
    return json.loads(gorillaz_result.summary_path.read_text())


def test_track_metadata(gorillaz_summary):
    t = gorillaz_summary["track"]
    assert t["key"] == "F minor"
    assert 105 < t["tempo_bpm"] < 110
    assert t["time_signature"] == "4/4"
    assert t["file"].endswith(".mp3")


def test_sections_empty_with_warning(gorillaz_summary):
    assert gorillaz_summary["sections"] == []
    assert any("sections deferred" in w for w in gorillaz_summary["provenance"]["warnings"])


def test_chord_count_and_first_chord(gorillaz_summary):
    chords = gorillaz_summary["chords"]
    assert len(chords) == 94
    # first non-N chord should be F:min (per validated cache)
    non_n = [c for c in chords if c["label"] != "N"]
    assert non_n[0]["label"] == "F:min"
    assert non_n[0]["roman"] == "i"
    assert non_n[0]["function"] == "tonic"


def test_analysis_block(gorillaz_summary):
    a = gorillaz_summary["analysis"]
    assert a["scale"] == "F natural minor"
    assert a["predominant_chord_loop"] is not None
    assert "F:min" in a["predominant_chord_loop"]
    assert "C:min" in a["predominant_chord_loop"]
    assert a["loop_roman"] is not None
    assert a["vocal_range"] is not None
    assert isinstance(a["vocal_range"]["low"], str)
    assert isinstance(a["vocal_range"]["high"], str)


def test_stems_have_enriched_notes(gorillaz_summary):
    stems = gorillaz_summary["stems"]
    assert "vocals" in stems
    assert "bass" in stems
    assert "drums" in stems
    assert stems["drums"]["transcribed"] is False
    # vocals stem has 1097 notes per validated cache
    assert len(stems["vocals"]["notes"]) == 1097
    # sample note has enrichment fields
    sample = stems["vocals"]["notes"][0]
    for fld in ["t", "dur", "midi", "name", "vel", "in_chord", "role", "scale_deg"]:
        assert fld in sample, f"missing field: {fld}"


def test_provenance(gorillaz_summary):
    p = gorillaz_summary["provenance"]
    assert p["pipeline_version"] == "0.1.0"
    assert "madmom" in p["models"]
    assert "skey" in p["models"]


def test_jams_validates(gorillaz_result):
    j = jams.load(str(gorillaz_result.jams_path))
    # If JAMS strict-validation fails, write_jams logs a warning but does not crash.
    # Here we want to confirm that the file is at least loadable.
    assert j.file_metadata.duration > 0
    assert len(j.search(namespace="beat")) >= 1
    assert len(j.search(namespace="chord")) >= 1
    assert len(j.search(namespace="key_mode")) >= 1


def test_no_required_stage_failures(gorillaz_summary):
    warnings = gorillaz_summary["provenance"]["warnings"]
    for w in warnings:
        assert "stems failed" not in w
        assert "beats failed" not in w
        assert "key failed" not in w
        assert "chords failed" not in w
        assert "transcription failed" not in w
```

- [ ] **Step 3: Run integration test**

Run:
```bash
pytest tests/integration/test_gorillaz.py -v
```

Expected: All ~7 tests PASS (or are skipped if the reference MP3/cache aren't present). Total wall time should be under 30 seconds (all stages cached; per-note enrichment over ~5000 notes is the main work).

- [ ] **Step 4: Run full test suite**

Run:
```bash
pytest tests/ -v
```

Expected: All tests pass — unit (cache, theory key/chord/roman/function/scale, loop_detect, note_enrichment, vocal_range, writers) + integration (gorillaz).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_gorillaz.py
git commit -m "test(integration): end-to-end pipeline against validated Gorillaz cache"
```

---

## Task 22: README + retire rerun-mp3.sh marker

**Files:**
- Modify: `docs/README.md` (replace the "not yet implemented" stanza)
- Create: `analyze/README.md` (brief module README)

- [ ] **Step 1: Update `docs/README.md` quick-start**

In `docs/README.md` find the section starting with `## Quick start` and the warning blockquote `> \`analyze.py\` is not yet implemented.` Replace the warning + the example invocation with:

```markdown
## Quick start

```bash
cd "<PROJECT_WSL_PATH>"
source .venv/bin/activate
python -m analyze "/mnt/c/Users/<you>/Videos/Any Video Converter Ultimate/Youtube/<song>.mp3"
```

This produces `cache/<slug>/<slug>.jams` (full multi-track annotation) and `cache/<slug>/<slug>.summary.json` (compact educational digest), where `<slug>` is auto-derived from the MP3 filename. Pass `--slug NAME` to override.

Stage outputs are cached per-song under `cache/<slug>/`. Re-running on the same MP3 reuses cached intermediates (~5-10 seconds total) unless you pass `--force`.

For the validated end-to-end example, see `cache/gorillaz_silent_running/`.
```

- [ ] **Step 2: Create `analyze/README.md`**

Create:

```markdown
# `analyze/` — MusIQ-Lab pipeline driver

Wraps the validated 8-stage MIR pipeline behind a single CLI:

```bash
python -m analyze <mp3>
```

Produces JAMS + `summary.json` under `cache/<slug>/`. See [`docs/superpowers/specs/2026-04-29-analyze-py-design.md`](../specs/2026-04-29-analyze-py-design.md) for the full spec.

## Module layout

- `cli.py` / `__main__.py` — argparse entry
- `pipeline.py` — stage orchestration + error policy
- `cache.py` — slug derivation, cache layout, staleness probes
- `stages/` — one module per pipeline stage; each runnable standalone via `python -m analyze.stages.<name> <mp3>`
- `derived/` — pure music-theory transforms (Roman numerals, scale, role classification, chord loop, vocal range)
- `writers/` — JAMS + summary.json writers

## Tests

```bash
pytest tests/        # unit + integration
```

The integration test (`tests/integration/test_gorillaz.py`) runs against the validated `cache/gorillaz_silent_running/` reference data — no GPU required when the cache is populated.
```

- [ ] **Step 3: Commit**

```bash
git add docs/README.md analyze/README.md
git commit -m "docs: replace analyze.py stub with shipping quick-start"
```

---

## Self-review

I checked the plan against the spec:

**Spec coverage:**
- Architecture (`analyze/` package with stages/derived/writers): Tasks 1, 11, 12-18, 19, 20 ✓
- Cache contract (slug, ensure_dir, clear, is_newer_than_mp3, per-stage probes): Task 1 + per-stage `cached()` in Tasks 12-18 ✓
- Music theory (key, chord, roman, function, scale): Tasks 3-7 ✓
- Per-note enrichment (in_chord, role, scale_deg): Task 9 ✓
- Loop detection: Task 8 ✓
- Vocal range: Task 10 ✓
- JAMS writer (validated-stack mapping; no allin1 / claude_orchestrator): Task 11 (skeleton) ✓ — note: the JAMS writer in Task 11 only handles beats/chords/key. Stage 6 note_midi annotations and Stage 7 pitch_contour annotations are not added in any task. **Gap.**
- summary.json writer (with v1 deltas): Tasks 11, 19 ✓
- CLI (a2 invocation, --force, --quiet, --slug): Task 20 ✓
- Error policy (hybrid hard/soft fail): Task 19 ✓
- Out-of-scope items NOT implemented: confirmed — no claude_orchestrator, no segmenter, no drums transcription, no modal scale detection. ✓
- Integration test against validated cache: Task 21 ✓

**Gap fix needed:** Task 11 only writes beats/chords/key JAMS annotations. The spec calls for note_midi (per stem), pitch_contour (FCPE + PESTO), beat_position (madmom), tempo (madmom_derived), and a snapped chord track (`lv_chordia_snapped`). Adding these in Task 11 would balloon it; they really belong in Task 19 where the pipeline has all the data. I'll add a Task 19.5 for completeness — but rather than a new task, I'll fold these additions into Task 19 as a separate substep so they stay in one place.

**Decision:** edit Task 19 to include the missing JAMS annotations, OR add a Task 19a. Going with the substep approach — keeping the plan clean.

Adding now:

---

## Task 19a: Complete the JAMS writer (note_midi, pitch_contour, beat_position, tempo, snapped chord)

**Files:**
- Modify: `analyze/writers/jams_writer.py`
- Modify: `tests/unit/test_writers.py`

- [ ] **Step 1: Extend `write_jams` to add the missing annotation types**

Modify `analyze/writers/jams_writer.py` — add helper builders and call them in `write_jams`:

```python
def _build_tempo_annotation(bpm: float, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="tempo", duration=duration)
    meta = _annotator_meta("madmom_derived", "analyze.stages.beats")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    ann.append(time=0.0, duration=duration, value=float(bpm), confidence=None)
    return ann


def _build_note_midi_annotation(midi_path: Path, stem: str, duration: float) -> jams.Annotation:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    ann = jams.Annotation(namespace="note_midi", duration=duration)
    meta = _annotator_meta(f"basic_pitch[{stem}]", "analyze.stages.transcription")
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for inst in pm.instruments:
        for n in inst.notes:
            ann.append(
                time=float(n.start),
                duration=float(n.end - n.start),
                value=float(n.pitch),
                confidence=round(float(n.velocity) / 127.0, 3),
            )
    return ann


def _build_pitch_contour_annotation(f0: list[float], frame_rate: float, annotator_name: str, module: str, duration: float) -> jams.Annotation:
    ann = jams.Annotation(namespace="pitch_contour", duration=duration)
    meta = _annotator_meta(annotator_name, module)
    for k, v in meta.items():
        if k == "annotator":
            ann.annotation_metadata.annotator = v
        else:
            setattr(ann.annotation_metadata, k, v)
    for i, hz in enumerate(f0):
        t = i / frame_rate
        ann.append(
            time=float(t),
            duration=1.0 / frame_rate,
            value={"frequency": float(hz), "voiced": bool(hz > 0)},
            confidence=None,
        )
    return ann


def _build_chord_snapped_annotation(chords: list[dict], downbeats: list[float], duration: float) -> jams.Annotation:
    """Snap chord starts to the nearest madmom downbeat (Stage 8 reconciliation)."""
    if not downbeats:
        return _build_chord_annotation(chords, "lv_chordia_snapped", "analyze.stages.chords", duration)
    snapped = []
    for c in chords:
        nearest = min(downbeats, key=lambda d: abs(d - c["start"]))
        snapped.append({"start": nearest, "end": c["end"], "label": c["label"]})
    return _build_chord_annotation(snapped, "lv_chordia_snapped", "analyze.stages.chords", duration)
```

In `write_jams`, add after the existing key annotation block:

```python
    # tempo
    if "beats" in results:
        j.annotations.append(
            _build_tempo_annotation(results["beats"]["bpm"], duration_sec)
        )
    # snapped chord track (Stage 8 reconciliation)
    if "chords" in results and "beats" in results:
        j.annotations.append(
            _build_chord_snapped_annotation(results["chords"], results["beats"]["downbeats"], duration_sec)
        )
    # note_midi per stem
    if "transcription" in results:
        for stem_name, info in results["transcription"].items():
            midi_path = Path(info["midi"])
            if midi_path.exists():
                j.annotations.append(_build_note_midi_annotation(midi_path, stem_name, duration_sec))
    # pitch_contour (FCPE + PESTO; only if vocal_f0 succeeded)
    if "vocal_f0" in results and "fcpe_array" in results["vocal_f0"]:
        # FCPE / PESTO are at 16 kHz audio; FCPE outputs ~100 fps; PESTO with step_size=10ms = 100 fps.
        f0_fcpe = results["vocal_f0"]["fcpe_array"].tolist()
        f0_pesto = results["vocal_f0"]["pesto_array"].tolist()
        # frame_rate derived: len / duration_sec — safer than hardcoding 100
        rate_fcpe = len(f0_fcpe) / duration_sec if duration_sec > 0 else 100.0
        rate_pesto = len(f0_pesto) / duration_sec if duration_sec > 0 else 100.0
        j.annotations.append(
            _build_pitch_contour_annotation(f0_fcpe, rate_fcpe, "torchfcpe", "analyze.stages.vocal_f0", duration_sec)
        )
        j.annotations.append(
            _build_pitch_contour_annotation(f0_pesto, rate_pesto, "pesto", "analyze.stages.vocal_f0", duration_sec)
        )
```

- [ ] **Step 2: Add tests for the new annotations**

Append to `tests/unit/test_writers.py`:

```python
def test_write_jams_includes_tempo(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    write_jams(out, mp3, fake_results, fake_derived, [], duration_sec=215.0)
    j = jams.load(str(out))
    tempos = j.search(namespace="tempo")
    assert len(tempos) == 1
    assert list(tempos[0].data)[0].value == fake_results["beats"]["bpm"]


def test_write_jams_includes_snapped_chord(tmp_path, fake_results, fake_derived):
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"")
    out = tmp_path / "song.jams"
    write_jams(out, mp3, fake_results, fake_derived, [], duration_sec=215.0)
    j = jams.load(str(out))
    chord_anns = j.search(namespace="chord")
    annotators = sorted(ann.annotation_metadata.annotator["name"] for ann in chord_anns)
    assert "lv_chordia" in annotators
    assert "lv_chordia_snapped" in annotators
```

(Skipping note_midi and pitch_contour unit tests because they need real MIDI files / numpy arrays — the integration test in Task 21 covers them via the Gorillaz reference data.)

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -v
```

Expected: all unit + integration tests pass; the integration test now also confirms note_midi annotations exist in the JAMS for each stem and pitch_contour annotations exist for FCPE + PESTO.

- [ ] **Step 4: Update integration test to assert presence of new JAMS annotations**

Append to `tests/integration/test_gorillaz.py`:

```python
def test_jams_has_full_validated_stack_annotations(gorillaz_result):
    j = jams.load(str(gorillaz_result.jams_path))
    # tempo
    assert len(j.search(namespace="tempo")) >= 1
    # snapped chord track
    chord_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="chord")]
    assert "lv_chordia" in chord_annotators
    assert "lv_chordia_snapped" in chord_annotators
    # note_midi per harmonic stem
    note_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="note_midi")]
    for stem in ["vocals", "bass", "guitar", "piano", "other"]:
        assert any(stem in a for a in note_annotators), f"missing note_midi for {stem}"
    # pitch_contour (FCPE + PESTO; soft-fail-safe — only if vocal_f0 stage ran)
    pc_annotators = [ann.annotation_metadata.annotator["name"] for ann in j.search(namespace="pitch_contour")]
    if pc_annotators:  # vocal_f0 is optional
        assert "torchfcpe" in pc_annotators
        assert "pesto" in pc_annotators
```

- [ ] **Step 5: Commit**

```bash
git add analyze/writers/jams_writer.py tests/unit/test_writers.py tests/integration/test_gorillaz.py
git commit -m "feat(writers): full JAMS annotation set (tempo, snapped chord, note_midi, pitch_contour)"
```

---

## Final self-review

**Placeholder scan:** No "TBD"/"TODO"/etc. — all steps have concrete code.

**Type consistency:** `Chord`, `Key`, `Mode`, `Function` defined in theory.py and used consistently in note_enrichment.py, loop_detect.py, pipeline.py, writers. `Optional[str]`-returning functions (`roman_for`, `function_for`) handled with `is None` checks at call sites.

**Spec coverage (final):** every spec section now has at least one task implementing it. Out-of-scope items (claude_orchestrator, segmenter, drums onset, modal scale detection, secondary dominant beyond trivial) explicitly NOT implemented and documented in the spec.

**One late-noticed clarification:** the fake `vocal_range` in Task 11's `fake_derived` fixture has form `{"low": "G3", "high": "D5"}` (ASCII). The real `vocal_range_from_midi` returns unicode (`G♯` etc when sharps are involved). Both forms are valid strings; the writer doesn't introspect them. No fix needed.

**Acknowledged spec gap (v1.x deferral):** the spec lists a `beat_position` JAMS annotation (madmom downbeat positions-in-bar). Including it would require:
1. Modifying `stages/beats.py` to persist `beats_with_position` (the raw `(time, position)` tuples from `DBNDownBeatTrackingProcessor`) into `madmom_downbeats.json`.
2. Adding a `_build_beat_position_annotation` helper in `writers/jams_writer.py`.
3. Either re-running Stage 2a against the validated cache (which would invalidate byte-for-byte determinism) OR adding a backwards-compat path that skips the annotation when cached data lacks the new field.

For v1, this is deferred. The downbeat list (`beat` namespace, `madmom` annotator, plus the `beats[].downbeats` field in `summary.json`) carries the same downbeat-position information; the per-beat position-in-bar (1, 2, 3, 4) is the part that's lost. When v1.x adds it, the stage output schema becomes `{bpm, beats, downbeats, beats_with_position, ...}` and the JAMS writer gains the missing annotation. Recorded here so it doesn't get lost.
