"""Parser for the pre-meeting 3GPP TDoc allocation workbook.

The allocation spreadsheet is published by the MCC (Mirko) on the Monday
evening before the meeting, typically days before the generated
``AgendaWithTdocAllocation_*.htm`` appears. It carries the same logical columns
as the agenda table, but the exact header spellings and column order are not
guaranteed, so headers are matched through a tolerant alias table.

The parser is read-only (``read_only=True``) and never executes macros
(``data_only=True``). It produces the same :class:`AgendaParseResult` as the
HTML parser so both sources share projection and lineage semantics.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

from mirko.ingest.agenda_html import (
    AgendaParseResult,
    _Cell,
    derive_lineage,
    interpret_rows,
    normalize_text,
)

MAX_HEADER_SEARCH_ROWS = 40


def _header_key(value: object) -> str | None:
    text = normalize_text(None if value is None else str(value))
    if not text:
        return None
    cleaned = []
    for character in text.casefold():
        cleaned.append(character if character.isalnum() else "_")
    return "_".join(part for part in "".join(cleaned).split("_") if part)


_CANONICAL_ALIASES: dict[str, set[str]] = {
    "agenda": {
        "agenda",
        "agenda_item",
        "agenda_no",
        "agenda_number",
        "agenda_point",
        "ai",
    },
    "topic": {"topic", "subject", "agenda_topic", "topic_title"},
    "tdoc": {
        "tdoc",
        "tdoc_number",
        "tdoc_no",
        "tdoc_num",
        "document",
        "document_number",
        "document_no",
        "doc",
        "doc_number",
        "temp_doc",
        "temporary_document",
        "temporary_doc_number",
    },
    "title": {"title", "document_title", "doc_title", "name"},
    "source": {
        "source",
        "from",
        "originator",
        "company",
        "source_company",
        "submitted_by",
    },
    "type": {"type", "document_type", "doc_type"},
    "for_action": {
        "for",
        "for_action",
        "action",
        "for_decision",
        "for_information",
        "requested_action",
        "for_action_information",
    },
    "avail": {"avail", "available", "availability", "avail_"},
    "treated": {"treated", "status", "handled", "treated_"},
    "decision": {"decision", "outcome", "result", "conclusion"},
    "wdrn": {"wdrn", "withdrawn", "wdrawn"},
    "replaced_by": {
        "replaced_by",
        "replacedby",
        "superseded_by",
        "superseded",
    },
    "replaces": {"replaces", "replaces_", "baseline", "replaces_baseline"},
}

_ALIAS_LOOKUP: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _CANONICAL_ALIASES.items()
    for alias in aliases
}


def _canonical_key(value: object) -> str | None:
    key = _header_key(value)
    if key is None:
        return None
    return _ALIAS_LOOKUP.get(key)


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize_text(str(value))


def _row_values(row: Iterable[object]) -> list[object]:
    return list(row)


def _is_blank(values: list[object]) -> bool:
    return all(_cell_text(value) == "" for value in values)


def _detect_header(
    rows: list[list[object]],
) -> tuple[int, list[str | None]] | None:
    limit = min(len(rows), MAX_HEADER_SEARCH_ROWS)
    for index in range(limit):
        values = rows[index]
        keys = [_canonical_key(value) for value in values]
        present = {key for key in keys if key is not None}
        if "tdoc" in present and ({"agenda", "topic"} & present or "title" in present):
            return index, keys
    return None


def parse_allocation_excel(data: bytes) -> AgendaParseResult:
    """Parse an allocation workbook into the agenda result shape."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ValueError(
            "Excel ingestion requires the 'openpyxl' package"
        ) from exc
    workbook = load_workbook(
        io.BytesIO(data), read_only=True, data_only=True
    )
    try:
        sheet = workbook.active
        if sheet is None:  # pragma: no cover - defensive
            raise ValueError("workbook has no active worksheet")
        raw_rows = [_row_values(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    detected = _detect_header(raw_rows)
    if detected is None:
        raise ValueError(
            "could not locate a header row with a TDoc column in the workbook"
        )
    header_index, keys = detected
    data_rows = raw_rows[header_index + 1 :]

    mapped_rows: list[dict[str, _Cell]] = []
    for values in data_rows:
        if _is_blank(values):
            continue
        mapped: dict[str, _Cell] = {}
        for key, value in zip(keys, values):
            if key is None:
                continue
            mapped[key] = _Cell(tag="td", text=_cell_text(value))
        if "tdoc" not in mapped or not _cell_text(mapped["tdoc"].text):
            continue
        mapped_rows.append(mapped)

    rows, issues = interpret_rows(mapped_rows)
    edges, lineage_issues = derive_lineage(rows)
    issues.extend(lineage_issues)
    issues.sort(key=lambda issue: (issue.kind, issue.tdoc or ""))

    header = [
        str(value) if value is not None else "" for value in raw_rows[header_index]
    ]
    return AgendaParseResult(
        source_timestamp=None,
        rows=rows,
        edges=edges,
        issues=issues,
        header=[normalize_text(item) for item in header],
        raw_row_count=len(data_rows),
    )


def parse_allocation_excel_file(path: str | Path) -> AgendaParseResult:
    return parse_allocation_excel(Path(path).read_bytes())


__all__ = ["parse_allocation_excel", "parse_allocation_excel_file"]
