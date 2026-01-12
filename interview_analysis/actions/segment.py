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

from interview_analysis.config import ConfigError, InterviewConfig
from interview_analysis.hash_utils import md5_file
from interview_analysis.transcripts.registry import TRANSCRIPT_PARSING_VERSION, read_transcript_paragraphs
from interview_analysis.yaml_io import read_yaml_mapping


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
                "path": self._rel_posix(config.base_dir, config.config_path),
            },
            "transcript_parsing_version": TRANSCRIPT_PARSING_VERSION,
            "segmentation": {
                "unit": "paragraph",
                "segment_paragraphs": segment_paragraphs,
                "overlap_paragraphs": overlap_paragraphs,
                "step_paragraphs": segment_paragraphs - overlap_paragraphs,
            },
            "documents": [],
        }

        updated = 0
        skipped = 0
        failed = 0
        for input_path in input_files:
            doc_record, did_update = self._segment_one_file(
                config=config,
                input_path=input_path,
                out_dir=out_dir,
                segment_paragraphs=segment_paragraphs,
                overlap_paragraphs=overlap_paragraphs,
            )
            index["documents"].append(doc_record)
            if doc_record.get("status") == "failed":
                failed += 1
            elif did_update:
                updated += 1
            else:
                skipped += 1

        index_path = out_dir / "index.yaml"
        index_path.write_text(
            yaml.safe_dump(index, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        total = len(input_files)
        print(
            f"Processed {total} transcript(s): updated {updated}, skipped {skipped}, failed {failed}. "
            f"Wrote index: {index_path}"
        )

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

        include_patterns = config.include
        paths: list[Path] = []
        for pat in include_patterns:
            include = self._normalize_glob_pattern(pat)
            include_glob = str((base_dir / include).as_posix())
            matches = glob.glob(include_glob, recursive=True)
            paths.extend(Path(p) for p in matches)

        exclude_patterns = config.exclude or []
        if exclude_patterns:
            exclude_norms = [self._normalize_glob_pattern(p) for p in exclude_patterns]
            paths = [
                p
                for p in paths
                if not any(
                    fnmatch.fnmatch(self._rel_posix(base_dir, p), ex)
                    for ex in exclude_norms
                )
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
    ) -> tuple[dict[str, Any], bool]:
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

        doc_id = self._document_id(config.base_dir, input_path)
        rel_path = self._rel_posix(config.base_dir, input_path)
        out_path = out_dir / f"{doc_id}.yaml"

        transcript_md5 = md5_file(input_path)
        if out_path.exists():
            existing = read_yaml_mapping(out_path)
            if self._segments_up_to_date(
                existing,
                rel_path=rel_path,
                transcript_md5=transcript_md5,
                segment_paragraphs=segment_paragraphs,
                overlap_paragraphs=overlap_paragraphs,
            ):
                print(f"Skipping unchanged transcript: {rel_path}")
                segments = existing.get("segments")
                segments_total = len(segments) if isinstance(segments, list) else 0
                paragraphs_total = int(existing.get("paragraphs_total") or 0)
                return (
                    {
                        "document_id": doc_id,
                        "source_path": rel_path,
                        "segments_file": self._rel_posix(config.base_dir, out_path),
                        "paragraphs_total": paragraphs_total,
                        "segments_total": segments_total,
                    },
                    False,
                )

        print(f"Segmenting: {rel_path} ", end="", flush=True)

        try:
            source_paragraphs = read_transcript_paragraphs(input_path)
        except ConfigError as exc:
            print()  # finish progress line
            print(f"WARNING: Skipping transcript due to parse error: {rel_path}\n{exc}")
            return (
                {
                    "document_id": doc_id,
                    "source_path": rel_path,
                    "status": "failed",
                    "error": str(exc),
                },
                False,
            )
        metadata, transcript_paragraphs = self._extract_document_metadata(source_paragraphs)

        segments = self._build_segments(
            doc_id=doc_id,
            paragraphs=transcript_paragraphs,
            segment_paragraphs=segment_paragraphs,
            overlap_paragraphs=overlap_paragraphs,
        )

        print("." * len(segments) + f" ({len(segments)} segment(s))")

        payload: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "transcript_parsing_version": TRANSCRIPT_PARSING_VERSION,
            "source": {
                "path": rel_path,
                "md5": transcript_md5,
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

        return (
            {
                "document_id": doc_id,
                "source_path": rel_path,
                "segments_file": self._rel_posix(config.base_dir, out_path),
                "paragraphs_total": len(transcript_paragraphs),
                "segments_total": len(segments),
            },
            True,
        )

    def _segments_up_to_date(
        self,
        existing: dict[str, Any],
        *,
        rel_path: str,
        transcript_md5: str,
        segment_paragraphs: int,
        overlap_paragraphs: int,
    ) -> bool:
        """Return True if an existing segment work file matches current inputs."""

        if int(existing.get("transcript_parsing_version") or 0) != TRANSCRIPT_PARSING_VERSION:
            return False

        source = existing.get("source")
        if not isinstance(source, dict):
            return False

        if str(source.get("path") or "") != rel_path:
            return False

        if str(source.get("md5") or "") != transcript_md5:
            return False

        seg_cfg = existing.get("segmentation")
        if not isinstance(seg_cfg, dict):
            return False

        if int(seg_cfg.get("segment_paragraphs") or 0) != segment_paragraphs:
            return False

        if int(seg_cfg.get("overlap_paragraphs") or 0) != overlap_paragraphs:
            return False

        return True

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

        meta_pattern = re.compile(
            r"^\s*(?P<key>[A-Za-z][A-Za-z0-9_\-]{0,63})\s*=\s*(?P<value>.*?)\s*$",
            re.IGNORECASE,
        )

        interviewers: list[str] = []
        interviewer_norm_seen: set[str] = set()
        fields: dict[str, Any] = {}
        transcript_paragraphs: list[dict[str, Any]] = []
        removed_metadata_paragraphs = 0

        for para in paragraphs:
            text = str(para.get("text", ""))
            match = meta_pattern.match(text)
            if match is None:
                transcript_paragraphs.append(para)
                continue

            removed_metadata_paragraphs += 1
            key = (match.group("key") or "").strip().lower()
            raw_value = (match.group("value") or "").strip()

            if key == "interviewer":
                if raw_value:
                    for part in raw_value.split(","):
                        label = " ".join(part.split()).strip()
                        label = label.rstrip(" :\t-–—").strip()
                        norm = label.casefold()
                        if label and norm not in interviewer_norm_seen:
                            interviewers.append(label)
                            interviewer_norm_seen.add(norm)
                continue

            if not raw_value:
                continue

            if key not in fields:
                fields[key] = raw_value
            else:
                prev = fields[key]
                if isinstance(prev, list):
                    if raw_value not in prev:
                        prev.append(raw_value)
                elif isinstance(prev, str):
                    if raw_value != prev:
                        fields[key] = [prev, raw_value]
                else:
                    fields[key] = raw_value

        metadata: dict[str, Any] = {
            "interviewers": interviewers,
            "metadata_paragraphs_removed": removed_metadata_paragraphs,
            "fields": fields,
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
