# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Smoke-test helpers.

Run via:

    poetry run python -m interview_analysis.smoke

This is intentionally lightweight: it only validates parsing and codebook
normalization/hashing (no LLM calls).
"""

import argparse
import json
from pathlib import Path

from interview_analysis.codebook import build_codebook, codebook_hash, orientations_by_topic
from interview_analysis.config import ConfigError, load_config


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interview Analysis smoke test")
    parser.add_argument(
        "--config",
        default="interviews.yaml",
        help="Path to interviews.yaml (default: ./interviews.yaml)",
    )
    parser.add_argument(
        "--print-codebook",
        action="store_true",
        help="Print the normalized codebook JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = Path(str(args.config))

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    codebook = build_codebook(cfg.topics)
    cb_hash = codebook_hash(codebook)
    allowed = orientations_by_topic(codebook)

    topic_count = 0
    orientation_count = 0
    details_count = 0

    topics = codebook.get("topics")
    if isinstance(topics, list):
        topic_count = len(topics)
        for t in topics:
            if not isinstance(t, dict):
                continue
            orientations = t.get("orientations")
            if isinstance(orientations, list):
                orientation_count += len([o for o in orientations if isinstance(o, str) and o.strip()])
            od = t.get("orientation_details")
            if isinstance(od, list):
                details_count += len(od)

    print(f"Config: {cfg.config_path}")
    print(f"Base dir: {cfg.base_dir}")
    print(f"Topics: {topic_count}")
    print(f"Orientations (labels): {orientation_count}")
    print(f"Orientations (with details): {details_count}")
    print(f"Codebook hash: {cb_hash}")

    # Small sanity check: allowed orientations mapping should only contain strings.
    bad = [k for k, v in allowed.items() if not isinstance(k, str) or not all(isinstance(x, str) for x in v)]
    if bad:
        print(f"INTERNAL ERROR: invalid allowed-orientations mapping for topics: {bad}")
        return 3

    if bool(args.print_codebook):
        print(json.dumps(codebook, ensure_ascii=False, sort_keys=True, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
