# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Small CLI interaction helpers.

These helpers centralize terminal interaction behavior so actions can stay
focused on their core job.

The project uses a safety-first approach:
- In interactive terminals, actions may prompt the user for confirmation.
- In non-interactive contexts (CI, pipes), actions should avoid prompts and
  require an explicit `--force`.
"""

import sys
from pathlib import Path


def is_interactive_tty() -> bool:
    """
    Determine whether we can safely prompt the user.

    Returns:
        True if both stdin and stdout are connected to a TTY.
    """

    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:  # noqa: BLE001
        return False


def prompt_yes_no(question: str, *, default_no: bool = True) -> bool:
    """
    Ask the user a yes/no question.

    Args:
        question:
            Prompt text without the trailing choice suffix.
        default_no:
            If true, empty input is treated as "no".

    Returns:
        True if the user answered yes.

    Raises:
        RuntimeError:
            If the prompt cannot be shown in a non-interactive session.
    """

    if not is_interactive_tty():
        raise RuntimeError("Cannot prompt in non-interactive mode")

    suffix = "[y/N]" if default_no else "[Y/n]"
    while True:
        answer = input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return not default_no
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def prompt_overwrite(path: Path) -> bool:
    """
    Ask the user whether to overwrite an existing file.

    Args:
        path:
            The file path that would be overwritten.

    Returns:
        True if the user agreed to overwrite.

    Raises:
        RuntimeError:
            If the prompt cannot be shown in a non-interactive session.
    """

    return prompt_yes_no(f"Output file already exists: {path}. Overwrite?", default_no=True)


def prompt_delete_contents(path: Path) -> bool:
    """
    Ask the user whether to delete all contents of a directory.

    Args:
        path:
            Directory whose contents would be deleted.

    Returns:
        True if the user agreed.

    Raises:
        RuntimeError:
            If the prompt cannot be shown in a non-interactive session.
    """

    return prompt_yes_no(f"This will delete all contents of '{path}'. Continue?", default_no=True)
