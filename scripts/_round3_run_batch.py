"""Round 3 batch — re-run identify on 15 Bucket-A/B slugs via WSL.

Serialized (concurrency=1). Captures per-slug stdout/stderr fragments and
the resulting identify.json.

Output:
    docs/superpowers/identify-overhaul/round-3-batch-records.json
    docs/superpowers/identify-overhaul/_fragments-round3/<slug>.{log,identify.json}
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKTREE = REPO
CACHE = REPO / "cache"
DOCS = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
FRAGMENTS = DOCS / "_fragments-round3"
OUT = DOCS / "round-3-batch-records.json"

BUCKET_A = [
    "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk",
    "balthazar-changes_official_video-p3jb998acqo",
    "charlie_puth_attention",
    "it_could_happen_to_you_2_render",
    "jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0",
    "joesef_comedown_official_video_zaprrzdhyiw",
    "nightbus-angles_mortz_official_video-igxitfxkd1i",
    "olivia_dean_dive_acoustic_yylsa4m2zzm",
    "ren_x_chinchilla_chalk_outlines",
    "she_s_hot_tea-p_3xutn8res",
    "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw",
    "submotion_orchestra-finest_hour_album_version-qplldpndsx8",
]

# Note: angus_julia_stone is bucket B per R1 corpus probe (top score 0.943, unlinked, 0.0s lead silence).
# The handoff prompt put it in Bucket-A; we reclassify per R1 source-of-truth.
# Per R1 probe: A=11, B=4.
BUCKET_A_TRUE = [s for s in BUCKET_A if s != "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk"]

BUCKET_B = [
    "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk",
    "moderat-reminder_official_video-cjwsnuoazug",
    "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe",
    "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a",
    "warhaus_love_s_a_stranger_official_video_gsjdhd0stag",
]
# warhaus already identified in R2 (it was bucket D). Per handoff prompt, Bucket-B = 4 unlinked-high-score tracks.
BUCKET_B_TRUE = [s for s in BUCKET_B if s != "warhaus_love_s_a_stranger_official_video_gsjdhd0stag"]

SLUGS = BUCKET_A_TRUE + BUCKET_B_TRUE
assert len(BUCKET_A_TRUE) == 11, f"Bucket A: {len(BUCKET_A_TRUE)}"
assert len(BUCKET_B_TRUE) == 4, f"Bucket B: {len(BUCKET_B_TRUE)}"

IDENTIFY_LINE_RE = re.compile(r"identify: slug=\S+ source=\S+ score=\S+ mbid=\S+ reason=.*")
SOURCE_RE = re.compile(r"source=(\S+)")
SCORE_RE = re.compile(r"score=(\S+)")
MBID_RE = re.compile(r"mbid=(\S+)")
REASON_RE = re.compile(r"reason=(.*)$")
SILENCE_STRIP_RE = re.compile(r"silence-strip: \S+ stripped ([0-9.]+)s")


def wsl_path(win: Path) -> str:
    s = str(win).replace("\\", "/")
    if s[1:3] == ":/":
        drive = s[0].lower()
        return f"/mnt/{drive}{s[2:]}"
    return s


def run_one(slug: str) -> dict:
    mp3 = CACHE / slug / f"{slug}.mp3"
    if not mp3.exists():
        return {
            "slug": slug, "exit_code": -1, "error": f"MP3 missing: {mp3}",
        }
    mp3_wsl = wsl_path(mp3)
    repo_wsl = wsl_path(REPO)
    worktree_wsl = wsl_path(WORKTREE)
    cmd = (
        f"cd '{repo_wsl}' && "
        "source .venv/bin/activate && "
        f"cd '{worktree_wsl}' && "
        f"python -u -m analyze '{mp3_wsl}' --stages-only identify"
    )
    t0 = time.monotonic()
    proc = subprocess.run(
        ["wsl", "--", "bash", "-c", cmd],
        capture_output=True, text=True, timeout=180, check=False,
    )
    elapsed = time.monotonic() - t0
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    identify_line = None
    for ln in combined.splitlines():
        if "identify: slug=" in ln:
            identify_line = ln.strip()
            break
    silence_match = SILENCE_STRIP_RE.search(combined)
    stripped_lead_sec = float(silence_match.group(1)) if silence_match else None

    src = score = mbid = reason = None
    if identify_line:
        m = SOURCE_RE.search(identify_line); src = m.group(1) if m else None
        m = SCORE_RE.search(identify_line); score = m.group(1) if m else None
        m = MBID_RE.search(identify_line); mbid = m.group(1) if m else None
        m = REASON_RE.search(identify_line); reason = m.group(1) if m else None

    identify_json = None
    ij_path = CACHE / slug / "identify.json"
    if ij_path.exists():
        try:
            identify_json = json.loads(ij_path.read_text())
        except json.JSONDecodeError:
            identify_json = {"_parse_error": True}

    # Persist raw log fragment + identify.json snapshot for this slug
    FRAGMENTS.mkdir(parents=True, exist_ok=True)
    (FRAGMENTS / f"{slug}.log").write_text(combined)
    if identify_json is not None:
        (FRAGMENTS / f"{slug}.identify.json").write_text(json.dumps(identify_json, indent=2))

    return {
        "slug": slug,
        "exit_code": proc.returncode,
        "elapsed_sec": round(elapsed, 2),
        "identify_log_line": identify_line,
        "log_source": src,
        "log_score": score,
        "log_mbid": mbid,
        "log_reason": reason,
        "stripped_lead_sec": stripped_lead_sec,
        "saw_acoustid_stripped": (src == "acoustid_stripped"),
        "identify_json": identify_json,
    }


def main() -> None:
    if FRAGMENTS.exists():
        # Keep a clean run; don't delete other artifacts though.
        for p in FRAGMENTS.glob("*"):
            if p.is_file():
                p.unlink()
    FRAGMENTS.mkdir(parents=True, exist_ok=True)

    records = []
    t0 = time.monotonic()
    for i, slug in enumerate(SLUGS, 1):
        print(f"[{i}/{len(SLUGS)}] {slug}", flush=True)
        rec = run_one(slug)
        print(f"    exit={rec.get('exit_code')} elapsed={rec.get('elapsed_sec')}s "
              f"src={rec.get('log_source')} mbid={rec.get('log_mbid')}", flush=True)
        records.append(rec)
    total = time.monotonic() - t0
    payload = {
        "schema": 1,
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "+00:00",
        "total_elapsed_sec": round(total, 2),
        "bucket_a": BUCKET_A_TRUE,
        "bucket_b": BUCKET_B_TRUE,
        "records": records,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {OUT} (total {round(total,1)}s)")


if __name__ == "__main__":
    main()
