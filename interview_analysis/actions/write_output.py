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
from typing import Any, cast

from odfdo import Document
from odfdo.cell import Cell
from odfdo.row import Row
from odfdo.table import Table
from odfdo.style import Style
from odfdo.column import Column
from odfdo.element import Element
from odfdo.config_elements import ConfigItem, ConfigItemMapEntry

from interview_analysis.cli_io import is_interactive_tty, prompt_overwrite
from interview_analysis.config import ConfigError, InterviewConfig
from interview_analysis.hash_utils import md5_text
from interview_analysis.yaml_io import read_yaml_mapping


_XML_ILLEGAL_CHARS_RE = re.compile(
    # XML 1.0 disallows most C0 control chars except TAB, LF, CR.
    r"[\x00-\x08\x0B\x0C\x0E-\x1F]"
    # Surrogates are never valid Unicode scalar values.
    r"|[\uD800-\uDFFF]"
    # Noncharacters.
    r"|[\uFFFE\uFFFF]"
)


def _xml_safe_text(value: Any) -> str:
    """Return a string that is safe to embed in XML/ODS.

    lxml (used by odfdo) rejects NULL bytes and some control characters.
    We strip these characters to ensure report generation cannot abort on
    real-world transcripts.
    """

    if value is None:
        return ""

    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8", errors="replace")
        except Exception:
            text = str(value)
    else:
        text = str(value)

    if not text:
        return ""

    return _XML_ILLEGAL_CHARS_RE.sub("", text)


def _make_style_name(prefix: str, scope: str, *, suffix: str = "") -> str:
    """Return a stable, ODF-friendly style name.

    Some spreadsheet viewers are picky about style names; keep them ASCII-ish
    and deterministic.
    """

    scope_key = re.sub(r"[^A-Za-z0-9_]", "_", scope or "")
    scope_key = scope_key.strip("_")[:40] or "x"
    digest = md5_text(scope)[:8]
    if suffix:
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", suffix)
    parts = [prefix, scope_key, digest]
    if suffix:
        parts.append(suffix)
    return "_".join(p for p in parts if p)


def _insert_automatic_style(doc: Document, style: Style | None) -> Style | None:
    """Insert style into document automatic-styles so viewers can apply it."""

    if style is None:
        return None
    try:
        doc.insert_style(style, automatic=True)
        return style
    except Exception:
        return None


def _set_config_item(entry: Element, *, name: str, config_type: str, value: str | int | bool) -> None:
    existing = None
    for item in entry.get_elements("config:config-item"):
        if isinstance(item, ConfigItem) and item.name == name:
            existing = item
            break
    if existing is None:
        existing = ConfigItem(name=name, config_type=config_type, value=value)
        entry.append(existing)
    else:
        existing.config_type = config_type
        existing.value = value


def _freeze_first_row_in_settings(doc: Document) -> None:
    """Best-effort: configure view settings to freeze the first row in each sheet.

    LibreOffice/Calc stores freeze pane configuration in settings.xml under
    ooo:view-settings -> Views -> Tables.
    """

    try:
        table_names = [t.name for t in doc.body.tables if getattr(t, "name", None)]
        if not table_names:
            return

        settings = doc.settings
        view_settings = settings.get_element(
            '//config:config-item-set[@config:name="ooo:view-settings"]'
        )
        if view_settings is None:
            return

        views = view_settings.get_element(
            'config:config-item-map-indexed[@config:name="Views"]'
        )
        if views is None:
            return

        view_entry = views.get_element("config:config-item-map-entry")
        if view_entry is None:
            return

        tables_map = view_entry.get_element(
            'config:config-item-map-named[@config:name="Tables"]'
        )
        if tables_map is None:
            return

        template = tables_map.get_element("config:config-item-map-entry")
        if template is None:
            return
        template_entry = cast(ConfigItemMapEntry, template)

        # Replace table view entries with our sheet names.
        for child in list(tables_map.children):
            tables_map.delete(child)

        for name in table_names:
            entry = cast(ConfigItemMapEntry, template_entry.clone)
            entry.name = name

            # Freeze first row (row index 1), no frozen columns.
            _set_config_item(entry, name="HorizontalSplitMode", config_type="short", value=0)
            _set_config_item(entry, name="HorizontalSplitPosition", config_type="int", value=0)
            _set_config_item(entry, name="VerticalSplitMode", config_type="short", value=2)
            _set_config_item(entry, name="VerticalSplitPosition", config_type="int", value=1)

            tables_map.append(entry)
    except Exception:
        # Never fail report generation because of viewer-specific settings.
        return


