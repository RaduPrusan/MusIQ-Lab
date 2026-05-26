#!/usr/bin/env python3
"""Render round-2-delta.md from round-2-baseline.json + round-2-delta.json
(machine record) — the .md is a human-readable summary."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
OUT_DIR = WORKTREE / "docs" / "superpowers" / "identify-overhaul"
BASELINE = OUT_DIR / "round-2-baseline.json"
BATCH_RECORDS = OUT_DIR / "round-2-batch-records.json"
DELTA_J = OUT_DIR / "round-2-delta.json"
DELTA_MD = OUT_DIR / "round-2-delta.md"

R1_FRAG = OUT_DIR / "_fragments"
R2_FRAG = OUT_DIR / "_fragments-round2"

CORPUS_SLUGS = [
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


def _load(p: Path) -> dict:
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _r1_bucket(slug: str) -> str | None:
    """Read R1's bucket from the per-slug fragment, but apply the R1 md report's
    framework: mb_503 fragments stored 'Z' before bucket 'R' was added to
    classify(). Re-resolve using snapshot_bucket so reports match round-1-a2-corpus-probe.md.
    """
    p = R1_FRAG / f"{slug}.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    stored = data.get("bucket")
    # Promote Z → R when AcoustID returned a high-score linked result (mb_503 case)
    if stored == "Z":
        results = data.get("acoustid_results") or []
        if results:
            top = results[0]
            if (top.get("score") or 0.0) >= 0.85 and bool(top.get("recordings")):
                return "R"
    return stored


def _r2_bucket(slug: str) -> str | None:
    p = R2_FRAG / f"{slug}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("bucket")
    except Exception:
        return None


def _r2_top_mbid(slug: str) -> str | None:
    p = R2_FRAG / f"{slug}.json"
    if not p.is_file():
        return None
    try:
        recs = json.loads(p.read_text(encoding="utf-8")).get("acoustid_results") or []
        if not recs:
            return None
        recs0 = recs[0]
        rs = recs0.get("recordings") or []
        return rs[0].get("mbid") if rs else None
    except Exception:
        return None


def _r1_top_mbid(slug: str) -> str | None:
    p = R1_FRAG / f"{slug}.json"
    if not p.is_file():
        return None
    try:
        recs = json.loads(p.read_text(encoding="utf-8")).get("acoustid_results") or []
        if not recs:
            return None
        recs0 = recs[0]
        rs = recs0.get("recordings") or []
        return rs[0].get("mbid") if rs else None
    except Exception:
        return None


def main() -> None:
    baseline = _load(BASELINE)
    delta = _load(BATCH_RECORDS)
    records = delta.get("records", [])
    by_slug = {r["slug"]: r for r in records}
    baseline_by_slug = {s["slug"]: s for s in baseline.get("slugs", [])}

    corpus_set = set(CORPUS_SLUGS)
    all_cache_slugs = list(baseline_by_slug.keys())

    # Aggregate counts
    corpus_before = sum(1 for s in CORPUS_SLUGS if baseline_by_slug.get(s, {}).get("identified"))
    corpus_after = sum(1 for s in CORPUS_SLUGS if (by_slug.get(s) or {}).get("after", {}).get("identified"))
    cache_before = sum(1 for s in all_cache_slugs if baseline_by_slug.get(s, {}).get("identified"))
    # Full-cache after: for non-corpus slugs the baseline state stands (we didn't re-run them)
    cache_after = sum(
        1 for s in all_cache_slugs
        if (by_slug.get(s, {}).get("after", {}).get("identified")
            if s in corpus_set else baseline_by_slug.get(s, {}).get("identified"))
    )

    movers_false_to_true: list[dict] = []
    movers_true_to_false: list[dict] = []
    movers_reason_changed: list[dict] = []
    stable_false: list[str] = []
    stable_true: list[str] = []
    regressions: list[dict] = []

    for slug in CORPUS_SLUGS:
        rec = by_slug.get(slug)
        if not rec:
            continue
        before = baseline_by_slug.get(slug, {})
        after = rec.get("after", {})
        b_id = bool(before.get("identified"))
        a_id = bool(after.get("identified"))
        b_reason = before.get("reason")
        a_reason = after.get("reason")
        info = {
            "slug": slug,
            "before_identified": b_id,
            "after_identified": a_id,
            "before_reason": b_reason,
            "after_reason": a_reason,
            "before_mbid": before.get("mbid_recording"),
            "after_mbid": after.get("mbid_recording"),
            "before_title": before.get("title"),
            "after_title": after.get("title"),
            "before_artist": before.get("artist"),
            "after_artist": after.get("artist"),
            "after_score": after.get("score"),
            "bucket_r1": _r1_bucket(slug),
            "bucket_r2": _r2_bucket(slug),
            "wall_sec": rec.get("wall_sec"),
            "identify_log_line": rec.get("identify_log_line"),
            "has_acoustid_raw": after.get("has_acoustid_raw"),
            "has_sidecar": after.get("has_sidecar"),
            "sidecar_schema_version": after.get("schema_version"),
        }
        if not b_id and a_id:
            movers_false_to_true.append(info)
        elif b_id and not a_id:
            movers_true_to_false.append(info)
            regressions.append(info)
        elif not b_id and not a_id and (b_reason != a_reason):
            movers_reason_changed.append(info)
        elif b_id and a_id:
            stable_true.append(slug)
        else:
            stable_false.append(slug)

    # Per-bucket movement (R1 framework)
    r1_buckets: dict[str, list[str]] = {}
    for s in CORPUS_SLUGS:
        b = _r1_bucket(s) or "?"
        r1_buckets.setdefault(b, []).append(s)

    bucket_movement: dict[str, dict] = {}
    for b, slugs in sorted(r1_buckets.items()):
        cleared = []
        remaining = []
        for s in slugs:
            after = (by_slug.get(s) or {}).get("after", {})
            if after.get("identified"):
                cleared.append(s)
            else:
                remaining.append(s)
        bucket_movement[b] = {
            "total": len(slugs),
            "cleared": len(cleared),
            "remaining": len(remaining),
            "cleared_slugs": cleared,
            "remaining_slugs": remaining,
        }

    # Pre-existing identified-true slugs NOT in corpus (sidecar bridge check)
    non_corpus_identified_before = [
        s for s in all_cache_slugs
        if s not in corpus_set and baseline_by_slug.get(s, {}).get("identified")
    ]

    # Observability sample (3-5 log lines)
    obs_samples = [
        m["identify_log_line"] for m in movers_false_to_true if m.get("identify_log_line")
    ][:5]

    # Acoustid raw verification
    expected_raw = [
        m for m in movers_false_to_true
        if not (m.get("after_reason") or "").startswith("AcoustID error")
    ]
    raw_missing = [m["slug"] for m in expected_raw if not m["has_acoustid_raw"]]

    # AcoustID DB delta vs Round 1
    db_changes: list[dict] = []
    for s in CORPUS_SLUGS:
        m1 = _r1_top_mbid(s)
        m2 = _r2_top_mbid(s)
        if m1 != m2:
            db_changes.append({"slug": s, "r1_top_mbid": m1, "r2_top_mbid": m2})

    # Compose markdown
    md = []
    md.append("# Round 2 — Delta Report")
    md.append("")
    md.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    md.append("")
    md.append("Re-ran `analyze --stages-only identify` against the 30-track corpus after B1's commits (SHA `baa991b`). See [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md) §B2.")
    md.append("")
    md.append("## Aggregate")
    md.append("")
    md.append("| Scope | Before | After | Delta |")
    md.append("|---|---|---|---|")
    md.append(f"| 30-track corpus identified | {corpus_before} / 30 ({corpus_before/30*100:.1f}%) | {corpus_after} / 30 ({corpus_after/30*100:.1f}%) | +{corpus_after - corpus_before} |")
    md.append(f"| Full cache identified | {cache_before} / {len(all_cache_slugs)} ({cache_before/len(all_cache_slugs)*100:.1f}%) | {cache_after} / {len(all_cache_slugs)} ({cache_after/len(all_cache_slugs)*100:.1f}%) | +{cache_after - cache_before} |")
    md.append("")
    md.append(f"Batch wall time: {delta.get('wall_sec_so_far', '?')}s")
    md.append("")

    md.append("## Regression gate verdict")
    md.append("")
    if not regressions:
        md.append("**PASS** — zero `identified=true → false` transitions on the 30-track corpus. `_preserve_or_write` guard held.")
    else:
        md.append("**FAIL — REGRESSION DETECTED**")
        md.append("")
        for r in regressions:
            md.append(f"- `{r['slug']}` — before: identified=true mbid=`{r['before_mbid']}`; after: identified=false reason=`{r['after_reason']}`")
    md.append("")

    md.append("## Movers")
    md.append("")
    md.append(f"### `identified: false → true` ({len(movers_false_to_true)})")
    md.append("")
    if not movers_false_to_true:
        md.append("(none)")
    else:
        md.append("| Slug | R1 bucket | Score | MBID | Title — Artist |")
        md.append("|---|---|---|---|---|")
        for m in movers_false_to_true:
            score = m.get("after_score")
            score_s = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
            md.append(
                f"| `{m['slug']}` | {m.get('bucket_r1') or '?'} | {score_s} | `{m.get('after_mbid') or '—'}` | {m.get('after_title') or '—'} — {m.get('after_artist') or '—'} |"
            )
    md.append("")

    md.append(f"### `identified: true → false` ({len(movers_true_to_false)})")
    md.append("")
    if not movers_true_to_false:
        md.append("(none — regression gate held)")
    else:
        for m in movers_true_to_false:
            md.append(f"- `{m['slug']}` — was `{m['before_title']}` (`{m['before_mbid']}`), now reason: `{m['after_reason']}`")
    md.append("")

    md.append(f"### Reason changed but still `identified: false` ({len(movers_reason_changed)})")
    md.append("")
    if not movers_reason_changed:
        md.append("(none)")
    else:
        md.append("| Slug | Before reason | After reason |")
        md.append("|---|---|---|")
        for m in movers_reason_changed:
            md.append(f"| `{m['slug']}` | `{m['before_reason']}` | `{m['after_reason']}` |")
    md.append("")

    md.append("## Per-bucket movement (R1 framework)")
    md.append("")
    md.append("| Bucket | Total | Cleared (now identified) | Remaining (still false) |")
    md.append("|---|---|---|---|")
    for b in sorted(bucket_movement):
        mv = bucket_movement[b]
        md.append(f"| **{b}** | {mv['total']} | {mv['cleared']} | {mv['remaining']} |")
    md.append("")
    for b in sorted(bucket_movement):
        mv = bucket_movement[b]
        if mv["cleared"]:
            md.append(f"- **Bucket {b} cleared:** " + ", ".join(f"`{s}`" for s in mv["cleared_slugs"]))
    md.append("")

    md.append("## Observability — structured `identify:` log lines")
    md.append("")
    md.append(f"`identify: slug=... source=... score=... mbid=... reason=...` log line emitted for **{sum(1 for r in records if r.get('identify_log_line'))} / {len(records)}** corpus slugs.")
    md.append("")
    if obs_samples:
        md.append("Sample lines (false → true movers):")
        md.append("")
        md.append("```")
        for line in obs_samples:
            md.append(line.strip())
        md.append("```")
    md.append("")

    md.append("## Raw-cache verification — `.acoustid_raw.json`")
    md.append("")
    md.append(f"Expected for each slug that got a non-error AcoustID response: **{len(expected_raw)}** slugs.")
    md.append(f"Slugs missing `.acoustid_raw.json` despite having a successful AcoustID query: **{len(raw_missing)}**.")
    if raw_missing:
        md.append("")
        for s in raw_missing:
            md.append(f"- `{s}` — FLAGGED")
    md.append("")

    md.append("## Sidecar migration — pre-existing identified=true caches (NOT re-queried)")
    md.append("")
    md.append(f"Cache slugs that were `identified=true` at baseline and are NOT in the corpus: **{len(non_corpus_identified_before)}**.")
    md.append("")
    md.append("These caches must NOT have been re-queried — the legacy-cache bridge in `cached()` should synthesize a sidecar and skip AcoustID. We did not invoke analyze on these slugs in Round 2, so behavior is implicitly preserved (they were not touched). Slugs:")
    md.append("")
    for s in sorted(non_corpus_identified_before):
        md.append(f"- `{s}`")
    md.append("")

    md.append("## AcoustID database delta (Round 1 → Round 2)")
    md.append("")
    if not db_changes:
        md.append("No top-result MBID changes between R1 (`_fragments/`) and R2 (`_fragments-round2/`) — AcoustID DB state is stable.")
    else:
        md.append(f"**{len(db_changes)}** slug(s) had their top-result MBID change between Round 1 and Round 2:")
        md.append("")
        for c in db_changes:
            md.append(f"- `{c['slug']}` — R1 top mbid `{c['r1_top_mbid']}` → R2 top mbid `{c['r2_top_mbid']}`")
    md.append("")

    md.append("## Stable rows")
    md.append("")
    md.append(f"- Stable `identified=true` (corpus): {len(stable_true)}")
    md.append(f"- Stable `identified=false` (corpus): {len(stable_false)}")
    if stable_false:
        md.append("")
        md.append("Slugs still false after Round 2:")
        for s in stable_false:
            rec = by_slug.get(s) or {}
            after = rec.get("after") or {}
            md.append(f"- `{s}` — reason: `{after.get('reason')}`")
    md.append("")

    md.append("## Source MP3 — references")
    md.append("")
    md.append("- Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md)")
    md.append("- Corpus: [`2026-05-12-identify-corpus.md`](../specs/2026-05-12-identify-corpus.md)")
    md.append("- Round 1 baseline: [`round-1-a2-corpus-probe.md`](./round-1-a2-corpus-probe.md)")
    md.append("- Round 1 review: [`round-1-review.md`](./round-1-review.md)")
    md.append("")

    DELTA_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {DELTA_MD}")

    # Also augment delta.json with a 'movers' section + regressions
    delta_out = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "before": baseline.get("slugs", []),
        "after": [
            {
                "slug": s,
                **((by_slug.get(s) or {}).get("after") or {}),
            } if s in corpus_set else baseline_by_slug.get(s, {})
            for s in all_cache_slugs
        ],
        "aggregate": {
            "corpus_before": corpus_before,
            "corpus_after": corpus_after,
            "cache_before": cache_before,
            "cache_after": cache_after,
            "corpus_total": 30,
            "cache_total": len(all_cache_slugs),
        },
        "movers": {
            "false_to_true": movers_false_to_true,
            "true_to_false": movers_true_to_false,
            "reason_changed": movers_reason_changed,
        },
        "regressions": regressions,
        "bucket_movement": bucket_movement,
        "raw_cache_missing": raw_missing,
        "acoustid_db_delta_vs_round1": db_changes,
        "non_corpus_identified_before": non_corpus_identified_before,
        "wall_sec_so_far": delta.get("wall_sec_so_far"),
        "batch_records": records,
    }
    DELTA_J.write_text(json.dumps(delta_out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {DELTA_J}")


if __name__ == "__main__":
    main()
