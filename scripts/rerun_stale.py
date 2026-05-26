"""Rerun only the stale stages per slug, in-process, to update the cache to
the current per-stage schema versions. Pins --stems-quality best (matches
on-disk sidecars) and skips essentia (PyPI build lacks gaia2)."""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

# Project root on sys.path so `analyze.*` resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from analyze.pipeline import analyze
from analyze.stages import (
    beats,
    beats_xcheck,
    chords as chords_stage,
    drums as drums_stage,
    essentia_extract,
    identify as identify_stage,
    key as key_stage,
    stems,
    stems_dynamics,
    transcription,
    transcription_piano,
    vocal_consensus_contour,
    vocal_f0,
)

CACHE = Path("cache")


def slug_stems_quality(cache_dir: Path) -> str:
    """Read the slug's existing stems quality from its sidecar so we pass the
    matching value to analyze() — otherwise cached() falsely flags stems stale."""
    p = cache_dir / "stems_6s" / ".params.json"
    if not p.exists():
        return stems.DEFAULT_STEMS_QUALITY
    try:
        data = json.loads(p.read_text())
        q = data.get("params", {}).get("quality")
        if q in stems.STEMS_QUALITY_PARAMS:
            return q
    except (json.JSONDecodeError, OSError):
        pass
    return stems.DEFAULT_STEMS_QUALITY


def stage_table(quality: str):
    return [
        ("stems", stems, {"quality": quality}),
        ("stems_dynamics", stems_dynamics, {}),
        ("identify", identify_stage, {}),
        ("beats", beats, {}),
        ("key", key_stage, {}),
        ("chords", chords_stage, {}),
        ("vocal_f0", vocal_f0, {}),
        ("transcription", transcription, {}),
        ("transcription_piano", transcription_piano, {}),
        ("beats_xcheck", beats_xcheck, {}),
        ("drums", drums_stage, {}),
        ("vocal_consensus_contour", vocal_consensus_contour, {}),
        # essentia intentionally excluded — gaia2 unavailable on PyPI build.
    ]

# vocal_consensus_contour depends on vocal_f0 — if we rerun vocal_f0 we must
# also rerun consensus to stay coherent.
COUPLING = {"vocal_f0": ("vocal_consensus_contour",)}

# Sub-stages that pipeline.analyze() doesn't accept as stages_only targets.
# transcription_piano runs inside transcription.run() (see
# analyze/stages/transcription.py:86), so when its sidecar is stale we
# re-run the umbrella `transcription` stage instead.
SUB_STAGE_UMBRELLA = {"transcription_piano": "transcription"}


def stage_is_stale(cache_dir: Path, name, mod, extra) -> bool:
    try:
        return not mod.cached(cache_dir, **extra)
    except TypeError:
        return not mod.cached(cache_dir)
    except Exception:
        return True


def main() -> int:
    slugs = sorted(p.name for p in CACHE.iterdir() if p.is_dir())
    plan: list[tuple[str, set[str], str]] = []
    for slug in slugs:
        d = CACHE / slug
        quality = slug_stems_quality(d)
        stale = set()
        for name, mod, extra in stage_table(quality):
            if stage_is_stale(d, name, mod, extra):
                stale.add(name)
        # Propagate vocal_f0 → vocal_consensus_contour coupling.
        for src, deps in COUPLING.items():
            if src in stale:
                stale.update(deps)
        # Remap sub-stages to their umbrella stage so analyze()'s stages_only
        # check accepts them.
        stale = {SUB_STAGE_UMBRELLA.get(name, name) for name in stale}
        if stale:
            plan.append((slug, stale, quality))

    print(f"=== rerun plan ===")
    print(f"slugs needing work: {len(plan)} / {len(slugs)}")
    for slug, stale, q in plan:
        print(f"  [{q:<6}] {slug[:60]:<60} -> {sorted(stale)}")
    print()

    overall_t0 = time.monotonic()
    failed: list[tuple[str, str]] = []
    for i, (slug, stale, quality) in enumerate(plan, 1):
        mp3 = CACHE / slug / f"{slug}.mp3"
        if not mp3.exists():
            # Some old slugs may have non-canonical mp3 names; glob.
            matches = list((CACHE / slug).glob("*.mp3"))
            if not matches:
                print(f"[{i:>2}/{len(plan)}] {slug}  SKIP (no mp3 found)")
                failed.append((slug, "no mp3"))
                continue
            mp3 = matches[0]
        # lv-chordia's chord_recognition resolves the path relative to its own
        # install dir (.venv/lib/.../site-packages/), so a relative `cache/...`
        # path explodes to a non-existent location. Always pass absolute.
        # (See `analyze_relative_path_bug` memory.)
        mp3 = mp3.resolve()
        t0 = time.monotonic()
        print(f"[{i:>2}/{len(plan)}] {slug}  ::  stages={sorted(stale)}  q={quality}", flush=True)
        try:
            res = analyze(
                mp3,
                slug=slug,
                stems_quality=quality,  # match on-disk stems sidecar
                stages_only=set(stale),
                skip_stages={"essentia_extract"},  # gaia2-blocked
                quiet=True,
            )
            dt = time.monotonic() - t0
            warn_lines = [w for w in res.warnings if "sections deferred" not in w]
            print(f"     done in {dt:5.1f}s; warnings={len(warn_lines)}")
            for w in warn_lines[:5]:
                print(f"       - {w}")
        except Exception as e:
            dt = time.monotonic() - t0
            print(f"     FAILED in {dt:5.1f}s :: {type(e).__name__}: {e}")
            traceback.print_exc(limit=2)
            failed.append((slug, f"{type(e).__name__}: {e}"))

    total = time.monotonic() - overall_t0
    print()
    print(f"=== done in {total/60:.1f} min ===")
    print(f"succeeded: {len(plan) - len(failed)} / {len(plan)}")
    if failed:
        print("failures:")
        for slug, why in failed:
            print(f"  - {slug}  ::  {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
