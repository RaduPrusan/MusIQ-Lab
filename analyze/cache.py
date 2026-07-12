"""Cache layout, slug derivation, staleness probes.

Cache layout:
    <PROJECT_ROOT>/cache/<slug>/
        <slug>.mp3                  (source mirror, copied at pipeline entry)
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
        stems_drums/{kick,snare,toms,hihat,cymbals}.wav  (Stage 9, optional)
        drums_summary.json          (Stage 9, optional)
        <slug>.jams                 (final)
        <slug>.summary.json         (final)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Slug normalization keeps "-" as the artist/title boundary marker (and the
# yt-dlp "<title>-<id>" boundary). Each run of non-alphanumeric input chars
# collapses into a single separator: "-" if the run contained any dash,
# otherwise "_". So:
#   "Baleen - Unmedicated.mp3"            -> "baleen-unmedicated"
#   "Arcade Fire - Reflektor.mp3"         -> "arcade_fire-reflektor"
#   "Joesef - Comedown (...)-zXYz.mp3"    -> "joesef-comedown_-zxyz"  (dash wins
#   over the ")," noise so the YT-ID boundary stays a single dash)
_SEP_RUN = re.compile(r"[^a-z0-9]+")


def slug_for(mp3_path: Path) -> str:
    stem = mp3_path.stem.lower()
    out: list[str] = []
    last = 0
    for m in _SEP_RUN.finditer(stem):
        out.append(stem[last : m.start()])
        out.append("-" if "-" in m.group() else "_")
        last = m.end()
    out.append(stem[last:])
    return "".join(out).strip("-_")


def ensure_dir(slug: str) -> Path:
    if not slug:
        raise ValueError("empty slug — refusing to use the cache root as a track dir")
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
