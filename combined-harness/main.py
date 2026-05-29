#!/usr/bin/env python3
"""
Combined Autonomous Coding Harness
===================================

Merges the automated Python loop from autonomous-coding with the
independent evaluator and evidence gate from claude-code-config.

Usage:
    python main.py --project-dir ./my_project
    python main.py --project-dir ./my_project --max-iterations 3
"""

import argparse
import asyncio
from pathlib import Path

from loop import run_loop


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
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Claude model to use (default: {DEFAULT_MODEL})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    project_dir = args.project_dir
    if not project_dir.is_absolute():
        project_dir = Path("generations") / project_dir

    try:
        asyncio.run(
            run_loop(
                project_dir=project_dir,
                model=args.model,
                max_iterations=args.max_iterations,
            )
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. To resume, run the same command again.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        raise


if __name__ == "__main__":
    main()
