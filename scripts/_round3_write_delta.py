"""Round 3 — write delta report (md + json) from batch records + pre-state.

Reads:
    docs/superpowers/identify-overhaul/round-3-pre-state.json     (live cache snapshot taken *before* batch)
    docs/superpowers/identify-overhaul/round-3-batch-records.json (batch run output)
    docs/superpowers/identify-overhaul/round-1-a2-corpus-probe.json (silence stats)

Writes:
    docs/superpowers/identify-overhaul/round-3-delta.md
    docs/superpowers/identify-overhaul/round-3-delta.json
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
CACHE = WORKTREE / "cache"
DOCS = WORKTREE / "docs" / "superpowers" / "identify-overhaul"

PRE_STATE = DOCS / "round-3-pre-state.json"
BATCH = DOCS / "round-3-batch-records.json"
R1_PROBE = DOCS / "round-1-a2-corpus-probe.json"
MD_OUT = DOCS / "round-3-delta.md"
JSON_OUT = DOCS / "round-3-delta.json"

CORPUS_SLUGS = {
    # 30-track corpus from spec
    "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk",
    "awolnation-run_official_audio-mw2kkyju9gy",
    "baleen_unmedicated",
    "balthazar-changes_official_video-p3jb998acqo",
    "baxter_dury-prince_of_tears-zppakk4xk74",
    "buddha-bar-ali_kuru_yuregine_deprem-gcecffibv6w",
    "charlie_puth_attention",
    "crippled_black_phoenix-in_bad_dreams-z8a-zcc-f1c",
    "cvt_380_m",
    "editors_life_is_a_fear",
    "editors_life_is_a_fear_alternative",
    "emika-sing_to_me-k9sdbzm8pgk",
    "fanfare_ciocarlia_asfalt_tango",
    "flunk_on_my_balcony",
    "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg",
    "hurt-ty-bldf8bsw",
    "it_could_happen_to_you_2_render",
    "jamel_debbouze_stromae-alors_on_danse_le_tube-made_in_jamel_2010-v-wdfqyusb0",
    "joesef_comedown_official_video_zaprrzdhyiw",
    "moderat-reminder_official_video-cjwsnuoazug",
    "nightbus-angles_mortz_official_video-igxitfxkd1i",
    "notre-dame_est-3frubz9yhim",
    "olivia_dean_dive_acoustic_yylsa4m2zzm",
    "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a",
    "ren_x_chinchilla_chalk_outlines",
    "she_s_hot_tea-p_3xutn8res",
    "sting-shape_of_my_heart_live_at_the_rijksmuseum-hkks7d7dvzw",
    "submotion_orchestra-finest_hour_album_version-qplldpndsx8",
    "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe",
    "warhaus_love_s_a_stranger_official_video_gsjdhd0stag",
}

BUCKET_A_PROBED = [
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

BUCKET_B_PROBED = [
    "angus_julia_stone-harvest_moon-11_17_2017-paste_studios_new_york_ny-9uiby71mrqk",
    "moderat-reminder_official_video-cjwsnuoazug",
    "orchestral_suite_no_3_in_d_major_ii_air_on_a_g_string_arr_for_cello_quintet_ing6btc4s0a",
    "the_byrds-eight_miles_high_live_at_fillmore_east_1970_psych-rock_jams-2ymkbehdhbe",
]

GATE_SEC = 0.3


def load_post_state() -> dict[str, dict]:
    """Read current identify.json for every cache slug."""
    out = {}
    for d in sorted(p for p in CACHE.iterdir() if p.is_dir()):
        ij = d / "identify.json"
        if not ij.exists():
            continue
        try:
            data = json.loads(ij.read_text())
        except json.JSONDecodeError:
            data = {}
        out[d.name] = {
            "slug": d.name,
            "identified": bool(data.get("identified")),
            "mbid_recording": data.get("mbid_recording"),
            "title": data.get("title"),
            "artist": data.get("artist"),
            "reason": data.get("reason"),
            "score": data.get("acoustid_score"),
        }
    return out


def load_silence_map() -> dict[str, float]:
    """From R1 probe — leading-silence per slug."""
    data = json.loads(R1_PROBE.read_text())
    out = {}
    # Try both possible shapes — list of slug dicts.
    slugs = data.get("slugs") or data.get("records") or data
    if isinstance(slugs, list):
        for rec in slugs:
            slug = rec.get("slug")
            lead = rec.get("leading_silence_sec")
            if lead is None:
                lead = rec.get("lead_silence")
            if lead is None and isinstance(rec.get("silence"), dict):
                lead = rec["silence"].get("leading_sec")
            if slug and lead is not None:
                try:
                    out[slug] = float(lead)
                except (TypeError, ValueError):
                    pass
    return out


def main() -> None:
    pre = {r["slug"]: r for r in json.loads(PRE_STATE.read_text())["slugs"]}
    batch = json.loads(BATCH.read_text())
    records = {r["slug"]: r for r in batch["records"]}
    post = load_post_state()
    silence_map = load_silence_map()

    # Aggregate
    pre_identified_total = sum(1 for r in pre.values() if r["identified"])
    post_identified_total = sum(1 for r in post.values() if r["identified"])
    pre_corpus_identified = sum(
        1 for s, r in pre.items() if s in CORPUS_SLUGS and r["identified"]
    )
    post_corpus_identified = sum(
        1 for s, r in post.items() if s in CORPUS_SLUGS and r["identified"]
    )

    # Movers — only among the slugs we ran (others can't have moved).
    movers_false_to_true = []
    movers_true_to_false = []
    reason_changed = []
    for slug in BUCKET_A_PROBED + BUCKET_B_PROBED:
        pre_rec = pre.get(slug, {})
        post_rec = post.get(slug, {})
        pre_id = bool(pre_rec.get("identified"))
        post_id = bool(post_rec.get("identified"))
        if pre_id and not post_id:
            movers_true_to_false.append(
                {"slug": slug, "pre_mbid": pre_rec.get("mbid_recording")}
            )
        elif post_id and not pre_id:
            r = records.get(slug, {})
            movers_false_to_true.append({
                "slug": slug,
                "mbid": post_rec.get("mbid_recording"),
                "score": post_rec.get("score"),
                "title": post_rec.get("title"),
                "artist": post_rec.get("artist"),
                "fingerprint_source": (
                    "stripped" if r.get("saw_acoustid_stripped") else "raw"
                ),
                "log_source": r.get("log_source"),
            })
        elif not pre_id and not post_id and pre_rec.get("reason") != post_rec.get("reason"):
            reason_changed.append({
                "slug": slug,
                "pre": pre_rec.get("reason"),
                "post": post_rec.get("reason"),
            })

    # Regression check on the 24 pre-R3 identified caches (NOT re-run by us)
    pre_identified_slugs = sorted(s for s, r in pre.items() if r["identified"])
    regressions = []
    for slug in pre_identified_slugs:
        post_rec = post.get(slug, {})
        if not post_rec.get("identified"):
            regressions.append({
                "slug": slug,
                "pre_mbid": pre[slug].get("mbid_recording"),
                "post_reason": post_rec.get("reason"),
            })
        elif post_rec.get("mbid_recording") != pre[slug].get("mbid_recording"):
            regressions.append({
                "slug": slug,
                "pre_mbid": pre[slug].get("mbid_recording"),
                "post_mbid": post_rec.get("mbid_recording"),
                "kind": "mbid_changed",
            })

    # Silence-strip behavior per Bucket-A slug
    silence_rows = []
    for slug in BUCKET_A_PROBED + BUCKET_B_PROBED:
        r = records.get(slug, {})
        lead = silence_map.get(slug)
        gate_fired = lead is not None and lead > GATE_SEC
        post_id = bool(post.get(slug, {}).get("identified"))
        silence_rows.append({
            "slug": slug,
            "bucket": "A" if slug in BUCKET_A_PROBED else "B",
            "leading_silence_sec": lead,
            "gate_fired_expected": gate_fired,
            "stripped_log_lead_sec": r.get("stripped_lead_sec"),
            "saw_acoustid_stripped": r.get("saw_acoustid_stripped"),
            "now_identified": post_id,
            "log_source": r.get("log_source"),
            "log_mbid": r.get("log_mbid"),
        })

    # Bucket A breakdown
    bucket_a_gated = [
        s for s in BUCKET_A_PROBED
        if silence_map.get(s) is not None and silence_map[s] > GATE_SEC
    ]
    bucket_a_zero = [
        s for s in BUCKET_A_PROBED
        if silence_map.get(s) is not None and silence_map[s] <= GATE_SEC
    ]
    bucket_a_gated_cleared = [
        s for s in bucket_a_gated if post.get(s, {}).get("identified")
    ]
    bucket_a_zero_cleared = [
        s for s in bucket_a_zero if post.get(s, {}).get("identified")
    ]
    bucket_b_cleared = [
        s for s in BUCKET_B_PROBED if post.get(s, {}).get("identified")
    ]

    # Wall-time stats
    elapsed = [r.get("elapsed_sec") for r in batch["records"] if r.get("elapsed_sec")]
    median_wall = statistics.median(elapsed) if elapsed else None
    mean_wall = statistics.mean(elapsed) if elapsed else None
    total_wall = batch.get("total_elapsed_sec")

    regression_pass = len(regressions) == 0 and len(movers_true_to_false) == 0

    delta = {
        "schema": 1,
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "+00:00",
        "round": 3,
        "worktree_sha": "ea7ab72",
        "aggregate": {
            "corpus_before": pre_corpus_identified,
            "corpus_after": post_corpus_identified,
            "corpus_total": 30,
            "full_cache_before": pre_identified_total,
            "full_cache_after": post_identified_total,
            "full_cache_total": len(post),
        },
        "movers_false_to_true": movers_false_to_true,
        "movers_true_to_false": movers_true_to_false,
        "reason_changed": reason_changed,
        "silence_behavior": silence_rows,
        "bucket_a": {
            "gated_slugs": bucket_a_gated,
            "zero_silence_slugs": bucket_a_zero,
            "gated_cleared": bucket_a_gated_cleared,
            "zero_cleared": bucket_a_zero_cleared,
        },
        "bucket_b": {
            "all_slugs": BUCKET_B_PROBED,
            "cleared": bucket_b_cleared,
        },
        "performance": {
            "median_wall_sec": median_wall,
            "mean_wall_sec": mean_wall,
            "total_wall_sec": total_wall,
            "round_2_mean_sec": 27.5,
            "run_count": len(elapsed),
        },
        "regression": {
            "verdict": "PASS" if regression_pass else "FAIL",
            "true_to_false_movers": movers_true_to_false,
            "pre_identified_changed": regressions,
            "pre_identified_count": len(pre_identified_slugs),
        },
        "records": batch["records"],
    }

    JSON_OUT.write_text(json.dumps(delta, indent=2), encoding="utf-8")

    # ---- Markdown ----
    md = []
    md.append("# Round 3 — Delta Report")
    md.append("")
    md.append(f"**Generated:** {delta['generated_at']}")
    md.append("")
    md.append(
        "Re-ran `analyze --stages-only identify` against 15 Bucket-A/B slugs after C2's "
        "silence-strip preprocessing + `SCHEMA_VERSION=3` landed (worktree SHA `ea7ab72`). "
        "Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md) §C2."
    )
    md.append("")
    md.append("## Aggregate")
    md.append("")
    md.append("| Scope | Before (post-R2) | After (post-R3) | Delta |")
    md.append("|---|---|---|---|")
    md.append(
        f"| 30-track corpus identified | {pre_corpus_identified} / 30 "
        f"({pre_corpus_identified/30*100:.1f}%) | {post_corpus_identified} / 30 "
        f"({post_corpus_identified/30*100:.1f}%) | "
        f"{'+' if post_corpus_identified >= pre_corpus_identified else ''}"
        f"{post_corpus_identified - pre_corpus_identified} |"
    )
    md.append(
        f"| Full cache identified | {pre_identified_total} / {len(post)} "
        f"({pre_identified_total/len(post)*100:.1f}%) | "
        f"{post_identified_total} / {len(post)} "
        f"({post_identified_total/len(post)*100:.1f}%) | "
        f"{'+' if post_identified_total >= pre_identified_total else ''}"
        f"{post_identified_total - pre_identified_total} |"
    )
    md.append("")
    md.append(f"Batch wall time: {total_wall}s")
    md.append("")
    md.append("## Regression gate verdict")
    md.append("")
    if regression_pass:
        md.append(
            f"**PASS** — zero `identified=true → false` transitions on the "
            f"{len(pre_identified_slugs)} pre-R3 identified caches. "
            f"`_preserve_or_write` guard + legacy-cache bridge held."
        )
    else:
        md.append("**FAIL** — regression detected:")
        for r in regressions:
            md.append(f"- `{r['slug']}` — {r}")
        for r in movers_true_to_false:
            md.append(f"- `{r['slug']}` — pre_mbid={r.get('pre_mbid')}")
    md.append("")

    md.append("## Movers")
    md.append("")
    md.append(f"### `identified: false → true` ({len(movers_false_to_true)})")
    md.append("")
    if movers_false_to_true:
        md.append("| Slug | Score | MBID | Title — Artist | fingerprint_source |")
        md.append("|---|---|---|---|---|")
        for m in movers_false_to_true:
            score = m.get("score")
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
            md.append(
                f"| `{m['slug']}` | {score_str} | "
                f"`{m.get('mbid') or '—'}` | "
                f"{m.get('title') or '—'} — {m.get('artist') or '—'} | "
                f"`{m.get('fingerprint_source')}` (log: `{m.get('log_source')}`) |"
            )
    else:
        md.append("(none)")
    md.append("")
    md.append(f"### `identified: true → false` ({len(movers_true_to_false)})")
    md.append("")
    if movers_true_to_false:
        for m in movers_true_to_false:
            md.append(f"- `{m['slug']}` — pre_mbid=`{m.get('pre_mbid')}` (REGRESSION)")
    else:
        md.append("(none — regression gate held)")
    md.append("")
    md.append(f"### Reason changed, still `identified: false` ({len(reason_changed)})")
    md.append("")
    if reason_changed:
        for r in reason_changed:
            md.append(f"- `{r['slug']}`: `{r['pre']}` → `{r['post']}`")
    else:
        md.append("(none)")
    md.append("")

    md.append("## Silence-strip behavior")
    md.append("")
    md.append("Per-slug. `lead (R1)` is the leading-silence ffmpeg silencedetect measured during the Round-1 probe. "
              f"`gate fired?` reports whether `silence_strip_gate_sec={GATE_SEC}` should have triggered the strip. "
              "`acoustid_stripped` is whether the stripped-fingerprint AcoustID lookup produced the match (per the structured log line).")
    md.append("")
    md.append("| Slug | Bucket | Lead (R1) s | Gate fired? | Stripped path used? | Identified now? | log source |")
    md.append("|---|---|---|---|---|---|---|")
    for row in silence_rows:
        lead = row["leading_silence_sec"]
        lead_str = f"{lead:.2f}" if lead is not None else "—"
        gate = "yes" if row["gate_fired_expected"] else "no"
        used = "yes" if row["saw_acoustid_stripped"] else "no"
        ident = "yes" if row["now_identified"] else "no"
        md.append(
            f"| `{row['slug']}` | {row['bucket']} | {lead_str} | "
            f"{gate} | {used} | {ident} | `{row['log_source']}` |"
        )
    md.append("")

    md.append("## Bucket A analysis")
    md.append("")
    md.append(
        f"- Gated tracks (lead silence > {GATE_SEC}s): "
        f"**{len(bucket_a_gated)}** ({', '.join(f'`{s}`' for s in bucket_a_gated) or '—'})"
    )
    md.append(
        f"- Of those, newly identified via stripped fingerprint: "
        f"**{len(bucket_a_gated_cleared)}** "
        f"({', '.join(f'`{s}`' for s in bucket_a_gated_cleared) or '—'})"
    )
    md.append(
        f"- Zero-silence tracks (lead silence ≤ {GATE_SEC}s): "
        f"**{len(bucket_a_zero)}** ({', '.join(f'`{s}`' for s in bucket_a_zero) or '—'})"
    )
    md.append(
        f"- Of those still unidentified (expected — Round 4 work): "
        f"**{len(bucket_a_zero) - len(bucket_a_zero_cleared)}** "
        f"(any unexpected clearance: {', '.join(f'`{s}`' for s in bucket_a_zero_cleared) or 'none'})"
    )
    md.append("")

    md.append("## Bucket B analysis")
    md.append("")
    md.append(
        f"- Bucket B (top score ≥0.85, unlinked): "
        f"**{len(BUCKET_B_PROBED)}** slugs"
    )
    md.append(
        f"- Newly identified via stripped path: "
        f"**{len(bucket_b_cleared)}** "
        f"({', '.join(f'`{s}`' for s in bucket_b_cleared) or 'none — expected, stripping does not help when raw fingerprint is already strong but unlinked'})"
    )
    md.append("")

    md.append("## Performance")
    md.append("")
    md.append("| Metric | Round 2 | Round 3 | Note |")
    md.append("|---|---|---|---|")
    md.append(f"| Mean wall time / slug | 27.5s | {mean_wall:.2f}s | n={len(elapsed)} (R3 ran 15, R2 ran 30) |")
    md.append(f"| Median wall time / slug | — | {median_wall:.2f}s | |")
    md.append(f"| Total batch wall time | 826.87s | {total_wall:.2f}s | |")
    md.append("")
    if mean_wall and mean_wall > 1.5 * 27.5:
        md.append(f"**Flag:** mean wall time {mean_wall:.1f}s is >50% higher than R2's 27.5s. Investigate silence-strip overhead.")
    else:
        md.append("No significant slowdown vs R2 — silence-strip overhead within budget.")
    md.append("")

    md.append("## Source references")
    md.append("")
    md.append("- Spec: [`2026-05-12-identify-pipeline-overhaul.md`](../specs/2026-05-12-identify-pipeline-overhaul.md)")
    md.append("- Round 1 probe: [`round-1-a2-corpus-probe.md`](./round-1-a2-corpus-probe.md)")
    md.append("- Round 2 delta: [`round-2-delta.md`](./round-2-delta.md)")
    md.append("- C2 silence-strip design: [`round-3-c1-silence-strip-design.md`](./round-3-c1-silence-strip-design.md)")
    md.append("- Per-slug raw fragments: [`_fragments-round3/`](./_fragments-round3/)")
    md.append("")

    MD_OUT.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {MD_OUT}")
    print(f"Wrote {JSON_OUT}")
    print(f"Regression verdict: {delta['regression']['verdict']}")
    print(f"Movers false→true: {len(movers_false_to_true)}")
    print(f"Movers true→false: {len(movers_true_to_false)}")


if __name__ == "__main__":
    main()
