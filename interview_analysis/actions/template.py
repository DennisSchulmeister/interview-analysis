# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Template configuration generator.

This action writes a ready-to-edit `interviews.yaml` file into the current
directory (or a user-specified path).
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from interview_analysis.config import ConfigError, InterviewConfig


@dataclass(frozen=True)
class TemplateAction:
    """
    `template` subcommand.

    This action does not require a YAML config because it produces one.
    """

    name: str = "template"
    help: str = "Write a template interviews.yaml config"
    requires_config: bool = False

    _TEMPLATE_YAML: str = "\n".join(
        [
            "# Recursive grep pattern for transcript files to include/exclude",
            'include: "**.odt"',
            'exclude: "private/**"',
            "",
            "# Working directory for intermediate files",
            "workdir: ./work",
            "",
            "# Final output file",
            "outfile: results.ods",
            "",
            "# Segmentation options (optional; defaults shown)",
            "# segmentation:",
            "#   segment_paragraphs: 12",
            "#   overlap_paragraphs: 3",
            "",
            "# Analysis options (optional; defaults shown)",
            "# analysis:",
            "#   # If true, exclude interviewer statements from coding.",
            "#   # To enable this, add a single metadata paragraph to each transcript:",
            "#   #   interviewer = Name1, Name2",
            "#   exclude_interviewer: false",
            "#",
            "#   # Strategy for LLM calls:",
            "#   #   segment: one call per segment with the full codebook",
            "#   #   topic: one call per segment per topic (more robust, more costly)",
            "#   strategy: segment",
            "",
            "# Topics and possible orientations for each topic",
            "topics:",
            "  - Perceived lecturer motivations for participation:",
            "      - Clear / plausible",
            "      - Mixed / ambiguous",
            "      - Unclear or questioned",
            "  - Offered participation opportunities:",
            "      - Limited / selective",
            "      - Moderate",
            "      - Extensive",
            "  - Clarity and transparency of participation offers:",
            "      - Clear",
            "      - Partially clear",
            "      - Unclear",
            "",
        ]
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `template` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        parser.add_argument(
            "path",
            nargs="?",
            default="interviews.yaml",
            help="Destination path for the template (default: ./interviews.yaml)",
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Allow overwriting an existing file",
        )

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute the template writer.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Unused for this action.

        Returns:
            None

        Raises:
            ConfigError:
                If the destination exists and `--force` is not set.
        """

        _ = config
        dest = Path(args.path)
        self._write_template(dest, force=bool(args.force))
        print(f"Wrote template config to: {dest}")

    def _write_template(self, dest: Path, *, force: bool) -> None:
        """
        Write a template YAML configuration file.

        Args:
            dest:
                Destination path for the template.
            force:
                If True, overwrite an existing file.

        Returns:
            None

        Raises:
            ConfigError:
                If the destination exists and `force` is False.
            OSError:
                If the file cannot be written.
        """

        if dest.exists() and not force:
            raise ConfigError(f"Refusing to overwrite existing file: {dest} (use --force)")

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self._TEMPLATE_YAML, encoding="utf-8")
