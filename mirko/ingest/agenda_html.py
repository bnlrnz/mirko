"""Parser for the 3GPP ``AgendaWithTdocAllocation_*.htm`` table.

The real file is a 1990s-style, windows-1252 HTML table with several quirks:

* TDoc numbers use U+2011 (non-breaking hyphen), usually written as
  ``&#x2011;`` in the source.
* Empty cells are literal U+00A0 (``&nbsp;``) and are not always padded.
* ``Agenda`` / ``Topic`` are populated only on the first row of a section and
  are empty on continuation rows (there is *no* rowspan in the real file).
* ``Treated`` is ``Yes`` plus an optional free-text note inside
  ``<span class="tooltiptext">``.
* Some ``<TD>`` cells are mis-closed with ``</TH>``.
* The header uses ``<TH>`` elements without an enclosing ``<TR>``.

The parser is deliberately dependency-free (stdlib ``html.parser``) and keeps the
raw cell text alongside the normalized values. It never guesses lineage: it
derives authoritative edges from ``Replaces`` / ``Replaced-by`` and reports
ambiguities as issues.

Usage::

    from mirko.ingest.agenda_html import parse_agenda_html

    result = parse_agenda_html(Path("AgendaWithTdocAllocation_...htm").read_bytes())
    for row in result.rows:
        print(row.tdoc, row.decision)
    for edge in result.edges:
        print(edge.source, edge.kind, edge.target)

CLI::

    python -m mirko.ingest.agenda_html path/to/agenda.htm
    python -m mirko.ingest.agenda_html path/to/agenda.htm --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# U+2010 HYPHEN, U+2011 NON-BREAKING HYPHEN, U+2012 FIGURE DASH,
# U+2013 EN DASH, U+2014 EM DASH, U+2015 HORIZONTAL BAR, U+2212 MINUS SIGN.
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_WHITESPACE = re.compile(r"\s+")
_TDOC_RE = re.compile(
    r"(?<![A-Za-z0-9])S3[-_ ]?(\d{6})(?!\d)", re.IGNORECASE
)
_TIMESTAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})[h:](\d{2})"
)


def normalize_text(value: str | None) -> str:
    """Collapse a table cell to a single-line, normalized string."""
    if not value:
        return ""
    value = value.replace("\xa0", " ")
    for dash in _DASHES:
        value = value.replace(dash, "-")
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return _WHITESPACE.sub(" ", value).strip()


def normalize_note(value: str | None) -> str:
    """Normalize free-text meeting notes while preserving line structure."""
    if not value:
        return ""
    value = value.replace("\xa0", " ")
    for dash in _DASHES:
        value = value.replace(dash, "-")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    kept: list[str] = []
    for line in lines:
        if line == "" and (not kept or kept[-1] == ""):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def canonical_tdoc(value: str | None) -> str | None:
    """Return ``S3-NNNNNN`` from any text, or ``None``.

    Accepts the visible U+2011 form, ``S3_NNNNNN``, ``S3 NNNNNN`` and
    ``S3NNNNNN``. Rejects malformed tokens such as ``S3-26abcd`` and
    ``S3-2604090`` (7 digits).
    """
    if not value:
        return None
    match = _TDOC_RE.search(normalize_text(value))
    return f"S3-{match.group(1)}" if match else None


def parse_yes_no(value: str | None) -> bool | None:
    text = normalize_text(value).casefold()
    if text in {"yes", "y", "true"}:
        return True
    if text in {"no", "n", "false"}:
        return False
    return None


_DECISION_ALIASES = {
    "not treated": "not treated",
    "not-treated": "not treated",
    "email approval": "email approval",
    "email-approval": "email approval",
    "replied to": "replied to",
    "replied-to": "replied to",
    "not pursued": "not pursued",
    "not-pursued": "not pursued",
}

_TYPE_ALIASES = {
    "cr": "CR",
    "pcr": "pCR",
    "draftcr": "draftCR",
    "draft cr": "draftCR",
    "ls in": "LS in",
    "ls out": "LS out",
    "report": "report",
    "agenda": "agenda",
    "other": "other",
    "discussion": "discussion",
    "draft ts": "draft TS",
    "draft tr": "draft TR",
    "sid new": "SID new",
    "sid revised": "SID revised",
    "wid new": "WID new",
    "wid revised": "WID revised",
}

_FOR_ALIASES = {
    "approval": "Approval",
    "agreement": "Agreement",
    "discussion": "Discussion",
    "endorsement": "Endorsement",
    "decision": "Decision",
    "information": "Information",
}


def normalize_decision(value: str | None) -> str | None:
    text = normalize_text(value).casefold()
    if not text or text == "-":
        return None
    return _DECISION_ALIASES.get(text, text)


def normalize_type(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    return _TYPE_ALIASES.get(text.casefold(), text)


def normalize_for(value: str | None) -> str | None:
    text = normalize_text(value)
    if not text or text == "-":
        return None
    return _FOR_ALIASES.get(text.casefold(), text)


def _normalize_href(value: str | None) -> str | None:
    if not value:
        return None
    return value.replace("\\", "/").strip() or None


def timestamp_from_filename(name: str) -> str | None:
    """Extract ``YYYY-MM-DDTHH:MM:00`` from an agenda filename."""
    match = _TIMESTAMP_RE.search(name)
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:00"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgendaRow:
    tdoc: str
    agenda_item: str | None
    topic: str | None
    title: str
    source: str
    type: str | None
    for_action: str | None
    avail: bool | None
    treated: bool | None
    treated_note: str | None
    decision: str | None
    withdrawn: bool | None
    replaced_by: str | None
    replaces: str | None
    zip_path: str | None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LineageEdge:
    source: str
    target: str
    kind: str  # revision_of | merged_into | based_on
    confidence: float
    verified: bool
    reason: str = ""


@dataclass(frozen=True)
class LineageIssue:
    kind: str
    tdoc: str | None
    detail: str


@dataclass(frozen=True)
class AgendaParseResult:
    source_timestamp: str | None
    rows: list[AgendaRow]
    edges: list[LineageEdge]
    issues: list[LineageIssue]
    header: list[str]
    raw_row_count: int


# ---------------------------------------------------------------------------
# Tolerant table parser
# ---------------------------------------------------------------------------


@dataclass
class _Cell:
    tag: str = "td"
    text_parts: list[str] = field(default_factory=list)
    note_parts: list[str] = field(default_factory=list)
    anchors: list[dict[str, str]] = field(default_factory=list)
    text: str = ""
    note: str = ""


class _TableParser(HTMLParser):
    """Extract rows/cells from the legacy table, tolerating its tag soup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.header: list[str] = []
        self.rows: list[list[_Cell]] = []
        self._table_depth = 0
        self._in_thead = False
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._tooltip_depth = 0

    # -- helpers ---------------------------------------------------------

    def _start_row(self) -> None:
        self._close_cell()
        self._close_row()
        self._row = []

    def _close_row(self) -> None:
        row = self._row
        self._row = None
        if not row:
            return
        if self._in_thead or all(cell.tag == "th" for cell in row):
            self.header = [cell.text for cell in row]
        else:
            self.rows.append(row)

    def _close_cell(self) -> None:
        cell = self._cell
        if cell is None:
            return
        self._cell = None
        self._tooltip_depth = 0
        cell.text = normalize_text("".join(cell.text_parts))
        cell.note = normalize_note("".join(cell.note_parts))
        if self._row is None:
            self._row = []
        self._row.append(cell)

    def finish(self) -> None:
        self._close_cell()
        self._close_row()

    # -- HTMLParser callbacks -------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): (value or "") for key, value in attrs}

        if tag == "table":
            self._table_depth += 1
            return
        if self._table_depth == 0:
            return

        if tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._start_row()
        elif tag in {"td", "th"}:
            self._close_cell()
            if self._row is None:
                self._row = []
            self._cell = _Cell(tag=tag)
        elif tag == "a":
            if self._cell is not None:
                self._cell.anchors.append(attr)
        elif tag == "span":
            if self._cell is not None and "tooltiptext" in attr.get("class", ""):
                self._tooltip_depth += 1
        elif tag == "br":
            if self._cell is not None:
                if self._tooltip_depth:
                    self._cell.note_parts.append("\n")
                else:
                    self._cell.text_parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            if self._table_depth == 1:
                self.finish()
            self._table_depth = max(0, self._table_depth - 1)
            return
        if self._table_depth == 0:
            return

        if tag in {"td", "th"}:
            # The real file closes some <TD> cells with </TH>; this handler
            # treats both as "end of the current cell".
            self._close_cell()
        elif tag == "tr":
            self._close_cell()
            self._close_row()
        elif tag == "thead":
            self._close_cell()
            self._close_row()
            self._in_thead = False
        elif tag == "span" and self._tooltip_depth:
            self._tooltip_depth -= 1

    def handle_data(self, data: str) -> None:
        cell = self._cell
        if cell is None:
            return
        if self._tooltip_depth:
            cell.note_parts.append(data)
        else:
            cell.text_parts.append(data)


# ---------------------------------------------------------------------------
# Cell interpretation
# ---------------------------------------------------------------------------

_FIXED_COLUMNS = [
    "agenda",
    "topic",
    "tdoc",
    "title",
    "source",
    "type",
    "for_action",
    "avail",
    "treated",
    "decision",
    "wdrn",
    "replaced_by",
    "replaces",
]


def _header_key(value: str) -> str:
    key = normalize_text(value).casefold().replace(" ", "_").replace("-", "_")
    return "for_action" if key == "for" else key


def _map_cells(cells: list[_Cell], header: list[str]) -> dict[str, _Cell]:
    keys = [_header_key(h) for h in header]
    if len(keys) != len(cells) or not {"agenda", "topic", "tdoc"}.issubset(keys):
        keys = _FIXED_COLUMNS[: len(cells)]
    return {keys[i]: cells[i] for i in range(len(cells))}


def _extract_tdoc_cell(cell: _Cell) -> tuple[str | None, str | None]:
    """Return (canonical TDoc, zip path) from a TDoc cell."""
    for anchor in cell.anchors:
        tdoc = canonical_tdoc(anchor.get("name")) or canonical_tdoc(anchor.get("href"))
        if tdoc:
            href = _normalize_href(anchor.get("href"))
            return tdoc, href
    return canonical_tdoc(cell.text), None