def _col_letters(index_1_based: int) -> str:
    """Convert 1-based column index to spreadsheet letters (A, B, ..., AA, ...)."""

    if index_1_based <= 0:
        return "A"
    n = index_1_based
    out: list[str] = []
    while n:
        n, rem = divmod(n - 1, 26)
        out.append(chr(ord("A") + rem))
    return "".join(reversed(out))


def _quote_sheet_name_for_range(name: str) -> str:
    # ODF range addresses use single quotes around sheet names.
    safe = (name or "").replace("'", "''")
    return f"'{safe}'"


def _enable_autofilter(doc: Document, sheet_ranges: list[tuple[str, int, int]]) -> None:
    """Best-effort: enable auto filter dropdowns for each sheet.

    LibreOffice/Calc stores autofilter definitions in content.xml under
    <table:database-ranges>. We create a database range per sheet that covers
    A1 through the last used cell and mark it as having headers.
    """

    try:
        if not sheet_ranges:
            return

        # Remove any existing database-ranges to keep output deterministic.
        for existing in doc.body.get_elements("table:database-ranges"):
            doc.body.delete(existing)

        db_ranges = Element.from_tag("table:database-ranges")

        for sheet_name, ncols, nrows in sheet_ranges:
            if not sheet_name or ncols <= 0 or nrows <= 0:
                continue

            end_col = _col_letters(ncols)
            end_row = max(1, int(nrows))
            addr = f"{_quote_sheet_name_for_range(sheet_name)}.A1:{end_col}{end_row}"

            db = Element.from_tag("table:database-range")
            db.set_attribute("table:name", _make_style_name("db", sheet_name))
            db.set_attribute("table:target-range-address", addr)
            db.set_attribute("table:display-filter-buttons", "true")
            db.set_attribute("table:contains-header", "true")

            # Empty filter element; viewers typically treat this as “autofilter on”.
            flt = Element.from_tag("table:filter")
            flt.set_attribute("table:display-filter-buttons", "true")
            db.append(flt)

            db_ranges.append(db)

        doc.body.append(db_ranges)
    except Exception:
        return


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

        summary_rows, per_doc_rows = self._collect_rows(
            documents,
            base_dir=config.base_dir,
            codebook_topics=config.topics,
        )

        sheet_ranges: list[tuple[str, int, int]] = []

        sheet_ranges.append(self._append_summary_sheet(doc, summary_rows, config=config))
        sheet_ranges.extend(self._append_transcript_sheets(doc, per_doc_rows, config=config))

        _freeze_first_row_in_settings(doc)
        _enable_autofilter(doc, sheet_ranges)

        outfile.parent.mkdir(parents=True, exist_ok=True)
        doc.save(outfile)
        print(f"Wrote ODS report: {outfile}")

    def _collect_rows(
        self,
        documents: list[Any],
        *,
        base_dir: Path,
        codebook_topics: list[Any] | None = None,
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

        topic_order, orientation_order = self._build_codebook_order(codebook_topics or [])

        # Pre-seed the summary with all codebook entries so zero-count rows are shown.
        summary_counts: dict[tuple[str, str], dict[str, Any]] = self._seed_summary_counts(
            codebook_topics or []
        )
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
                        rationale = a.get("rationale")
                        rejected_assignments = a.get("rejected_assignments")
                        kind = a.get("kind")
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

                        kind_norm = "primary"
                        if isinstance(kind, str) and kind.strip().lower() in {"secondary", "minor", "s"}:
                            kind_norm = "secondary"

                        rationale_norm = ""
                        if isinstance(rationale, str):
                            rationale_norm = " ".join(rationale.split()).strip()

                        rejected_norm = self._format_rejected_assignments(rejected_assignments)

                        orientation_bucket = orientation_key if orientation_key else "(none)"

                        if kind_norm != "secondary":
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

                            # If the summary row was pre-seeded (zero-count), it
                            # starts with an empty example quote. Use the first
                            # observed evidence as the example.
                            if not str(agg.get("example_quote") or "").strip() and evidence.strip():
                                agg["example_quote"] = evidence

                        # Each sheet contains exactly one transcript, so the
                        # paragraph id is sufficient.
                        where_found = self._pretty_paragraph_ref(para_id)
                        evidence_rows.append(
                            {
                                "topic": topic_key,
                                "orientation": orientation_bucket,
                                "role": kind_norm,
                                "rationale": rationale_norm,
                                "rejected_assignments": rejected_norm,
                                "researcher_decision": "",
                                "researcher_comment": "",
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
            key=lambda r: self._summary_sort_key(
                r,
                topic_order=topic_order,
                orientation_order=orientation_order,
            ),
        )
        return summary_rows, per_doc

    def _build_codebook_order(
        self,
        topics: list[Any],
    ) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
        """Build stable ordering maps from the YAML config topics.

        Returns:
            - topic_order: topic -> index
            - orientation_order: (topic, orientation) -> index
        """

        topic_order: dict[str, int] = {}
        orientation_order: dict[tuple[str, str], int] = {}

        for t_idx, t in enumerate(topics, start=1):
            topic_name = getattr(t, "topic", None)
            if not isinstance(topic_name, str):
                continue
            topic_name = topic_name.strip()
            if not topic_name:
                continue

            topic_order.setdefault(topic_name, t_idx)

            orientations = getattr(t, "orientations", None)
            if not isinstance(orientations, list):
                continue

            if not orientations:
                # Topic has no explicit orientations; it will appear with "(none)".
                orientation_order.setdefault((topic_name, "(none)"), 1)
                continue

            for o_idx, o in enumerate(orientations, start=1):
                label = getattr(o, "label", None)
                if not isinstance(label, str):
                    continue
                label = label.strip()
                if not label:
                    continue
                orientation_order.setdefault((topic_name, label), o_idx)

        return topic_order, orientation_order

    def _seed_summary_counts(self, topics: list[Any]) -> dict[tuple[str, str], dict[str, Any]]:
        """Create summary rows for every codebook topic/orientation pair.

        This ensures the Summary sheet includes zero-count entries.
        """

        out: dict[tuple[str, str], dict[str, Any]] = {}
        for t in topics:
            topic_name = getattr(t, "topic", None)
            if not isinstance(topic_name, str) or not topic_name.strip():
                continue
            topic_name = topic_name.strip()

            orientations = getattr(t, "orientations", None)
            if not isinstance(orientations, list) or not orientations:
                key = (topic_name, "(none)")
                out.setdefault(
                    key,
                    {
                        "topic": topic_name,
                        "orientation": "(none)",
                        "count": 0,
                        "example_quote": "",
                    },
                )
                continue

            for o in orientations:
                label = getattr(o, "label", None)
                if not isinstance(label, str) or not label.strip():
                    continue
                label = label.strip()
                key = (topic_name, label)
                out.setdefault(
                    key,
                    {
                        "topic": topic_name,
                        "orientation": label,
                        "count": 0,
                        "example_quote": "",
                    },
                )

        return out

    def _summary_sort_key(
        self,
        row: dict[str, Any],
        *,
        topic_order: dict[str, int],
        orientation_order: dict[tuple[str, str], int],
    ) -> tuple[int, int, int, str, str]:
        """Sort summary rows by codebook order (topic, then orientations)."""

        topic = str(row.get("topic") or "").strip()
        orientation = str(row.get("orientation") or "").strip()

        # Topics not found in the configured codebook go last.
        t_idx = topic_order.get(topic, 1_000_000)

        # Orientations not found in the configured topic go last.
        o_idx = orientation_order.get((topic, orientation), 1_000_000)

        # Keep the synthetic bucket last within each topic, but only when it's
        # not part of the configured codebook (topics with no orientations use
        # "(none)" as their only valid orientation).
        none_bucket = 1 if orientation == "(none)" and (topic, orientation) not in orientation_order else 0
        if none_bucket:
            o_idx = 2_000_000

        return (t_idx, none_bucket, o_idx, orientation, topic)

    def _resolve_from_base(self, base_dir: Path, path_value: str) -> Path:
        """Resolve a potentially-relative path from the config base dir."""

        p = Path(path_value)
        if p.is_absolute():
            return p
        return (base_dir / p).resolve()

    def _append_summary_sheet(
        self,
        doc: Document,
        rows: list[dict[str, Any]],
        *,
        config: InterviewConfig,
    ) -> tuple[str, int, int]:
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

        require_evidence = bool(getattr(getattr(config.analysis, "llm_guidance", None), "require_textual_evidence", True))

        # Keep the Summary sheet stable, but drop the example quote column when
        # textual evidence is not required/desired.
        columns: list[tuple[str, str]] = [
            ("topic", "Topic"),
            ("orientation", "Orientation"),
            ("count", "Count"),
        ]
        if require_evidence:
            columns.append(("example_quote", "Example quote"))

        # Create a bold header style and apply it to the first row's cells.
        try:
            header_style = cast(
                Style,
                Style(
                "table-cell",
                name=_make_style_name("hdr", "Summary"),
                area="text",
                bold=True,
                ),
            )
        except Exception:
            header_style = None
        header_style = _insert_automatic_style(doc, header_style)

        # Compute simple column widths based on content length (cheap heuristic)
        col_max_chars: list[int] = [0] * len(columns)
        for c_idx, (_k, title) in enumerate(columns):
            col_max_chars[c_idx] = max(col_max_chars[c_idx], len(str(title or "")))
        for r in rows:
            for c_idx, (key, _title) in enumerate(columns):
                val = _xml_safe_text(r.get(key, ""))
                col_max_chars[c_idx] = max(col_max_chars[c_idx], len(str(val)))

        # Create and append column styles (table-column) to set widths.
        for c_idx, chars in enumerate(col_max_chars, start=1):
            # simple width heuristic: 0.12 cm per character, clamp to [3cm, 24cm]
            try:
                width_cm = max(3.0, min(chars * 0.12, 24.0))
                col_style = cast(
                    Style,
                    Style(
                    "table-column",
                    name=_make_style_name("col", "Summary", suffix=str(c_idx)),
                    area="table-column",
                    width=f"{width_cm:.2f}cm",
                    ),
                )
                # If supported by the viewer, prefer optimal width.
                col_style.set_properties(
                    {"style:use-optimal-column-width": "true"},
                    area="table-column",
                )
                col_style = _insert_automatic_style(doc, col_style)
                if col_style is None:
                    raise RuntimeError("style insert failed")
                col = Column(style=col_style.name)
                table.append(col)
            except Exception:
                # If style/column creation fails, continue without widths
                pass

        header = Row()
        for _key, title in columns:
            cell = Cell(text=_xml_safe_text(title))
            if header_style is not None:
                try:
                    cell.style = header_style
                except Exception:
                    pass
            header.append_cell(cell)
        # Put header row inside a table-header-rows element so it is treated
        # as a sheet header by many spreadsheet viewers (helps freezing).
        try:
            hdr_group = Element.from_tag("table:table-header-rows")
            hdr_group.append(header)
            table.append(hdr_group)
        except Exception:
            table.append_row(header)

        for r in rows:
            row = Row()
            for key, _title in columns:
                if key == "count":
                    row.append_cell(Cell(value=int(r.get("count", 0))))
                else:
                    row.append_cell(Cell(text=_xml_safe_text(r.get(key, ""))))
            table.append_row(row)

        doc.body.append(table)

        # (sheet name, columns, rows)
        return ("Summary", len(columns), 1 + len(rows))

    def _append_transcript_sheets(
        self,
        doc: Document,
        per_doc: list[dict[str, Any]],
        *,
        config: InterviewConfig,
    ) -> list[tuple[str, int, int]]:
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

        allow_secondary = bool(getattr(config.analysis, "allow_secondary_assignments", False))
        llm_guidance = getattr(config.analysis, "llm_guidance", None)
        explain_assignments = bool(getattr(llm_guidance, "explain_assignments", False))
        list_rejected = bool(getattr(llm_guidance, "list_rejected_assignments", False))
        require_evidence = bool(getattr(llm_guidance, "require_textual_evidence", True))

        # Only include columns that are enabled by the corresponding YAML settings.
        # The two researcher review columns are always present by design.
        columns: list[tuple[str, str]] = [
            ("topic", "Topic"),
            ("orientation", "Orientation"),
        ]
        if allow_secondary:
            columns.append(("role", "Role"))
        if explain_assignments:
            columns.append(("rationale", "Rationale"))
        if list_rejected:
            columns.append(("rejected_assignments", "Rejected Assignments"))
        columns.extend(
            [
                ("researcher_decision", "Researcher Decision (accepted/modified/rejected)"),
                ("final_topic", "Final Topic"),
                ("final_orientation", "Final Orientation"),
                ("researcher_comment", "Comment"),
                ("where_found", "Where Found"),
            ]
        )
        if require_evidence:
            columns.append(("evidence", "Evidence Quote"))

        out: list[tuple[str, int, int]] = []

        for entry in per_doc:
            name = str(entry.get("sheet_name") or "Transcript")
            name = self._unique_sheet_name(name, used_names)
            used_names.add(name)

            print(f"Writing sheet: {name}")
            table = Table(name)

            # Create header style for bold first row
            try:
                header_style = cast(
                    Style,
                    Style(
                    "table-cell",
                    name=_make_style_name("hdr", name),
                    area="text",
                    bold=True,
                    ),
                )
            except Exception:
                header_style = None
            header_style = _insert_automatic_style(doc, header_style)

            # Compute column widths from header and data
            rows = entry.get("rows") or []
            col_max_chars: list[int] = [0] * len(columns)
            for c_idx, (_k, title) in enumerate(columns):
                col_max_chars[c_idx] = max(col_max_chars[c_idx], len(str(title or "")))
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    for c_idx, (key, _title) in enumerate(columns):
                        val = _xml_safe_text(r.get(key, ""))
                        col_max_chars[c_idx] = max(col_max_chars[c_idx], len(str(val)))

            # Create and append column styles (table-column)
            for c_idx, chars in enumerate(col_max_chars, start=1):
                try:
                    width_cm = max(4.0, min(chars * 0.12, 24.0))
                    col_style = cast(
                        Style,
                        Style(
                        "table-column",
                        name=_make_style_name("col", name, suffix=str(c_idx)),
                        area="table-column",
                        width=f"{width_cm:.2f}cm",
                        ),
                    )
                    col_style.set_properties(
                        {"style:use-optimal-column-width": "true"},
                        area="table-column",
                    )
                    col_style = _insert_automatic_style(doc, col_style)
                    if col_style is None:
                        raise RuntimeError("style insert failed")
                    col = Column(style=col_style.name)
                    table.append(col)
                except Exception:
                    pass

            header = Row()
            for _key, title in columns:
                cell = Cell(text=_xml_safe_text(title))
                if header_style is not None:
                    try:
                        cell.style = header_style
                    except Exception:
                        pass
                header.append_cell(cell)
            try:
                hdr_group = Element.from_tag("table:table-header-rows")
                hdr_group.append(header)
                table.append(hdr_group)
            except Exception:
                table.append_row(header)

            rows = entry.get("rows")
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    row = Row()
                    for key, _title in columns:
                        row.append_cell(Cell(text=_xml_safe_text(r.get(key, ""))))
                    table.append_row(row)

            doc.body.append(table)

            out.append((name, len(columns), 1 + (len(rows) if isinstance(rows, list) else 0)))

        return out

    def _sheet_name(self, *, display_id: str) -> str:
        """Determine a human-readable sheet name for the ODS.

        We use the unique display id (stem or path-based) so sheet names match
        the identifiers shown in the report.
        """

        base = str(display_id or "Transcript").strip() or "Transcript"
        base = _xml_safe_text(base)
        base = base.replace("\n", " ").replace("\r", " ")
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

    def _format_rejected_assignments(self, value: Any) -> str:
        """Format rejected assignments list for a single spreadsheet cell."""

        if not isinstance(value, list) or not value:
            return ""

        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic")
            orientation = item.get("orientation")
            if not isinstance(topic, str) or not topic.strip():
                continue

            topic_key = topic.strip()
            orientation_key = ""
            if isinstance(orientation, str) and orientation.strip():
                orientation_key = orientation.strip()

            label = topic_key
            if orientation_key:
                label = f"{label} ({orientation_key})"
            parts.append(_xml_safe_text(label))

            if len(parts) >= 5:
                break

        return _xml_safe_text(" | ".join(parts))

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

        candidate = _xml_safe_text(name)
        candidate = candidate.replace("\n", " ").replace("\r", " ")[:31]
        if candidate not in used:
            return candidate

        idx = 2
        while True:
            suffix = f"_{idx}"
            trimmed = candidate[: max(1, 31 - len(suffix))] + suffix
            if trimmed not in used:
                return trimmed
            idx += 1

    
