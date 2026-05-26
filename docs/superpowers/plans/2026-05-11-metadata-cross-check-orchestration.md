# Music Metadata + Cross-Check Integration — Orchestration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute the three sub-plans referenced below, in the order specified. This document is the orchestrator's map — the work itself lives in the per-subsystem plan files.

**Goal:** Land three independent integrations that fill the gaps left by Spotify's 2024 audio-features lockdown and the YT-derived metadata's poor signal: AcoustID/MusicBrainz for canonical identity, Last.fm for crowd tags and similar artists, and local Essentia for a true MIR second opinion on tempo / key / loudness / mood.

**Architecture:** Each integration writes a new JSON artifact into the existing `cache/<slug>/` bundle. AcoustID + Essentia plug into the `analyze/` pipeline as new stages with the standard `cached / load / run` interface, soft-failing identically to the existing optional stages (`drums`, `beats_xcheck`). Last.fm runs webui-side and is keyed off the MBID that the AcoustID stage produces. All three are individually feature-flagged so partial deployments work.

**Tech Stack:** Python 3.11 (WSL `.venv`) for `analyze/` additions; `httpx` for HTTP; `fpcalc` (Chromaprint CLI binary, vendored); `essentia` Python package (≥2.1b6) with MTG-hosted SVM models; FastAPI + plain JS for webui; pytest for unit tests; existing playwright tests-e2e harness for UI checks.

**Dependency graph between plans:**

```
Plan A (AcoustID + MusicBrainz)  ──→  Plan B (Last.fm)
                                  └─→  webui sidebar canonical-metadata card

Plan C (Essentia second opinion)  ──→  webui sidebar acoustic-profile card
                                  └─→  analyze modal cross-check row
```

Plan B reads the `mbid_*` fields written by Plan A, so **Plan A must ship first.** Plan C is independent and can run in parallel — but to keep subagent dispatch sequential and reviews clean, the recommended execution order is A → B → C.

---

## The three sub-plans

| Order | Plan | File | Tasks | Subagent model |
|---|---|---|---:|---|
| 1 | AcoustID + MusicBrainz | [`2026-05-11-acoustid-musicbrainz.md`](2026-05-11-acoustid-musicbrainz.md) | 11 | sonnet (HTTP + stage); haiku for vendoring + flag wiring |
| 2 | Last.fm tags + similar | [`2026-05-11-lastfm-tags.md`](2026-05-11-lastfm-tags.md) | 7 | haiku (mostly mechanical) |
| 3 | Essentia second opinion | [`2026-05-11-essentia-second-opinion.md`](2026-05-11-essentia-second-opinion.md) | 10 | sonnet (install + extraction); opus for the cross-check derivation design |

Each plan is self-contained: it can be executed end-to-end without touching the other two. After Plan A lands, Plan B becomes useful. After Plan C lands, the analyze modal grows a new row. After all three land, the Track sidebar has three new subsections (canonical metadata, acoustic profile, tags + similar).

## Decisions locked in

These were left open at the end of the design conversation. Defaults are now committed; revisit only if a plan task surfaces a hard blocker.

- **AcoustID runs in the `analyze/` pipeline** (WSL-side), not webui-side. Same dispatch model as `drums` / `beats_xcheck` — registered in `_STAGE_EXECUTION_ORDER` + `STAGE_DEPS` in `analyze/pipeline.py`, soft-fails to `{"identified": false}` if the API is unreachable or the score is below threshold.
- **API keys live in `.env`** at the project root (`<PROJECT_PATH>/.env`), loaded via a new tiny `analyze/keys.py` helper. `.env` itself is already gitignored under the general `.env*` glob — verify before first commit if missing, add explicit rule.
- **Essentia installs into the WSL `.venv`** that the rest of the analyze stack already uses. Windows-side install is not pursued. SVM models download as a one-shot script (`scripts/install-essentia-models.sh`) into `analyze/vendor/essentia-models/` (gitignored, same pattern as LarsNet weights).
- **AcoustID match threshold defaults to `0.85`**, overridable via `ACOUSTID_MIN_SCORE` env var. Below threshold → `identified: false` + warning. Subjects with weak fingerprints (live recordings, jazz with intros) won't poison the cache with wrong identities.
- **Last.fm cache TTL defaults to 7 days**, overridable via `LASTFM_TTL_DAYS`. Tags drift slowly; refresh is cheap when stale.
- **All three integrations are opt-out via CLI flags / env vars**, not opt-in. The pipeline runs them by default; `--no-identify`, `--no-essentia`, and `LASTFM_DISABLED=1` exist for fully-offline reruns.

## Subagent dispatch protocol

Following `superpowers:subagent-driven-development`:

