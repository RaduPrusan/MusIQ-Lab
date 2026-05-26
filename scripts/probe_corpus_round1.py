#!/usr/bin/env python3
"""Round 1 / Subagent A2 — empirical AcoustID probe of the 30-track corpus.

For each slug in docs/superpowers/specs/2026-05-12-identify-corpus.md:
  - fpcalc fingerprint + duration_sec (skip ≤30s)
  - AcoustID lookup with meta=recordings+releasegroups+compress, top 5 results
  - leading_silence / trailing_silence via ffmpeg silencedetect
  - artist_guess / title_guess derived from slug

Read-only on the live cache. Resume-safe: per-slug fragments under
docs/superpowers/identify-overhaul/_fragments/<slug>.json are reused on
re-run, so a crash does not force re-queries.

Run from worktree root:
    python .claude/worktrees/identify-overhaul/scripts/probe_corpus_round1.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Worktree root: repo root or .claude/worktrees/identify-overhaul
WORKTREE = Path(__file__).resolve().parent.parent
# Project root with the live cache. In a worktree this should point at the
# worktree cache view; in the main repo it points at the main cache.
PROJECT_ROOT = WORKTREE

CACHE_DIR = PROJECT_ROOT / "cache"
FPCALC_WIN = PROJECT_ROOT / "analyze" / "vendor" / "chromaprint" / "fpcalc"
ENV_FILE = PROJECT_ROOT / ".env"

OUT_DIR = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
FRAGMENTS_DIR = OUT_DIR / "_fragments"
OUT_JSON = OUT_DIR / "round-1-a2-corpus-probe.json"
OUT_MD = OUT_DIR / "round-1-a2-corpus-probe.md"

FRAGMENTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Corpus (from 2026-05-12-identify-corpus.md, frozen snapshot)
# ---------------------------------------------------------------------------

# Tuple is (snapshot_bucket, slug, duration_sec_from_corpus_md)
CORPUS: list[tuple[str, str, int]] = [
    ("mb_503", "awolnation-run_official_audio-mw2kkyju9gy", 242),
    ("mb_503", "baleen_unmedicated", 194),
    ("mb_503", "baxter_dury-prince_of_tears-zppakk4xk74", 189),
    ("mb_503", "buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w", 227),
    ("mb_503", "crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c", 188),
    ("mb_503", "editors_life_is_a_fear", 264),
    ("mb_503", "editors_life_is_a_fear_alternative", 303),
    ("mb_503", "emika-sing_to_me-k9sdbzm8pgk", 253),
    ("mb_503", "fanfare_ciocarlia_asfalt_tango", 373),
    ("mb_503", "flunk_on_my_balcony", 180),
    ("mb_503", "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg", 215),
    ("mb_503", "hurt-ty-bldf8bsw", 374),
    ("mb_503", "notre-dame_est-3frubz9yhim", 147),
    ("no_match", "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk", 260),
    ("no_match", "balthazar-changes_official_video-p3jb998acqo", 200),
    ("no_match", "charlie_puth_attention", 302),
    ("no_match", "cvt_380_m", 7),
    ("no_match", "it_could_happen_to_you_2_render", 139),
    ("no_match", "jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0", 208),
    ("no_match", "joesef_comedown_official_video_zaprrzdhyiw", 272),
    ("no_match", "moderat-reminder_official_video-cjwsnuoazug", 206),
    ("no_match", "nightbus-angles_mortz_official_video-igxitfxkd1i", 269),
    ("no_match", "olivia_dean_dive_acoustic_yylsa4m2zzm", 199),
    ("no_match", "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a", 327),
    ("no_match", "ren_x_chinchilla_chalk_outlines", 345),
    ("no_match", "she_s_hot_tea-p_3xutn8res", 360),
    ("no_match", "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw", 283),
    ("no_match", "submotion_orchestra-finest_hour_album_version-qplldpndsx8", 255),
    ("no_match", "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe", 592),
    ("no_match", "warhaus_love_s_a_stranger_official_video_gsjdhd0stag", 210),
]


# ---------------------------------------------------------------------------
# .env loader (mirrors scripts/probe_acoustid.py)
# ---------------------------------------------------------------------------

def _load_env(env_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# Windows → WSL path translation
# ---------------------------------------------------------------------------

def win_to_wsl(p: Path) -> str:
    """Convert a Windows path to /mnt/<drive>/... shell-safe form."""
    s = str(p).replace("\\", "/")
    # F:/foo  →  /mnt/f/foo
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if not m:
        return s
    drive = m.group(1).lower()
    rest = m.group(2)
    return f"/mnt/{drive}/{rest}"


# ---------------------------------------------------------------------------
# fpcalc via WSL
# ---------------------------------------------------------------------------

def run_fpcalc(mp3_path: Path) -> tuple[dict | None, str | None]:
    """Returns (fp_dict | None, error | None). fp_dict has keys 'fingerprint', 'duration'."""
    wsl_fpcalc = win_to_wsl(FPCALC_WIN)
    wsl_mp3 = win_to_wsl(mp3_path)
    # Build bash command — single-quote both paths so the shell doesn't expand $ etc.
    bash_cmd = f"'{wsl_fpcalc}' -json '{wsl_mp3}'"
    try:
        proc = subprocess.run(
            ["wsl", "-e", "bash", "-c", bash_cmd],
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None, "fpcalc timeout"
    except Exception as exc:
        return None, f"fpcalc subprocess error: {exc!r}"

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip() or f"exit={proc.returncode}"
        return None, f"fpcalc exit {proc.returncode}: {err[:200]}"

    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except Exception as exc:
        return None, f"fpcalc JSON parse: {exc!r}"

    if "fingerprint" not in data or "duration" not in data:
        return None, f"fpcalc output missing keys: {list(data.keys())}"
    return data, None


# ---------------------------------------------------------------------------
# ffmpeg silencedetect via WSL
# ---------------------------------------------------------------------------

_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+\.?[0-9]*)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+\.?[0-9]*)")


def detect_silence(mp3_path: Path, duration_sec: float) -> tuple[float | None, float | None, str | None]:
    """Returns (leading_silence_sec, trailing_silence_sec, error).

    leading_silence_sec = timestamp of first non-silent sample. If the file
    does not start with silence (no silence_start at ~0), this is 0.0.
    trailing_silence_sec = total duration - silence_start_of_final_silence.
    """
    wsl_mp3 = win_to_wsl(mp3_path)
    # silencedetect at -50 dB for 0.3 s minimum
    bash_cmd = (
        f"ffmpeg -hide_banner -nostats -i '{wsl_mp3}' "
        f"-af 'silencedetect=noise=-50dB:d=0.3' -f null - 2>&1"
    )
    try:
        proc = subprocess.run(
            ["wsl", "-e", "bash", "-c", bash_cmd],
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return None, None, "ffmpeg timeout"
    except Exception as exc:
        return None, None, f"ffmpeg subprocess error: {exc!r}"

    # silencedetect logs to stderr, but we merged 2>&1 so it ends up in stdout
    output = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace")

    starts: list[float] = []
    ends: list[float] = []
    for line in output.splitlines():
        m_end = _SILENCE_END_RE.search(line)
        if m_end:
            try:
                ends.append(float(m_end.group(1)))
            except ValueError:
                pass
        m_start = _SILENCE_START_RE.search(line)
        if m_start:
            try:
                starts.append(float(m_start.group(1)))
            except ValueError:
                pass

    # Leading silence: if first silence_start is ≤ 0.5s, the file starts with
    # silence and the leading silence ends at the first silence_end. Otherwise
    # the leading-silence is 0.
    leading = 0.0
    if starts and ends:
        if starts[0] <= 0.5:
            leading = ends[0]
    elif ends and not starts:
        # silencedetect always emits both for completed segments, so this is rare;
        # but if we see an end without a paired start, treat it as leading silence.
        leading = ends[0]

    # Trailing silence: if the last silence segment has no closing silence_end
    # within duration, it's trailing. Approximate: if there's a silence_start
    # past (duration - 1.0) without a matching subsequent silence_end, the
    # trailing silence is (duration - that silence_start).
    trailing = 0.0
    if starts:
        last_start = starts[-1]
        # If number of starts > number of ends, the last segment is open-ended (trailing).
        if len(starts) > len(ends):
            trailing = max(0.0, duration_sec - last_start)
        elif last_start >= duration_sec - 1.0:
            # Edge: closing end coincides with EOF
            trailing = max(0.0, duration_sec - last_start)

    return leading, trailing, None


# ---------------------------------------------------------------------------
# AcoustID lookup
# ---------------------------------------------------------------------------

ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"


def acoustid_lookup(api_key: str, fingerprint: str, duration: int) -> tuple[dict | None, str | None]:
    # AcoustID expects multiple meta keys SPACE-separated (urlencoded to %20),
    # NOT '+'-separated (literal plus). A '+' between keys is treated as part
    # of an unknown single key and silently drops the recordings array.
    params = urllib.parse.urlencode(
        {
            "client": api_key,
            "meta": "recordings releasegroups",
            "fingerprint": fingerprint,
            "duration": duration,
        }
    )
    url = f"{ACOUSTID_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MusIQ-Lab-Probe-Round1/0.1 ( https://github.com/RaduPrusan/MusIQ-Lab )"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body_bytes = resp.read()
            body = json.loads(body_bytes.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        # Try to read error body for AcoustID's structured error response
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return None, f"HTTP {exc.code}: {err_body[:300] or exc.reason}"
    except Exception as exc:
        return None, f"network error: {exc!r}"
    return body, None


# ---------------------------------------------------------------------------
# Slug → artist / title guess
# ---------------------------------------------------------------------------

# 11-char YouTube ID matcher (alphanumeric, _, -, exactly 11 chars)
_YT_ID = re.compile(r"(?:^|[-_])([A-Za-z0-9_-]{11})$")

NOISE_TOKENS = [
    "official video",
    "official audio",
    "official music video",
    "official visualizer",
    "official lyric video",
    "lyric video",
    "audio",
    "music video",
    "video",
    "live at",
    "live in",
    "live",
    "acoustic",
    "alternative",
    "remix",
    "edit",
    "feat",
    "ft",
    "album version",
    "remaster",
    "remastered",
    "hd",
    "hq",
    "psych-rock jams",
    "made in jamel 2010",
    "11 17 2017",
    "paste studios new york ny",
    "fillmore east 1970",
    "2015 mix",
    "arr for cello quintet",
]


def parse_slug(slug: str) -> tuple[str, str, str, str]:
    """Returns (raw_artist, raw_title, clean_artist, clean_title)."""
    # Strip trailing YouTube ID if present
    base = slug
    m = _YT_ID.search(slug)
    if m:
        candidate_id = m.group(1)
        # only strip if it really looks like a YT ID (has at least one digit or mixed case)
        if any(c.isdigit() for c in candidate_id) or not candidate_id.islower():
            base = slug[: m.start()].rstrip("-_")

    # First split on '-' if present, else split on '_' assuming first token = artist
    if "-" in base:
        parts = base.split("-", 1)
        raw_artist = parts[0].replace("_", " ").strip()
        raw_title = parts[1].replace("_", " ").strip()
    else:
        # No dash → harder to tell. Heuristic: first two underscore-words = artist,
        # rest = title. Works for charlie_puth_attention but not for everything.
        words = base.split("_")
        if len(words) <= 2:
            raw_artist = words[0] if words else ""
            raw_title = words[1] if len(words) > 1 else ""
        else:
            raw_artist = " ".join(words[:2])
            raw_title = " ".join(words[2:])

    def titlecase(s: str) -> str:
        return " ".join(w.capitalize() for w in s.split())

    raw_artist_tc = titlecase(raw_artist)
    raw_title_tc = titlecase(raw_title)

    # Clean: strip noise tokens
    def clean(s: str) -> str:
        s_lower = " " + s.lower() + " "
        for tok in NOISE_TOKENS:
            s_lower = re.sub(r"\b" + re.escape(tok) + r"\b", " ", s_lower)
        # Remove parenthetical years
        s_lower = re.sub(r"\(?\b(19|20)\d{2}\b\)?", " ", s_lower)
        # collapse whitespace
        s_lower = re.sub(r"\s+", " ", s_lower).strip()
        return titlecase(s_lower)

    return raw_artist_tc, raw_title_tc, clean(raw_artist), clean(raw_title)


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def classify(record: dict, threshold_high: float = 0.85, threshold_mid: float = 0.5) -> str:
    """Bucket per spec §1 + extensions.

    A — AcoustID returns results: []
    B — top is high-score (≥0.85) unlinked, no usable linked alternative
    C — top score below 0.85 but a linked recording is above 0.5 (threshold)
    D — high-score unlinked top hides a usable linked result below it (bug-C target)
    E — fingerprint computed but AcoustID errored / non-ok status
    F — fpcalc failed (codec, missing file, duration <30s)
    R — current production code WOULD identify this; in the no_match corpus only
        because the original analyze run hit a transient AcoustID gap. In the
        mb_503 corpus it's the expected good state for `identify-retry`.
    Z — novel pattern, see notes.
    """
    if not record.get("fpcalc_ok"):
        return "F"

    if (record.get("duration_sec") or 0) < 30:
        return "F"

    status = record.get("acoustid_status")
    if status != "ok":
        return "E"

    results = record.get("acoustid_results") or []
    if not results:
        return "A"

    # results are already sorted by score descending in record
    top = results[0]
    top_score = top.get("score") or 0.0
    top_linked = bool(top.get("recordings"))

    # If top is linked AND high enough → current production code identifies this.
    # In the mb_503 corpus this is the expected good outcome (AcoustID side fine,
    # only MB step had transient 503). In the no_match corpus it would mean the
    # original analyze run hit a transient AcoustID issue that has since resolved.
    if top_linked and top_score >= threshold_high:
        return "R"

    # D: top is high-score unlinked but a LINKED result above threshold_mid exists below it
    if top_score >= threshold_high and not top_linked:
        any_linked_above_mid = any(
            r.get("recordings") and (r.get("score") or 0.0) >= threshold_mid for r in results
        )
        if any_linked_above_mid:
            return "D"
        return "B"

    # C: top below threshold_high. If a linked result exists above threshold_mid
    # the threshold-recalibration alone would fix it.
    if top_score < threshold_high:
        linked_mid = [
            r for r in results if r.get("recordings") and (r.get("score") or 0.0) >= threshold_mid
        ]
        if linked_mid:
            return "C"
        unlinked_mid = [
            r for r in results if not r.get("recordings") and (r.get("score") or 0.0) >= threshold_mid
        ]
        if unlinked_mid:
            return "B"  # unlinked-only, score wedge between 0.5 and 0.85
        return "Z"

    return "Z"


# ---------------------------------------------------------------------------
# Top-5 compact normalization
# ---------------------------------------------------------------------------

def compact_results(raw_results: list[dict]) -> list[dict]:
    """Strip to top 5, keep only the fields downstream rounds need."""
    sorted_r = sorted(raw_results, key=lambda r: r.get("score", 0.0), reverse=True)
    out: list[dict] = []
    for r in sorted_r[:5]:
        recs = r.get("recordings") or []
        rec_summary = []
        for rec in recs[:3]:
            artists = [a.get("name", "?") for a in (rec.get("artists") or [])]
            rgs = rec.get("releasegroups") or []
            rg_titles = [rg.get("title", "?") for rg in rgs[:3]]
            rec_summary.append(
                {
                    "mbid": rec.get("id"),
                    "title": rec.get("title"),
                    "artists": artists,
                    "duration": rec.get("duration"),
                    "releasegroups": rg_titles,
                }
            )
        out.append(
            {
                "acoustid_id": r.get("id"),
                "score": r.get("score"),
                "recording_count": len(recs),
                "recordings": rec_summary,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-slug probe
# ---------------------------------------------------------------------------

def probe_slug(snapshot_bucket: str, slug: str, expected_duration: int, api_key: str) -> dict:
    fragment_path = FRAGMENTS_DIR / f"{slug}.json"
    if fragment_path.is_file():
        try:
            cached = json.loads(fragment_path.read_text(encoding="utf-8"))
            # Re-classify so a refined bucket rule applies without re-querying AcoustID
            cached["bucket"] = classify(cached)
            print(f"  [cached] {slug}  -> bucket {cached['bucket']}")
            return cached
        except Exception:
            print(f"  [cache-bad, redoing] {slug}")

    slug_dir = CACHE_DIR / slug
    mp3 = slug_dir / f"{slug}.mp3"

    raw_artist, raw_title, clean_artist, clean_title = parse_slug(slug)

    record: dict = {
        "slug": slug,
        "snapshot_bucket": snapshot_bucket,
        "expected_duration_sec": expected_duration,
        "duration_sec": None,
        "leading_silence_sec": None,
        "trailing_silence_sec": None,
        "artist_guess_raw": raw_artist,
        "title_guess_raw": raw_title,
        "artist_guess_clean": clean_artist,
        "title_guess_clean": clean_title,
        "mp3_exists": mp3.is_file(),
        "fpcalc_ok": False,
        "fpcalc_error": None,
        "fingerprint_prefix": None,  # first 40 chars; full FP is huge
        "fingerprint_length": None,
        "acoustid_status": None,
        "acoustid_error": None,
        "acoustid_results": [],
        "bucket": None,
        "notes": "",
    }

    if not mp3.is_file():
        record["fpcalc_error"] = f"mp3 missing: {mp3}"
        record["bucket"] = "F"
        record["notes"] = "Source MP3 not present in cache."
        fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    # fpcalc
    print(f"  fpcalc {slug}")
    fp, fp_err = run_fpcalc(mp3)
    if fp is None:
        record["fpcalc_error"] = fp_err
        record["bucket"] = "F"
        record["notes"] = f"fpcalc failed: {fp_err}"
        fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    record["fpcalc_ok"] = True
    record["duration_sec"] = fp["duration"]
    fingerprint = fp["fingerprint"]
    record["fingerprint_prefix"] = fingerprint[:40]
    record["fingerprint_length"] = len(fingerprint)

    # Skip AcoustID if too short
    if (fp["duration"] or 0) < 30:
        record["bucket"] = "F"
        record["notes"] = f"Duration {fp['duration']:.1f}s < 30s — Chromaprint below useful range."
        fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    # silence detection
    print(f"  silence  {slug}")
    leading, trailing, sil_err = detect_silence(mp3, fp["duration"])
    record["leading_silence_sec"] = leading
    record["trailing_silence_sec"] = trailing
    if sil_err:
        record["notes"] = (record["notes"] + f" silencedetect: {sil_err};").strip()

    # AcoustID — rate-limit ≤3/sec
    print(f"  acoustid {slug}")
    body, ac_err = acoustid_lookup(api_key, fingerprint, int(round(fp["duration"])))
    time.sleep(0.4)  # rate-limit guard

    if ac_err:
        record["acoustid_status"] = "error"
        record["acoustid_error"] = ac_err
        record["bucket"] = "E"
        record["notes"] = (record["notes"] + f" AcoustID error: {ac_err};").strip()
        fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    record["acoustid_status"] = body.get("status")
    if body.get("status") != "ok":
        record["acoustid_error"] = body.get("error", {}).get("message") or str(body.get("error"))
        record["bucket"] = "E"
        record["notes"] = (
            record["notes"] + f" AcoustID status={body.get('status')} error={record['acoustid_error']};"
        ).strip()
        fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    raw_results = body.get("results") or []
    record["acoustid_results"] = compact_results(raw_results)
    record["bucket"] = classify(record)

    fragment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


# ---------------------------------------------------------------------------
# Canary check (single known-identified track)
# ---------------------------------------------------------------------------

def canary_check(api_key: str) -> str | None:
    """Quick canary: fpcalc + AcoustID against a known-identified slug.

    Returns None on success, or an error string on failure.
    """
    # Pick a known-good identified slug from the cache
    canary_slug = None
    for candidate in ("jamiroquai_everyday", "where_is_my_mind_49fb9hhoo6c", "radiohead_creep_heads_on_the_radio"):
        if (CACHE_DIR / candidate / f"{candidate}.mp3").is_file():
            canary_slug = candidate
            break
    if not canary_slug:
        return "canary skipped (no known-good slug present)"

    mp3 = CACHE_DIR / canary_slug / f"{canary_slug}.mp3"
    fp, err = run_fpcalc(mp3)
    if fp is None:
        return f"canary fpcalc failed: {err}"
    body, ac_err = acoustid_lookup(api_key, fp["fingerprint"], int(round(fp["duration"])))
    if ac_err:
        return f"canary AcoustID network error: {ac_err}"
    if body.get("status") != "ok":
        err_obj = body.get("error") or {}
        return f"canary AcoustID status={body.get('status')} error={err_obj}"
    return None


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def render_markdown(records: list[dict]) -> str:
    by_bucket: dict[str, list[dict]] = {}
    for rec in records:
        by_bucket.setdefault(rec["bucket"], []).append(rec)

    lines: list[str] = []
    lines.append("# Round 1 — Subagent A2 — Empirical Corpus Probe")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("Probed 30 unidentified slugs from the corpus with fpcalc + AcoustID + ffmpeg silencedetect. Read-only; live cache untouched.")
    lines.append("")
    lines.append("## Bucket framework")
    lines.append("")
    lines.append("- **A**: AcoustID returns `results: []` — fingerprint not in DB, or windows misaligned by leading silence.")
    lines.append("- **B**: top result is high-score (≥0.85) and unlinked (`recordings: []`), no linked result below it. Fingerprint claimed by an AcoustID ID that was never linked to a MusicBrainz recording.")
    lines.append("- **C**: top score is below 0.85 but at least one linked result is above 0.5. Threshold issue.")
    lines.append("- **D**: results exist with linked recordings *below* a higher-score unlinked result — the current `max-by-score-then-bail-if-no-recordings` logic in `acoustid_client.lookup` throws away the correct row.")
    lines.append("- **E**: fingerprint computed but AcoustID HTTP/key/status error.")
    lines.append("- **F**: fpcalc failed (codec, duration <30s, missing file).")
    lines.append("- **R**: AcoustID returns a high-score linked top result — current production `acoustid_client.lookup` WOULD identify this. In the `mb_503` corpus this is the expected state (only MB step failed historically); they should clear via `scripts/identify-retry.*`. In the `no_match` corpus it indicates the original analyze run hit a transient AcoustID issue that has since resolved.")
    lines.append("- **Z**: novel / hybrid pattern — see notes per slug.")
    lines.append("")
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Bucket | Count | Slugs |")
    lines.append("|--------|-------|-------|")
    bucket_order = ["A", "B", "C", "D", "E", "F", "R", "Z"]
    for b in bucket_order:
        recs = by_bucket.get(b, [])
        if not recs:
            continue
        slug_list = ", ".join(f"`{r['slug'][:50]}`" for r in recs[:3])
        if len(recs) > 3:
            slug_list += f", ... (+{len(recs)-3})"
        lines.append(f"| **{b}** | {len(recs)} | {slug_list} |")
    lines.append("")

    # Silence stats per bucket
    lines.append("## Leading-silence stats per bucket")
    lines.append("")
    lines.append("| Bucket | n | mean leading (s) | p90 leading (s) | max leading (s) | mean trailing (s) | max trailing (s) |")
    lines.append("|--------|---|------------------|-----------------|-----------------|-------------------|------------------|")
    for b in bucket_order:
        recs = [r for r in by_bucket.get(b, []) if r.get("leading_silence_sec") is not None]
        if not recs:
            continue
        leads = sorted(r["leading_silence_sec"] for r in recs)
        trails = sorted((r.get("trailing_silence_sec") or 0.0) for r in recs)
        n = len(leads)
        mean_l = sum(leads) / n
        p90_idx = max(0, int(round(0.9 * (n - 1))))
        p90_l = leads[p90_idx]
        max_l = max(leads)
        mean_t = sum(trails) / n
        max_t = max(trails)
        lines.append(f"| **{b}** | {n} | {mean_l:.2f} | {p90_l:.2f} | {max_l:.2f} | {mean_t:.2f} | {max_t:.2f} |")
    lines.append("")

    # Per-bucket detail
    BUCKET_FIX = {
        "A": "Round 3 (silence-strip preprocessing) — should unlock commercial cuts; Round 4 (MB text-search fallback) for niche / live / non-commercial / DAW renders.",
        "B": "Round 4 (MB text-search fallback). The AcoustID match exists but is unlinked, so no MBID is reachable even after the Bucket-C bug fix. Long-term: a write-side submit-back path.",
        "C": "Round 2 (threshold recalibration) — lowering DEFAULT_MIN_SCORE from 0.85 to ~0.65-0.70 captures these.",
        "D": "Round 2 (Bucket-C bug fix in `acoustid_client.lookup`) — iterate results, return first linked above threshold. Cheapest, lowest-risk fix in the entire overhaul.",
        "E": "Round 1/3 (AcoustID error handling). If 400 invalid API key, coordinate with A3.",
        "F": "Out of scope for identification - short / corrupt / missing files. Pipeline should fail-soft, NOT silently demote previously-identified records.",
        "R": "Re-run identify. For `mb_503` slugs this is the operational `scripts/identify-retry.*` path. After Round 2's SCHEMA_VERSION bump, the staleness chip in the sidebar will surface the re-run prompt automatically.",
        "Z": "Novel - see slug notes; may need Round 5 attention.",
    }
    for b in bucket_order:
        recs = by_bucket.get(b, [])
        if not recs:
            continue
        lines.append(f"### Bucket {b} ({len(recs)} slugs)")
        lines.append("")
        lines.append(f"**Fix path:** {BUCKET_FIX[b]}")
        lines.append("")
        lines.append("| Slug | snap | dur (s) | lead silence | top score | top linked | top mbid (if any) | top recording |")
        lines.append("|------|------|---------|--------------|-----------|------------|-------------------|----------------|")
        for r in recs:
            top_score = ""
            top_linked = ""
            top_mbid = ""
            top_rec = ""
            if r.get("acoustid_results"):
                t = r["acoustid_results"][0]
                top_score = f"{t.get('score', 0):.3f}" if t.get("score") is not None else "—"
                top_linked = "yes" if t.get("recordings") else "no"
                if t.get("recordings"):
                    rec0 = t["recordings"][0]
                    top_mbid = (rec0.get("mbid") or "")[:8]
                    artists = "/".join(rec0.get("artists") or []) or "?"
                    title = rec0.get("title") or "?"
                    top_rec = f"{artists} — {title}"[:60]
            lead = r.get("leading_silence_sec")
            lead_s = f"{lead:.2f}" if lead is not None else "—"
            dur = r.get("duration_sec")
            dur_s = f"{dur:.1f}" if dur is not None else "—"
            lines.append(
                f"| `{r['slug'][:55]}` | {r['snapshot_bucket']} | {dur_s} | {lead_s} | {top_score} | {top_linked} | `{top_mbid}` | {top_rec} |"
            )
        lines.append("")

    # Special call-outs
    lines.append("## Call-outs")
    lines.append("")
    lines.append("### Surprising AcoustID responses")
    lines.append("")
    lines.append("Slugs where the AcoustID payload contains evidence the current code can't reach today, or where today's AcoustID response disagrees with the cached identify.json reason string:")
    lines.append("- **Bucket D**: correct linked match present below a higher-score unlinked top result. Round 2 bug fix unlocks.")
    lines.append("- **Bucket C**: top score below 0.85 but a linked recording exists. Round 2 threshold recalibration unlocks.")
    lines.append("- **Bucket R + `no_match` snapshot**: cached `identify.json` says \"no AcoustID match above threshold\" but the live API now returns a usable linked recording. Either the AcoustID DB was updated since the original analyze, or the original run hit a transient gap.")
    lines.append("")
    surprising = [r for r in records if r.get("bucket") in ("C", "D") or (r.get("bucket") == "R" and r.get("snapshot_bucket") == "no_match")]
    if not surprising:
        lines.append("_(none)_")
    else:
        for r in surprising:
            lines.append(f"- `{r['slug']}` — bucket {r['bucket']}, top score {r['acoustid_results'][0].get('score', 0):.3f}")
            # Find best linked result + score
            best_linked = next((x for x in r["acoustid_results"] if x.get("recordings")), None)
            if best_linked:
                rec0 = best_linked["recordings"][0]
                lines.append(
                    f"    - Best linked candidate: score={best_linked['score']:.3f}, `{rec0.get('mbid')}` — "
                    f"{'/'.join(rec0.get('artists') or [])} — {rec0.get('title')}"
                )
    lines.append("")

    lines.append("### Mangled slug guesses (Round 4 fallback risk)")
    lines.append("")
    lines.append("Slugs whose derived artist/title is so noisy that a MusicBrainz text-search fallback may struggle. Round 4 design should pay attention to these.")
    lines.append("")
    for r in records:
        # Heuristic for "mangled": more than 6 words in title, OR contains certain noise even after cleaning, OR title-clean is empty
        title_clean = r.get("title_guess_clean", "")
        artist_clean = r.get("artist_guess_clean", "")
        title_words = title_clean.split()
        flag = False
        reasons = []
        if not artist_clean or not title_clean:
            flag = True
            reasons.append("empty artist or title after cleaning")
        if len(title_words) > 6:
            flag = True
            reasons.append(f"title has {len(title_words)} words")
        if flag:
            lines.append(f"- `{r['slug']}` → artist=`{artist_clean}` title=`{title_clean}` ({'; '.join(reasons)})")
    lines.append("")

    lines.append("### Easy wins (Round 2 alone, plus mb_503 retry path)")
    lines.append("")
    lines.append("Slugs that bucket as **D** (max-by-score bug) or **C** (threshold), plus bucket **R** entries from the `no_match` corpus (current code already identifies them - the only reason they're in this corpus is that the original analyze run hit a transient AcoustID issue that has since resolved). The `mb_503` entries also fall in bucket R and are addressable via `scripts/identify-retry.*` rather than a code fix.")
    lines.append("")
    easy = [r for r in records if r.get("bucket") in ("C", "D")]
    if not easy:
        lines.append("_(none in C/D)_")
    else:
        for r in easy:
            best_linked = next((x for x in r["acoustid_results"] if x.get("recordings")), None)
            mbid = best_linked["recordings"][0].get("mbid") if best_linked and best_linked.get("recordings") else "?"
            score = best_linked.get("score") if best_linked else "?"
            score_s = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
            lines.append(f"- `{r['slug']}` - bucket {r['bucket']}, expect MBID `{mbid}` at score {score_s}")
    lines.append("")
    bucket_r_no_match = [r for r in records if r.get("bucket") == "R" and r.get("snapshot_bucket") == "no_match"]
    if bucket_r_no_match:
        lines.append("Bucket R / `no_match` corpus members - just need a re-run of identify (Round 2 SCHEMA_VERSION bump will mark these stale and surface the chip):")
        for r in bucket_r_no_match:
            top = r["acoustid_results"][0]
            rec0 = (top.get("recordings") or [{}])[0]
            lines.append(f"- `{r['slug']}` - score {top.get('score'):.3f}, MBID `{rec0.get('mbid')}` ({'/'.join(rec0.get('artists') or [])} - {rec0.get('title')})")
        lines.append("")

    lines.append("### Hard cases (need Rounds 3 + 4 combined)")
    lines.append("")
    lines.append("Slugs that bucket as **A** (zero AcoustID results) — Round 3 silence-strip may rescue commercial cuts; everything else falls through to Round 4 MB text-search fallback. The live/acoustic/niche cuts will almost certainly need Round 4.")
    lines.append("")
    hard = [r for r in records if r.get("bucket") == "A"]
    for r in hard:
        lead = r.get("leading_silence_sec") or 0.0
        likely_commercial = "official" in r["slug"].lower() or "audio" in r["slug"].lower()
        marker = " (likely commercial — silence-strip should help)" if likely_commercial else ""
        lines.append(f"- `{r['slug']}` — leading silence {lead:.2f}s{marker}")
    lines.append("")

    # mb_503 verification
    lines.append("### mb_503 corpus members — AcoustID-side verification")
    lines.append("")
    lines.append("These slugs already had AcoustID matches at original analyze time but failed on MusicBrainz HTTP 503. We re-probe AcoustID only — the operational `identify-retry` script handles the MB retry.")
    lines.append("")
    mb503_records = [r for r in records if r.get("snapshot_bucket") == "mb_503"]
    for r in mb503_records:
        top = (r.get("acoustid_results") or [{}])[0]
        score = top.get("score")
        linked = bool(top.get("recordings"))
        score_s = f"{score:.3f}" if score is not None else "—"
        verdict = "OK (still resolvable)" if linked and score and score >= 0.5 else "NEEDS REVIEW"
        lines.append(f"- `{r['slug']}` — top score {score_s}, linked={linked} → {verdict}")
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    env_vars = _load_env(ENV_FILE)
    api_key = os.environ.get("ACOUSTID_API_KEY") or env_vars.get("ACOUSTID_API_KEY")
    if not api_key:
        print("FATAL: no ACOUSTID_API_KEY in env or .env", file=sys.stderr)
        return 2

    print(f"AcoustID key loaded (length={len(api_key)}); running canary check...")
    canary_err = canary_check(api_key)
    if canary_err:
        if "invalid API key" in (canary_err or "").lower() or "HTTP 400" in (canary_err or ""):
            print(f"FATAL: canary failed — likely User Key instead of Application Key. Details: {canary_err}", file=sys.stderr)
            return 3
        print(f"WARN: canary returned: {canary_err}", file=sys.stderr)
    else:
        print("Canary OK — key is valid Application Key.")

    records: list[dict] = []
    for idx, (snap, slug, expected_dur) in enumerate(CORPUS, start=1):
        print(f"[{idx:2}/{len(CORPUS)}] {slug}")
        rec = probe_slug(snap, slug, expected_dur, api_key)
        records.append(rec)

    # Sort by bucket then slug for the final output
    records.sort(key=lambda r: (r.get("bucket") or "Z", r["slug"]))

    out_doc = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_source": "docs/superpowers/specs/2026-05-12-identify-corpus.md",
        "fpcalc_binary": str(FPCALC_WIN),
        "acoustid_meta": "recordings releasegroups",
        "silencedetect_threshold_db": -50,
        "silencedetect_min_duration_s": 0.3,
        "rate_limit_sleep_s": 0.4,
        "slugs": records,
    }
    OUT_JSON.write_text(json.dumps(out_doc, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_markdown(records), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
