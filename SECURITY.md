# Security Policy

MusIQ-Lab is a local, single-user desktop web app. It is not designed to be
exposed to the public internet or a shared LAN.

## Supported Use

- Run the web UI bound to `127.0.0.1` or `localhost`.
- Keep API keys in a local `.env` file. Do not commit `.env` or generated
  cache artifacts.
- Treat `cache/` as private user data: it can contain local media paths,
  downloaded audio, lyrics, chat transcripts, and analysis output.

## Reporting Security Issues

Use GitHub private vulnerability reporting on the repository if it is enabled.
If it is not, report issues privately to the maintainer through the repository
owner — do not open a public issue for a security problem.

Please include:

- affected commit or release,
- a short reproduction path,
- whether the issue requires non-loopback network access,
- whether secrets, local files, or arbitrary command execution are involved.

## Known Non-Goals

- No multi-user authentication or authorization.
- No public deployment hardening.
- No server-side sandbox for arbitrary media files beyond upload size/type
  checks and path validation.

## Known Dependency Constraints

The WSL analysis environment intentionally stays on the Torch 2.7/cu126 lane
because `deezer/skey` currently constrains that dependency family. The public
lock files pin the newest 2.7.x patch version used by this project, but OSV
still reports PyTorch advisories whose fixes require Torch 2.8/2.9 or have no
fixed 2.7 release. Until the MIR stack can move off this lane, only run trusted
model checkpoints and keep the app loopback-only.

If you need a public service, put this code behind a separate authenticated
application boundary and re-audit the file, subprocess, and model-execution
surfaces first.
