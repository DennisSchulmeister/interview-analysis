from __future__ import annotations

"""
CLI entrypoint for the interview analysis tool.

This module builds a git-style subcommand CLI (via argparse) and dispatches
execution to action modules.
"""

import argparse
import sys
from dotenv import load_dotenv

from interview_analysis.actions.analyze import AnalyzeAction
from interview_analysis.actions.clean import CleanAction
from interview_analysis.actions.segment import SegmentAction
from interview_analysis.actions.template import TemplateAction
from interview_analysis.actions.write_output import WriteOutputAction
from interview_analysis.config import ConfigError, find_config_path, load_config


def _action_repository():
	"""
	Construct the action registry.

	Returns:
		A mapping from subcommand name to an action instance.
	"""
	actions = [
		TemplateAction(),
		CleanAction(),
		SegmentAction(),
		AnalyzeAction(),
		WriteOutputAction(),
	]
	return {a.name: a for a in actions}


def build_parser() -> argparse.ArgumentParser:
	"""
	Build the top-level argument parser.

	The parser uses subcommands (similar to `git`) where each action registers its
	own arguments.

	Returns:
		The configured ArgumentParser instance.
	"""
	parser = argparse.ArgumentParser(
		prog="interview-analysis",
		description=(
			"Automate a non-interpretive topic frequency/orientation coding over interview transcripts."
		),
	)

	actions = _action_repository()

	config_parent = argparse.ArgumentParser(add_help=False)
	config_parent.add_argument(
		"--config",
		"-c",
		help=(
			"Path to interviews.yaml. If omitted, ./interviews.yaml in the current directory is used."
		),
	)

	subparsers = parser.add_subparsers(dest="action", metavar="COMMAND", required=True)

	for name, action in actions.items():
		parents = [config_parent] if action.requires_config else []
		sub = subparsers.add_parser(name, help=action.help, parents=parents)
		action.add_arguments(sub)
		sub.set_defaults(_action_name=name)

	return parser


def main(argv: list[str] | None = None) -> int:
	"""
	Run the CLI.

	Args:
		argv:
			Optional argument list (without program name). If omitted, argparse
			reads from sys.argv.

	Returns:
		Process exit code. `0` on success, `2` on configuration/usage errors,
		`3` for not-yet-implemented actions.

	Raises:
		SystemExit:
			When invoked via `python -m interview_analysis.app` (see module guard).
	"""
	load_dotenv()

	parser = build_parser()
	args = parser.parse_args(argv)

	try:
		actions = _action_repository()
		action_name = getattr(args, "_action_name", None)
		if not action_name or action_name not in actions:
			parser.error("Unknown or missing command")
			return 2

		action = actions[action_name]

		config = None
		if action.requires_config:
			config_path = find_config_path(getattr(args, "config", None))
			config = load_config(config_path)

		action.run(args, config)
		return 0
	except ConfigError as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 2
	except NotImplementedError as exc:
		print(f"not implemented: {exc}", file=sys.stderr)
		return 3


if __name__ == "__main__":
	raise SystemExit(main())
