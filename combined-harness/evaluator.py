"""
Evaluator Client Factory
========================

Creates a restricted ClaudeSDKClient for independent evaluation.
The evaluator has NO Write/Edit tools and NO Puppeteer — it reviews
evidence from a fresh context without trusting the builder's assessment.
"""

import json
import platform
import re
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


# A verdict line either IS, or ENDS WITH, a standalone PASS / NEEDS_WORK token
# (tolerating markdown like **PASS** and a glued preamble like
# "...examining evidence.PASS"). The token must sit at the end of the line so we
# don't match it mid-sentence.
_VERDICT_TAIL = re.compile(r"(NEEDS[ _]WORK|PASS)[\s*`#:.\-]*$", re.IGNORECASE)


def parse_verdict(response: str) -> tuple[str, str | None]:
    """
    Parse the evaluator's PASS / NEEDS_WORK verdict from its full response.

    LLMs often prepend a preamble ("I'll review...") before the verdict and may
    glue the token onto it ("...evidence.PASS"), so the first line alone cannot
    be trusted. We scan every line for a trailing verdict token and take the
    LAST one — the evaluator typically restates its conclusion in a closing
    summary. Everything else becomes the findings.

    Returns:
        (verdict, findings) where verdict is "PASS" or "NEEDS_WORK" and findings
        is the evaluator's detailed feedback (None on a clean PASS).
    """
    verdict: str | None = None
    body: list[str] = []

    for line in response.strip().split("\n"):
        match = _VERDICT_TAIL.search(line.strip())
        if match:
            token = match.group(1).upper().replace(" ", "_")
            verdict = "NEEDS_WORK" if token.startswith("NEEDS") else "PASS"
            # Keep any text before the verdict token (e.g. the glued preamble).
            remainder = _VERDICT_TAIL.sub("", line).rstrip()
            if remainder:
                body.append(remainder)
        else:
            body.append(line)

    findings = "\n".join(body).strip() or None

    if verdict is None:
        # No verdict token anywhere — flag loudly instead of silently "passing".
        print(
            "[parse_verdict] WARNING: no PASS/NEEDS_WORK found in evaluator "
            "response; defaulting to NEEDS_WORK"
        )
        return "NEEDS_WORK", response.strip()

    if verdict == "PASS":
        return "PASS", findings
    return "NEEDS_WORK", findings or response.strip()
