"""
Progress Tracking Utilities
===========================

Reads feature_list.json and displays pass/fail statistics.
"""

import json
from pathlib import Path


def count_passing_tests(project_dir: Path) -> tuple[int, int]:
    """
    Count passing and total tests in feature_list.json.

    Returns:
        (passing_count, total_count)
    """
    tests_file = project_dir / "feature_list.json"
    if not tests_file.exists():
        return 0, 0

    try:
        content = tests_file.read_text(encoding="utf-8")
        if not content.strip():
            return 0, 0
        tests = json.loads(content)
        if not isinstance(tests, list):
            return 0, 0
        total = len(tests)
        passing = sum(1 for t in tests if t.get("passes", False))
        return passing, total
    except (json.JSONDecodeError, IOError, OSError):
        return 0, 0


def print_session_header(session_num: int, is_initializer: bool, phase: str = "BUILD") -> None:
    """Print a formatted header for the session."""
    if is_initializer:
        label = "INITIALIZER"
    else:
        label = f"ITERATION {session_num} — {phase}"

    print("\n" + "=" * 70)
    print(f"  {label}")
    print("=" * 70 + "\n")


def print_progress_summary(project_dir: Path) -> None:
    """Print a summary of current progress."""
    passing, total = count_passing_tests(project_dir)
    if total > 0:
        pct = (passing / total) * 100
        bar_len = 30
        filled = int(bar_len * passing / total)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\n  Progress: [{bar}] {passing}/{total} ({pct:.1f}%)")
    else:
        print("\n  Progress: feature_list.json not yet created")
