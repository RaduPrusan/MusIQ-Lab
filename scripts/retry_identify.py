"""Retry identify on slugs whose cached identify.json is a transient-error stub
(typically HTTP 503 from AcoustID or MusicBrainz). Deletes identify.json +
sidecar to invalidate the cache, then runs `--stages-only identify`."""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze.pipeline import analyze

RETRIES = [
    ("notre-dame_est-3frubz9yhim", "best"),
    ("the_national-graceless-jpz_guyimhw", "normal"),
]

for slug, q in RETRIES:
    d = Path("cache") / slug
    for f in ["identify.json", ".params_identify.json"]:
        p = d / f
        if p.exists():
            p.unlink()
    mp3 = next(d.glob("*.mp3"))
    print(f"=== {slug} (q={q}) ===")
    t0 = time.monotonic()
    try:
        analyze(
            mp3, slug=slug, stems_quality=q,
            stages_only={"identify"},
            skip_stages={"essentia_extract"},
            quiet=True,
        )
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
        continue
    dt = time.monotonic() - t0
    out = json.loads((d / "identify.json").read_text())
    if out.get("identified"):
        artist = out.get("artist")
        title = out.get("title")
        print(f"  IDENTIFIED in {dt:.1f}s: {artist} - {title}")
    else:
        reason = (out.get("reason") or "")[:140]
        print(f"  still stub in {dt:.1f}s: {reason}")
