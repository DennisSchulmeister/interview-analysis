# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Topic frequency analysis action.

This action reads segmentation work files from the work directory, calls the LLM
to assign topics/orientations to each statement (paragraph), and writes YAML work
files that capture the assignments and the exact evidence text.
"""

import argparse
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from interview_analysis.ai_llm import ai_conversation_json
from interview_analysis.config import ConfigError, InterviewConfig
from interview_analysis.hash_utils import md5_file
from interview_analysis.yaml_io import read_yaml_mapping


@dataclass(frozen=True)
class AnalyzeAction:
    """
    `analyze` subcommand.

    Intended to locate exact text passages per topic and compute frequency and
    predominant orientation without interpretive analysis.
    """

    name: str = "analyze"
    help: str = "Run topic coding using the LLM"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `analyze` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        _ = parser

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute topic frequency analysis.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            RuntimeError:
                If no configuration was provided.
        """

        _ = args
        if config is None:
            raise RuntimeError("AnalyzeAction requires a config, but none was provided")

        asyncio.run(self._run_async(config))

    async def _run_async(self, config: InterviewConfig) -> None:
        """
        Run the analysis pipeline.

        Args:
            config:
                Loaded configuration.

        Returns:
            None
        """

        workdir = config.workdir
        segments_dir = workdir / "segments"
        segments_index = segments_dir / "index.yaml"

        if not segments_index.exists():
            raise ConfigError(
                "No segmentation index found. Run the 'segment' command first: "
                f"{segments_index}"
            )

        analysis_dir = workdir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        print(f"Loading segmentation index: {segments_index}")
        index = read_yaml_mapping(segments_index)
        documents = index.get("documents")
        if not isinstance(documents, list) or not documents:
            print("No documents found in segmentation index. Nothing to analyze.")
            return

        codebook = self._build_codebook(config)
        strategy = config.analysis.strategy
        exclude_interviewer = config.analysis.exclude_interviewer

        analysis_index: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "path": str(config.config_path),
            },
            "analysis": {
                "strategy": strategy,
                "exclude_interviewer": exclude_interviewer,
            },
            "documents": [],
        }

        total_docs = len(documents)
        for doc_idx, doc_entry in enumerate(documents, start=1):
            if not isinstance(doc_entry, dict):
                print(f"Skipping invalid document entry at index {doc_idx}")
                continue

            segments_file = doc_entry.get("segments_file")
            if not isinstance(segments_file, str) or not segments_file.strip():
                print(f"Skipping document entry without segments_file at index {doc_idx}")
                continue

            segments_path = Path(segments_file)
            if not segments_path.exists():
                print(f"Skipping missing segments file: {segments_path}")
                continue

            segments_md5 = md5_file(segments_path)
            derived_doc_id = segments_path.stem
            out_path = analysis_dir / f"{derived_doc_id}.yaml"

            if out_path.exists():
                existing = read_yaml_mapping(out_path)
                if self._analysis_up_to_date(
                    existing,
                    segments_file=str(segments_path),
                    segments_md5=segments_md5,
                    strategy=strategy,
                    exclude_interviewer=exclude_interviewer,
                ):
                    existing_doc_id = existing.get("document_id")
                    doc_id = (
                        existing_doc_id.strip()
                        if isinstance(existing_doc_id, str) and existing_doc_id.strip()
                        else derived_doc_id
                    )

                    existing_segments = existing.get("segments")
                    segments_total = len(existing_segments) if isinstance(existing_segments, list) else 0

                    print(f"[{doc_idx}/{total_docs}] Skipping unchanged analysis: {doc_id}")
                    analysis_index["documents"].append(
                        {
                            "document_id": doc_id,
                            "analysis_file": str(out_path),
                            "segments_total": segments_total,
                        }
                    )
                    continue

            print(f"[{doc_idx}/{total_docs}] Loading segments: {segments_path}")
            seg_doc = read_yaml_mapping(segments_path)

            doc_id = seg_doc.get("document_id")
            if not isinstance(doc_id, str) or not doc_id.strip():
                print(f"Skipping segments file without document_id: {segments_path}")
                continue

            out_path = analysis_dir / f"{doc_id}.yaml"

            metadata = seg_doc.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            interviewers = metadata.get("interviewers")
            if not isinstance(interviewers, list) or not all(isinstance(x, str) for x in interviewers):
                interviewers = []

            segments = seg_doc.get("segments")
            if not isinstance(segments, list):
                print(f"Skipping segments file without segments list: {segments_path}")
                continue

            print(
                f"[{doc_idx}/{total_docs}] Analyzing document '{doc_id}' "
                f"with {len(segments)} segment(s) (strategy={strategy})"
            )

            analyzed_segments: list[dict[str, Any]] = []
            for seg_idx, segment in enumerate(segments, start=1):
                if not isinstance(segment, dict):
                    continue

                seg_id = segment.get("id")
                if not isinstance(seg_id, str) or not seg_id.strip():
                    continue

                seg_paras = segment.get("paragraphs")
                if not isinstance(seg_paras, list):
                    continue

                print(f"  - Segment {seg_idx}/{len(segments)}: {seg_id}")

                paragraph_records = self._prepare_paragraphs_for_coding(
                    seg_paras,
                    exclude_interviewer=exclude_interviewer,
                    interviewer_labels=interviewers,
                )

                result: dict[str, Any] = {
                    "id": seg_id,
                    "segment_index": segment.get("segment_index"),
                    "start_paragraph": segment.get("start_paragraph"),
                    "end_paragraph": segment.get("end_paragraph"),
                    "paragraphs": paragraph_records,
                    "errors": [],
                }

                target_paragraphs = [p for p in paragraph_records if p.get("target") is True]
                if not target_paragraphs:
                    analyzed_segments.append(result)
                    continue

                if strategy == "segment":
                    mapping, errors = await self._code_segment_full_codebook(
                        segment_id=seg_id,
                        paragraphs=paragraph_records,
                        codebook=codebook,
                        exclude_interviewer=exclude_interviewer,
                        interviewer_labels=interviewers,
                    )
                else:
                    mapping, errors = await self._code_segment_per_topic(
                        segment_id=seg_id,
                        paragraphs=paragraph_records,
                        codebook=codebook,
                        exclude_interviewer=exclude_interviewer,
                        interviewer_labels=interviewers,
                    )

                if errors:
                    result["errors"].extend(errors)

                self._apply_assignments(paragraph_records, mapping)
                analyzed_segments.append(result)

            payload: dict[str, Any] = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "config": {
                    "path": str(config.config_path),
                },
                "input": {
                    "segments_file": str(segments_path),
                    "segments_md5": segments_md5,
                },
                "document_id": doc_id,
                "source": seg_doc.get("source"),
                "metadata": metadata,
                "analysis": {
                    "strategy": strategy,
                    "exclude_interviewer": exclude_interviewer,
                },
                "codebook": codebook,
                "segments": analyzed_segments,
            }

            out_path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

            analysis_index["documents"].append(
                {
                    "document_id": doc_id,
                    "analysis_file": str(out_path),
                    "segments_total": len(analyzed_segments),
                }
            )

        index_path = analysis_dir / "index.yaml"
        index_path.write_text(
            yaml.safe_dump(analysis_index, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"Wrote analysis index: {index_path}")

    def _analysis_up_to_date(
        self,
        existing: dict[str, Any],
        *,
        segments_file: str,
        segments_md5: str,
        strategy: str,
        exclude_interviewer: bool,
    ) -> bool:
        """Return True if an existing analysis work file matches current inputs."""

        inp = existing.get("input")
        if not isinstance(inp, dict):
            return False

        if str(inp.get("segments_file") or "") != segments_file:
            return False

        if str(inp.get("segments_md5") or "") != segments_md5:
            return False

        analysis_cfg = existing.get("analysis")
        if not isinstance(analysis_cfg, dict):
            return False

        if str(analysis_cfg.get("strategy") or "") != strategy:
            return False

        if bool(analysis_cfg.get("exclude_interviewer")) != exclude_interviewer:
            return False

        return True

    def _build_codebook(self, config: InterviewConfig) -> dict[str, Any]:
        """
        Build the codebook structure passed to the LLM and written to work files.

        Args:
            config:
                Loaded configuration.

        Returns:
            Codebook mapping.
        """

        topics: list[dict[str, Any]] = []
        for idx, spec in enumerate(config.topics, start=1):
            topics.append(
                {
                    "id": f"t{idx}",
                    "topic": spec.topic,
                    "orientations": list(spec.orientations),
                }
            )
        return {"topics": topics}

    def _prepare_paragraphs_for_coding(
        self,
        paragraphs: list[Any],
        *,
        exclude_interviewer: bool,
        interviewer_labels: list[str],
    ) -> list[dict[str, Any]]:
        """
        Prepare paragraph records from a segmentation work file for LLM coding.

        Args:
            paragraphs:
                Paragraph list from the segmentation segment record.
            exclude_interviewer:
                Whether interviewer statements should be excluded from coding.
            interviewer_labels:
                List of interviewer labels extracted from transcript metadata.

        Returns:
            Normalized paragraph records.
        """

        prepared: list[dict[str, Any]] = []
        for p in paragraphs:
            if not isinstance(p, dict):
                continue

            para_id = p.get("id")
            text = p.get("text")
            role = p.get("role")

            if not isinstance(para_id, str) or not isinstance(text, str):
                continue

            excluded_reason: str | None = None
            if role == "ref":
                excluded_reason = "overlap_reference"

            if excluded_reason is None and exclude_interviewer:
                if self._is_interviewer_statement(text, interviewer_labels):
                    excluded_reason = "interviewer_statement"

            target = excluded_reason is None and role == "new"

            prepared.append(
                {
                    "id": para_id,
                    "index": p.get("index"),
                    "role": role,
                    "text": text,
                    "target": target,
                    "excluded_reason": excluded_reason,
                    "assignments": [],
                }
            )

        return prepared

    def _is_interviewer_statement(self, text: str, interviewer_labels: list[str]) -> bool:
        """
        Heuristic to decide whether a statement is attributed to the interviewer.

        This matches prefixes like `Name:` or `Name -` at the start of the
        paragraph.

        Args:
            text:
                Paragraph text.
            interviewer_labels:
                List of interviewer labels.

        Returns:
            True if the statement appears to be spoken by the interviewer.
        """

        stripped = text.lstrip()
        if not stripped or not interviewer_labels:
            return False

        for label in interviewer_labels:
            if not label.strip():
                continue
            escaped = re.escape(label.strip())
            if re.match(rf"^{escaped}\s*[:\-–]\s+", stripped, flags=re.IGNORECASE):
                return True
        return False

    def _build_system_prompt(
        self,
        *,
        exclude_interviewer: bool,
        interviewer_labels: list[str],
        extra_instructions: list[str] | None = None,
    ) -> str:
        """
        Build the system prompt shared by both analysis strategies.

        Args:
            exclude_interviewer:
                Whether interviewer statements should be excluded.
            interviewer_labels:
                Interviewer labels extracted from transcript metadata.
            extra_instructions:
                Optional extra system-level instructions.

        Returns:
            System prompt text.
        """

        system_parts = [
            "You are assisting with a qualitative content coding task.",
            "Do not interpret or infer.",
            "Only assign if there is explicit textual evidence.",
            "Always quote the exact evidence text from the paragraph.",
        ]

        if extra_instructions:
            system_parts.extend([x for x in extra_instructions if x.strip()])

        if exclude_interviewer and interviewer_labels:
            system_parts.append(
                "Important: Ignore interviewer statements. A paragraph is an interviewer statement if it starts "
                "with one of these labels: "
                + ", ".join(interviewer_labels)
                + ". Do not assign any topics/orientations to interviewer statements."
            )

        return " ".join(system_parts)

    async def _call_llm_json(self, *, system: str, user_payload: dict[str, Any]) -> Any:
        """
        Call the LLM with a system prompt and a YAML-serialized payload.

        Args:
            system:
                System prompt.
            user_payload:
                User payload that is serialized to YAML for readability.

        Returns:
            Parsed JSON response (or an error object with `_error`).
        """

        return await ai_conversation_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": yaml.safe_dump(user_payload, sort_keys=False)},
            ]
        )

    async def _code_segment_full_codebook(
        self,
        *,
        segment_id: str,
        paragraphs: list[dict[str, Any]],
        codebook: dict[str, Any],
        exclude_interviewer: bool,
        interviewer_labels: list[str],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        """
        Code a segment with a single LLM call using the full codebook.

        Args:
            segment_id:
                Segment identifier.
            paragraphs:
                Paragraph records (including context and targets).
            codebook:
                Codebook mapping.

        Returns:
            Tuple of (paragraph_id -> assignments list, errors list).
        """

        system = self._build_system_prompt(
            exclude_interviewer=exclude_interviewer,
            interviewer_labels=interviewer_labels,
            extra_instructions=[
                "Only assign a topic/orientation if the paragraph explicitly contains textual evidence.",
            ],
        )

        user_payload = {
            "segment_id": segment_id,
            "task": (
                "For each paragraph where target=true, assign zero or more topics from the codebook. "
                "For each assignment, choose exactly one allowed orientation for that topic and "
                "provide an evidence quote that appears verbatim in the paragraph."
            ),
            "interviewer_labels": interviewer_labels if exclude_interviewer else [],
            "codebook": codebook,
            "paragraphs": [
                {
                    "id": p["id"],
                    "role": p.get("role"),
                    "target": bool(p.get("target")),
                    "text": p.get("text", ""),
                }
                for p in paragraphs
            ],
            "output_format": {
                "paragraphs": [
                    {
                        "id": "<paragraph id>",
                        "assignments": [
                            {
                                "topic": "<topic name>",
                                "orientation": "<one of the allowed orientations>",
                                "evidence": "<exact quote from the paragraph>",
                            }
                        ],
                    }
                ]
            },
        }

        result = await self._call_llm_json(system=system, user_payload=user_payload)

        mapping: dict[str, list[dict[str, Any]]] = {}
        errors: list[str] = []

        if isinstance(result, dict) and "_error" in result:
            errors.append(str(result.get("_error")))
            return mapping, errors

        if not isinstance(result, dict):
            errors.append("LLM returned non-object JSON")
            return mapping, errors

        para_items = result.get("paragraphs")
        if not isinstance(para_items, list):
            errors.append("LLM response missing 'paragraphs' list")
            return mapping, errors

        for item in para_items:
            if not isinstance(item, dict):
                continue
            pid = item.get("id")
            assigns = item.get("assignments")
            if not isinstance(pid, str) or not isinstance(assigns, list):
                continue
            normalized: list[dict[str, Any]] = []
            for a in assigns:
                if not isinstance(a, dict):
                    continue
                topic = a.get("topic")
                orientation = a.get("orientation")
                evidence = a.get("evidence")
                if not isinstance(topic, str) or not isinstance(orientation, str) or not isinstance(evidence, str):
                    continue
                if not topic.strip() or not orientation.strip() or not evidence.strip():
                    continue
                normalized.append(
                    {
                        "topic": topic.strip(),
                        "orientation": orientation.strip(),
                        "evidence": evidence,
                    }
                )
            if normalized:
                mapping[pid] = normalized

        return mapping, errors

    async def _code_segment_per_topic(
        self,
        *,
        segment_id: str,
        paragraphs: list[dict[str, Any]],
        codebook: dict[str, Any],
        exclude_interviewer: bool,
        interviewer_labels: list[str],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        """
        Code a segment by calling the LLM once per topic.

        Args:
            segment_id:
                Segment identifier.
            paragraphs:
                Paragraph records.
            codebook:
                Codebook mapping.

        Returns:
            Tuple of (paragraph_id -> assignments list, errors list).
        """

        topics = codebook.get("topics")
        if not isinstance(topics, list):
            return {}, ["Invalid codebook: missing topics"]

        combined: dict[str, list[dict[str, Any]]] = {}
        errors: list[str] = []

        system = self._build_system_prompt(
            exclude_interviewer=exclude_interviewer,
            interviewer_labels=interviewer_labels,
        )

        for topic in topics:
            if not isinstance(topic, dict):
                continue
            topic_name = topic.get("topic")
            orientations = topic.get("orientations")
            if not isinstance(topic_name, str) or not isinstance(orientations, list):
                continue

            print(f"    * Topic: {topic_name}")
            user_payload = {
                "segment_id": segment_id,
                "task": (
                    "For each paragraph where target=true, decide whether it explicitly addresses the given topic. "
                    "If yes, select exactly one orientation from the allowed list and provide an evidence quote "
                    "that appears verbatim in the paragraph."
                ),
                "interviewer_labels": interviewer_labels if exclude_interviewer else [],
                "topic": {
                    "topic": topic_name,
                    "orientations": orientations,
                },
                "paragraphs": [
                    {
                        "id": p["id"],
                        "target": bool(p.get("target")),
                        "text": p.get("text", ""),
                    }
                    for p in paragraphs
                ],
                "output_format": {
                    "matches": [
                        {
                            "paragraph_id": "<paragraph id>",
                            "orientation": "<one of the allowed orientations>",
                            "evidence": "<exact quote from the paragraph>",
                        }
                    ]
                },
            }

            result = await self._call_llm_json(system=system, user_payload=user_payload)

            if isinstance(result, dict) and "_error" in result:
                errors.append(f"{topic_name}: {result.get('_error')}")
                continue

            if not isinstance(result, dict):
                errors.append(f"{topic_name}: LLM returned non-object JSON")
                continue

            matches = result.get("matches")
            if not isinstance(matches, list):
                errors.append(f"{topic_name}: missing matches list")
                continue

            for m in matches:
                if not isinstance(m, dict):
                    continue
                pid = m.get("paragraph_id")
                orientation = m.get("orientation")
                evidence = m.get("evidence")
                if not isinstance(pid, str) or not isinstance(orientation, str) or not isinstance(evidence, str):
                    continue
                if not pid.strip() or not orientation.strip() or not evidence.strip():
                    continue

                combined.setdefault(pid, []).append(
                    {
                        "topic": topic_name,
                        "orientation": orientation.strip(),
                        "evidence": evidence,
                    }
                )

        return combined, errors

    def _apply_assignments(
        self,
        paragraphs: list[dict[str, Any]],
        mapping: dict[str, list[dict[str, Any]]],
    ) -> None:
        """
        Apply paragraph assignments to the prepared paragraph records.

        Args:
            paragraphs:
                Prepared paragraph records.
            mapping:
                Mapping of paragraph_id -> assignments.

        Returns:
            None
        """

        for p in paragraphs:
            if p.get("target") is not True:
                p["assignments"] = []
                continue

            pid = p.get("id")
            if not isinstance(pid, str):
                p["assignments"] = []
                continue

            assigns = mapping.get(pid, [])
            if not isinstance(assigns, list):
                p["assignments"] = []
                continue

            p["assignments"] = assigns
