"""Round 5 batch: run `analyze --stages-only identify` against all 30 corpus slugs.

Identical to round4_batch.py but writes output under round-5-* and uses
round=5 in the JSON envelope. Captures the gorillaz flip (Item 1) and any
new identifications from the slug-parser-no-dash + threshold tuning (Item 2).
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKTREE = REPO
CACHE = REPO / "cache"
OUT = WORKTREE / r"docs\superpowers\identify-overhaul\round-5-batch-records.json"
LOG = WORKTREE / r"docs\superpowers\identify-overhaul\round-5-batch.log"

CORPUS = [
    "awolnation-run_official_audio-mw2kkyju9gy",
    "baleen_unmedicated",
    "baxter_dury-prince_of_tears-zppakk4xk74",
    "buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w",
    "crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c",
    "editors_life_is_a_fear",
    "editors_life_is_a_fear_alternative",
    "emika-sing_to_me-k9sdbzm8pgk",
    "fanfare_ciocarlia_asfalt_tango",
    "flunk_on_my_balcony",
    "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg",
    "hurt-ty-bldf8bsw",
    "notre-dame_est-3frubz9yhim",
    "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk",
    "balthazar-changes_official_video-p3jb998acqo",
    "charlie_puth_attention",
    "cvt_380_m",
    "it_could_happen_to_you_2_render",
    "jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0",
    "joesef_comedown_official_video_zaprrzdhyiw",
    "moderat-reminder_official_video-cjwsnuoazug",
    "nightbus-angles_mortz_official_video-igxitfxkd1i",
    "olivia_dean_dive_acoustic_yylsa4m2zzm",
    "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a",
    "ren_x_chinchilla_chalk_outlines",
    "she_s_hot_tea-p_3xutn8res",
    "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw",
    "submotion_orchestra-finest_hour_album_version-qplldpndsx8",
    "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe",
    "warhaus_love_s_a_stranger_official_video_gsjdhd0stag",
]

LOG_RE = re.compile(
    r"identify:\s+slug=(?P<slug>\S+)\s+source=(?P<source>\S+)"
    r"(?:\s+score=(?P<score>\S+))?"
    r"(?:\s+mbid=(?P<mbid>\S+))?"
    r"(?:\s+reason=(?P<reason>.+))?$"
)


def _wsl_path(p: pathlib.Path) -> str:
    s = str(p).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s


def run_slug(slug: str) -> dict:
    mp3 = CACHE / slug / f"{slug}.mp3"
    if not mp3.is_file():
        return {"slug": slug, "skipped": True, "reason": "mp3-missing"}
    wsl_repo = _wsl_path(REPO)
    wsl_wt = _wsl_path(WORKTREE)
    wsl_mp3 = _wsl_path(mp3)
    bash = (
        f"cd '{wsl_repo}' && source .venv/bin/activate && "
        f"cd '{wsl_wt}' && "
        f"python -u -m analyze '{wsl_mp3}' --stages-only identify"
    )
    cmd = ["wsl", "--", "bash", "-c", bash]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        rc = proc.returncode
        stderr = proc.stderr or ""
        stdout = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        return {
            "slug": slug,
            "timed_out": True,
            "wall_sec": time.monotonic() - t0,
            "exit_code": None,
            "stderr_tail": (exc.stderr or "")[-2000:] if exc.stderr else "",
        }
    wall = time.monotonic() - t0

    log_line = None
    log_parsed = None
    for line in stderr.splitlines():
        if "identify:" in line and "slug=" in line:
            log_line = line.strip()
            m = LOG_RE.search(log_line)
            if m:
                log_parsed = m.groupdict()
            break

    ident_path = CACHE / slug / "identify.json"
    ident = None
    if ident_path.is_file():
        try:
            ident = json.loads(ident_path.read_text(encoding="utf-8"))
        except Exception as exc:
            ident = {"_parse_error": str(exc)}

    keep = {}
    if ident:
        for k in (
            "identified",
            "source",
            "match_method",
            "mbid_recording",
            "title",
            "artist",
            "album",
            "year",
            "reason",
            "score",
            "duration_variance_pct",
            "title_similarity",
            "schema_version",
        ):
            if k in ident:
                keep[k] = ident[k]

    return {
        "slug": slug,
        "exit_code": rc,
        "wall_sec": round(wall, 2),
        "log_line": log_line,
        "log_parsed": log_parsed,
        "identify": keep,
        "stderr_tail": stderr[-1500:],
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    records = {
        "schema": 1,
        "round": 5,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "records": [],
    }
    log_fh = LOG.open("w", encoding="utf-8")
    t_batch = time.monotonic()
    for i, slug in enumerate(CORPUS, 1):
        print(f"[{i}/{len(CORPUS)}] {slug}", flush=True)
        log_fh.write(f"\n=== [{i}/{len(CORPUS)}] {slug} ===\n")
        log_fh.flush()
        rec = run_slug(slug)
        log_fh.write(json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        log_fh.flush()
        records["records"].append(rec)
        records["finished_at"] = datetime.now(timezone.utc).isoformat()
        records["elapsed_sec"] = round(time.monotonic() - t_batch, 2)
        OUT.write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        ident = rec.get("identify") or {}
        marker = "OK" if ident.get("identified") else "no"
        src = ident.get("source", "-")
        print(
            f"  -> {marker} source={src} wall={rec.get('wall_sec')}s",
            flush=True,
        )
    log_fh.close()
    print(f"batch done in {records['elapsed_sec']}s; records -> {OUT}")


if __name__ == "__main__":
    main()
