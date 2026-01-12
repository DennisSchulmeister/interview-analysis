# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Topic frequency analysis action.

This module currently contains a stub implementation.
"""

import argparse
from dataclasses import dataclass

from interview_analysis.config import InterviewConfig


@dataclass(frozen=True)
class AnalyzeAction:
    """
    `analyze` subcommand.

    Intended to locate exact text passages per topic and compute frequency and
    predominant orientation without interpretive analysis.
    """

    name: str = "analyze"
    help: str = "Run topic frequency analysis (stub for now)"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `analyze` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        _ = parser

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute topic frequency analysis.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            NotImplementedError:
                Always, until the analysis step is implemented.
        """

        _ = args
        if config is None:
            raise RuntimeError("AnalyzeAction requires a config, but none was provided")
        raise NotImplementedError("Topic frequency analysis is not implemented yet")
