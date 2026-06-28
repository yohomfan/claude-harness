"""
Prompt Loading Utilities
========================

Loads prompt templates from the prompts/ directory.
"""

import shutil
from pathlib import Path


PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template by name (without extension)."""
    prompt_path = PROMPTS_DIR / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")


def get_initializer_prompt() -> str:
    return load_prompt("initializer_prompt")


def get_coding_prompt() -> str:
    return load_prompt("coding_prompt")


def get_evaluator_prompt() -> str:
    return load_prompt("evaluator_prompt")


def get_extender_prompt() -> str:
    return load_prompt("extender_prompt")


def copy_spec_to_project(project_dir: Path) -> None:
    """Copy the app spec into the project directory for the agent to read."""
    spec_dest = project_dir / "app_spec.txt"
    if spec_dest.exists():
        return

    spec_source = PROMPTS_DIR / "app_spec.txt"
    if spec_source.exists():
        shutil.copy(spec_source, spec_dest)
        print("Copied app_spec.txt to project directory")
    else:
        print(
            "WARNING: No app_spec.txt found. Create one from the template:\n"
            f"  cp {PROMPTS_DIR / 'app_spec.template.txt'} {PROMPTS_DIR / 'app_spec.txt'}\n"
            "  Then edit it with your project specification."
        )
