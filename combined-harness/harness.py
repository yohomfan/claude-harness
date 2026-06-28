#!/usr/bin/env python3
"""
Claude Harness — Unified CLI
==============================

One command to rule them all:

    python harness.py init   <project>                   # Create a new project from template
    python harness.py run    <project> [options]          # Start the build-evaluate loop
    python harness.py extend <project> [requirements]     # Append new requirements as test cases
    python harness.py dashboard <project> [--port 8077]   # Open the web monitoring dashboard
    python harness.py stop   <project> [action]           # pause / resume / quit / status
    python harness.py steer  <project> <message>          # Inject instructions mid-run
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import sys
from http.server import HTTPServer
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
PROMPTS_DIR = Path(__file__).parent / "prompts"


def resolve_project_dir(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).parent / "generations" / p
    return p.resolve()


# ─── init ───────────────────────────────────────────────────────────

def cmd_init(args):
    project_dir = resolve_project_dir(args.project)
    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"Directory already exists and is not empty: {project_dir}")
        print("To resume an existing project, use: python harness.py run " + args.project)
        sys.exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)

    template = PROMPTS_DIR / "app_spec.template.txt"
    dest = project_dir / "app_spec.txt"
    if template.exists():
        shutil.copy(template, dest)

    # Drop a Conventional Commits message template; the Initializer agent will
    # `git init` and run `git config commit.template .gitmessage` (see prompt).
    gitmessage = PROMPTS_DIR / "gitmessage.template"
    if gitmessage.exists():
        shutil.copy(gitmessage, project_dir / ".gitmessage")

    print("=" * 60)
    print("  Project initialized!")
    print("=" * 60)
    print(f"\n  Location: {project_dir}")
    print(f"\n  Next steps:")
    print(f"    1. Edit the spec file:")
    print(f"       {dest}")
    print(f"    2. Start the harness:")
    print(f"       python harness.py run {args.project}")
    print(f"    3. Monitor progress (optional):")
    print(f"       python harness.py dashboard {args.project}")
    print()


# ─── run ────────────────────────────────────────────────────────────

def cmd_run(args):
    from loop import parse_duration, run_loop

    project_dir = resolve_project_dir(args.project)

    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        print(f"Run 'python harness.py init {args.project}' first.")
        sys.exit(1)

    spec_file = project_dir / "app_spec.txt"
    if not spec_file.exists():
        template_hint = PROMPTS_DIR / "app_spec.template.txt"
        print(f"No app_spec.txt found in {project_dir}")
        print(f"Copy and edit the template: {template_hint}")
        sys.exit(1)

    async def _run():
        shutdown = asyncio.Event()

        def _handle_sigterm():
            if not shutdown.is_set():
                print("\n[SIGTERM] Received. Will exit after current iteration.")
                shutdown.set()

        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        except NotImplementedError:
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

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n\nInterrupted. To resume: python harness.py run " + args.project)


# ─── extend ─────────────────────────────────────────────────────────

def cmd_extend(args):
    project_dir = resolve_project_dir(args.project)

    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        print(f"Initialize first: python harness.py init {args.project}")
        sys.exit(1)

    feature_file = project_dir / "feature_list.json"
    if not feature_file.exists():
        print(f"No feature_list.json in {project_dir}.")
        print("`extend` works on existing projects. Run `python harness.py run "
              f"{args.project}` once to let the Initializer create it.")
        sys.exit(1)

    # Resolve requirements text — file > inline > stdin
    if args.requirements_file:
        req_path = Path(args.requirements_file)
        if not req_path.exists():
            print(f"Requirements file not found: {req_path}")
            sys.exit(1)
        requirements = req_path.read_text(encoding="utf-8").strip()
    elif args.requirements:
        requirements = " ".join(args.requirements).strip()
    else:
        print("Reading requirements from stdin (Ctrl+D to finish)...")
        requirements = sys.stdin.read().strip()

    if not requirements:
        print("Empty requirements — nothing to extend.")
        sys.exit(1)

    # Snapshot for delta reporting + post-run validation
    try:
        before = json.loads(feature_file.read_text(encoding="utf-8"))
        before_count = len(before) if isinstance(before, list) else 0
    except (json.JSONDecodeError, OSError):
        print(f"WARNING: {feature_file.name} is unreadable before extend. Aborting.")
        sys.exit(1)

    async def _run():
        from extender import create_extender_client
        from loop import run_agent_session
        from prompts import get_extender_prompt

        prompt = (
            get_extender_prompt()
            + "\n\n---\n\n## NEW REQUIREMENTS\n\n"
            + requirements
        )

        client = create_extender_client(project_dir, args.model)
        async with client:
            status, _ = await run_agent_session(client, prompt, label="Extender")

        if status == "error":
            print("\nExtender session failed.")
            sys.exit(1)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return

    # Post-run validation: JSON must still parse and grow (not shrink/change)
    try:
        after = json.loads(feature_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"\nERROR: feature_list.json is now invalid JSON: {e}")
        print("Run `git diff feature_list.json` in the project to investigate.")
        sys.exit(1)

    if not isinstance(after, list):
        print(f"\nERROR: feature_list.json is no longer a JSON array.")
        sys.exit(1)

    after_count = len(after)
    added = after_count - before_count

    print()
    print("=" * 60)
    if added > 0:
        print(f"  Extended: +{added} new tests ({before_count} -> {after_count})")
    elif added == 0:
        print(f"  No new tests added. Total unchanged at {after_count}.")
    else:
        print(f"  WARNING: feature_list.json SHRANK by {-added} entries "
              f"({before_count} -> {after_count}).")
        print("  The extender was supposed to append only. Run "
              "`git diff feature_list.json` to inspect.")
    print("=" * 60)
    print(f"\n  Next: python harness.py run {args.project}\n")


# ─── dashboard ──────────────────────────────────────────────────────

def cmd_dashboard(args):
    from dashboard import DashboardHandler
    from tracker import read_status, read_history

    project_dir = resolve_project_dir(args.project)
    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        sys.exit(1)

    DashboardHandler.project_dir = project_dir
    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Dashboard:  http://localhost:{args.port}")
    print(f"Monitoring: {project_dir}")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


# ─── stop ───────────────────────────────────────────────────────────

def cmd_stop(args):
    project_dir = resolve_project_dir(args.project)
    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        sys.exit(1)

    action = args.action
    stop_file = project_dir / "AGENT_STOP"
    quit_file = project_dir / "AGENT_QUIT"
    steer_file = project_dir / "STEER.md"

    if action == "pause":
        stop_file.touch()
        print("Paused. Agent will halt at next poll (up to 60s).")
        print(f"Resume: python harness.py stop {args.project} resume")

    elif action == "resume":
        if stop_file.exists():
            stop_file.unlink()
            print("Resumed. Agent will continue at next poll.")
        else:
            print("Not paused (AGENT_STOP does not exist).")

    elif action == "quit":
        quit_file.touch()
        print("Quit signal sent. Agent will exit after current iteration.")

    elif action == "status":
        print(f"Project: {project_dir}\n")

        if stop_file.exists():
            print("  AGENT_STOP:  ACTIVE (paused)")
        else:
            print("  AGENT_STOP:  not set")

        if quit_file.exists():
            print("  AGENT_QUIT:  ACTIVE (will exit after current iteration)")
        else:
            print("  AGENT_QUIT:  not set")

        if steer_file.exists() and steer_file.stat().st_size > 0:
            print("  STEER.md:    has content (pending injection)")
        else:
            print("  STEER.md:    empty or absent")

        feature_file = project_dir / "feature_list.json"
        if feature_file.exists():
            try:
                data = json.loads(feature_file.read_text(encoding="utf-8"))
                passing = sum(1 for t in data if t.get("passes"))
                total = len(data)
                pct = (passing / total * 100) if total else 0
                print(f"\n  Progress:    {passing}/{total} tests passing ({pct:.1f}%)")
            except (json.JSONDecodeError, OSError):
                pass

        status_file = project_dir / ".harness" / "status.json"
        if status_file.exists():
            try:
                st = json.loads(status_file.read_text(encoding="utf-8"))
                print(f"  Iteration:   {st.get('iteration', '?')}")
                print(f"  Phase:       {st.get('phase', '?')}")
                elapsed = st.get("elapsed_seconds", 0)
                h, m = divmod(elapsed // 60, 60)
                print(f"  Elapsed:     {int(h)}h {int(m)}m {elapsed % 60}s")
            except (json.JSONDecodeError, OSError):
                pass
        print()


# ─── steer ──────────────────────────────────────────────────────────

def cmd_steer(args):
    project_dir = resolve_project_dir(args.project)
    if not project_dir.exists():
        print(f"Project not found: {project_dir}")
        sys.exit(1)

    steer_file = project_dir / "STEER.md"
    message = " ".join(args.message)
    steer_file.write_text(message, encoding="utf-8")
    print(f"Steering instruction written. Agent will pick it up at next tool call.")
    print(f"  Content: {message[:200]}")


# ─── main ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Claude Harness — autonomous coding with build-evaluate feedback loop",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Create a new project from template")
    p_init.add_argument("project", help="Project name (relative to generations/) or absolute path")

    # run
    p_run = sub.add_parser("run", help="Start the build-evaluate loop")
    p_run.add_argument("project", help="Project name or path")
    p_run.add_argument("--max-iterations", type=int, default=None, help="Max loop iterations")
    p_run.add_argument("--max-runtime", type=str, default=None, help="Time limit: 4h / 30m / 90s")
    p_run.add_argument("--max-stall", type=int, default=None, help="Quit after N consecutive NEEDS_WORK")
    p_run.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Model ID (default: {DEFAULT_MODEL})")
    p_run.add_argument("--puppeteer", action="store_true", default=False, help="Enable Puppeteer browser testing")

    # extend
    p_ext = sub.add_parser(
        "extend",
        help="Append new requirements as additional test cases (passes:false)",
    )
    p_ext.add_argument("project", help="Project name or path")
    p_ext.add_argument(
        "--requirements", nargs="+", default=None,
        help="New requirements as inline text",
    )
    p_ext.add_argument(
        "--requirements-file", type=str, default=None,
        help="Path to a file containing the new requirements (md/txt)",
    )
    p_ext.add_argument(
        "--model", type=str, default=DEFAULT_MODEL,
        help=f"Model ID (default: {DEFAULT_MODEL})",
    )

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Open the web monitoring dashboard")
    p_dash.add_argument("project", help="Project name or path")
    p_dash.add_argument("--port", type=int, default=8077, help="HTTP port (default: 8077)")

    # stop
    p_stop = sub.add_parser("stop", help="Pause / resume / quit / check status")
    p_stop.add_argument("project", help="Project name or path")
    p_stop.add_argument("action", nargs="?", default="status",
                        choices=["pause", "resume", "quit", "status"],
                        help="Action to take (default: status)")

    # steer
    p_steer = sub.add_parser("steer", help="Inject instructions into a running agent")
    p_steer.add_argument("project", help="Project name or path")
    p_steer.add_argument("message", nargs="+", help="Instruction text to inject")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "run": cmd_run,
        "extend": cmd_extend,
        "dashboard": cmd_dashboard,
        "stop": cmd_stop,
        "steer": cmd_steer,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
