# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Shared statement parsing helpers.

File format parsers (TXT/MD/ODT) extract *raw* text blocks/paragraphs. This
module turns those blocks into normalized statement records:

- Speaker statements start with `Label: ...`.
- Unlabeled blocks are treated as a continuation of the previous statement.
- Unlabeled blocks *before* the first statement are ignored (common for
  transcription tool headers).
- Metadata blocks (currently `interviewer = ...`) are preserved as special
  records with `source_index = 0`.

The output is compatible with the segmentation step.
"""

import re
from typing import Any, Iterable


# Accept common Markdown prefixes (block quotes, bullet points, numbered lists)
# before a required `Label: ...` pattern.
_LABEL_RE = re.compile(
    r"^\s*(?:>\s*)*(?:[-+*]\s+|\d+[\.)]\s+)?(?P<label>[^:\n]{1,80}):\s*\S"
)

# Allow the metadata marker to be formatted like normal statements in Markdown
# (e.g., block quotes or list items) and ignore case.
_META_RE = re.compile(
    r"^\s*(?:>\s*)*(?:[-+*]\s+|\d+[\.)]\s+)?(?P<key>[A-Za-z][A-Za-z0-9_\-]{0,63})\s*=\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)


def parse_statement_blocks(blocks: Iterable[str]) -> list[dict[str, Any]]:
    """Parse extracted blocks into statement paragraph records.

    Args:
        blocks:
            Iterable of raw text blocks/paragraphs. Empty/whitespace-only blocks
            are ignored.

    Returns:
        Paragraph records with stable `source_index` numbering for statements.
        Metadata blocks are included with `source_index = 0`.
    """

    paragraphs: list[dict[str, Any]] = []
    statement_index = 0

    for block in blocks:
        cleaned = " ".join(str(block).split())
        if not cleaned:
            continue

        meta = _META_RE.match(cleaned)
        if meta:
            key = (meta.group("key") or "").strip().lower()
            value = (meta.group("value") or "").strip()
            paragraphs.append(
                {
                    "source_index": 0,
                    "text": f"{key} = {value}",
                }
            )
            continue

        if _LABEL_RE.match(cleaned):
            statement_index += 1
            paragraphs.append({"source_index": statement_index, "text": cleaned})
            continue

        # Ignore any unlabeled blocks before the first statement.
        if statement_index == 0:
            continue

        # Continuation: append to the last *statement* (skip metadata records).
        prev_statement: dict[str, Any] | None = None
        for rec in reversed(paragraphs):
            if int(rec.get("source_index") or 0) != 0:
                prev_statement = rec
                break

        if prev_statement is None:
            # Defensive: should not happen if statement_index > 0.
            continue

        prev_text = str(prev_statement.get("text") or "")
        prev_statement["text"] = (prev_text + " " + cleaned).strip()

    return paragraphs
