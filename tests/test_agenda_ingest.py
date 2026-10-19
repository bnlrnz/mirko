"""Tests for persisting agenda HTML into projections and assertions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mirko.ingest.agenda_ingest import (
    AgendaIngestor,
    select_latest_agenda,
)
from mirko.meeting_folder import MeetingFolder

FIXTURE = Path(__file__).parent / "fixtures" / "agenda_excerpt.htm"

HEADER = [
    "Agenda",
    "Topic",
    "TDoc",
    "Title",
    "Source",
    "Type",
    "For",
    "Avail",
    "Treated",
    "Decision",
    "Wdrn",
    "Replaced-by",
    "Replaces",
]


def minimal_config() -> dict:
    return {
        "schema_version": 1,
        "meeting": {
            "id": "SA3#130",
            "title": "SA3#130 Prague",
            "timezone": "Europe/Prague",
            "days": ["2026-10-12", "2026-10-16"],
            "tdoc_series_prefix": "S3-26",
        },
        "source": {
            "kind": "local",
            "protocol": "ftp",
            "host": "10.10.10.10",
            "port": 21,
            "base_path": "/ftp/SA/SA3",
            "username": "anonymous",
        },
    }


def make_row(tdoc: str, **overrides: str) -> list[str]:
    row = {
        "agenda": "1",
        "topic": "Topic",
        "tdoc": tdoc,
        "title": f"Title for {tdoc}",
        "source": "Source",
        "type": "CR",
        "for_action": "Approval",
        "avail": "Yes",
        "treated": "No",
        "decision": "",
        "wdrn": "No",
        "replaced_by": "",
        "replaces": "",
    }
    row.update(overrides)
    return [row[key] for key in (
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
    )]


def agenda_html(rows: list[list[str]], *, timestamp: str = "2026-10-16 14:37") -> str:
    parts = [
        "<html><body>",
        f"<p>{timestamp}</p>",
        "<table><thead>",
        "".join(f"<th>{h}</th>" for h in HEADER),
        "</thead>",
    ]
    for row in rows:
        parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table></body></html>")
    return "".join(parts)


def clock_at(*moments: datetime):
    iterator = iter(moments)
    return lambda: next(iterator)


@pytest.fixture()
def folder(tmp_path: Path) -> MeetingFolder:
    return MeetingFolder.create(tmp_path / "SA3-130", minimal_config())


def test_ingest_records_documents_and_provenance(folder: MeetingFolder) -> None:
    ingestor = AgendaIngestor(folder)
    html = agenda_html(
        [
            make_row("S3-263700", decision="revised"),
            make_row("S3-263701"),
        ]
    )

    result = ingestor.ingest(html, path="Inbox/agenda.htm")

    assert result.status == "ingested"
    assert result.row_count == 2
    assert result.issue_count == 2
    assert result.source_timestamp == "2026-10-16T14:37:00"

    connection = folder.connect()
    try:
        documents = {
            row["tdoc_number"]: row
            for row in connection.execute("SELECT * FROM tdoc_current")
        }
        assert set(documents) == {"S3-263700", "S3-263701"}
        assert documents["S3-263700"]["decision"] == "revised"
        assert documents["S3-263700"]["state_source"] == "html"
        assert documents["S3-263701"]["decision"] == "open"
        assert documents["S3-263701"]["state_source"] == "inferred"
        assert documents["S3-263700"]["is_provisional"] == 0
        assert documents["S3-263700"]["is_tracked"] == 0

        runs = connection.execute(
            "SELECT * FROM ingest_run ORDER BY id"
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["kind"] == "agenda_html"
        assert runs[0]["status"] == "success"
        assert runs[0]["path"] == "Inbox/agenda.htm"
        assert runs[0]["row_count"] == 2
        assert runs[0]["content_hash"] == result.content_hash
        assert runs[0]["endpoint_id"] == "ftp://10.10.10.10:21/ftp/SA/SA3"
    finally:
        connection.close()


def test_reingesting_same_content_is_idempotent(folder: MeetingFolder) -> None:
    ingestor = AgendaIngestor(folder)
    html = agenda_html([make_row("S3-263700", decision="revised")])

    first = ingestor.ingest(html)
    second = ingestor.ingest(html)

    assert first.status == "ingested"
    assert second.status == "unchanged"
    assert second.ingest_run_id == first.ingest_run_id

    connection = folder.connect()
    try:
        assert connection.execute("SELECT COUNT(*) FROM ingest_run").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM tdoc").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM assertion").fetchone()[0] == 1
        )
    finally:
        connection.close()


def test_changed_decision_supersedes_prior_assertion(
    folder: MeetingFolder,
) -> None:
    ingestor = AgendaIngestor(folder)

    ingestor.ingest(agenda_html([make_row("S3-263700")]))
    ingestor.ingest(agenda_html([make_row("S3-263700", decision="revised")]))

    connection = folder.connect()
    try:
        rows = connection.execute(
            "SELECT id, value, active, muted, superseded_by, verified "
            "FROM assertion WHERE predicate = 'decision' ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        old, new = rows
        assert old["value"] == "open"
        assert old["active"] == 0
        assert old["muted"] == 1
        assert old["superseded_by"] == new["id"]
        assert new["value"] == "revised"
        assert new["active"] == 1
        assert new["verified"] == 1

        document = connection.execute(
            "SELECT decision, state_source FROM tdoc WHERE tdoc_number = ?",
            ("S3-263700",),
        ).fetchone()
        assert document["decision"] == "revised"
        assert document["state_source"] == "html"
    finally:
        connection.close()


def test_lineage_edges_are_projected(folder: MeetingFolder) -> None:
    ingestor = AgendaIngestor(folder)
    html = agenda_html(
        [
            make_row("S3-263700", decision="revised", replaced_by="S3-263701"),
            make_row("S3-263701", decision="agreed", replaces="S3-263700"),
        ]
    )

    result = ingestor.ingest(html)
    assert result.edge_count == 1

    connection = folder.connect()
    try:
        edges = connection.execute("SELECT * FROM edge_current").fetchall()
        assert len(edges) == 1
        assert edges[0]["source"] == "S3-263700"
        assert edges[0]["target"] == "S3-263701"
        assert edges[0]["kind"] == "revision_of"
        assert edges[0]["verified"] == 1
        assert edges[0]["confidence"] == 1.0
    finally:
        connection.close()


def test_later_snapshot_preserves_first_seen_and_fills_blanks(
    folder: MeetingFolder,
) -> None:
    first_seen = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    last_seen = datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc)
    ingestor = AgendaIngestor(folder, clock=clock_at(first_seen, last_seen))

    ingestor.ingest(
        agenda_html([make_row("S3-263700", title="Original title")])
    )
    ingestor.ingest(
        agenda_html([make_row("S3-263700", title="", decision="revised")])
    )

    connection = folder.connect()
    try:
        document = connection.execute(
            "SELECT title, decision, first_seen_at, last_seen_at FROM tdoc "
            "WHERE tdoc_number = ?",
            ("S3-263700",),
        ).fetchone()
        assert document["title"] == "Original title"
        assert document["decision"] == "revised"
        assert document["first_seen_at"] == "2026-10-16T10:00:00.000000Z"
        assert document["last_seen_at"] == "2026-10-16T11:00:00.000000Z"
    finally:
        connection.close()


def test_ingest_reports_parser_issues(folder: MeetingFolder) -> None:
    result = AgendaIngestor(folder).ingest(agenda_html([make_row("S3-263700")]))

    kinds = {issue.kind for issue in result.issues}
    assert "inferred_open" in kinds
    assert result.issue_count == len(result.issues)


def test_ingest_fixture_bytes(folder: MeetingFolder) -> None:
    raw = FIXTURE.read_bytes()
    result = AgendaIngestor(folder).ingest(raw, path="agenda_excerpt.htm")

    assert result.status == "ingested"
    assert result.row_count > 0

    connection = folder.connect()
    try:
        inserted = connection.execute("SELECT COUNT(*) FROM tdoc").fetchone()[0]
        assert inserted == result.row_count
    finally:
        connection.close()


def test_select_latest_agenda_prefers_newest_timestamp() -> None:
    names = [
        "AgendaWithTdocAllocation_2026-10-16_09h00.htm",
        "AgendaWithTdocAllocation_2026-10-16_14h37.htm",
        "unrelated.htm",
    ]

    selected = select_latest_agenda(names)
    assert selected == "AgendaWithTdocAllocation_2026-10-16_14h37.htm"
    assert select_latest_agenda(["unrelated.htm"]) is None


def test_select_latest_agenda_handles_paths() -> None:
    names = [
        "Inbox/AgendaWithTdocAllocation_2026-10-15_09h00.htm",
        "Inbox/AgendaWithTdocAllocation_2026-10-16_09h00.htm",
    ]
    assert (
        select_latest_agenda(names)
        == "Inbox/AgendaWithTdocAllocation_2026-10-16_09h00.htm"
    )
