#!/usr/bin/env python3
"""Diagnostic: query AcoustID with explicit fingerprints from selected cache
slugs and show the TOP results regardless of threshold.

Use to investigate why a known commercial track is reporting
"no AcoustID match above threshold" — the real questions are
(a) does AcoustID have a fingerprint at all, and
(b) what score does the YouTube transcode actually get?
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


SLUGS = [
    "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw",
    "balthazar-changes_official_video-p3jb998acqo",
    "joesef_comedown_official_video_zaprrzdhyiw",
    "moderat-reminder_official_video-cjwsnuoazug",
    "warhaus_love_s_a_stranger_official_video_gsjdhd0stag",
    "charlie_puth_attention",
    "olivia_dean_dive_acoustic_yylsa4m2zzm",
]

ROOT = Path(__file__).resolve().parent.parent
FPCALC = ROOT / "analyze" / "vendor" / "chromaprint" / "fpcalc"


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


def main() -> int:
    env = _load_env(ROOT / ".env")
    api_key = os.environ.get("ACOUSTID_API_KEY") or env.get("ACOUSTID_API_KEY")
    if not api_key:
        print("no ACOUSTID_API_KEY in env or .env", file=sys.stderr)
        return 2

    for slug in SLUGS:
        mp3 = ROOT / "cache" / slug / f"{slug}.mp3"
        print(f"\n=== {slug} ===")
        if not mp3.is_file():
            print(f"  mp3 missing: {mp3}")
            continue

        try:
            raw = subprocess.check_output([str(FPCALC), "-json", str(mp3)], timeout=60)
        except Exception as exc:
            print(f"  fpcalc failed: {exc}")
            continue
        fp = json.loads(raw)

        params = urllib.parse.urlencode({
            "client": api_key,
            "meta": "recordings",
            "fingerprint": fp["fingerprint"],
            "duration": int(round(fp["duration"])),
        })
        url = "https://api.acoustid.org/v2/lookup?" + params
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                body = json.loads(resp.read())
        except Exception as exc:
            print(f"  AcoustID HTTP error: {exc}")
            continue
        if body.get("status") != "ok":
            print(f"  AcoustID status={body.get('status')} error={body.get('error')}")
            continue
        results = body.get("results") or []
        if not results:
            print("  (no AcoustID results at all — fingerprint never submitted)")
            continue
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        for r in results[:3]:
            score = r.get("score", 0.0)
            recs = r.get("recordings") or []
            if recs:
                rec = recs[0]
                artists = "; ".join((a.get("name", "?") for a in rec.get("artists", [])))
                title = rec.get("title", "?")
                rec_mbid = rec.get("id", "?")
                print(f"  score={score:.3f}  {artists} — {title}")
                print(f"                mbid_recording={rec_mbid}")
            else:
                print(f"  score={score:.3f}  (no recordings linked; AcoustID-only ID={r.get('id', '?')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
