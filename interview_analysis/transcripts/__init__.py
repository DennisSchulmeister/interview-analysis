"""Transcript parsing.

The segmentation step can read transcripts from different source formats.
Each parser converts the source file into a normalized list of paragraph records:

- `source_index`: 1-based statement/paragraph number in the source
- `text`: plain text content (whitespace-normalized)

Metadata detection (e.g. interviewer labels) is handled elsewhere.
"""

from interview_analysis.transcripts.base import TranscriptParser
from interview_analysis.transcripts.registry import get_transcript_parser

__all__ = [
    "TranscriptParser",
    "get_transcript_parser",
]
