# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Data segmentation action.

This action turns transcript documents into stable, paragraph-based text passages
with unique IDs for later coding.

Segments are overlapping to provide local context. The overlap portion is marked
as reference-only so downstream coding can ignore it when counting frequency.
"""

import argparse
import fnmatch
import glob
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from odfdo import Document

from interview_analysis.config import ConfigError, InterviewConfig


@dataclass(frozen=True)
class SegmentAction:
    """
    `segment` subcommand.

    Intended to segment transcripts into stable text passages for later coding.
    """

    name: str = "segment"
    help: str = "Run data segmentation"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `segment` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        _ = parser

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute data segmentation.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            ConfigError:
                If configured segmentation options are invalid or if input files
                cannot be processed.
        """

        if config is None:
            raise RuntimeError("SegmentAction requires a config, but none was provided")

        _ = args
        segment_paragraphs = config.segmentation.segment_paragraphs
        overlap_paragraphs = config.segmentation.overlap_paragraphs

        workdir = config.workdir
        workdir.mkdir(parents=True, exist_ok=True)

        out_dir = workdir / "segments"
        out_dir.mkdir(parents=True, exist_ok=True)

        input_files = self._discover_input_files(config)
        if not input_files:
            print("No input transcript files found.")
            return

        index: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "path": str(config.config_path),
            },
            "segmentation": {
                "unit": "paragraph",
                "segment_paragraphs": segment_paragraphs,
                "overlap_paragraphs": overlap_paragraphs,
                "step_paragraphs": segment_paragraphs - overlap_paragraphs,
            },
            "documents": [],
        }

        written = 0
        for input_path in input_files:
            doc_record = self._segment_one_file(
                config=config,
                input_path=input_path,
                out_dir=out_dir,
                segment_paragraphs=segment_paragraphs,
                overlap_paragraphs=overlap_paragraphs,
            )
            index["documents"].append(doc_record)
            written += 1

        index_path = out_dir / "index.yaml"
        index_path.write_text(
            yaml.safe_dump(index, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        print(f"Segmented {written} transcript(s). Wrote index: {index_path}")

    def _discover_input_files(self, config: InterviewConfig) -> list[Path]:
        """
        Find transcript files based on include/exclude patterns.

        Patterns are resolved relative to the directory containing the YAML
        configuration.

        Args:
            config:
                Loaded configuration.

        Returns:
            Sorted list of paths to transcript files.
        """

        base_dir = config.base_dir

        include = self._normalize_glob_pattern(config.include)
        include_glob = str((base_dir / include).as_posix())
        matches = glob.glob(include_glob, recursive=True)
        paths = [Path(p) for p in matches]

        exclude = config.exclude
        if exclude:
            exclude_norm = self._normalize_glob_pattern(exclude)
            paths = [
                p
                for p in paths
                if not fnmatch.fnmatch(self._rel_posix(base_dir, p), exclude_norm)
            ]

        paths = [p for p in paths if p.is_file()]
        return sorted({p.resolve() for p in paths})

    def _segment_one_file(
        self,
        *,
        config: InterviewConfig,
        input_path: Path,
        out_dir: Path,
        segment_paragraphs: int,
        overlap_paragraphs: int,
    ) -> dict[str, Any]:
        """
        Segment one transcript file and write its YAML work file.

        Args:
            config:
                Loaded configuration.
            input_path:
                Path to the transcript (ODT).
            out_dir:
                Output directory inside the workdir.
            segment_paragraphs:
                Number of paragraphs per segment.
            overlap_paragraphs:
                Number of overlapping paragraphs.

        Returns:
            A document entry for the index file.
        """

        source_paragraphs = self._extract_odt_paragraphs(input_path)
        metadata, transcript_paragraphs = self._extract_document_metadata(source_paragraphs)
        doc_id = self._document_id(config.base_dir, input_path)
        rel_path = self._rel_posix(config.base_dir, input_path)

        segments = self._build_segments(
            doc_id=doc_id,
            paragraphs=transcript_paragraphs,
            segment_paragraphs=segment_paragraphs,
            overlap_paragraphs=overlap_paragraphs,
        )

        out_path = out_dir / f"{doc_id}.yaml"
        payload: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "path": rel_path,
                "absolute_path": str(input_path.resolve()),
            },
            "document_id": doc_id,
            "metadata": metadata,
            "segmentation": {
                "unit": "paragraph",
                "segment_paragraphs": segment_paragraphs,
                "overlap_paragraphs": overlap_paragraphs,
                "step_paragraphs": segment_paragraphs - overlap_paragraphs,
            },
            "source_paragraphs_total": len(source_paragraphs),
            "paragraphs_total": len(transcript_paragraphs),
            "segments": segments,
        }
        out_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        return {
            "document_id": doc_id,
            "source_path": rel_path,
            "segments_file": str(out_path),
            "paragraphs_total": len(transcript_paragraphs),
            "segments_total": len(segments),
        }

    def _extract_odt_paragraphs(self, path: Path) -> list[dict[str, Any]]:
        """
        Extract plain-text paragraphs from an ODT document.

        This function intentionally discards formatting. Each paragraph in the
        result corresponds to a transcript paragraph (typically one speaker turn).

        Args:
            path:
                ODT path.

        Returns:
            List of paragraph dictionaries (trimmed, without empty paragraphs).

            Each paragraph dictionary has:
                - `source_index`: 1-based paragraph number in the source document
                - `text`: normalized plain text

        Raises:
            ConfigError:
                If the file cannot be read or parsed.
        """

        try:
            doc = Document(path)
            body = doc.body
            paras: list[dict[str, Any]] = []
            source_index = 0
            for p in body.get_paragraphs():
                source_index += 1
                text = getattr(p, "text", None)
                if text is None:
                    # Fall back to string conversion if the API differs.
                    text = str(p)
                cleaned = " ".join(str(text).split())
                if cleaned:
                    paras.append({"source_index": source_index, "text": cleaned})
            return paras
        except Exception as exc:  # noqa: BLE001
            raise ConfigError(f"Failed to parse ODT file '{path}': {exc}") from exc

    def _extract_document_metadata(
        self,
        paragraphs: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Extract document metadata from special paragraphs.

        Currently supported metadata:
        - `interviewer = ...` (case-insensitive)

        The metadata paragraph(s) are removed from the paragraph list so they do
        not become part of segments and do not affect paragraph IDs.

        Args:
            paragraphs:
                Paragraph records extracted from the source.

        Returns:
            A tuple of (`metadata`, `transcript_paragraphs`).
        """

        interviewer_pattern = re.compile(r"^\s*interviewer\s*=\s*(.*?)\s*$", re.IGNORECASE)

        interviewers: list[str] = []
        transcript_paragraphs: list[dict[str, Any]] = []
        removed_metadata_paragraphs = 0

        for para in paragraphs:
            text = str(para.get("text", ""))
            match = interviewer_pattern.match(text)
            if match is None:
                transcript_paragraphs.append(para)
                continue

            removed_metadata_paragraphs += 1
            raw = (match.group(1) or "").strip()
            if raw:
                for part in raw.split(","):
                    label = part.strip()
                    if label and label not in interviewers:
                        interviewers.append(label)

        metadata: dict[str, Any] = {
            "interviewers": interviewers,
            "metadata_paragraphs_removed": removed_metadata_paragraphs,
        }
        return metadata, transcript_paragraphs

    def _build_segments(
        self,
        *,
        doc_id: str,
        paragraphs: list[dict[str, Any]],
        segment_paragraphs: int,
        overlap_paragraphs: int,
    ) -> list[dict[str, Any]]:
        """
        Build overlapping paragraph segments.

        The overlap exists to provide context. Paragraphs in the overlap portion
        are marked with role `ref`, while non-overlapping paragraphs are marked
        as `new`.

        Args:
            doc_id:
                Stable document identifier.
            paragraphs:
                Paragraph records.
            segment_paragraphs:
                Number of paragraphs per segment.
            overlap_paragraphs:
                Number of overlapping paragraphs.

        Returns:
            List of segment dictionaries ready for YAML serialization.
        """

        total = len(paragraphs)
        if total == 0:
            return []

        step = segment_paragraphs - overlap_paragraphs
        segments: list[dict[str, Any]] = []
        seg_index = 0
        start = 0
        while start < total:
            end_exclusive = min(start + segment_paragraphs, total)

            start_source_index = int(paragraphs[start]["source_index"])
            end_source_index = int(paragraphs[end_exclusive - 1]["source_index"])

            para_records: list[dict[str, Any]] = []
            for idx in range(start, end_exclusive):
                para = paragraphs[idx]
                source_index = int(para["source_index"])
                text = str(para["text"])

                role = "new"
                if seg_index > 0 and overlap_paragraphs > 0 and idx < start + overlap_paragraphs:
                    role = "ref"

                para_records.append(
                    {
                        "id": f"{doc_id}:p{source_index:04d}",
                        "index": source_index,
                        "role": role,
                        "text": text,
                    }
                )

            segment_id = f"{doc_id}:p{start_source_index:04d}-p{end_source_index:04d}"
            segments.append(
                {
                    "id": segment_id,
                    "segment_index": seg_index + 1,
                    "start_paragraph": start_source_index,
                    "end_paragraph": end_source_index,
                    "overlap_paragraphs": overlap_paragraphs if seg_index > 0 else 0,
                    "paragraphs": para_records,
                }
            )

            seg_index += 1
            start += step
        return segments

    def _document_id(self, base_dir: Path, input_path: Path) -> str:
        """
        Compute a stable document identifier from the file path.

        Args:
            base_dir:
                Base directory for relative path calculation.
            input_path:
                Absolute transcript path.

        Returns:
            A stable, filesystem-friendly identifier.
        """

        rel = self._rel_posix(base_dir, input_path)
        digest = hashlib.sha1(rel.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        stem = input_path.stem
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in stem)
        safe = safe.strip("_") or "document"
        return f"{safe}-{digest}"

    def _normalize_glob_pattern(self, pattern: str) -> str:
        """
        Normalize user-provided glob patterns to Python's recursive glob syntax.

        The sample config uses `**.odt`, which is not a standard recursive glob
        segment. This function converts patterns like `**.odt` to `**/*.odt`.

        Args:
            pattern:
                Raw pattern from config.

        Returns:
            A pattern suitable for `glob.glob(..., recursive=True)`.
        """

        p = pattern.strip()
        if p.startswith("**.") and "/" not in p:
            ext = p[3:]
            return f"**/*.{ext}"
        if p == "**" or p == "**/":
            return "**/*"
        return p

    def _rel_posix(self, base_dir: Path, path: Path) -> str:
        """
        Compute a stable POSIX-style relative path.

        Args:
            base_dir:
                Base directory.
            path:
                Path to relativize.

        Returns:
            Relative path using '/' separators.
        """

        try:
            rel = path.resolve().relative_to(base_dir.resolve())
        except Exception:  # noqa: BLE001
            rel = path.resolve()
        return rel.as_posix()
