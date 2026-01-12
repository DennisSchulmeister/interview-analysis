from __future__ import annotations

"""
Output writer action.

This module currently contains a stub implementation.
"""

import argparse
from dataclasses import dataclass

from interview_analysis.config import InterviewConfig


@dataclass(frozen=True)
class WriteOutputAction:
    """
    `write-output` subcommand.

    Intended to write the final `.ods` report based on earlier segmentation and
    analysis outputs.
    """

    name: str = "write-output"
    help: str = "Write the output file (stub for now)"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `write-output` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        _ = parser

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute output writing.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            NotImplementedError:
                Always, until output writing is implemented.
        """

        _ = args
        if config is None:
            raise RuntimeError("WriteOutputAction requires a config, but none was provided")
        raise NotImplementedError("Writing the output file is not implemented yet")
