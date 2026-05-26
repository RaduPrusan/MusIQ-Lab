"""Extract user prompts and assistant text from a Claude Code session JSONL.
Usage: python _session_extract.py <session-id-or-path> [--vram-only]

Searches for the session in $CLAUDE_PROJECT_DIR (set this to the Claude Code
project directory under ~/.claude/projects/), or defaults to the one matching
this repo's path under the user's home directory.
"""
import json
import os
import sys
import io
from pathlib import Path

# Ensure stdout can emit non-cp1252 chars (★ etc.) on Windows.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _default_project_dir() -> Path:
    """Best-effort guess at ~/.claude/projects/<sanitized-cwd-path>."""
    cwd = Path.cwd().resolve()
    # Claude Code's path-sanitization: replace separators with `-`.
    parts = str(cwd).replace(":", "").replace("\\", "/").lstrip("/").split("/")
    slug = "-".join(parts).replace("--", "-")
    return Path.home() / ".claude" / "projects" / f"F----{slug}"


PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or _default_project_dir())

def find_session(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = PROJECT / f"{arg}.jsonl"
    if candidate.exists():
        return candidate
    matches = list(PROJECT.glob(f"{arg}*.jsonl"))
    if matches:
        return matches[0]
    raise FileNotFoundError(arg)

def extract(path: Path, vram_only: bool = False):
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp", "")[:19]
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                text = "\n".join(parts)
            else:
                continue
            if not text.strip():
                continue
            if vram_only:
                low = text.lower()
                if not any(k in low for k in ("vram", "video memory", "vmemory",
                                              "video card", "memory leek", "memory leak",
                                              "out of memory", "oom", "nvidia-smi",
                                              "subprocess", "_stage_runner")):
                    continue
            preview = text[:600].replace("\n", " ")
            print(f"[{ts}] {role:9s} {preview}")
            print("-" * 100)

if __name__ == "__main__":
    args = sys.argv[1:]
    vram_only = "--vram-only" in args
    args = [a for a in args if not a.startswith("--")]
    if not args:
        print("usage: python _session_extract.py <session-id> [--vram-only]")
        sys.exit(1)
    extract(find_session(args[0]), vram_only=vram_only)
