#!/usr/bin/env python3
"""Round 2 identify-stage refresh for the 30-track corpus.

For each slug, deletes identify.json + .params_identify.json + .acoustid_raw.json,
then calls analyze.pipeline.analyze(..., stages_only={"identify"}). Captures
stdout/stderr + log output to a per-slug record. Re-reads identify.json
and identify.sidecar.json afterward.

Writes streamed progress to round-2-delta.json so a crash leaves a partial.
Must run from inside WSL2 with the project .venv active (Linux fpcalc binary).

Run:
    source .venv/bin/activate
    python scripts/round2_run_identify.py
"""
from __future__ import annotations

import io
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Worktree imports (the worktree analyze code) — the script is at
# WORKTREE/scripts/, so adding WORKTREE to sys.path gets the right analyze.
WORKTREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKTREE))

PROJECT_ROOT = WORKTREE
# Use the worktree's cache view (junction to main cache). The analyze package
# computes its own PROJECT_ROOT from __file__, so we must use the same view
# so cache_dir matches what analyze writes into.
CACHE_DIR = WORKTREE / "cache"
OUT_DIR = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
# Write the raw batch records to a separate file so the renderer can read it
# without clobbering its own output.
DELTA_JSON = OUT_DIR / "round-2-batch-records.json"
BASELINE_JSON = OUT_DIR / "round-2-baseline.json"

CORPUS: list[tuple[str, str]] = [
    # (bucket_snapshot, slug)
    ("mb_503", "awolnation-run_official_audio-mw2kkyju9gy"),
    ("mb_503", "baleen_unmedicated"),
    ("mb_503", "baxter_dury-prince_of_tears-zppakk4xk74"),
    ("mb_503", "buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w"),
    ("mb_503", "crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c"),
    ("mb_503", "editors_life_is_a_fear"),
    ("mb_503", "editors_life_is_a_fear_alternative"),
    ("mb_503", "emika-sing_to_me-k9sdbzm8pgk"),
    ("mb_503", "fanfare_ciocarlia_asfalt_tango"),
    ("mb_503", "flunk_on_my_balcony"),
    ("mb_503", "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg"),
    ("mb_503", "hurt-ty-bldf8bsw"),
    ("mb_503", "notre-dame_est-3frubz9yhim"),
    ("no_match", "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk"),
    ("no_match", "balthazar-changes_official_video-p3jb998acqo"),
    ("no_match", "charlie_puth_attention"),
    ("no_match", "cvt_380_m"),
    ("no_match", "it_could_happen_to_you_2_render"),
    ("no_match", "jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0"),
    ("no_match", "joesef_comedown_official_video_zaprrzdhyiw"),
    ("no_match", "moderat-reminder_official_video-cjwsnuoazug"),
    ("no_match", "nightbus-angles_mortz_official_video-igxitfxkd1i"),
    ("no_match", "olivia_dean_dive_acoustic_yylsa4m2zzm"),
    ("no_match", "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a"),
    ("no_match", "ren_x_chinchilla_chalk_outlines"),
    ("no_match", "she_s_hot_tea-p_3xutn8res"),
    ("no_match", "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw"),
    ("no_match", "submotion_orchestra-finest_hour_album_version-qplldpndsx8"),
    ("no_match", "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe"),
    ("no_match", "warhaus_love_s_a_stranger_official_video_gsjdhd0stag"),
]


def read_identify(slug_dir: Path) -> dict:
    p = slug_dir / "identify.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_read_error": str(e)}


