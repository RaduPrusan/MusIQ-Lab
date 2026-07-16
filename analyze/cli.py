"""CLI entry: python -m analyze <mp3> [--force] [--quiet] [--slug NAME] [--stems-quality {fast,normal,best}]."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from analyze.pipeline import PipelineError, analyze
from analyze.stages.stems import DEFAULT_STEMS_QUALITY, STEMS_QUALITY_PARAMS


# Matches analyze.cache.slug_for output: lowercase alnum + `_` + `-`,
# first char alnum, max 128 chars. Auto-derived slugs go through slug_for
# so they always conform; this validator only matters for the --slug
# override, which would otherwise let a caller plant cache contents at
# `cache/../whatever`.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


def _validate_slug(value: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"invalid slug: {value!r} (must match [a-z0-9][a-z0-9_-]{{0,127}})"
        )
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyze", description="MusIQ-Lab music analysis pipeline")
    parser.add_argument("mp3_path", type=Path, help="path to MP3 file")
    parser.add_argument("--force", action="store_true", help="ignore cache, recompute all stages")
    parser.add_argument("--quiet", action="store_true", help="suppress per-stage progress on stderr")
    parser.add_argument("--slug", type=_validate_slug, default=None, help="override the auto-derived cache slug")
    parser.add_argument(
        "--stems-quality",
        choices=sorted(STEMS_QUALITY_PARAMS),
        default=DEFAULT_STEMS_QUALITY,
        help=f"htdemucs_6s quality preset (default: {DEFAULT_STEMS_QUALITY})",
    )
    parser.add_argument(
        "--stages-only",
        type=lambda s: set(s.split(",")),
        default=None,
        help="comma-separated stages to run; requires upstream cache present",
    )
    parser.add_argument(
        "--from-stage",
        default=None,
        help="run this stage and everything downstream of it",
    )
    parser.add_argument(
        "--params-json",
        type=Path,
        default=None,
        help="path to JSON file with per-stage param overrides",
    )
    parser.add_argument(
        "--no-identify",
        action="store_true",
        help="skip the AcoustID/MusicBrainz identify stage",
    )
    parser.add_argument(
        "--no-essentia",
        action="store_true",
        help="skip the Essentia second-opinion stage",
    )
    args = parser.parse_args(argv)

    # Surface log.info() from analyze.* to stderr so the per-spec
    # `identify: slug=... source=... ...` line reaches webui.log via the
    # captured analyze subprocess output. Without this the analyze root
    # logger has no handlers and INFO records are silently discarded.
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            stream=sys.stderr,
            format="%(name)s %(levelname)s %(message)s",
        )

    if not args.mp3_path.exists():
        print(f"error: MP3 not found: {args.mp3_path}", file=sys.stderr)
        return 2

    params = None
    if args.params_json:
        params = json.loads(args.params_json.read_text())

    skip_stages: set[str] = set()
    if args.no_identify:
        skip_stages.add("identify")
    if args.no_essentia:
        skip_stages.add("essentia_extract")
    # Future --no-X flags add their stage names here.

    try:
        result = analyze(
            args.mp3_path,
            force=args.force,
            quiet=args.quiet,
            slug=args.slug,
            stems_quality=args.stems_quality,
            stages_only=args.stages_only,
            from_stage=args.from_stage,
            params=params,
            skip_stages=skip_stages or None,
        )
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        # Unknown --from-stage / --stages-only names raise ValueError; surface
        # a clean error line instead of a raw traceback.
        print(f"error: {e}", file=sys.stderr)
        return 2
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
