"""Vocal range derivation from a stem MIDI file + instrumental-track detector."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pretty_midi
import soundfile as sf

_PITCH_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]

# Vocals/instrumental RMS ratio below which the track is treated as instrumental.
# Empirical separation on the validation set is wide:
#   real vocal tracks (Gorillaz / Lou Reed / Charlie Puth):  0.57 – 0.71
#   instrumental tracks (Bach cello quintet / sax-led jazz / no-vocals backing): 0.002 – 0.057
# A threshold of 0.15 puts ~3.8× margin to the real-vocal floor and ~2.6× margin to the
# instrumental ceiling, comfortably catching all six validation tracks correctly.
INSTRUMENTAL_VOCAL_RATIO = 0.15


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


def _wav_rms(wav_path: Path) -> float:
    """RMS amplitude of a WAV file, streamed in blocks so 5-min stereo stems don't blow memory."""
    sum_sq = 0.0
    n_samples = 0
    with sf.SoundFile(str(wav_path)) as f:
        for block in f.blocks(blocksize=65536, dtype="float32"):
            sum_sq += float(np.sum(np.asarray(block, dtype=np.float64) ** 2))
            n_samples += block.size
    if n_samples == 0:
        return 0.0
    return float(np.sqrt(sum_sq / n_samples))


_STEM_LABEL_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _find_stem(stems_dir: Path, name: str) -> Optional[Path]:
    """Locate a separator output WAV by matching the bracketed stem label.

    Demucs/bs_roformer emit ``..._(Vocals)_<model>.wav`` etc. A free substring
    match on the stem name collides with titles that contain the same word
    (e.g. "Hurt (Piano Tutorial)" → every stem file contains "piano"). Match
    the ``_(<Stem>)_`` token instead, case-insensitive.
    """
    import re
    pat = _STEM_LABEL_RE_CACHE.get(name)
    if pat is None:
        pat = re.compile(r"_\(" + re.escape(name) + r"\)_", re.IGNORECASE)
        _STEM_LABEL_RE_CACHE[name] = pat
    for wav in stems_dir.glob("*.wav"):
        if pat.search(wav.name):
            return wav
    return None


def is_instrumental(
    bsroformer_stems_dir: Path,
    *,
    ratio_threshold: float = INSTRUMENTAL_VOCAL_RATIO,
) -> bool:
    """Heuristic: True iff BS-RoFormer's vocals stem RMS is < ratio_threshold × its instrumental stem RMS.

    Used to suppress `vocal_range` on instrumental tracks where the upstream separators
    have leaked pitched content (cello, sax, lead guitar) into the "vocals" stem.

    Uses BS-RoFormer (not htdemucs_6s) because BS-RoFormer is trained specifically for
    vocal/instrumental separation, so its vocals stem on a truly instrumental track is
    near-silent — giving a much wider margin between vocal (~0.6) and instrumental
    (~0.05) ratios than htdemucs (whose general-purpose 6-stem separator leaks any
    voice-band content into "vocals").

    Returns False (i.e. assume vocal) if either stem is missing or the instrumental
    stem RMS is zero — without a usable denominator the ratio is meaningless.
    """
    vocals = _find_stem(bsroformer_stems_dir, "vocals")
    instrumental = _find_stem(bsroformer_stems_dir, "instrumental")
    if vocals is None or instrumental is None:
        return False
    inst_rms = _wav_rms(instrumental)
    if inst_rms == 0.0:
        return False
    return (_wav_rms(vocals) / inst_rms) < ratio_threshold
