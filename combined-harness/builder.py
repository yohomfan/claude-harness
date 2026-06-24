"""
Builder Client Factory
======================

Creates the builder ClaudeSDKClient with full tools and all hooks
(security + evidence gate + operator controls).
Puppeteer MCP is optional — pass enable_puppeteer=True to include it.
"""

import json
import platform
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


def _is_sandbox_supported() -> bool:
    return platform.system() in ("Darwin", "Linux")


def create_builder_client(
    project_dir: Path,
    model: str,
    *,
    system_prompt: str | None = None,
    enable_puppeteer: bool = False,
) -> ClaudeSDKClient:
    """
    Create a builder ClaudeSDKClient with multi-layered security.

    Args:
        project_dir: Working directory for the agent.
        model: Claude model ID.
        system_prompt: Custom system prompt. If None, uses a generic default.
        enable_puppeteer: Whether to include Puppeteer MCP for browser testing.
    """
    clear_evidence_log(project_dir)

    allowed_tools = [*BUILTIN_TOOLS]
    tool_permissions = [
        "Read(./**)",
        "Write(./**)",
        "Edit(./**)",
        "Glob(./**)",
        "Grep(./**)",
        "Bash(*)",
    ]
    mcp_servers = {}

    if enable_puppeteer:
        allowed_tools.extend(PUPPETEER_TOOLS)
        tool_permissions.extend(PUPPETEER_TOOLS)
        mcp_servers["puppeteer"] = {
            "command": "npx",
            "args": ["puppeteer-mcp-server"],
        }

    use_sandbox = _is_sandbox_supported()
    security_settings = {
        "sandbox": {"enabled": use_sandbox, "autoAllowBashIfSandboxed": use_sandbox},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": tool_permissions,
        },
    }

    project_dir.mkdir(parents=True, exist_ok=True)
    settings_file = project_dir / ".claude_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)

    bound_kill_switch = partial(kill_switch_hook, project_dir=project_dir)
    bound_steer = partial(steer_hook, project_dir=project_dir)
    bound_track_read = partial(track_read_hook, project_dir=project_dir)
    bound_verify_gate = partial(verify_gate_hook, project_dir=project_dir)

    if system_prompt is None:
        system_prompt = (
            "You are an expert developer working on a long-running autonomous coding task. "
            "An independent evaluator will review your work after this session — "
            "leave thorough evidence (screenshots, console logs, test output)."
        )

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers if mcp_servers else None,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="*", hooks=[bound_kill_switch, bound_steer]),
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                    HookMatcher(matcher="Read", hooks=[bound_track_read]),
                    HookMatcher(matcher="Write|Edit", hooks=[bound_verify_gate]),
                ],
            },
            max_turns=1000,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )
