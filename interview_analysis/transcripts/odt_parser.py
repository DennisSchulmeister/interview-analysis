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

            def _node_text(node: object) -> str:
                # odfdo Paragraph objects often expose richer text via
                # `inner_text`/`text_recursive` than via `.text`.
                for attr in ("inner_text", "text_recursive", "text"):
                    if hasattr(node, attr):
                        try:
                            value = getattr(node, attr)
                            if callable(value):
                                value = value()
                            if value is not None:
                                return str(value)
                        except Exception:
                            pass
                return str(node)

            blocks: list[str] = []

            # Using XPath is more robust than `get_paragraphs()` for documents
            # converted from DOCX or containing formatted content (lists, tables,
            # frames, etc.).
            nodes: list[object] = []
            try:
                nodes = list(body.xpath(".//text:p | .//text:h"))
            except Exception:
                nodes = []

            if nodes:
                for n in nodes:
                    blocks.append(_node_text(n))
            else:
                # Fallback for unexpected odfdo versions/doc structures.
                for p in body.get_paragraphs():
                    blocks.append(_node_text(p))

            return parse_statement_blocks(blocks)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"Failed to parse ODT file '{path}': {exc}") from exc
