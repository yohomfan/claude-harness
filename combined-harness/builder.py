"""
Builder Client Factory
======================

Creates the builder ClaudeSDKClient with full tools, Puppeteer MCP,
and all hooks (security + evidence gate + operator controls).
"""

import json
from functools import partial
from pathlib import Path

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
from claude_code_sdk.types import HookMatcher

from hooks import (
    bash_security_hook,
    clear_evidence_log,
    kill_switch_hook,
    steer_hook,
    track_read_hook,
    verify_gate_hook,
)


PUPPETEER_TOOLS = [
    "mcp__puppeteer__puppeteer_navigate",
    "mcp__puppeteer__puppeteer_screenshot",
    "mcp__puppeteer__puppeteer_click",
    "mcp__puppeteer__puppeteer_fill",
    "mcp__puppeteer__puppeteer_select",
    "mcp__puppeteer__puppeteer_hover",
    "mcp__puppeteer__puppeteer_evaluate",
]

BUILTIN_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]


def create_builder_client(project_dir: Path, model: str) -> ClaudeSDKClient:
    """
    Create a builder ClaudeSDKClient with multi-layered security.

    Security layers (defense in depth):
    1. Sandbox — OS-level bash command isolation
    2. Permissions — file operations restricted to project_dir only
    3. Bash allowlist hook — only permitted commands can run
    4. Evidence gate — can't mark tests passing without reading evidence
    5. Operator controls — kill-switch and steer hooks
    """
    # Clear evidence log at session start
    clear_evidence_log(project_dir)

    # Security settings
    security_settings = {
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Glob(./**)",
                "Grep(./**)",
                "Bash(*)",
                *PUPPETEER_TOOLS,
            ],
        },
    }

    project_dir.mkdir(parents=True, exist_ok=True)
    settings_file = project_dir / ".claude_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)

    # Bind project_dir to hooks that need it
    bound_kill_switch = partial(kill_switch_hook, project_dir=project_dir)
    bound_steer = partial(steer_hook, project_dir=project_dir)
    bound_track_read = partial(track_read_hook, project_dir=project_dir)
    bound_verify_gate = partial(verify_gate_hook, project_dir=project_dir)

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=(
                "You are an expert full-stack developer building a production-quality "
                "web application. An independent evaluator will review your work after "
                "this session — leave thorough evidence (screenshots, console logs)."
            ),
            allowed_tools=[*BUILTIN_TOOLS, *PUPPETEER_TOOLS],
            mcp_servers={
                "puppeteer": {
                    "command": "npx",
                    "args": ["puppeteer-mcp-server"],
                    "env": {
                        "PUPPETEER_EXECUTABLE_PATH": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    },
                }
            },
            hooks={
                "PreToolUse": [
                    # Kill switch and steer on ALL tools
                    HookMatcher(matcher="*", hooks=[bound_kill_switch, bound_steer]),
                    # Bash security
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                    # Track evidence reads
                    HookMatcher(matcher="Read", hooks=[bound_track_read]),
                    # Verify gate on Write|Edit
                    HookMatcher(matcher="Write|Edit", hooks=[bound_verify_gate]),
                ],
            },
            max_turns=1000,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )
