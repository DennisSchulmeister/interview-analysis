# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""TXT/Markdown transcript parser.

Rules:
- Statements are separated by at least one empty line.
- A statement should start with a label in the form `Name: ...`.
- If a block does not start with a label, it is treated as a continuation of the
  previous statement.

The parser only performs raw parsing and text normalization.
"""

from pathlib import Path
import re
from typing import Any

from interview_analysis.transcripts.base import ParserError, TranscriptParser


class TextTranscriptParser:
    """Parse .txt and .md transcripts into statement records."""

    # Accept common Markdown prefixes (block quotes, bullet points, numbered lists)
    # before a required `Label: ...` pattern.
    _LABEL_RE = re.compile(
        r"^\s*(?:>\s*)*(?:[-+*]\s+|\d+[\.)]\s+)?(?P<label>[^:\n]{1,80}):\s*\S"
    )

    # Allow the metadata marker to be formatted like normal statements in Markdown
    # (e.g., block quotes or list items) and ignore case.
    _INTERVIEWER_META_RE = re.compile(
        r"^\s*(?:>\s*)*(?:[-+*]\s+|\d+[\.)]\s+)?interviewer\s*=\s*(?P<value>.*?)\s*$",
        re.IGNORECASE,
    )

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".md"}

    def read_paragraphs(self, path: Path) -> list[dict[str, Any]]:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"Failed to read text file: {exc}", path=path) from exc

        text = raw.replace("\r\n", "\n").replace("\r", "\n")

        blocks: list[tuple[int, str]] = []
        current: list[str] = []
        start_line: int | None = None

        for idx, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                if current:
                    blocks.append((start_line or idx, "\n".join(current).strip()))
                    current = []
                    start_line = None
                continue

            if start_line is None:
                start_line = idx
            current.append(line)

        if current:
            blocks.append((start_line or 1, "\n".join(current).strip()))

        paragraphs: list[dict[str, Any]] = []
        statement_index = 0

        for block_start_line, block in blocks:
            cleaned = " ".join(block.split())
            if not cleaned:
                continue

            meta = self._INTERVIEWER_META_RE.match(cleaned)
            if meta:
                # Keep metadata as a paragraph record so the segment action can
                # extract it, but ensure it does not affect paragraph numbering.
                paragraphs.append(
                    {
                        "source_index": 0,
                        "text": f"interviewer = {(meta.group('value') or '').strip()}",
                    }
                )
                continue

            if self._LABEL_RE.match(cleaned):
                statement_index += 1
                paragraphs.append({"source_index": statement_index, "text": cleaned})
                continue

            if not paragraphs:
                first_line = block.splitlines()[0].strip() if block.splitlines() else cleaned
                # Instead of failing hard, skip unparseable leading blocks and
                # try to continue with later blocks.
                continue

            # Continuation: append to previous statement.
            prev = paragraphs[-1]
            prev_text = str(prev.get("text") or "")
            prev["text"] = (prev_text + " " + cleaned).strip()

        return paragraphs
