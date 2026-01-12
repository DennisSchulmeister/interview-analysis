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
from typing import Any

from interview_analysis.transcripts.base import ParserError, TranscriptParser
from interview_analysis.transcripts.statement_blocks import parse_statement_blocks


class TextTranscriptParser:
    """Parse .txt and .md transcripts into statement records."""

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

        return parse_statement_blocks(block for _, block in blocks)
