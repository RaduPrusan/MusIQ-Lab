#!/usr/bin/env python3
"""Reconstruct round-2-batch-records.json by reading the live cache state.

The original round-2-delta.json (which was the batch's output) got clobbered
by an early render pass. The cache itself is the source of truth — re-read
identify.json + .params_identify.json + .acoustid_raw.json per corpus slug.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
OUT_DIR = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
BATCH_RECORDS = OUT_DIR / "round-2-batch-records.json"
BASELINE = OUT_DIR / "round-2-baseline.json"
BATCH_LOG = OUT_DIR / "round-2-batch.log"
CACHE_DIR = WORKTREE / "cache"

CORPUS = [
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


def _read_json(p: Path) -> dict | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_batch_log() -> dict[str, dict]:
    """Walk round-2-batch.log and pull per-slug (wall_sec, identify_log_line)."""
    out: dict[str, dict] = {}
    if not BATCH_LOG.is_file():
        return out
    cur_slug = None
    for line in BATCH_LOG.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("[") and "/30]" in s:
            # "[ 1/30] <slug>"
            cur_slug = s.split("] ", 1)[-1].strip()
            out.setdefault(cur_slug, {})
        elif cur_slug and s.startswith("bucket="):
            # "bucket=mb_503 t=27.45s after.identified=True mover=false_to_true"
            tok = dict(p.split("=", 1) for p in s.split(" ") if "=" in p)
            t = tok.get("t", "0s")
            try:
                out[cur_slug]["wall_sec"] = float(t.rstrip("s"))
            except Exception:
                pass
        elif cur_slug and s.startswith("LOG:"):
            # "LOG: analyze.stages.identify INFO identify: slug=... ..."
            out[cur_slug]["identify_log_line"] = s[len("LOG: "):]
    return out


def main() -> int:
    baseline_doc = _read_json(BASELINE) or {}
    baseline_by_slug = {s["slug"]: s for s in baseline_doc.get("slugs", [])}
    log_data = _parse_batch_log()

    records: list[dict] = []
    for bucket, slug in CORPUS:
        slug_dir = CACHE_DIR / slug
        ident = _read_json(slug_dir / "identify.json") or {}
        sidecar = _read_json(slug_dir / ".params_identify.json") or _read_json(slug_dir / "identify.sidecar.json")
        rec = {
            "slug": slug,
            "bucket_snapshot": bucket,
            "baseline": baseline_by_slug.get(slug, {}),
            "after": {
                "identified": bool(ident.get("identified", False)),
                "mbid_recording": ident.get("mbid_recording"),
                "title": ident.get("title"),
                "artist": ident.get("artist"),
                "reason": ident.get("reason"),
                "score": ident.get("acoustid_score"),
                "schema_version": (sidecar or {}).get("schema_version"),
                "has_acoustid_raw": (slug_dir / ".acoustid_raw.json").is_file(),
                "has_sidecar": sidecar is not None,
            },
            "wall_sec": log_data.get(slug, {}).get("wall_sec"),
            "identify_log_line": log_data.get(slug, {}).get("identify_log_line"),
        }
        before_id = bool(rec["baseline"].get("identified"))
        after_id = rec["after"]["identified"]
        if before_id and not after_id:
            rec["regression"] = True
            rec["mover"] = "true_to_false"
        elif not before_id and after_id:
            rec["mover"] = "false_to_true"
        elif before_id and after_id:
            rec["mover"] = "stable_true"
        else:
            rec["mover"] = "stable_false"
        records.append(rec)

    total_wall = sum((r.get("wall_sec") or 0) for r in records)
    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "in_progress": False,
        "wall_sec_so_far": round(total_wall, 2),
        "wall_sec_total_batch_real": 828.11,  # captured from completion line
        "corpus": [s for _, s in CORPUS],
        "records": records,
        "source": "reconstructed from live cache + round-2-batch.log",
    }
    BATCH_RECORDS.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {BATCH_RECORDS}")
    print(f"  total wall (sum of per-slug): {total_wall:.1f}s")
    print(f"  records: {len(records)}")
    movers = sum(1 for r in records if r['mover'] == 'false_to_true')
    print(f"  false_to_true: {movers}")
    print(f"  regressions: {sum(1 for r in records if r.get('regression'))}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
