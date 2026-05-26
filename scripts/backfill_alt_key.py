"""One-shot helper: backfill summary.chords_alt_key onto existing cached
summaries that already have an essentia_agreement with key.ok=false.

This is a migration aid for the Plan-C cross-check toggle work — production
runs get the block automatically from the updated summary_writer. Run from
WSL: `python scripts/backfill_alt_key.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from analyze.derived.alt_key import derive_alt_key_block

CACHE = Path("cache")


def main() -> None:
    for child in sorted(CACHE.iterdir()):
        if not child.is_dir():
            continue
        summary_path = child / f"{child.name}.summary.json"
        if not summary_path.is_file():
            continue
        s = json.loads(summary_path.read_text(encoding="utf-8"))
        agreement = s.get("essentia_agreement") or {}
        key_xc = agreement.get("key")
        if not (key_xc and key_xc.get("ok") is False and key_xc.get("essentia_consensus")):
            continue
        if "chords_alt_key" in s:
            print(f"{child.name}: already has chords_alt_key")
            continue
        try:
            block = derive_alt_key_block(
                s["chords"],
                (s.get("analysis") or {}).get("predominant_chord_loop"),
                key_xc["essentia_consensus"],
            )
        except ValueError as exc:
            print(f"{child.name}: SKIP ({exc})")
            continue
        s["chords_alt_key"] = block
        summary_path.write_text(json.dumps(s, indent=2), encoding="utf-8")
        canonical_key = (s.get("track") or {}).get("key", "?")
        print(
            f"{child.name}: {canonical_key} -> {block['key']} ({block['scale']}); "
            f"modal_count {block['modal_interchange_count']}"
        )


if __name__ == "__main__":
    main()