def _extract_tdoc_value(cell: _Cell) -> str | None:
    for anchor in cell.anchors:
        tdoc = canonical_tdoc(anchor.get("href")) or canonical_tdoc(anchor.get("name"))
        if tdoc:
            return tdoc
    return canonical_tdoc(cell.text)


def _parse_treated(cell: _Cell) -> tuple[bool | None, str | None]:
    text = cell.text
    note = cell.note or ""
    folded = text.casefold()
    treated: bool | None = None
    if folded.startswith("yes"):
        treated = True
        remainder = text[3:].strip()
    elif folded.startswith("no"):
        treated = False
        remainder = text[2:].strip()
    else:
        remainder = ""
    if remainder and not note:
        note = normalize_note(remainder)
    return treated, note or None


# ---------------------------------------------------------------------------
# Lineage derivation
# ---------------------------------------------------------------------------


def derive_lineage(
    rows: Iterable[AgendaRow],
) -> tuple[list[LineageEdge], list[LineageIssue]]:
    """Derive revision/merge edges from ``Replaces`` / ``Replaced-by``.

    Merges are discovered from the reverse index: every source row points
    ``Replaced-by`` at the merged result, while ``Replaces`` on the result
    names only the baseline.
    """
    rows = list(rows)
    by_tdoc: dict[str, AgendaRow] = {}
    issues: list[LineageIssue] = []

    for row in rows:
        if row.tdoc in by_tdoc:
            issues.append(
                LineageIssue("duplicate_tdoc", row.tdoc, "TDoc appears more than once")
            )
        else:
            by_tdoc[row.tdoc] = row

    sources_of: dict[str, list[AgendaRow]] = defaultdict(list)
    for row in rows:
        if row.replaced_by:
            sources_of[row.replaced_by].append(row)

    edges: list[LineageEdge] = []
    seen: set[tuple[str, str, str]] = set()
    handled: set[tuple[str, str]] = set()

    def add(edge: LineageEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        if key not in seen:
            seen.add(key)
            edges.append(edge)

    for target, sources in sources_of.items():
        source_ids = {row.tdoc for row in sources}
        target_row = by_tdoc.get(target)
        if target_row is None:
            issues.append(
                LineageIssue(
                    "target_missing",
                    target,
                    "Replaced-by points at a TDoc absent from this table",
                )
            )

        baseline: str | None = None
        if target_row and target_row.replaces and target_row.replaces in source_ids:
            baseline = target_row.replaces

        if baseline is None:
            revised = [row.tdoc for row in sources if row.decision == "revised"]
            if len(revised) == 1:
                baseline = revised[0]
            elif len(sources) == 1:
                baseline = sources[0].tdoc
            else:
                issues.append(
                    LineageIssue(
                        "ambiguous_baseline",
                        target,
                        "cannot determine baseline among "
                        + ", ".join(sorted(source_ids)),
                    )
                )

        if baseline is not None:
            baseline_row = by_tdoc.get(baseline)
            if baseline_row and baseline_row.decision != "revised":
                issues.append(
                    LineageIssue(
                        "baseline_not_revised",
                        baseline,
                        f"chosen baseline has Decision={baseline_row.decision}",
                    )
                )

        if (
            target_row
            and target_row.replaces
            and target_row.replaces not in source_ids
        ):
            issues.append(
                LineageIssue(
                    "baseline_not_linked",
                    target,
                    f"Replaces={target_row.replaces} but that row does not "
                    f"point Replaced-by at {target}",
                )
            )

        for source_row in sources:
            if source_row.tdoc == target:
                continue
            if baseline is None:
                add(
                    LineageEdge(
                        source_row.tdoc,
                        target,
                        "based_on",
                        0.3,
                        False,
                        "ambiguous baseline",
                    )
                )
            else:
                kind = "revision_of" if source_row.tdoc == baseline else "merged_into"
                add(LineageEdge(source_row.tdoc, target, kind, 1.0, True))
            handled.add((source_row.tdoc, target))

    # Standalone Replaces relationships without a matching reverse link.
    for row in rows:
        if not row.replaces or row.replaces == row.tdoc:
            continue
        pair = (row.replaces, row.tdoc)
        if pair in handled:
            continue
        source_row = by_tdoc.get(row.replaces)
        if source_row and source_row.replaced_by == row.tdoc:
            # A reverse link exists, so the grouping above owns this edge.
            continue
        add(
            LineageEdge(
                row.replaces,
                row.tdoc,
                "based_on",
                0.5,
                False,
                "Replaces without reverse link",
            )
        )

    # Consistency checks.
    for row in rows:
        if row.decision in {"revised", "merged"} and not row.replaced_by:
            issues.append(
                LineageIssue(
                    "missing_replaced_by",
                    row.tdoc,
                    f"Decision={row.decision} but Replaced-by is empty",
                )
            )

    edges.sort(key=lambda edge: (edge.target, edge.source, edge.kind))
    issues.sort(key=lambda issue: (issue.kind, issue.tdoc or ""))
    return edges, issues


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _decode(raw: bytes, encoding: str | None) -> str:
    if encoding:
        return raw.decode(encoding, errors="replace")
    for candidate in ("utf-8-sig", "utf-8", "windows-1252", "cp1252"):
        try:
            return raw.decode(candidate)
        except UnicodeDecodeError:
            continue
    return raw.decode("windows-1252", errors="replace")


def _extract_timestamp(text: str) -> str | None:
    head = text[:4000]
    match = _TIMESTAMP_RE.search(head)
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:00"


def interpret_rows(
    mapped_rows: list[dict[str, _Cell]],
) -> tuple[list[AgendaRow], list[LineageIssue]]:
    """Turn header-mapped cells into agenda rows.

    Each item maps canonical column keys to cells. This is shared by the HTML
    parser (which maps ``<TH>``/``<TD>`` cells) and the Excel parser so that
    both sources interpret values identically.
    """
    rows: list[AgendaRow] = []
    current_agenda: str | None = None
    current_topic: str | None = None
    issues: list[LineageIssue] = []

    for mapped in mapped_rows:
        agenda = normalize_text(mapped.get("agenda", _Cell()).text)
        topic = normalize_text(mapped.get("topic", _Cell()).text)
        if agenda:
            current_agenda = agenda
            current_topic = topic or None
        else:
            agenda = current_agenda
            if topic:
                current_topic = topic
            topic = current_topic

        tdoc_cell = mapped.get("tdoc", _Cell())
        tdoc, zip_path = _extract_tdoc_cell(tdoc_cell)
        if not tdoc:
            # Agenda/section heading row.
            continue

        title = normalize_text(mapped.get("title", _Cell()).text)
        source = normalize_text(mapped.get("source", _Cell()).text)
        type_value = normalize_type(mapped.get("type", _Cell()).text)
        for_action = normalize_for(mapped.get("for_action", _Cell()).text)
        avail = parse_yes_no(mapped.get("avail", _Cell()).text)
        treated, treated_note = _parse_treated(mapped.get("treated", _Cell()))

        decision_raw = normalize_text(mapped.get("decision", _Cell()).text)
        decision = normalize_decision(decision_raw)
        if decision is None:
            decision = "open"
            issues.append(
                LineageIssue(
                    "inferred_open",
                    tdoc,
                    "Decision cell was empty; projected as 'open'",
                )
            )

        withdrawn = parse_yes_no(mapped.get("wdrn", _Cell()).text)
        replaced_by = _extract_tdoc_value(mapped.get("replaced_by", _Cell()))
        replaces = _extract_tdoc_value(mapped.get("replaces", _Cell()))

        raw = {
            key: normalize_text(cell.text)
            for key, cell in mapped.items()
            if key not in {"treated"}
        }
        if treated_note:
            raw["treated_note"] = treated_note

        rows.append(
            AgendaRow(
                tdoc=tdoc,
                agenda_item=agenda or None,
                topic=topic or None,
                title=title,
                source=source,
                type=type_value,
                for_action=for_action,
                avail=avail,
                treated=treated,
                treated_note=treated_note,
                decision=decision,
                withdrawn=withdrawn,
                replaced_by=replaced_by,
                replaces=replaces,
                zip_path=zip_path,
                raw=raw,
            )
        )

    return rows, issues


def parse_agenda_html(
    html: str | bytes, *, encoding: str | None = None
) -> AgendaParseResult:
    """Parse an agenda/allocation HTML document.

    ``html`` may be bytes (decoded using the declared/utf-8/cp1252 fallback
    chain) or an already-decoded string.
    """
    text = _decode(html, encoding) if isinstance(html, bytes) else html

    parser = _TableParser()
    parser.feed(text)
    parser.finish()

    mapped_rows = [_map_cells(cells, parser.header) for cells in parser.rows]
    rows, issues = interpret_rows(mapped_rows)

    edges, lineage_issues = derive_lineage(rows)
    issues.extend(lineage_issues)
    issues.sort(key=lambda issue: (issue.kind, issue.tdoc or ""))

    return AgendaParseResult(
        source_timestamp=_extract_timestamp(text),
        rows=rows,
        edges=edges,
        issues=issues,
        header=[normalize_text(h) for h in parser.header],
        raw_row_count=len(parser.rows),
    )


def parse_agenda_file(path: str | Path) -> AgendaParseResult:
    return parse_agenda_html(Path(path).read_bytes())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _summary(result: AgendaParseResult) -> dict[str, object]:
    decisions: dict[str, int] = defaultdict(int)
    types: dict[str, int] = defaultdict(int)
    for row in result.rows:
        decisions[row.decision or "?"] += 1
        types[row.type or "?"] += 1
    kinds: dict[str, int] = defaultdict(int)
    for edge in result.edges:
        kinds[edge.kind] += 1
    return {
        "source_timestamp": result.source_timestamp,
        "rows": len(result.rows),
        "header": result.header,
        "decisions": dict(sorted(decisions.items())),
        "types": dict(sorted(types.items())),
        "edges": dict(sorted(kinds.items())),
        "issues": len(result.issues),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", help="dump the full result")
    args = parser.parse_args(argv)

    result = parse_agenda_file(args.path)
    payload = asdict(result) if args.json else _summary(result)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
