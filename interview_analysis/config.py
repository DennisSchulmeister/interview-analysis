# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Configuration loading and validation.

This module handles reading `interviews.yaml`, validating required keys, and
normalizing paths so that downstream actions can rely on a typed config object.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TopicSpec:
    """
    Topic definition with its allowed orientations.

    Attributes:
        topic:
            Human-readable topic name.
        orientations:
            Allowed orientation labels for the topic.
    """

    topic: str
    orientations: list[str]


@dataclass(frozen=True)
class SegmentationConfig:
    """
    Configuration for transcript segmentation.

    Attributes:
        segment_paragraphs:
            Number of paragraphs per segment.
        overlap_paragraphs:
            Number of paragraphs repeated from the previous segment to provide
            context.
    """

    segment_paragraphs: int = 12
    overlap_paragraphs: int = 3


@dataclass(frozen=True)
class InterviewConfig:
    """
    Parsed configuration for an interview analysis run.

    Attributes:
        config_path:
            Path to the YAML config file used for this run.
        base_dir:
            Directory that relative paths and glob patterns are resolved against.
        include:
            Glob pattern for transcript files to include.
        exclude:
            Optional glob pattern for transcript files to exclude.
        workdir:
            Directory for intermediate outputs.
        outfile:
            Target ODS path for the final report.
        topics:
            List of topics and their allowed orientations.
        segmentation:
            Settings used by the segmentation step.
    """

    config_path: Path
    base_dir: Path
    include: str
    exclude: str | None
    workdir: Path
    outfile: Path
    topics: list[TopicSpec]
    segmentation: SegmentationConfig


class ConfigError(RuntimeError):
    """
    Raised when the YAML configuration is missing, invalid, or cannot be parsed.
    """

    pass


def find_config_path(cli_path: str | None) -> Path:
    """
    Determine which YAML config file to use.

    Args:
        cli_path:
            Optional config path provided on the command line.

    Returns:
        The resolved Path object (not necessarily existing).
    """

    if cli_path:
        return Path(cli_path)

    return Path.cwd() / "interviews.yaml"


def _parse_topics(value: Any) -> list[TopicSpec]:
    """
    Parse and validate the `topics` section from the YAML.

    The expected format is a list of single-key mappings, where the key is the
    topic name and the value is a list of orientations.

    Args:
        value:
            Raw YAML value.

    Returns:
        A list of TopicSpec objects.

    Raises:
        ConfigError:
            If the structure does not match the expected schema.
    """

    if not isinstance(value, list) or not value:
        raise ConfigError("'topics' must be a non-empty list")

    topics: list[TopicSpec] = []
    for idx, item in enumerate(value, start=1):
        if not isinstance(item, dict) or len(item) != 1:
            raise ConfigError(
                "Each item in 'topics' must be a mapping with exactly one key (topic name)"
                f" (problem at index {idx})"
            )

        (topic_name, orientations) = next(iter(item.items()))
        if not isinstance(topic_name, str) or not topic_name.strip():
            raise ConfigError(f"Topic name must be a non-empty string (problem at index {idx})")
        if not isinstance(orientations, list) or not all(
            isinstance(o, str) and o.strip() for o in orientations
        ):
            raise ConfigError(
                f"Orientations for topic '{topic_name}' must be a list of non-empty strings"
            )

        topics.append(
            TopicSpec(topic=topic_name.strip(), orientations=[o.strip() for o in orientations])
        )

    return topics


def load_config(path: Path) -> InterviewConfig:
    """
    Load and validate an `interviews.yaml` configuration file.

    Args:
        path:
            Path to the YAML config file.

    Returns:
        A validated InterviewConfig instance.

    Raises:
        ConfigError:
            If the file is missing, unreadable, cannot be parsed as YAML, or is
            missing required keys.
    """

    if not path.exists():
        raise ConfigError(
            "No interviews.yaml found in current directory and no --config provided. "
            "Use --write-template to create one or pass --config PATH."
        )
    if not path.is_file():
        raise ConfigError(f"Config path is not a file: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"Failed to read YAML config: {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config YAML must contain a mapping at the top level")

    missing = [k for k in ("include", "workdir", "outfile", "topics") if k not in raw]
    if missing:
        raise ConfigError(f"Config is missing required key(s): {', '.join(missing)}")

    include = raw.get("include")
    if not isinstance(include, str) or not include.strip():
        raise ConfigError("'include' must be a non-empty string")

    exclude = raw.get("exclude")
    if exclude is not None and (not isinstance(exclude, str) or not exclude.strip()):
        raise ConfigError("'exclude' must be a non-empty string if provided")

    workdir = raw.get("workdir")
    if not isinstance(workdir, str) or not workdir.strip():
        raise ConfigError("'workdir' must be a non-empty string")

    outfile = raw.get("outfile")
    if not isinstance(outfile, str) or not outfile.strip():
        raise ConfigError("'outfile' must be a non-empty string")

    topics = _parse_topics(raw.get("topics"))

    segmentation = _parse_segmentation(raw.get("segmentation"))

    # Interpret workdir/outfile and glob patterns relative to config file location.
    base_dir = path.parent.resolve()
    workdir_path = (base_dir / workdir).resolve()
    outfile_path = (base_dir / outfile).resolve()

    return InterviewConfig(
        config_path=path.resolve(),
        base_dir=base_dir,
        include=include.strip(),
        exclude=exclude.strip() if isinstance(exclude, str) else None,
        workdir=workdir_path,
        outfile=outfile_path,
        topics=topics,
        segmentation=segmentation,
    )


def _parse_segmentation(value: Any) -> SegmentationConfig:
    """
    Parse and validate the optional `segmentation` section.

    Args:
        value:
            Raw YAML value for the `segmentation` key.

    Returns:
        A SegmentationConfig instance (with defaults if section is missing).

    Raises:
        ConfigError:
            If the section exists but is not valid.
    """

    if value is None:
        return SegmentationConfig()

    if not isinstance(value, dict):
        raise ConfigError("'segmentation' must be a mapping if provided")

    segment_paragraphs = value.get("segment_paragraphs", SegmentationConfig.segment_paragraphs)
    overlap_paragraphs = value.get("overlap_paragraphs", SegmentationConfig.overlap_paragraphs)

    if not isinstance(segment_paragraphs, int):
        raise ConfigError("segmentation.segment_paragraphs must be an integer")
    if not isinstance(overlap_paragraphs, int):
        raise ConfigError("segmentation.overlap_paragraphs must be an integer")

    if segment_paragraphs <= 0:
        raise ConfigError("segmentation.segment_paragraphs must be > 0")
    if overlap_paragraphs < 0:
        raise ConfigError("segmentation.overlap_paragraphs must be >= 0")
    if overlap_paragraphs >= segment_paragraphs:
        raise ConfigError(
            "segmentation.overlap_paragraphs must be < segmentation.segment_paragraphs"
        )

    return SegmentationConfig(
        segment_paragraphs=segment_paragraphs,
        overlap_paragraphs=overlap_paragraphs,
    )
