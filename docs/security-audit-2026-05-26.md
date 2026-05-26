# Security Audit - 2026-05-26

Scope: current repository working tree, dependency manifests, local web UI
request surface, public-release hygiene, and tracked generated artifacts.

## Executive Summary

MusIQ-Lab is ready to publish as a local, single-user project, with one
important disclosure: the WSL analysis stack remains constrained to the Torch
2.7/cu126 family by the current MIR dependency set. The web UI dependency set
is clean after updates, no real secrets were found in the current tracked tree,
and the local-only web surface now has stricter Host/Origin and JSON-body
handling.

Do not present this as an internet-hosted service. The supported security model
is loopback-only use with trusted local media, trusted model checkpoints, and
private `cache/` and `.env` directories.

## Changes Made

- Added `SECURITY.md` with the local-only threat model, reporting guidance, and
  residual Torch dependency disclosure.
- Added `.github/dependabot.yml` for pip and npm dependency monitoring.
- Hardened `webui/webui/_security.py` so malformed Host and Origin values are
  rejected instead of loosely split.
- Added JSON object parsing helper in `webui/webui/server.py`; malformed JSON
  now returns HTTP 400 on rename, YouTube analyze, lyrics, and chat routes.
- Updated vulnerable web UI dependencies:
  - avoided `fastapi==0.136.3` (`MAL-2026-4750`),
  - updated Starlette above `1.0.0` (`PYSEC-2026-161`),
  - updated `idna` above `3.13` (`GHSA-65pc-fj4g-8rjx`),
  - updated pytest to `9.0.3` (`GHSA-6w46-j5rx-g56g`),
  - updated `jsdom` to `^29.1.1`.
- Raised the WSL Torch lane from `2.7.0` to `2.7.1` to clear 2.7.0-only OSV
  advisories while staying within the `skey`-compatible 2.7 family.
- Removed maintainer-specific email and machine paths from the current tracked
  tree; runnable helper scripts now resolve the project root relative to their
  own location.

## Verification Run

- `python -m pytest webui/tests/test_server.py -q`: 78 passed.
- `python -m compileall webui\webui scripts install-logs .research`: passed.
- `npm audit --json` in `webui/`: 0 vulnerabilities.
- `npm audit --json` in `webui/tests-e2e/`: 0 vulnerabilities.
- `uvx pip-audit -r webui/requirements.lock --no-deps --format json`: 0 known vulnerabilities.
- `uvx pip-audit -r requirements-dev.txt --format json`: 0 known vulnerabilities.
- `uvx bandit -r analyze webui/webui scripts -lll -f json`: 0 high-severity findings.
- Secret/path sweeps: no real API keys, private keys, committed `.env`, tracked
  cache, tracked model weights, or original maintainer email/path strings found
  in the current tracked tree.

## Residual Findings

### Torch 2.7.x advisories

`pip-audit` against the Linux analysis stack still reports PyTorch advisories
for Torch 2.7.x. The highest-impact practical mitigation would be a future
dependency-lane migration to Torch 2.9+ or a replacement/fork of the dependency
that keeps this project on Torch 2.7. Until then, keep the analysis stack local
and do not load untrusted model checkpoints.

Reference advisories checked during this audit:

- FastAPI malicious-package advisory: <https://osv.dev/vulnerability/MAL-2026-4750>
- Starlette Host-header advisory: <https://osv.dev/vulnerability/PYSEC-2026-161>
- pytest tmpdir advisory: <https://osv.dev/vulnerability/GHSA-6w46-j5rx-g56g>
- idna DoS advisory: <https://osv.dev/vulnerability/GHSA-65pc-fj4g-8rjx>
- PyTorch residual advisory example: <https://osv.dev/vulnerability/GHSA-887c-mr87-cxwp>

### Git History Hygiene

The current tree has been scrubbed, but the existing Git history still contains
personal paths and email references in older commits. Before making the GitHub
repository public, publish from a fresh/squashed history or rewrite history and
force-push the sanitized repository.

### Medium Static-Analysis Findings

Bandit medium findings remain in diagnostic scripts:

- hardcoded temporary paths in Charlie Puth one-off decoder probes,
- `urllib.request.urlopen` in AcoustID probe scripts with project-constructed
  HTTPS URLs.

These are not app request paths and are acceptable for public source, but they
should not be promoted to service endpoints without replacing them with managed
temporary files and stricter URL validation.

## Public Release Checklist

- Publish sanitized working tree only.
- Prefer a fresh public repository or squashed initial commit.
- Keep GitHub secret scanning and Dependabot enabled.
- Do not commit `.env`, `cache/`, model weights, or real MP3 corpora.
- Keep the README/SECURITY wording explicit: local app, loopback-only, trusted
  model/media inputs.
