#!/usr/bin/env python3
"""Round 2 read-only AcoustID re-probe of the 30-track corpus.

Identical to probe_corpus_round1.py but writes fragments to
docs/superpowers/identify-overhaul/_fragments-round2/ so we can diff
Round 1 vs Round 2 AcoustID-DB-level changes without touching the cache.

Run from inside WSL2:
    source .venv/bin/activate
    python scripts/round2_probe_acoustid.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKTREE / "scripts"))

# Import the round-1 probe module, then redirect its FRAGMENTS_DIR + OUT files.
import probe_corpus_round1 as p1  # noqa: E402

OUT_DIR = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
ROUND2_FRAG_DIR = OUT_DIR / "_fragments-round2"
ROUND2_FRAG_DIR.mkdir(parents=True, exist_ok=True)

# Monkey-patch the probe module so probe_slug writes into _fragments-round2
p1.FRAGMENTS_DIR = ROUND2_FRAG_DIR
p1.OUT_JSON = OUT_DIR / "round-2-a2-corpus-probe.json"
p1.OUT_MD = OUT_DIR / "round-2-a2-corpus-probe.md"

# probe_corpus_round1 was designed to run from Windows Python (it shells out to
# `wsl -e bash` for fpcalc + silencedetect). Keep that contract — this wrapper
# only redirects output paths. We do NOT patch PROJECT_ROOT.


def main() -> int:
    env = p1._load_env(p1.ENV_FILE)
    api_key = env.get("ACOUSTID_API_KEY")
    if not api_key:
        print("ERROR: ACOUSTID_API_KEY missing from .env", file=sys.stderr)
        return 2

    canary_err = p1.canary_check(api_key)
    if canary_err:
        print(f"canary failed: {canary_err}", file=sys.stderr)
        return 2

    records: list[dict] = []
    t_start = time.monotonic()
    for i, (bucket, slug, dur) in enumerate(p1.CORPUS, 1):
        print(f"[{i:>2}/{len(p1.CORPUS)}] {slug}", flush=True)
        rec = p1.probe_slug(bucket, slug, dur, api_key)
        records.append(rec)

    payload = {
        "schema": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wall_sec": round(time.monotonic() - t_start, 2),
        "corpus": [s for _, s, _ in p1.CORPUS],
        "records": records,
    }
    p1.OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {p1.OUT_JSON} ({len(records)} records, {payload['wall_sec']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
