# Interview Analysis
# © 2026 Dennis Schulmeister-Zimolong <dennis@wpvs.de>
#
# This source code is licensed under the BSD 3-Clause License found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

"""
Output writer action.

This action writes a final `.ods` report based on the analysis work files.

The output contains:
        - A summary sheet with topic/orientation counts and an example quote.
        - One sheet per transcript containing a full, chronological track record of
            evidence quotes.
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odfdo import Document
from odfdo.cell import Cell
from odfdo.row import Row
from odfdo.table import Table

from interview_analysis.cli_io import is_interactive_tty, prompt_overwrite
from interview_analysis.config import ConfigError, InterviewConfig
from interview_analysis.yaml_io import read_yaml_mapping


@dataclass(frozen=True)
class WriteOutputAction:
    """
    `write-output` subcommand.

    Intended to write the final `.ods` report based on earlier segmentation and
    analysis outputs.
    """

    name: str = "write-output"
    help: str = "Write the output file (.ods)"
    requires_config: bool = True

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        Register CLI arguments for the `write-output` subcommand.

        Args:
            parser:
                Subparser for this command.

        Returns:
            None
        """

        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="Overwrite the output file if it already exists",
        )

    def run(self, args: argparse.Namespace, config: InterviewConfig | None) -> None:
        """
        Execute output writing.

        Args:
            args:
                Parsed args for the subcommand.
            config:
                Loaded configuration.

        Returns:
            None

        Raises:
            RuntimeError:
                If prerequisites are missing or output cannot be written.
        """

        if config is None:
            raise RuntimeError("WriteOutputAction requires a config, but none was provided")

        outfile = config.outfile
        if outfile.exists() and not bool(getattr(args, "force", False)):
            if not is_interactive_tty():
                raise RuntimeError(
                    f"Output file already exists: {outfile}. Refusing to overwrite in non-interactive mode. "
                    "Use --force to overwrite."
                )
            if not prompt_overwrite(outfile):
                print(f"Keeping existing file: {outfile}")
                return

        analysis_dir = config.workdir / "analysis"
        analysis_index = analysis_dir / "index.yaml"
        if not analysis_index.exists():
            raise ConfigError(
                "No analysis index found. Run the 'analyze' command first: "
                f"{analysis_index}"
            )

        print(f"Loading analysis index: {analysis_index}")
        index = read_yaml_mapping(analysis_index)
        documents = index.get("documents")
        if not isinstance(documents, list) or not documents:
            print("No documents found in analysis index. Nothing to write.")
            return

        print(f"Building ODS report: {outfile}")
        doc = Document.new("spreadsheet")

        # odfdo creates a default empty sheet (often named "Feuille1").
        # Remove all existing tables so the output contains only our sheets.
        for table in list(doc.body.tables):
            doc.body.delete(table)

        summary_rows, per_doc_rows = self._collect_rows(documents, base_dir=config.base_dir)

        self._append_summary_sheet(doc, summary_rows)
        self._append_transcript_sheets(doc, per_doc_rows)

        outfile.parent.mkdir(parents=True, exist_ok=True)
        doc.save(outfile)
        print(f"Wrote ODS report: {outfile}")

    def _collect_rows(
        self,
        documents: list[Any],
        *,
        base_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Collect summary and per-document track records from analysis work files.

        Args:
            documents:
                Documents list from analysis index.

        Returns:
            Tuple of:
                - summary rows (topic/orientation aggregated)
                - per-document rows (each includes sheet name and evidence rows)
        """

        summary_counts: dict[tuple[str, str], dict[str, Any]] = {}
        per_doc: list[dict[str, Any]] = []

        loaded: list[dict[str, Any]] = []
        stem_counts: dict[str, int] = {}

        # First pass: load analysis work files and detect duplicate stems.
        for doc_entry in documents:
            if not isinstance(doc_entry, dict):
                continue
            analysis_file = doc_entry.get("analysis_file")
            if not isinstance(analysis_file, str) or not analysis_file.strip():
                continue
            path = self._resolve_from_base(base_dir, analysis_file)
            if not path.exists():
                print(f"Skipping missing analysis file: {path}")
                continue

            analyzed = read_yaml_mapping(path)
            doc_id = analyzed.get("document_id")
            if not isinstance(doc_id, str) or not doc_id.strip():
                print(f"Skipping analysis file without document_id: {path}")
                continue

            source = analyzed.get("source")
            source_path = None
            if isinstance(source, dict):
                source_path = source.get("path")
            stem = None
            if isinstance(source_path, str) and source_path.strip():
                stem = Path(source_path).stem.strip()
            if stem:
                stem_counts[stem] = stem_counts.get(stem, 0) + 1

            loaded.append(
                {
                    "doc_id": doc_id,
                    "source_path": source_path,
                    "analyzed": analyzed,
                }
            )

        # Second pass: collect evidence rows using stable display ids.
        for entry in loaded:
            doc_id = str(entry.get("doc_id") or "")
            source_path = entry.get("source_path")
            analyzed = entry.get("analyzed")
            if not isinstance(analyzed, dict):
                continue

            display_id = self._display_id(
                doc_id=doc_id,
                source_path=source_path,
                base_dir=base_dir,
                stem_counts=stem_counts,
            )
            sheet_name = self._sheet_name(display_id=display_id)

            segments = analyzed.get("segments")
            if not isinstance(segments, list):
                print(f"Skipping analysis file without segments: {doc_id}")
                continue

            evidence_rows: list[dict[str, Any]] = []
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                seg_id = segment.get("id")
                if not isinstance(seg_id, str):
                    seg_id = ""

                paras = segment.get("paragraphs")
                if not isinstance(paras, list):
                    continue

                for p in paras:
                    if not isinstance(p, dict):
                        continue
                    assigns = p.get("assignments")
                    if not isinstance(assigns, list) or not assigns:
                        continue

                    para_id = p.get("id")
                    para_index = p.get("index")
                    if not isinstance(para_id, str):
                        continue

                    for a in assigns:
                        if not isinstance(a, dict):
                            continue
                        topic = a.get("topic")
                        orientation = a.get("orientation")
                        evidence = a.get("evidence")
                        if not isinstance(topic, str) or not isinstance(evidence, str):
                            continue

                        topic_key = topic.strip()
                        orientation_key = ""
                        if isinstance(orientation, str):
                            orientation_key = orientation.strip()
                        elif orientation is None:
                            orientation_key = ""

                        if not topic_key:
                            continue

                        orientation_bucket = orientation_key if orientation_key else "(none)"

                        key = (topic_key, orientation_bucket)
                        agg = summary_counts.setdefault(
                            key,
                            {
                                "topic": topic_key,
                                "orientation": orientation_bucket,
                                "count": 0,
                                "example_quote": evidence,
                            },
                        )
                        agg["count"] = int(agg.get("count", 0)) + 1

                        # Each sheet contains exactly one transcript, so the
                        # paragraph id is sufficient.
                        where_found = self._pretty_paragraph_ref(para_id)
                        evidence_rows.append(
                            {
                                "topic": topic_key,
                                "orientation": orientation_bucket,
                                "where_found": where_found,
                                "evidence": evidence,
                                "paragraph_index": para_index,
                            }
                        )

            evidence_rows.sort(
                key=lambda r: (
                    int(r.get("paragraph_index") or 0),
                    str(r.get("where_found") or ""),
                )
            )

            per_doc.append(
                {
                    "document_id": doc_id,
                    "source_path": source_path,
                    "sheet_name": sheet_name,
                    "rows": evidence_rows,
                }
            )

        summary_rows = sorted(
            summary_counts.values(),
            key=lambda r: (str(r.get("topic") or ""), str(r.get("orientation") or "")),
        )
        return summary_rows, per_doc

    def _resolve_from_base(self, base_dir: Path, path_value: str) -> Path:
        """Resolve a potentially-relative path from the config base dir."""

        p = Path(path_value)
        if p.is_absolute():
            return p
        return (base_dir / p).resolve()

    def _append_summary_sheet(self, doc: Document, rows: list[dict[str, Any]]) -> None:
        """
        Add the summary sheet to the ODS document.

        Args:
            doc:
                ODF spreadsheet document.
            rows:
                Summary rows.

        Returns:
            None
        """

        print("Writing sheet: Summary")
        table = Table("Summary")

        header = Row()
        header.append_cell(Cell(text="Topic"))
        header.append_cell(Cell(text="Orientation"))
        header.append_cell(Cell(text="Count"))
        header.append_cell(Cell(text="Example quote"))
        table.append_row(header)

        for r in rows:
            row = Row()
            row.append_cell(Cell(text=str(r.get("topic", ""))))
            row.append_cell(Cell(text=str(r.get("orientation", ""))))
            row.append_cell(Cell(value=int(r.get("count", 0))))
            row.append_cell(Cell(text=str(r.get("example_quote", ""))))
            table.append_row(row)

        doc.body.append(table)

    def _append_transcript_sheets(self, doc: Document, per_doc: list[dict[str, Any]]) -> None:
        """
        Add one sheet per transcript with the full evidence track record.

        Args:
            doc:
                ODF spreadsheet document.
            per_doc:
                Per-document data, including sheet names and evidence rows.

        Returns:
            None
        """

        used_names: set[str] = {"Summary"}
        for entry in per_doc:
            name = str(entry.get("sheet_name") or "Transcript")
            name = self._unique_sheet_name(name, used_names)
            used_names.add(name)

            print(f"Writing sheet: {name}")
            table = Table(name)

            header = Row()
            header.append_cell(Cell(text="Topic"))
            header.append_cell(Cell(text="Orientation"))
            header.append_cell(Cell(text="Where Found"))
            header.append_cell(Cell(text="Evidence Quote"))
            table.append_row(header)

            rows = entry.get("rows")
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    row = Row()
                    row.append_cell(Cell(text=str(r.get("topic", ""))))
                    row.append_cell(Cell(text=str(r.get("orientation", ""))))
                    row.append_cell(Cell(text=str(r.get("where_found", ""))))
                    row.append_cell(Cell(text=str(r.get("evidence", ""))))
                    table.append_row(row)

            doc.body.append(table)

    def _sheet_name(self, *, display_id: str) -> str:
        """Determine a human-readable sheet name for the ODS.

        We use the unique display id (stem or path-based) so sheet names match
        the identifiers shown in the report.
        """

        base = str(display_id or "Transcript").strip() or "Transcript"
        base = base.replace("/", "_").replace("\\", "_")
        return base[:31]

    def _display_id(
        self,
        *,
        doc_id: str,
        source_path: str | None,
        base_dir: Path | None = None,
        stem_counts: dict[str, int] | None = None,
    ) -> str:
        """Return a human-friendly document label for the report.

        Internal `document_id` values contain a short hash suffix for stability
        and uniqueness. For report output, we prefer the file stem when
        available, otherwise we strip the `-<10hex>` suffix if present.
        """

        if isinstance(source_path, str) and source_path.strip():
            src = Path(source_path)
            stem = src.stem.strip()
            if stem:
                counts = stem_counts or {}
                if counts.get(stem, 0) <= 1:
                    return stem

                # If the stem is not unique, include the relative directory to disambiguate.
                # Example: "group1/Lecturer A" instead of "Lecturer A".
                rel = src.with_suffix("")
                try:
                    if isinstance(base_dir, Path):
                        rel = rel.relative_to(base_dir)
                except Exception:
                    # If relative_to fails (e.g., old absolute paths), keep the best effort.
                    pass
                return rel.as_posix()

        return re.sub(r"-[0-9a-f]{10}$", "", doc_id)

    def _pretty_where_found(self, where_found: str, *, doc_id: str, display_id: str) -> str:
        """Rewrite internal IDs into prettier report identifiers."""

        # 1) Prefer an exact match for this document's internal id.
        prefix = f"{doc_id}:"
        out = where_found
        if prefix:
            out = out.replace(prefix, f"{display_id}:")

        # 2) Also strip any "-<10hex>" suffix used in internal document ids.
        # This fixes cases where the analysis file's `document_id` or the
        # evidence ids are not perfectly aligned.
        def _repl(m: re.Match[str]) -> str:
            return f"{display_id}:{m.group(2)}"

        out = re.sub(
            r"\b([A-Za-z0-9_-]+)-[0-9a-f]{10}:(p\d{4}(?:-p\d{4})?)\b",
            _repl,
            out,
        )
        return out

    def _pretty_paragraph_ref(self, para_id: str) -> str:
        """Return a compact paragraph reference for per-transcript sheets.

        The paragraph id is normally `${document_id}:p0003`. Within a
        transcript sheet, `p0003` is sufficient.
        """

        if not isinstance(para_id, str):
            return ""

        m = re.search(r"\b(p\d{4})\b", para_id)
        if m:
            return m.group(1)

        # Fallback: strip everything up to the last colon.
        return para_id.rsplit(":", 1)[-1]

    def _unique_sheet_name(self, name: str, used: set[str]) -> str:
        """
        Ensure a sheet name is unique within the document.

        Args:
            name:
                Preferred name.
            used:
                Already used names.

        Returns:
            A unique name.
        """

        candidate = name[:31]
        if candidate not in used:
            return candidate

        idx = 2
        while True:
            suffix = f"_{idx}"
            trimmed = candidate[: max(1, 31 - len(suffix))] + suffix
            if trimmed not in used:
                return trimmed
            idx += 1

    
