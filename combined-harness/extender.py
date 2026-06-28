"""
Extender Client Factory
=======================

Creates a focused ClaudeSDKClient that APPENDS new test cases to
feature_list.json based on a new-requirements text. Used by
`harness.py extend` to handle incremental requirements without
re-running the full Initializer.

Constraints vs Builder:
- No Puppeteer (extender does not browse the app)
- No verify_gate hook (extender adds passes:false entries, not passing claims)
- No track_read hook (only useful with verify_gate)
- Lower max_turns (focused single-file task)
"""

import json
import platform
from functools import partial
from pathlib import Path

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
from claude_code_sdk.types import HookMatcher

from hooks import bash_security_hook, kill_switch_hook, steer_hook


EXTENDER_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]


def _is_sandbox_supported() -> bool:
    return platform.system() in ("Darwin", "Linux")


def create_extender_client(project_dir: Path, model: str) -> ClaudeSDKClient:
    """
    Create the Extender client: append-only edits to feature_list.json.
    """
    use_sandbox = _is_sandbox_supported()
    security_settings = {
        "sandbox": {"enabled": use_sandbox, "autoAllowBashIfSandboxed": use_sandbox},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Glob(./**)",
                "Grep(./**)",
                "Bash(*)",
            ],
        },
    }

    settings_file = project_dir / ".claude_extender_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)

    bound_kill_switch = partial(kill_switch_hook, project_dir=project_dir)
    bound_steer = partial(steer_hook, project_dir=project_dir)

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=(
                "You are an EXTENDER agent. Your sole job is to APPEND new test "
                "cases to feature_list.json based on a new-requirements text in "
                "the user message. You MUST NOT modify, reorder, rename, or "
                "delete any existing entry. All new entries you add MUST have "
                '"passes": false. Do not implement features, do not run the '
                "app, do not take screenshots — only edit feature_list.json."
            ),
            allowed_tools=EXTENDER_TOOLS,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="*", hooks=[bound_kill_switch, bound_steer]),
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                ],
            },
            max_turns=50,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )
