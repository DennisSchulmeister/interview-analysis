from __future__ import annotations

"""
Shared action interface.

Actions implement a small protocol so the CLI can dynamically register arguments
and dispatch execution based on the selected subcommand.
"""

import argparse
from typing import Protocol

from interview_analysis.config import InterviewConfig


class Action(Protocol):
    """
    Interface for a CLI action (subcommand).

    Implementations are expected to:
    - Provide a `name` used as the subcommand.
    - Provide a short `help` string for `--help`.
    - Declare whether they require a valid YAML config.
    """

    name: str
    help: str
    requires_config: bool

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register action-specific CLI arguments.

        Args:
            parser:
                The subparser dedicated to this action.

        Returns:
            None
        """

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute the action.

        Args:
            args:
                Parsed arguments for this subcommand.
            config:
                Loaded configuration, if `requires_config` is True.

        Returns:
            None
        """
