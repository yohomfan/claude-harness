"""
Core Loop: Build → Evaluate → Feedback
=======================================

Orchestrates the builder and evaluator agents in a quality loop.
Each iteration:
  1. BUILD  — fresh builder session implements one feature
  2. COMMIT — checkpoint changes to git
  3. EVAL   — fresh evaluator reviews the work
  4. FEED   — NEEDS_WORK findings injected into next builder prompt
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from claude_code_sdk import ClaudeSDKClient

from builder import create_builder_client
from evaluator import create_evaluator_client, parse_verdict
from progress import print_session_header, print_progress_summary, count_passing_tests
from prompts import get_initializer_prompt, get_coding_prompt, get_evaluator_prompt, copy_spec_to_project


AUTO_CONTINUE_DELAY = 3


async def run_agent_session(
    client: ClaudeSDKClient,
    message: str,
    label: str = "Agent",
) -> tuple[str, str]:
    """
    Run a single agent session, streaming output.

    Returns:
        (status, response_text) where status is "continue" or "error".
    """
    print(f"[{label}] Sending prompt...\n")

    try:
        await client.query(message)

        response_text = ""
        async for msg in client.receive_response():
            msg_type = type(msg).__name__

            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__
                    if block_type == "TextBlock" and hasattr(block, "text"):
                        response_text += block.text
                        print(block.text, end="", flush=True)
                    elif block_type == "ToolUseBlock" and hasattr(block, "name"):
                        print(f"\n  [{label} Tool: {block.name}]", flush=True)

            elif msg_type == "UserMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    if type(block).__name__ == "ToolResultBlock":
                        is_error = getattr(block, "is_error", False)
                        content = str(getattr(block, "content", ""))
                        if "blocked" in content.lower():
                            print(f"  [BLOCKED] {content[:200]}", flush=True)
                        elif is_error:
                            print(f"  [Error] {content[:300]}", flush=True)

        print("\n" + "-" * 70)
        return "continue", response_text

    except Exception as e:
        print(f"\n[{label}] Error: {e}")
        return "error", str(e)


async def commit_checkpoint(project_dir: Path) -> None:
    """Commit tracked changes as a session checkpoint (equivalent to commit-on-stop.sh)."""
    # Check if git repo exists
    result = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "--git-dir",
        cwd=str(project_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await result.wait()
    if result.returncode != 0:
        return  # Not a git repo

    # Check for changes
    diff = await asyncio.create_subprocess_exec(
        "git", "diff", "--quiet",
        cwd=str(project_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await diff.wait()

    cached = await asyncio.create_subprocess_exec(
        "git", "diff", "--cached", "--quiet",
        cwd=str(project_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await cached.wait()

    if diff.returncode != 0 or cached.returncode != 0:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-am", f"session checkpoint: {timestamp}",
            cwd=str(project_dir),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode == 0:
            print("[Checkpoint] Changes committed to git")


async def run_loop(
    project_dir: Path,
    model: str,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Main build-evaluate-feedback loop.
    """
    print("\n" + "=" * 70)
    print("  COMBINED AUTONOMOUS CODING HARNESS")
    print("  Build → Evaluate → Feedback Loop")
    print("=" * 70)
    print(f"\n  Project:    {project_dir}")
    print(f"  Model:      {model}")
    print(f"  Iterations: {max_iterations or 'Unlimited'}")

    # Operator controls
    print(f"\n  Kill switch:  touch {project_dir}/AGENT_STOP")
    print(f"  Steer agent:  echo 'new direction' > {project_dir}/STEER.md")
    print()

    project_dir.mkdir(parents=True, exist_ok=True)

    # Check first run
    tests_file = project_dir / "feature_list.json"
    is_first_run = not tests_file.exists()

    if is_first_run:
        print("=" * 70)
        print("  FIRST RUN — Initializer agent will set up the project")
        print("  This takes 10-20+ minutes (generating 200 test cases)")
        print("=" * 70)
        copy_spec_to_project(project_dir)
    else:
        print("Continuing existing project")
        print_progress_summary(project_dir)

    iteration = 0
    findings: Optional[str] = None  # Evaluator feedback carried forward

    while True:
        iteration += 1
        if max_iterations and iteration > max_iterations:
            print(f"\nReached max iterations ({max_iterations})")
            break

        # Check kill switch before starting
        if (project_dir / "AGENT_STOP").exists():
            print("\nKill switch engaged. Remove AGENT_STOP to resume.")
            await asyncio.sleep(5)
            iteration -= 1  # Don't count this
            continue

        # Check if all tests pass
        passing, total = count_passing_tests(project_dir)
        if total > 0 and passing == total:
            print(f"\nAll {total} tests passing! Project complete.")
            break

        # =============================================
        # PHASE 1: BUILD
        # =============================================
        print_session_header(iteration, is_first_run, phase="BUILD")

        builder = create_builder_client(project_dir, model)

        if is_first_run:
            prompt = get_initializer_prompt()
            is_first_run = False
        else:
            prompt = get_coding_prompt()
            # Inject evaluator findings from previous iteration
            if findings:
                prompt = (
                    "## EVALUATOR FINDINGS FROM PREVIOUS SESSION\n\n"
                    f"{findings}\n\n"
                    "Address these findings FIRST before implementing new features.\n\n"
                    "---\n\n"
                    f"{prompt}"
                )
                findings = None

        async with builder:
            status, build_response = await run_agent_session(builder, prompt, label="Builder")

        if status == "error":
            print("Builder session failed. Retrying...")
            await asyncio.sleep(AUTO_CONTINUE_DELAY)
            continue

        # =============================================
        # PHASE 2: CHECKPOINT
        # =============================================
        await commit_checkpoint(project_dir)

        # =============================================
        # PHASE 3: EVALUATE
        # =============================================
        print_session_header(iteration, False, phase="EVALUATE")

        eval_client = create_evaluator_client(project_dir, model)
        eval_prompt = get_evaluator_prompt()

        async with eval_client:
            _, eval_response = await run_agent_session(eval_client, eval_prompt, label="Evaluator")

        verdict, eval_findings = parse_verdict(eval_response)

        # =============================================
        # PHASE 4: FEEDBACK
        # =============================================
        if verdict == "PASS":
            print("\n  >>> EVALUATOR VERDICT: PASS <<<")
            if eval_findings:
                print(f"  Evidence: {eval_findings[:200]}")
            findings = None
        else:
            print("\n  >>> EVALUATOR VERDICT: NEEDS_WORK <<<")
            if eval_findings:
                print(f"  Findings: {eval_findings[:500]}")
            findings = eval_findings  # Inject into next builder prompt

        print_progress_summary(project_dir)
        print(f"\nNext iteration in {AUTO_CONTINUE_DELAY}s...\n")
        await asyncio.sleep(AUTO_CONTINUE_DELAY)

    # Final commit
    await commit_checkpoint(project_dir)

    # Final summary
    print("\n" + "=" * 70)
    print("  LOOP COMPLETE")
    print("=" * 70)
    print(f"\n  Project: {project_dir}")
    print_progress_summary(project_dir)
    print(f"\n  Run the app:  cd {project_dir.resolve()} && ./init.sh")
    print()
