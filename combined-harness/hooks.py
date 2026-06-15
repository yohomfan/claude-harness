"""
Combined Hooks: Security + Evidence Gate + Operator Controls
============================================================

Merges:
- Bash security allowlist from autonomous-coding/security.py
- Evidence tracking and verify gate from claude-code-config/hooks/track-read.sh + verify-gate.sh
- Operator controls from claude-code-config/hooks/kill-switch.sh + steer.sh
"""

import fnmatch
import os
import re
import shlex
from pathlib import Path


# ===========================================================================
# Bash Security Allowlist (from autonomous-coding/security.py)
# ===========================================================================

ALLOWED_COMMANDS = {
    # File inspection
    "ls", "cat", "head", "tail", "wc", "grep", "find", "file",
    # File operations
    "cp", "mkdir", "chmod", "mv", "rm", "touch",
    # Text processing
    "echo", "printf", "tee", "sort", "uniq", "tr", "cut", "sed", "awk",
    "xargs", "jq", "true", "false", "test",
    # Directory
    "pwd", "cd", "basename", "dirname",
    # Node.js development
    "npm", "npx", "node", "pnpm",
    # Version control
    "git",
    # Process management
    "ps", "lsof", "sleep", "pkill", "kill",
    # Network (read-only)
    "curl", "wget",
    # System
    "open", "which", "env", "date",
    # Script execution
    "init.sh",
}

COMMANDS_NEEDING_EXTRA_VALIDATION = {"pkill", "kill", "chmod", "rm", "init.sh"}


def split_command_segments(command_string: str) -> list[str]:
    """Split a compound command into individual command segments."""
    segments = re.split(r"\s*(?:&&|\|\|)\s*", command_string)
    result = []
    for segment in segments:
        sub_segments = re.split(r'(?<!["\'])\s*;\s*(?!["\'])', segment)
        for sub in sub_segments:
            sub = sub.strip()
            if sub:
                result.append(sub)
    return result


def extract_commands(command_string: str) -> list[str]:
    """Extract command names from a shell command string."""
    commands = []
    segments = re.split(r'(?<!["\'])\s*;\s*(?!["\'])', command_string)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return []
        if not tokens:
            continue

        expect_command = True
        for token in tokens:
            if token in ("|", "||", "&&", "&"):
                expect_command = True
                continue
            if token in (
                "if", "then", "else", "elif", "fi", "for", "while", "until",
                "do", "done", "case", "esac", "in", "!", "{", "}",
            ):
                continue
            if token.startswith("-"):
                continue
            if "=" in token and not token.startswith("="):
                continue
            if expect_command:
                cmd = os.path.basename(token)
                commands.append(cmd)
                expect_command = False

    return commands


def validate_pkill_command(command_string: str) -> tuple[bool, str]:
    """Validate pkill commands - only allow killing dev-related processes."""
    allowed_process_names = {"node", "npm", "npx", "vite", "next"}
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse pkill command"
    if not tokens:
        return False, "Empty pkill command"

    args = [t for t in tokens[1:] if not t.startswith("-")]
    if not args:
        return False, "pkill requires a process name"

    target = args[-1]
    if " " in target:
        target = target.split()[0]

    if target in allowed_process_names:
        return True, ""
    return False, f"pkill only allowed for dev processes: {allowed_process_names}"


def validate_chmod_command(command_string: str) -> tuple[bool, str]:
    """Validate chmod commands - only allow +x."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse chmod command"
    if not tokens or tokens[0] != "chmod":
        return False, "Not a chmod command"

    mode = None
    files = []
    for token in tokens[1:]:
        if token.startswith("-"):
            return False, "chmod flags are not allowed"
        elif mode is None:
            mode = token
        else:
            files.append(token)

    if mode is None:
        return False, "chmod requires a mode"
    if not files:
        return False, "chmod requires at least one file"
    if not re.match(r"^[ugoa]*\+x$", mode):
        return False, f"chmod only allowed with +x mode, got: {mode}"
    return True, ""


def validate_rm_command(command_string: str) -> tuple[bool, str]:
    """Validate rm commands - block recursive force delete on dangerous paths."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse rm command"

    # Block rm -rf / or rm -rf ~ or any absolute path outside project
    dangerous_patterns = ["/", "~", "$HOME", "/etc", "/usr", "/var", "/tmp"]
    for token in tokens[1:]:
        if token in dangerous_patterns or (token.startswith("/") and not token.startswith("./")):
            return False, f"rm on '{token}' is not allowed — only project-relative paths"

    return True, ""


