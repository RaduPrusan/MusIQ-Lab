"""Regression tests for stem-WAV lookup against title/label collisions.

Demucs preserves the source MP3's basename inside every output WAV, so naive
substring matching on the stem name collides with titles like "Hurt (Piano
Tutorial)" or "Bass Solo Cover". Both lookup helpers must anchor on the
bracketed ``_(<Stem>)_`` token instead.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from analyze.derived.vocal_range import _find_stem
from analyze.pipeline import _find_stem_wav


def _touch_wav(path: Path) -> None:
    sf.write(str(path), np.zeros(8, dtype=np.float32), 44100)


def _make_demucs_dir(tmp_path: Path, title: str) -> Path:
    d = tmp_path / "stems_6s"
    d.mkdir()
    for stem in ("Vocals", "Bass", "Drums", "Guitar", "Piano", "Other"):
        _touch_wav(d / f"{title}_({stem})_htdemucs_6s.wav")
    return d


def _make_bsroformer_dir(tmp_path: Path, title: str) -> Path:
    d = tmp_path / "stems_bsroformer"
    d.mkdir()
    for stem in ("Vocals", "Instrumental"):
        _touch_wav(d / f"{title}_({stem})_model_bs_roformer_ep_317_sdr_12.wav")
    return d


def test_piano_tutorial_title_does_not_shadow_piano_stem(tmp_path: Path) -> None:
    # The failing case: every stem file contains "Piano Tutorial" in the title.
    d = _make_demucs_dir(tmp_path, "Nine Inch Nails - Hurt (Piano Tutorial)")
    assert _find_stem_wav(d, "piano").name.endswith("_(Piano)_htdemucs_6s.wav")
    assert _find_stem_wav(d, "bass").name.endswith("_(Bass)_htdemucs_6s.wav")
    assert _find_stem_wav(d, "vocals").name.endswith("_(Vocals)_htdemucs_6s.wav")


def test_other_title_collision(tmp_path: Path) -> None:
    d = _make_demucs_dir(tmp_path, "Other People - Some Song")
    assert _find_stem_wav(d, "other").name.endswith("_(Other)_htdemucs_6s.wav")
    assert _find_stem_wav(d, "piano").name.endswith("_(Piano)_htdemucs_6s.wav")


def test_all_stems_resolve_when_no_title_collision(tmp_path: Path) -> None:
    d = _make_demucs_dir(tmp_path, "Gorillaz - Silent Running")
    for stem in ("vocals", "bass", "drums", "guitar", "piano", "other"):
        wav = _find_stem_wav(d, stem)
        assert wav is not None and f"({stem.capitalize()})" in wav.name


def test_missing_stem_returns_none(tmp_path: Path) -> None:
    d = tmp_path / "stems_6s"
    d.mkdir()
    _touch_wav(d / "song_(Piano)_htdemucs_6s.wav")
    assert _find_stem_wav(d, "bass") is None


def test_bsroformer_vocal_range_lookup(tmp_path: Path) -> None:
    # The vocal_range._find_stem variant must behave identically on bs_roformer
    # output names, where the model suffix is "_model_bs_roformer_..." instead
    # of "_htdemucs_*".
    d = _make_bsroformer_dir(tmp_path, "Gorillaz - Silent Running (Instrumental Mix)")
    assert _find_stem(d, "vocals").name.endswith("_(Vocals)_model_bs_roformer_ep_317_sdr_12.wav")
    assert _find_stem(d, "instrumental").name.endswith(
        "_(Instrumental)_model_bs_roformer_ep_317_sdr_12.wav"
    )
