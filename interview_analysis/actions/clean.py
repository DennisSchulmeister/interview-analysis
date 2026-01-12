from __future__ import annotations

"""
Working directory cleanup action.

The `clean` subcommand removes all files and directories inside the configured
working directory (`workdir`) without removing the directory itself.

For safety:
- If `--force` is not provided and the process is attached to an interactive TTY,
  the user is prompted for confirmation.
- If `--force` is not provided and the process is not interactive, the action
  aborts.
"""

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from interview_analysis.config import ConfigError, InterviewConfig


@dataclass(frozen=True)
class CleanAction:
    """
    `clean` subcommand.

    Removes all files and directories inside the configured `workdir`.
    """

    name: str = "clean"
    help: str = "Empty the configured working directory"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `clean` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Do not prompt for confirmation",
        )

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute the cleanup.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            ConfigError:
                If the workdir is unsafe, cannot be cleaned, or if confirmation
                is required but cannot be requested.
        """

        if config is None:
            raise RuntimeError("CleanAction requires a config, but none was provided")

        workdir = config.workdir
        if self._is_dangerous_workdir(workdir):
            raise ConfigError(f"Refusing to clean dangerous workdir: {workdir}")

        if not args.force:
            if not self._is_interactive_tty():
                raise ConfigError(
                    "Refusing to clean without confirmation on a non-interactive TTY. "
                    "Re-run with --force."
                )

            answer = input(f"This will delete all contents of '{workdir}'. Continue? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Aborted.")
                return

        removed = self._empty_directory(workdir)
        print(f"Cleaned {removed} item(s) from: {workdir}")

    def _is_interactive_tty(self) -> bool:
        """
        Determine whether we can safely prompt the user.

        Returns:
            True if both stdin and stdout are connected to a TTY.
        """

        return sys.stdin.isatty() and sys.stdout.isatty()

    def _is_dangerous_workdir(self, path: Path) -> bool:
        """
        Check whether a path looks too dangerous to delete recursively.

        Args:
            path:
                Candidate workdir path.

        Returns:
            True if the path is considered dangerous.
        """

        resolved = path.resolve()

        if resolved == Path("/"):
            return True

        try:
            if resolved == Path.home().resolve():
                return True
        except Exception:  # noqa: BLE001
            # If home cannot be resolved, don't treat it as safe.
            pass

        return False

    def _empty_directory(self, directory: Path) -> int:
        """
        Remove all entries within a directory.

        Args:
            directory:
                Directory whose contents should be removed.

        Returns:
            Number of entries removed.

        Raises:
            ConfigError:
                If the directory does not exist, is not a directory, or if
                deletion fails.
        """

        if not directory.exists():
            return 0
        if not directory.is_dir():
            raise ConfigError(f"workdir is not a directory: {directory}")

        removed = 0
        for child in directory.iterdir():
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            except Exception as exc:  # noqa: BLE001
                raise ConfigError(f"Failed to remove '{child}': {exc}") from exc

        return removed