def validate_kill_command(command_string: str) -> tuple[bool, str]:
    """Validate kill commands - only allow killing specific PIDs (no -9 on system processes)."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse kill command"

    # Block kill -9 without a PID
    if len(tokens) < 2:
        return False, "kill requires a PID"

    return True, ""


def validate_init_script(command_string: str) -> tuple[bool, str]:
    """Validate init.sh script execution."""
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse init script command"
    if not tokens:
        return False, "Empty command"
    script = tokens[0]
    if script == "./init.sh" or script.endswith("/init.sh"):
        return True, ""
    return False, f"Only ./init.sh is allowed, got: {script}"


def get_command_for_validation(cmd: str, segments: list[str]) -> str:
    """Find the specific command segment that contains the given command."""
    for segment in segments:
        segment_commands = extract_commands(segment)
        if cmd in segment_commands:
            return segment
    return ""


async def bash_security_hook(input_data, tool_use_id=None, context=None, **kwargs):
    """
    Pre-tool-use hook: validate bash commands against allowlist.
    """
    if input_data.get("tool_name") != "Bash":
        return {}

    command = input_data.get("tool_input", {}).get("command", "")
    if not command:
        return {}

    commands = extract_commands(command)
    if not commands:
        return {
            "decision": "block",
            "reason": f"Could not parse command for security validation: {command}",
        }

    segments = split_command_segments(command)

    for cmd in commands:
        if cmd not in ALLOWED_COMMANDS:
            return {
                "decision": "block",
                "reason": f"Command '{cmd}' is not in the allowed commands list",
            }
        if cmd in COMMANDS_NEEDING_EXTRA_VALIDATION:
            cmd_segment = get_command_for_validation(cmd, segments) or command
            if cmd == "pkill":
                allowed, reason = validate_pkill_command(cmd_segment)
            elif cmd == "kill":
                allowed, reason = validate_kill_command(cmd_segment)
            elif cmd == "chmod":
                allowed, reason = validate_chmod_command(cmd_segment)
            elif cmd == "rm":
                allowed, reason = validate_rm_command(cmd_segment)
            elif cmd == "init.sh":
                allowed, reason = validate_init_script(cmd_segment)
            else:
                continue
            if not allowed:
                return {"decision": "block", "reason": reason}

    return {}


# ===========================================================================
# Operator Controls (from claude-code-config/hooks/)
# ===========================================================================

async def kill_switch_hook(input_data, tool_use_id=None, context=None, *, project_dir: Path, **kwargs):
    """
    Halt every tool call while AGENT_STOP file exists.
    touch AGENT_STOP to engage; rm AGENT_STOP to resume.
    """
    stop_file = project_dir / "AGENT_STOP"
    if stop_file.exists():
        return {
            "decision": "block",
            "reason": "Kill switch engaged: AGENT_STOP file exists. Agent is halted. Remove the file to resume.",
        }
    return {}


async def steer_hook(input_data, tool_use_id=None, context=None, *, project_dir: Path, **kwargs):
    """
    Surface STEER.md content to the agent once, then clear it.
    Write to STEER.md from another terminal to redirect mid-run.
    """
    steer_file = project_dir / "STEER.md"
    if steer_file.exists() and steer_file.stat().st_size > 0:
        content = steer_file.read_text().strip()
        steer_file.write_text("")
        return {
            "decision": "block",
            "reason": (
                f"OPERATOR STEERING: {content}\n\n"
                "Pause what you were about to do, incorporate this guidance, "
                "then continue toward the feature goal."
            ),
        }
    return {}


# ===========================================================================
# Evidence Gate (from claude-code-config/hooks/track-read.sh + verify-gate.sh)
# ===========================================================================

EVIDENCE_PATTERNS = ["*/screenshots/*", "*-console.txt", "*-result.txt", "*.png"]
RESULTS_FILENAME = "feature_list.json"


def _evidence_log_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / ".evidence-reads"


def clear_evidence_log(project_dir: Path) -> None:
    """Clear the evidence log at the start of each builder session."""
    log_file = _evidence_log_path(project_dir)
    if log_file.exists():
        log_file.write_text("")


async def track_read_hook(input_data, tool_use_id=None, context=None, *, project_dir: Path, **kwargs):
    """
    Record which evidence files (screenshots, console logs) the agent has opened.
    verify_gate_hook consults this before allowing writes to the results file.
    """
    file_path = input_data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return {}

    is_evidence = any(fnmatch.fnmatch(file_path, pat) for pat in EVIDENCE_PATTERNS)

    if is_evidence and Path(file_path).exists():
        log_file = _evidence_log_path(project_dir)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(file_path + "\n")

    return {}  # track-read never blocks


async def verify_gate_hook(input_data, tool_use_id=None, context=None, *, project_dir: Path, **kwargs):
    """
    Deny writes to feature_list.json unless evidence has been Read first.
    After a successful write, the evidence log is cleared (next write needs fresh proof).
    """
    target_path = input_data.get("tool_input", {}).get("file_path", "")
    if not target_path:
        return {}

    if Path(target_path).name != RESULTS_FILENAME:
        return {}

    # Allow initial creation — only gate updates to an existing file
    results_file = project_dir / RESULTS_FILENAME
    if not results_file.exists():
        return {}

    log_file = _evidence_log_path(project_dir)
    if not log_file.exists() or log_file.stat().st_size == 0:
        return {
            "decision": "block",
            "reason": (
                "Cannot modify the results file: no screenshot or console-log evidence "
                "has been Read this session. Open the evidence file with the Read tool first, "
                "then retry."
            ),
        }

    # Consume evidence — next write needs fresh proof
    log_file.write_text("")
    return {}