def read_sidecar(slug_dir: Path) -> dict | None:
    p = slug_dir / "identify.sidecar.json"
    if not p.is_file():
        # SR fallback: hidden .params_identify.json
        alt = slug_dir / ".params_identify.json"
        if alt.is_file():
            try:
                return json.loads(alt.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def stems_quality_from_sidecar(slug_dir: Path) -> str:
    sc = slug_dir / "stems_6s" / ".params.json"
    if not sc.is_file():
        return "best"
    try:
        return json.loads(sc.read_text(encoding="utf-8")).get("params", {}).get("quality") or "best"
    except Exception:
        return "best"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from analyze.pipeline import analyze, PipelineError  # noqa: E402

    # Capture log output from analyze.stages.identify
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    identify_logger = logging.getLogger("analyze.stages.identify")
    identify_logger.setLevel(logging.INFO)
    identify_logger.addHandler(handler)
    identify_logger.propagate = False

    records: list[dict] = []
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    baseline_by_slug = {s["slug"]: s for s in baseline["slugs"]}

    t_start = time.monotonic()
    for i, (bucket, slug) in enumerate(CORPUS, 1):
        slug_dir = CACHE_DIR / slug
        mp3 = slug_dir / f"{slug}.mp3"
        if not mp3.is_file():
            mp3s = list(slug_dir.glob("*.mp3"))
            mp3 = mp3s[0] if mp3s else mp3
        print(f"[{i:>2}/30] {slug}", flush=True)
        rec: dict = {
            "slug": slug,
            "bucket_snapshot": bucket,
            "baseline": baseline_by_slug.get(slug, {}),
        }

        # Clear log buffer
        log_buf.seek(0); log_buf.truncate()

        # Delete identify.json + sidecar to force re-run
        cleared: list[str] = []
        for f in ["identify.json", ".params_identify.json", "identify.sidecar.json", ".acoustid_raw.json"]:
            p = slug_dir / f
            if p.exists():
                try:
                    p.unlink()
                    cleared.append(f)
                except Exception as e:
                    print(f"  WARN: failed to delete {f}: {e}", flush=True)
        rec["cleared"] = cleared

        quality = stems_quality_from_sidecar(slug_dir)
        t0 = time.monotonic()
        try:
            analyze(
                mp3,
                slug=slug,
                stems_quality=quality,
                stages_only={"identify"},
                skip_stages={"essentia_extract"},
                quiet=True,
            )
            rec["analyze_status"] = "ok"
        except PipelineError as e:
            rec["analyze_status"] = "pipeline_error"
            rec["analyze_error"] = str(e)
        except Exception as e:
            rec["analyze_status"] = "exception"
            rec["analyze_error"] = f"{type(e).__name__}: {e}"
            rec["traceback"] = traceback.format_exc()
        rec["wall_sec"] = round(time.monotonic() - t0, 2)
        rec["log_lines"] = log_buf.getvalue().splitlines()
        identify_line = next((ln for ln in rec["log_lines"] if "identify: slug=" in ln), None)
        rec["identify_log_line"] = identify_line

        # Re-read state
        after = read_identify(slug_dir)
        sidecar_after = read_sidecar(slug_dir)
        rec["after"] = {
            "identified": bool(after.get("identified", False)) if after else False,
            "mbid_recording": after.get("mbid_recording") if after else None,
            "title": after.get("title") if after else None,
            "artist": after.get("artist") if after else None,
            "reason": after.get("reason") if after else None,
            "score": after.get("acoustid_score") if after else None,
            "schema_version": (sidecar_after or {}).get("schema_version"),
            "has_acoustid_raw": (slug_dir / ".acoustid_raw.json").is_file(),
            "has_sidecar": sidecar_after is not None,
        }

        before_id = (baseline_by_slug.get(slug) or {}).get("identified", False)
        after_id = rec["after"]["identified"]
        if before_id and not after_id:
            rec["regression"] = True
        elif not before_id and after_id:
            rec["mover"] = "false_to_true"
        elif before_id and after_id:
            rec["mover"] = "stable_true"
        else:
            rec["mover"] = "stable_false"

        records.append(rec)
        print(f"      bucket={bucket} t={rec['wall_sec']}s after.identified={after_id} mover={rec.get('mover')}", flush=True)
        if identify_line:
            print(f"      LOG: {identify_line.strip()}", flush=True)

        # Persist partial state after each slug
        DELTA_JSON.write_text(json.dumps({
            "schema": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "in_progress": i < len(CORPUS),
            "wall_sec_so_far": round(time.monotonic() - t_start, 2),
            "corpus": [c[1] for c in CORPUS],
            "records": records,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        # STOP if regression
        if rec.get("regression"):
            print(f"  REGRESSION DETECTED on {slug} — stopping batch", flush=True)
            return 2

    print(f"\nbatch complete in {round(time.monotonic() - t_start, 2)}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