1. **Pre-flight (this session, before dispatching):**
   - Read each plan file once; extract all tasks with full text + context into TodoWrite.
   - Verify .env has `ACOUSTID_API_KEY` and `LASTFM_API_KEY` set (Plans A and B will fail loudly without them — *not* a soft fail, since the user explicitly opted into these integrations). If missing, surface to the user and pause.
   - Confirm WSL `.venv` is reachable and the existing analyze tests pass on `main`: `wsl -d Ubuntu-24.04 -- bash -c 'cd "<PROJECT_WSL_PATH>" && source .venv/bin/activate && pytest tests/unit -q'`. This is the baseline against which review subagents compare.

2. **Per task:**
   - Dispatch fresh implementer subagent with `./implementer-prompt.md` template + full task text + the relevant plan file's "Architecture" section as context. Subagent must not read the plan file itself; it gets the task text directly.
   - Wait for implementer status. Handle DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED per the skill.
   - Dispatch spec-compliance reviewer subagent with `./spec-reviewer-prompt.md`. Re-loop implementer on issues.
   - Dispatch code-quality reviewer subagent with `./code-quality-reviewer-prompt.md`. Re-loop implementer on issues.
   - Mark task complete in TodoWrite. Move to next task. Do not check in with the user between tasks unless BLOCKED.

3. **Per plan completion:**
   - Run the full pytest suite (`pytest tests/ -q`) — no new failures.
   - Run the webui pytest suite (`cd webui && .venv/Scripts/python -m pytest -q`) — no new failures.
   - For Plans A and C, run a smoke analyze against the Gorillaz fixture (`cache/gorillaz_silent_running/`): `python -m analyze tests/mp3/silent-running.mp3 --force` and verify the new artifact exists.
   - Commit with prefix matching the plan: `feat(identify):`, `feat(lastfm):`, `feat(essentia):`.

4. **Post-orchestration:**
   - Dispatch final code-reviewer subagent across all three plans' diffs.
   - Use `superpowers:finishing-a-development-branch` to decide on commit strategy (probably squash into three feature commits + push to main, given the user's "commit straight to main" workflow per memory).

## Non-goals (explicitly out of scope)

These showed up in the design conversation but are excluded from this orchestration. They become candidates for follow-up work *after* this lands.

- **Discogs / TheAudioDB / WhoSampled / Genius integrations.** The three chosen integrations cover the identified gaps; adding more before validating these adds complexity without obvious payoff.
- **Essentia TensorFlow embeddings (VGGish / MusiCNN / Discogs-EffNet) for similarity search.** Mentioned as a possibility; deferred. The SVM-based high-level descriptors give the cross-check value; embeddings are a separate "find similar tracks in cache" feature.
- **Migrating the existing slug heuristics in `tracks.py`** out of the regex world. AcoustID will supersede the regex for any identifiable track, but the regex stays as fallback for unidentified ones. Don't rip it out.
- **Spotify Web API integration.** The earlier design conversation considered Spotify as a "library → study queue" source. That's a separate workflow (download trigger) rather than a metadata cross-check, and belongs in its own plan if pursued.

## Failure-mode catalog (what each plan must handle gracefully)

Each per-plan task list includes specific test cases for these, but here's the catalog so reviewers can spot omissions:

| Failure | Pipeline behavior | UI behavior |
|---|---|---|
| AcoustID API unreachable | Soft-fail stage; `summary.json` gets `identify: {identified: false, reason: "..."}` | Sidebar shows raw slug-derived title |
| Chromaprint `fpcalc` binary missing | Soft-fail stage; warning surfaced in `summary.provenance.warnings` | Same as above |
| AcoustID score below threshold | Soft-fail; reason includes the actual score | Same as above |
| MusicBrainz 404 (unmapped fingerprint) | Soft-fail; AcoustID match retained but no canonical metadata | Sidebar shows AcoustID-known title (limited) |
| Last.fm API key missing | Endpoint returns `{"available": false, "reason": "no api key"}` | Tags / similar section hidden |
| Track has no MBID (Plan A failed or skipped) | Last.fm endpoint returns 404 immediately | Tags / similar section hidden |
| Essentia not installed | Soft-fail stage; warning logged | Acoustic-profile section hidden |
| Essentia disagrees with analyze on tempo (delta > 1 BPM) or key | Cross-check JSON records `ok: false` per field; not a fatal | Modal stats panel shows yellow warning icon next to that field |

---

## Execution decision

This document is the orchestration map. The implementer plans (A / B / C) are the actual TDD task lists.

**Recommended path:** Subagent-Driven Development, sequence A → B → C, fresh subagent per task with the two-stage review protocol above. Once approved I'll proceed by reading the three plan files into memory, building the TodoWrite list, and dispatching the first implementer subagent for Plan A Task 1.
