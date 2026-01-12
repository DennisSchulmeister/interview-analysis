# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""YAML I/O helpers.

This module centralizes common YAML loading behavior used across actions.
"""

from pathlib import Path
from typing import Any

import yaml

from interview_analysis.config import ConfigError


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file into a dictionary.

    Args:
        path:
            YAML file path.

    Returns:
        Parsed YAML mapping.

    Raises:
        ConfigError:
            If the file cannot be read or does not contain a mapping.
    """

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"Failed to read YAML file '{path}': {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"YAML file must contain a mapping: {path}")

    return raw
