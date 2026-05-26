import asyncio
import logging
import sys

import uvicorn

from .server import app


def _configure_logging() -> None:
    """Surface app-level loggers (webui.*) at INFO. Uvicorn's default config
    only formats its own loggers; without this, every `log.info()` from
    chat_actor / chat / etc. is dropped silently because the root logger
    has no handlers."""
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        root.addHandler(h)
    root.setLevel(logging.INFO)
    # Quiet anyio/httpx debug noise even if someone bumps the root to DEBUG.
    for noisy in ("anyio", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()
    import argparse

    parser = argparse.ArgumentParser(prog="python -m webui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--cache-dir", default=None, help="override auto-resolved cache path")
    args = parser.parse_args()

    if args.cache_dir:
        import os
        os.environ["WEBUI_CACHE_DIR"] = args.cache_dir

    # The OriginGuard middleware rejects any request whose Host header isn't
    # a loopback name, so binding past 127.0.0.1 won't actually let strangers
    # in unless the user also disables that check. Make the security model
    # loud anyway — if someone copies `--host 0.0.0.0` off Stack Overflow
    # they'll see this banner and understand the app has no authentication.
    _LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
    if args.host not in _LOOPBACK:
        print(
            f"\n  ⚠  webui is being bound to host={args.host}, which is NOT a loopback\n"
            f"     address. The app has no authentication; OriginGuard middleware\n"
            f"     still rejects non-loopback Host headers, so casual reach should be\n"
            f"     blocked — but this is a deliberate guard rail, not a security model.\n"
            f"     Do NOT expose this app to a public network or shared LAN.\n",
            file=sys.stderr,
        )

    # claude-agent-sdk spawns claude.exe via anyio.open_process, which
    # requires asyncio subprocess support — that's only available on
    # ProactorEventLoop on Windows. With loop="auto" / "asyncio" uvicorn's
    # asyncio_loop_factory(use_subprocess=...) returns SelectorEventLoop
    # whenever use_subprocess is True, which is set whenever --reload or
    # workers>1 is used. Under --reload the *worker* process re-imports
    # webui.server fresh (skipping this file), so a monkey-patch here
    # wouldn't reach it either. Refuse --reload on Windows so the SDK
    # chat doesn't silently break in dev — the user can re-run the
    # process to pick up code changes.
    if sys.platform == "win32":
        if args.reload:
            print(
                "warning: --reload is incompatible with claude-agent-sdk on Windows "
                "(uvicorn forces SelectorEventLoop in reload workers, which can't "
                "spawn asyncio subprocesses). Reload disabled; restart manually to "
                "pick up code changes.",
                file=sys.stderr,
            )
            args.reload = False
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    uvicorn.run("webui.server:app", host=args.host, port=args.port, reload=args.reload, loop="asyncio")


if __name__ == "__main__":
    main()
