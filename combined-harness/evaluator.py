"""
Evaluator Client Factory
========================

Creates a restricted ClaudeSDKClient for independent evaluation.
The evaluator has NO Write/Edit tools and NO Puppeteer — it reviews
evidence from a fresh context without trusting the builder's assessment.
"""

import json
import platform
from functools import partial
from pathlib import Path

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
from claude_code_sdk.types import HookMatcher

from hooks import bash_security_hook, kill_switch_hook


EVALUATOR_TOOLS = ["Read", "Glob", "Grep", "Bash"]


def _is_sandbox_supported() -> bool:
    return platform.system() in ("Darwin", "Linux")


def create_evaluator_client(project_dir: Path, model: str) -> ClaudeSDKClient:
    """
    Create a restricted evaluator ClaudeSDKClient.

    Key restrictions vs builder:
    - No Write or Edit tools (cannot modify code or results)
    - No Puppeteer (reviews evidence, does not interact with the app)
    - No steer or evidence hooks (only kill-switch and bash security)
    - Lower max_turns (evaluation is shorter than building)
    """
    use_sandbox = _is_sandbox_supported()
    security_settings = {
        "sandbox": {"enabled": use_sandbox, "autoAllowBashIfSandboxed": use_sandbox},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)",
                "Glob(./**)",
                "Grep(./**)",
                "Bash(*)",
            ],
        },
    }

    settings_file = project_dir / ".claude_evaluator_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)

    bound_kill_switch = partial(kill_switch_hook, project_dir=project_dir)

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt=(
                "You are a skeptical second-opinion reviewer. You did not see how "
                "the code was built and you should not trust the builder's own assessment. "
                "You have no Write or Edit tools — you cannot modify anything."
            ),
            allowed_tools=EVALUATOR_TOOLS,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="*", hooks=[bound_kill_switch]),
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                ],
            },
            max_turns=200,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )


def parse_verdict(response: str) -> tuple[str, str | None]:
    """
    Parse evaluator response. First line should be PASS or NEEDS_WORK.

    Returns:
        (verdict, findings) where verdict is "PASS" or "NEEDS_WORK"
        and findings is the evaluator's detailed feedback (None on PASS).
    """
    lines = response.strip().split("\n")
    first_line = lines[0].strip() if lines else ""

    if first_line == "PASS":
        evidence = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        return "PASS", evidence or None
    elif first_line == "NEEDS_WORK":
        findings = "\n".join(lines[1:]).strip() if len(lines) > 1 else response.strip()
        return "NEEDS_WORK", findings
    else:
        # Could not parse — treat as NEEDS_WORK with full response
        return "NEEDS_WORK", response.strip()
