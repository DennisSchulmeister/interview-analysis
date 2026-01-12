# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""ODT transcript parser."""

from pathlib import Path
from typing import Any

from odfdo import Document

from interview_analysis.transcripts.base import ParserError, TranscriptParser
from interview_analysis.transcripts.statement_blocks import parse_statement_blocks


class OdtTranscriptParser:
    """Parse ODT files into paragraph records."""

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() == ".odt"

    def read_paragraphs(self, path: Path) -> list[dict[str, Any]]:
        """Extract plain-text paragraphs from an ODT document.

        Each paragraph in the result corresponds to one source paragraph.
        Whitespace is normalized to single spaces.
        """

        try:
            doc = Document(path)
            body = doc.body

            blocks: list[str] = []
            for p in body.get_paragraphs():
                text = getattr(p, "text", None)
                if text is None:
                    text = str(p)
                blocks.append(str(text))

            return parse_statement_blocks(blocks)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"Failed to parse ODT file '{path}': {exc}") from exc
