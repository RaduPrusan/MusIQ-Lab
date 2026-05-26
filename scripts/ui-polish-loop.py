"""
ui-polish-loop.py — autonomous polish loop for the webui.

Per docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md:
  iter:
    1. Implementer subagent (Opus, fresh context) addresses verdict.json issues.
    2. Orchestrator runs `npx playwright test visual-review.spec.js` + merge step.
    3. Reviewer subagent (Opus, fresh context, blind to implementer) updates verdict.
    4. Commit verdict + emit iteration log.
    5. If verdict.passed two iterations in a row -> exit 0.
    6. Cap: MAX_ITER iterations.

Usage:
  python scripts/ui-polish-loop.py [--cap N] [--dry-run] [--start-iter N]
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "docs/superpowers/specs/2026-05-09-ui-polish-themable-tokens-design.md"
VERDICT = REPO / "webui/tests-e2e/visual-review/verdict.json"
PROMPT_IMPL = REPO / "prompts/ui-polish-implementer.md"
PROMPT_REVIEW = REPO / "prompts/ui-polish-reviewer.md"
TESTS_E2E = REPO / "webui/tests-e2e"
ITER_LOG_DIR = REPO / "install-logs"
DEFAULT_MAX_ITER = 8

REVIEW_PROJECTS = [
    "review-classic-dark", "review-midnight",
    "review-studio-light", "review-high-contrast",
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_playwright(iteration: int) -> None:
    log(f"iter {iteration}: running visual-review.spec.js across 4 presets...")
    env = os.environ.copy()
    env["MUSIQ_ITER"] = str(iteration)
    cmd = ["npx", "playwright", "test", "visual-review.spec.js"]
    for proj in REVIEW_PROJECTS:
        cmd.extend(["--project", proj])
    result = subprocess.run(cmd, cwd=TESTS_E2E, env=env)
    log(f"iter {iteration}: playwright exit code {result.returncode}")
    # Now run merge step to combine per-preset verdicts:
    merge_cmd = ["node", "scripts/merge-verdicts.js"]
    merge_env = env.copy()
    merge_result = subprocess.run(merge_cmd, cwd=TESTS_E2E, env=merge_env)
    log(f"iter {iteration}: merge exit code {merge_result.returncode}")


async def run_subagent(role: str, prompt_path: Path, allowed_tools: list[str], iteration: int) -> str:
    """
    Dispatch a fresh Claude subagent. Returns the final stdout summary line.
    Uses claude-agent-sdk ClaudeSDKClient in streaming mode.

    Notes on SDK API (verified against installed version):
    - ClaudeSDKClient is used as async context manager; __aenter__ calls connect().
    - client.query(str) sends the user message over the transport.
    - client.receive_response() yields Message objects until ResultMessage.
    - AssistantMessage.content is a list of ContentBlock (TextBlock, ToolUseBlock, etc.).
    - TextBlock has a .text attribute.
    - ResultMessage has .total_cost_usd (float | None).
    """
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
    )

    system_prompt = prompt_path.read_text(encoding="utf-8")
    user_msg = (
        f"This is iteration {iteration} of the UI polish loop. "
        f"Read the spec at {SPEC.relative_to(REPO).as_posix()} and the latest verdict "
        f"at {VERDICT.relative_to(REPO).as_posix()} (if it exists). Begin."
    )
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=str(REPO),
        allowed_tools=allowed_tools,
        model="claude-opus-4-7",
        permission_mode="acceptEdits",
    )
    log(f"iter {iteration}: dispatching {role} subagent...")
    last_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_msg)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        last_text = block.text
            elif isinstance(msg, ResultMessage):
                cost = getattr(msg, "total_cost_usd", None)
                cost_str = f"${cost:.4f}" if cost is not None else "n/a"
                log(f"iter {iteration}: {role} done; cost {cost_str}")
    return last_text.strip().split("\n")[-1] if last_text else ""


def read_verdict() -> dict:
    if not VERDICT.exists():
        return {"passed": False, "summary": "no verdict yet", "issues": []}
    try:
        return json.loads(VERDICT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"passed": False, "summary": "verdict.json corrupt", "issues": []}


def commit_iteration(iteration: int, summary: str) -> None:
    log_path = ITER_LOG_DIR / f"ui-polish-2026-05-09-iter-{iteration}.md"
    add_paths = [
        "webui/tests-e2e/visual-review/verdict.json",
        "webui/tests-e2e/visual-review/axe.json",
    ]
    if log_path.exists():
        add_paths.append(str(log_path.relative_to(REPO).as_posix()))
    subprocess.run(["git", "add", *add_paths], cwd=REPO, check=False)
    msg = f"polish(webui): iter {iteration} — {summary}"
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"], cwd=REPO, check=False)


def write_iter_log(iteration: int, impl_summary: str, review_summary: str, verdict: dict) -> None:
    ITER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = ITER_LOG_DIR / f"ui-polish-2026-05-09-iter-{iteration}.md"
    blockers = sum(1 for i in verdict.get("issues", []) if i.get("severity") == "blocker")
    log_path.write_text(
        f"# Iteration {iteration}\n\n"
        f"- **Implementer summary:** {impl_summary}\n"
        f"- **Reviewer summary:** {review_summary}\n"
        f"- **Verdict:** passed={verdict.get('passed')} blockers={blockers}\n"
        f"- **Total issues:** {len(verdict.get('issues', []))}\n",
        encoding="utf-8",
    )


async def main_async(cap: int, dry_run: bool, start_iter: int) -> int:
    prev_pass = False
    for iteration in range(start_iter, cap + 1):
        log(f"=== iter {iteration} of {cap} ===")
        if dry_run:
            log("dry-run: skipping subagent dispatch + playwright")
            return 0

        impl_summary = await run_subagent(
            role="implementer",
            prompt_path=PROMPT_IMPL,
            allowed_tools=["Read", "Edit", "Write", "Grep", "Glob", "Bash"],
            iteration=iteration,
        )

        run_playwright(iteration)

        review_summary = await run_subagent(
            role="reviewer",
            prompt_path=PROMPT_REVIEW,
            allowed_tools=["Read", "Write"],   # Write only for verdict.json — the prompt enforces this
            iteration=iteration,
        )

        verdict = read_verdict()
        write_iter_log(iteration, impl_summary, review_summary, verdict)
        commit_iteration(iteration, verdict.get("summary", "(no summary)"))

        if verdict.get("passed"):
            log(f"iter {iteration}: PASSED")
            if prev_pass:
                log(f"iter {iteration}: convergence (passed twice in a row); exiting 0")
                return 0
            prev_pass = True
        else:
            log(f"iter {iteration}: NOT passed; {len(verdict.get('issues', []))} issues remaining")
            prev_pass = False

    log(f"hit cap of {cap} iterations without convergence")
    return 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cap", type=int, default=DEFAULT_MAX_ITER)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--start-iter", type=int, default=1)
    args = p.parse_args()

    if not shutil.which("npx") and not shutil.which("npx.cmd"):
        print("ERROR: npx not on PATH; install Node and rerun.", file=sys.stderr)
        return 2
    if not SPEC.exists():
        print(f"ERROR: spec not found at {SPEC}", file=sys.stderr)
        return 2
    if not PROMPT_IMPL.exists() or not PROMPT_REVIEW.exists():
        print("ERROR: prompt files missing", file=sys.stderr)
        return 2

    return asyncio.run(main_async(cap=args.cap, dry_run=args.dry_run, start_iter=args.start_iter))


if __name__ == "__main__":
    sys.exit(main())
