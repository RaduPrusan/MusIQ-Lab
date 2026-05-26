"""Compare summary.json output across two pipeline runs and emit a Markdown delta table.

Usage:
    python -m scripts.lib.benchmark_compare baseline-summaries/ candidate-summaries/ \
        --labels tests/corpus/labels/ --out install-logs/phase-a-validation.md

Schema observed against:
    cache/gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg/
    gorillaz_silent_running_ft_adeleye_omotayo_official_video_0pf48rqssg.summary.json

    Top-level keys: track, sections, downbeats, chords, stems, analysis, provenance
    track keys: file, windows_path, wsl_path, duration_sec, tempo_bpm, key,
                key_confidence, time_signature
    stems keys: bass, guitar, other, piano, vocals, drums
    stems.<name> keys (non-drums): notes (list), transcribed, presence
    downbeats: top-level list (NOT nested under track)
    chords: top-level list (NOT nested under track)

    Piano notes count: len(summary["stems"]["piano"]["notes"])   → 326 for Gorillaz
    Vocal notes count: len(summary["stems"]["vocals"]["notes"])  → 1079 for Gorillaz
    chord_count:       len(summary["chords"])                    → 94 for Gorillaz
    downbeat_count:    len(summary["downbeats"])                 → 95 for Gorillaz
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REGRESSION_KEYS = ("key", "tempo_bpm", "chord_count", "downbeat_count")


def _load_summary(path: Path) -> dict:
    return json.loads(path.read_text())


def _label_for(slug: str, labels_dir: Path) -> dict:
    p = labels_dir / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def compare(baseline_dir: Path, candidate_dir: Path, labels_dir: Path) -> str:
    rows = []
    for cand_path in sorted(candidate_dir.glob("*.summary.json")):
        slug = cand_path.stem.removesuffix(".summary")
        base_path = baseline_dir / cand_path.name
        if not base_path.exists():
            continue
        base = _load_summary(base_path)
        cand = _load_summary(cand_path)
        labels = _label_for(slug, labels_dir)

        # downbeats and chords live at top level (not under track)
        base_chord_count = len(base.get("chords") or [])
        cand_chord_count = len(cand.get("chords") or [])
        base_downbeat_count = len(base.get("downbeats") or [])
        cand_downbeat_count = len(cand.get("downbeats") or [])

        rows.append({
            "slug": slug,
            "base_key": base.get("track", {}).get("key"),
            "cand_key": cand.get("track", {}).get("key"),
            "label_key": labels.get("key"),
            "base_bpm": _fmt_bpm(base.get("track", {}).get("tempo_bpm")),
            "cand_bpm": _fmt_bpm(cand.get("track", {}).get("tempo_bpm")),
            "label_bpm": labels.get("bpm"),
            "base_chords": base_chord_count,
            "cand_chords": cand_chord_count,
            "base_downbeats": base_downbeat_count,
            "cand_downbeats": cand_downbeat_count,
            "base_piano_notes": _piano_notes(base),
            "cand_piano_notes": _piano_notes(cand),
            "base_vocal_notes": _vocal_notes(base),
            "cand_vocal_notes": _vocal_notes(cand),
        })
    return _render(rows)


def _fmt_bpm(val: float | None) -> str | None:
    if val is None:
        return None
    return f"{val:.2f}"


def _piano_notes(summary: dict) -> int | None:
    # stems.piano.notes is a list of note dicts
    stems = summary.get("stems") or {}
    p = stems.get("piano") or {}
    notes = p.get("notes")
    return len(notes) if isinstance(notes, list) else None


def _vocal_notes(summary: dict) -> int | None:
    # stems.vocals.notes is a list of note dicts
    stems = summary.get("stems") or {}
    v = stems.get("vocals") or {}
    notes = v.get("notes")
    return len(notes) if isinstance(notes, list) else None


def _render(rows: list[dict]) -> str:
    lines = [
        "# Phase A validation",
        "",
        "| Track | Key (base→cand, label) | BPM (base→cand, label) | Chords (base→cand) | Downbeats (base→cand) | Piano notes (base→cand) | Vocal notes (base→cand) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slug']} | "
            f"{r['base_key']}→{r['cand_key']} ({r['label_key']}) | "
            f"{r['base_bpm']}→{r['cand_bpm']} ({r['label_bpm']}) | "
            f"{r['base_chords']}→{r['cand_chords']} | "
            f"{r['base_downbeats']}→{r['cand_downbeats']} | "
            f"{r['base_piano_notes']}→{r['cand_piano_notes']} | "
            f"{r['base_vocal_notes']}→{r['cand_vocal_notes']} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Compare two pipeline snapshot dirs and emit a Markdown delta table."
    )
    parser.add_argument("baseline", type=Path, help="Directory of baseline *.summary.json files")
    parser.add_argument("candidate", type=Path, help="Directory of candidate *.summary.json files")
    parser.add_argument("--labels", type=Path, required=True, help="Directory of <slug>.json hand-label files")
    parser.add_argument("--out", type=Path, required=True, help="Output Markdown file path")
    args = parser.parse_args()
    md = compare(args.baseline, args.candidate, args.labels)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
