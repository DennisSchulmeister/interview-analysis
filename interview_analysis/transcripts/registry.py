# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""Transcript parser registry."""

from pathlib import Path

from interview_analysis.config import ConfigError
from interview_analysis.transcripts.base import ParserError, TranscriptParser
from interview_analysis.transcripts.odt_parser import OdtTranscriptParser
from interview_analysis.transcripts.text_parser import TextTranscriptParser


# Bump this whenever transcript parsing semantics change in a way that should
# force regeneration of segment work files even if the underlying transcript
# file bytes are unchanged.
TRANSCRIPT_PARSING_VERSION = 5


_PARSERS: list[TranscriptParser] = [
    OdtTranscriptParser(),
    TextTranscriptParser(),
]


def get_transcript_parser(path: Path) -> TranscriptParser:
    """Select a transcript parser based on the file.

    Args:
        path:
            Transcript file path.

    Returns:
        A parser instance.

    Raises:
        ConfigError:
            If no parser supports the file.
    """

    for parser in _PARSERS:
        if parser.can_read(path):
            return parser

    supported = ", ".join(sorted({".odt", ".txt", ".md"}))
    raise ConfigError(f"Unsupported transcript format: {path} (supported: {supported})")


def read_transcript_paragraphs(path: Path) -> list[dict[str, object]]:
    """Read a transcript and normalize errors to ConfigError."""

    parser = get_transcript_parser(path)
    try:
        return parser.read_paragraphs(path)
    except ParserError as exc:
        raise ConfigError(str(exc)) from exc
