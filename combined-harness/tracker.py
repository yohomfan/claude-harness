"""
Tracker — Status & History Persistence
=======================================

Writes .harness/status.json (current state) and .harness/history.jsonl
(per-iteration records) so the dashboard can read them.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _harness_dir(project_dir: Path) -> Path:
    d = project_dir / ".harness"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_status(
    project_dir: Path,
    *,
    iteration: int,
    phase: str,
    passing: int,
    total: int,
    model: str,
    start_time: float,
    consecutive_stall: int = 0,
    paused: bool = False,
    exit_reason: Optional[str] = None,
) -> None:
    elapsed = time.monotonic() - start_time
    data = {
        "iteration": iteration,
        "phase": phase,
        "paused": paused,
        "passing": passing,
        "total": total,
        "model": model,
        "start_time_iso": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed),
        "consecutive_stall": consecutive_stall,
        "exit_reason": exit_reason,
    }
    path = _harness_dir(project_dir) / "status.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def append_history(
    project_dir: Path,
    *,
    iteration: int,
    verdict: str,
    passing: int,
    total: int,
    build_seconds: float,
    eval_seconds: float,
    findings_summary: Optional[str] = None,
) -> None:
    record = {
        "iteration": iteration,
        "verdict": verdict,
        "passing": passing,
        "total": total,
        "build_seconds": round(build_seconds, 1),
        "eval_seconds": round(eval_seconds, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "findings_summary": (findings_summary or "")[:200],
    }
    path = _harness_dir(project_dir) / "history.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_status(project_dir: Path) -> Optional[dict]:
    path = project_dir / ".harness" / "status.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_history(project_dir: Path) -> list[dict]:
    path = project_dir / ".harness" / "history.jsonl"
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                records.append(json.loads(line))
    except (json.JSONDecodeError, OSError):
        pass
    return records
