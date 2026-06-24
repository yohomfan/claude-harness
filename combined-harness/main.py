#!/usr/bin/env python3
"""
Combined Autonomous Coding Harness
===================================

Merges the automated Python loop from autonomous-coding with the
independent evaluator and evidence gate from claude-code-config.

Usage:
    python main.py --project-dir ./my_project
    python main.py --project-dir ./my_project --max-iterations 3
    python main.py --project-dir ./my_project --max-runtime 4h
    python main.py --project-dir ./my_project --max-stall 5
"""

import argparse
import asyncio
import signal
from pathlib import Path

from loop import parse_duration, run_loop


DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combined Autonomous Coding Harness — Build + Evaluate + Feedback loop",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("./project"),
        help="Directory for the project (default: ./project)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of build-evaluate iterations (default: unlimited)",
    )
    parser.add_argument(
        "--max-runtime",
        type=str,
        default=None,
        help="Wall-clock time limit, e.g. '4h' / '30m' / '90s' / pure seconds (default: unlimited)",
    )
    parser.add_argument(
        "--max-stall",
        type=int,
        default=None,
        help="Quit after N consecutive NEEDS_WORK verdicts (default: never)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--puppeteer",
        action="store_true",
        default=False,
        help="Enable Puppeteer MCP for browser-based testing (default: off)",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace, project_dir: Path) -> None:
    shutdown = asyncio.Event()

    def _handle_sigterm() -> None:
        if not shutdown.is_set():
            print("\n[SIGTERM] Received. Will exit after current iteration.")
            shutdown.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
    except NotImplementedError:
        # add_signal_handler is not implemented on Windows event loops
        pass

    max_runtime_seconds = parse_duration(args.max_runtime) if args.max_runtime else None

    await run_loop(
        project_dir=project_dir,
        model=args.model,
        max_iterations=args.max_iterations,
        max_runtime_seconds=max_runtime_seconds,
        max_stall=args.max_stall,
        shutdown_event=shutdown,
        enable_puppeteer=args.puppeteer,
    )


def main() -> None:
    args = parse_args()

    project_dir = args.project_dir
    if not project_dir.is_absolute():
        project_dir = Path("generations") / project_dir

    try:
        asyncio.run(_run(args, project_dir))
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. To resume, run the same command again.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        raise


if __name__ == "__main__":
    main()
