# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Codebook helpers.

The YAML configuration supports multiple ways to define topics. Once parsed into
`TopicSpec` objects, this module converts them into a normalized structure that
is passed to the LLM and written into analysis work files.
"""

import json
from typing import Any

from interview_analysis.config import OrientationSpec, TopicSpec
from interview_analysis.hash_utils import md5_text


def build_codebook(topics: list[TopicSpec]) -> dict[str, Any]:
    """Build the codebook structure passed to the LLM and written to work files."""

    out: list[dict[str, Any]] = []
    for idx, spec in enumerate(topics, start=1):
        orientation_labels: list[str] = []
        orientation_details: list[dict[str, Any]] = []

        for o in spec.orientations:
            if not isinstance(o, OrientationSpec):
                continue
            label = o.label.strip()
            if not label:
                continue
            orientation_labels.append(label)
            detail: dict[str, Any] = {"label": label}
            if isinstance(o.description, str) and o.description.strip():
                detail["description"] = o.description.strip()
            orientation_details.append(detail)

        entry: dict[str, Any] = {
            "id": f"t{idx}",
            "topic": spec.topic,
            # Keep "orientations" as a list of strings for backwards compatibility
            # with existing prompting/validation logic.
            "orientations": orientation_labels,
            "allow_multiple_orientations": bool(getattr(spec, "allow_multiple_orientations", False)),
        }
        if isinstance(spec.description, str) and spec.description.strip():
            entry["description"] = spec.description.strip()
        if orientation_details:
            entry["orientation_details"] = orientation_details
        out.append(entry)

    return {"topics": out}


def codebook_hash(codebook: dict[str, Any]) -> str:
    """Return a stable hash for a normalized codebook.

    This is used for incremental analysis: if the codebook changes, re-run the
    LLM coding even if segments did not change.
    """

    canonical = json.dumps(codebook, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return md5_text(canonical)


def orientations_by_topic(codebook: dict[str, Any]) -> dict[str, list[str]]:
    """Return a mapping topic -> allowed orientations list."""

    topics = codebook.get("topics")
    if not isinstance(topics, list):
        return {}

    mapping: dict[str, list[str]] = {}
    for t in topics:
        if not isinstance(t, dict):
            continue
        name = t.get("topic")
        orientations = t.get("orientations")
        if not isinstance(name, str):
            continue
        if not isinstance(orientations, list) or not all(isinstance(x, str) for x in orientations):
            orientations = []
        mapping[name] = [x for x in (o.strip() for o in orientations) if x]

    return mapping
