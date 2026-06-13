"""Migrate cached summary.json key/scale spelling to the canonical form.

Background
----------
The enharmonic-coherence fix (2026-06-13) routes summary.track.key through
``canonical_key_name`` at the writer boundary, so track.key now matches
analysis.scale (e.g. "E♭ natural minor" instead of "D# minor"). The fix
changed NO stage schema, so existing caches keep the old spelling until their
summary.json is re-derived.

This script migrates them. It is GPU-FREE: ``--apply`` re-derives each summary
from already-cached stage outputs (``stages_only=set()`` forces every stage to
load from cache and run nothing; any uncached stage is skipped). It never
re-runs a stage. essentia is loaded where cached (so the essentia_agreement /
chords_alt_key blocks are preserved and re-canonicalized) and skipped where not.

Default mode is ``--dry-run``: for each track, report track.key before -> after
(the after value is exactly what the writer will produce: it equals
``canonical_key_name(parse_key(current_track_key))`` because the old writer
stored the raw skey output verbatim). No files are written.

Usage:
    python scripts/migrate_key_spelling.py            # dry-run (default)
    python scripts/migrate_key_spelling.py --apply     # write
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

# Project root on sys.path so analyze.* / rerun_stale resolve regardless of cwd.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ for rerun_stale

from analyze.derived.theory import canonical_key_name, parse_key  # noqa: E402

CACHE = Path("cache")


def _summary_path(d: Path) -> Path | None:
    cands = sorted(d.glob("*.summary.json"))
    return cands[0] if cands else None


def _would_be(key_str: str) -> str:
    """The canonical spelling the migrated writer will emit for this key."""
    return canonical_key_name(parse_key(key_str))


def dry_run(slugs: list[str]) -> int:
    print("=== migrate key spelling — DRY RUN (no writes) ===\n")
    changed = unchanged = unparseable = missing = 0
    for slug in slugs:
        sp = _summary_path(CACHE / slug)
        if sp is None:
            missing += 1
            print(f"  [no-summary] {slug[:48]}")
            continue
        try:
            data = json.loads(sp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            missing += 1
            print(f"  [read-err]   {slug[:48]}: {e}")
            continue
        cur = (data.get("track") or {}).get("key")
        scale = (data.get("analysis") or {}).get("scale")
        if not cur:
            missing += 1
            print(f"  [no-key]     {slug[:48]}")
            continue
        try:
            after = _would_be(cur)
        except Exception as e:  # noqa: BLE001
            unparseable += 1
            print(f"  [UNPARSEABLE] {slug[:42]} key={cur!r}: {e}")
            continue
        if after == cur:
            unchanged += 1
            mark = "same  "
        else:
            changed += 1
            mark = "CHANGE"
        coherence = "scale-ok" if after == scale else f"scale!={scale!r}"
        print(f"  [{mark}] {slug[:38]:<38} {cur!r:>22} -> {after!r:<22} ({coherence})")

    print(
        f"\nsummary: {changed} change, {unchanged} already-canonical, "
        f"{unparseable} unparseable, {missing} no-summary  / {len(slugs)} tracks"
    )
    print("\nRe-run with --apply to write (GPU-free re-derive from cached stages).")
    return 1 if unparseable else 0


def apply(slugs: list[str]) -> int:
    # Heavy imports only on the write path.
    from analyze.pipeline import _STAGE_EXECUTION_ORDER, analyze
    from rerun_stale import slug_stems_quality

    def _cached(mod, cache_dir: Path, extra: dict) -> bool:
        try:
            return bool(mod.cached(cache_dir, **extra))
        except TypeError:
            try:
                return bool(mod.cached(cache_dir))
            except Exception:  # noqa: BLE001
                return False
        except Exception:  # noqa: BLE001
            return False

    print("=== migrate key spelling — APPLY (re-derive from cached stages) ===\n")
    t0 = time.monotonic()
    ok = 0
    skipped: list[tuple[str, str]] = []
    for i, slug in enumerate(slugs, 1):
        d = CACHE / slug
        mp3s = sorted(d.glob("*.mp3"))
        if not mp3s:
            skipped.append((slug, "no mp3"))
            print(f"[{i:>2}/{len(slugs)}] {slug[:48]:<48} SKIP (no mp3)")
            continue
        mp3 = mp3s[0].resolve()
        quality = slug_stems_quality(d)
        # Skip every stage that isn't already cached, so stages_only=set()
        # loads the rest and runs nothing. Stems cached() is quality-aware.
        skip = set()
        for name, mod in _STAGE_EXECUTION_ORDER:
            extra = {"quality": quality} if name == "stems" else {}
            if not _cached(mod, d, extra):
                skip.add(name)
        try:
            analyze(
                mp3,
                slug=slug,
                stems_quality=quality,
                stages_only=set(),   # load all non-skipped stages; run nothing
                skip_stages=skip,
                quiet=True,
            )
            ok += 1
            print(f"[{i:>2}/{len(slugs)}] {slug[:48]:<48} re-derived (skipped: {sorted(skip) or 'none'})")
        except Exception as e:  # noqa: BLE001
            skipped.append((slug, f"{type(e).__name__}: {e}"))
            print(f"[{i:>2}/{len(slugs)}] {slug[:48]:<48} FAILED :: {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)

    dt = time.monotonic() - t0
    print(f"\n=== done in {dt:.1f}s — re-derived {ok}/{len(slugs)} ===")
    if skipped:
        print("not migrated:")
        for slug, why in skipped:
            print(f"  - {slug}  ::  {why}")
    return 1 if skipped else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="preview only (default)")
    g.add_argument("--apply", action="store_true", help="write re-derived summaries")
    args = ap.parse_args()

    if not CACHE.is_dir():
        print(f"no cache dir at {CACHE.resolve()}")
        return 1
    slugs = sorted(p.name for p in CACHE.iterdir() if p.is_dir())

    if args.apply:
        return apply(slugs)
    return dry_run(slugs)


if __name__ == "__main__":
    raise SystemExit(main())
