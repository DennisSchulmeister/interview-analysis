# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Transcript parser interface."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class TranscriptParser(Protocol):
    """Interface for transcript file parsing.

    Implementations must only perform raw text extraction and normalization.
    Any higher-level metadata detection must remain outside the parser.
    """

    def can_read(self, path: Path) -> bool:
        """Return True if this parser supports the given file."""

        raise NotImplementedError

    def read_paragraphs(self, path: Path) -> list[dict[str, Any]]:
        """Return paragraph/statement records for the given transcript file."""

        raise NotImplementedError


@dataclass(frozen=True)
class ParserError(RuntimeError):
    """Raised for transcript parsing errors."""

    message: str
    path: Path | None = None
    line: int | None = None
    excerpt: str | None = None

    def __str__(self) -> str:  # pragma: no cover
        parts: list[str] = []

        if self.path is not None:
            if self.line is not None:
                parts.append(f"{self.path}:{self.line}: {self.message}")
            else:
                parts.append(f"{self.path}: {self.message}")
        else:
            parts.append(self.message)

        if isinstance(self.excerpt, str) and self.excerpt.strip():
            excerpt = self.excerpt.strip().replace("\n", " ")
            if len(excerpt) > 160:
                excerpt = excerpt[:157] + "..."
            parts.append(f"> {excerpt}")

        return "\n".join(parts)
