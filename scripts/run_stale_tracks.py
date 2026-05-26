"""Re-run analyze on every track that has at least one stale stage.

Pairs with survey_stale_stages.py — same per-stage cached() probe, then for
each stale track invokes analyze() in-process. Fresh stages are skipped via
their own cached() inside the pipeline, so this is incremental per-track.

Usage:
    .venv/bin/python scripts/run_stale_tracks.py            # do it
    .venv/bin/python scripts/run_stale_tracks.py --dry-run  # show what would run
    .venv/bin/python scripts/run_stale_tracks.py --only-stage identify
            # restrict to tracks whose ONLY stale stage is `identify`
            # (useful guardrail when you don't want a surprise GPU re-run)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

# Several stages shell out to CLIs installed into the venv's bin/ (audio-separator
# for stems, fpcalc for identify, ffprobe for duration). When this script is
# invoked as `.venv/bin/python scripts/...` instead of `source .venv/bin/activate
# && python ...`, those subprocesses won't find the binaries. Detect and self-heal
# by prepending the venv bin dir to PATH for subprocesses we spawn.
_venv_bin = Path(sys.executable).parent
if str(_venv_bin) not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = str(_venv_bin) + os.pathsep + os.environ.get("PATH", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="list tracks that would be re-analyzed, then exit")
    parser.add_argument("--only-stage", default=None,
                        help="restrict to tracks whose ONLY stale stage matches this name "
                             "(prevents accidentally triggering heavy re-runs)")
    args = parser.parse_args()

    from analyze import pipeline as pipeline_mod
    from analyze.pipeline import analyze, PipelineError
    from analyze.stages import stems as stems_stage

    project_root = Path(__file__).resolve().parent.parent
    cache_root = project_root / "cache"

    stage_kwargs: dict[str, dict] = {
        "stems": {"quality": stems_stage.DEFAULT_STEMS_QUALITY},
    }

    targets: list[tuple[Path, list[str]]] = []
    skipped_no_mp3: list[str] = []
    for cache_dir in sorted(p for p in cache_root.iterdir() if p.is_dir()):
        slug = cache_dir.name
        mp3 = cache_dir / f"{slug}.mp3"

        stale = []
        for name, module in pipeline_mod._STAGE_EXECUTION_ORDER:
            try:
                if not module.cached(cache_dir, **stage_kwargs.get(name, {})):
                    stale.append(name)
            except Exception:
                stale.append(name)

        if not stale:
            continue
        if not mp3.exists():
            skipped_no_mp3.append(slug)
            continue
        if args.only_stage and stale != [args.only_stage]:
            print(f"skipping {slug} (stale on {stale}, not just {args.only_stage!r})",
                  file=sys.stderr)
            continue

        targets.append((mp3, stale))

    print(f"\nFound {len(targets)} re-runnable stale tracks "
          f"({len(skipped_no_mp3)} skipped: missing MP3)\n")
    for mp3, stale in targets:
        print(f"  {mp3.parent.name}  stale: {', '.join(stale)}")
    if skipped_no_mp3:
        print("\nSkipped (no source MP3):")
        for s in skipped_no_mp3:
            print(f"  {s}")

    if args.dry_run:
        print("\n(dry-run; no analyze() invoked)")
        return 0

    print(f"\n{'='*70}\nRunning analyze() on {len(targets)} tracks\n{'='*70}\n")
    ok, fail = 0, 0
    t0 = time.monotonic()
    for i, (mp3, stale) in enumerate(targets, 1):
        slug = mp3.parent.name
        print(f"\n--- [{i}/{len(targets)}] {slug}  (stale: {','.join(stale)})", flush=True)
        try:
            t_start = time.monotonic()
            result = analyze(mp3, quiet=True)
            dt = time.monotonic() - t_start
            ok += 1
            warns = len(result.warnings or [])
            print(f"    OK in {dt:.1f}s  ({warns} warnings)", flush=True)
        except PipelineError as e:
            fail += 1
            print(f"    PIPELINE ERROR: {e}", flush=True)
        except Exception as e:
            fail += 1
            print(f"    UNEXPECTED ERROR: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()

    total = time.monotonic() - t0
    print(f"\n{'='*70}\nDone in {total:.1f}s — {ok} OK, {fail} failed, "
          f"{len(skipped_no_mp3)} skipped (no MP3)\n{'='*70}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
