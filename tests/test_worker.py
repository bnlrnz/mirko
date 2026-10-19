"""Tests for the one-shot sync + ingestion worker."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mirko.ftp import FakeFtpClient
from mirko.meeting_folder import MeetingFolder
from mirko.worker import SyncWorker

NOW = datetime(2026, 10, 16, 14, 37, tzinfo=timezone.utc)

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
            "hours": {"start": "09:00", "end": "18:00"},
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


def agenda_html() -> str:
    row = [
        "5.3.1.3",
        "Topic",
        "S3-264202",
        "Original",
        "Source",
        "CR",
        "Approval",
        "Yes",
        "No",
        "revised",
        "No",
        "S3-264203",
        "",
    ]
    parts = ["<table><thead>"]
    parts += [f"<th>{header}</th>" for header in HEADER]
    parts.append("</thead>")
    parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def rows(folder: MeetingFolder, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
    connection = folder.connect()
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def test_sync_worker_runs_full_cycle(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    client = FakeFtpClient(
        {
            "AgendaWithTdocAllocation_2026-10-16_14h37.htm": agenda_html().encode(),
            "Inbox/Drafts/draft S3-264202-r1.docx": b"draft",
            "Inbox/S3-264999.zip": b"zip",
        }
    )

    result = SyncWorker(folder, client=client, clock=lambda: NOW).run()

    assert result.status == "ok"
    assert result.fetched == 3
    assert result.agenda in {"ingested", "unchanged"}
    assert result.drafts is not None
    assert result.drafts.processed == 2
    assert result.mail is not None and result.mail.kind is None
    payload = result.as_dict()
    assert payload["drafts"]["processed"] == 2
    assert payload["status"] == "ok"

    tdocs = {row["tdoc_number"] for row in rows(folder, "SELECT tdoc_number FROM tdoc")}
    assert "S3-264202" in tdocs

    state = rows(folder, "SELECT * FROM sync_state")
    assert len(state) == 1
    assert state[0]["health"] == "ok"
    assert state[0]["last_error"] is None
    assert state[0]["last_success_at"] == "2026-10-16T14:37:00.000000Z"


def test_sync_worker_records_errors_without_losing_data(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    client = FakeFtpClient(
        {
            "Inbox/Drafts/draft S3-264202-r1.docx": b"draft",
            "Inbox/S3-264999.zip": b"zip",
        }
    )
    client.fail_fetch.add("Inbox/S3-264999.zip")

    result = SyncWorker(folder, client=client, clock=lambda: NOW).run()

    assert result.status == "degraded"
    assert any("S3-264999.zip" in error for error in result.errors)
    state = rows(folder, "SELECT * FROM sync_state")
    assert state[0]["health"] == "degraded"
    assert "S3-264999.zip" in state[0]["last_error"]
    tdocs = {row["tdoc_number"] for row in rows(folder, "SELECT tdoc_number FROM tdoc")}
    assert tdocs
