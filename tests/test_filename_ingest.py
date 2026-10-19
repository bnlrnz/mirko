"""Integration tests for filename-derived artifacts and provisional TDocs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from mirko.ftp import FakeFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.ingest.filename_ingest import (
    FilenameIngestor,
    discover_new_numbers,
)
from mirko.meeting_folder import MeetingFolder
from mirko.sync import Syncer

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


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


def make_folder(tmp_path: Path) -> MeetingFolder:
    return MeetingFolder.create(tmp_path / "SA3-130", minimal_config())


def rows(folder: MeetingFolder, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
    connection = folder.connect()
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def sync_files(folder: MeetingFolder, files: dict[str, bytes]) -> None:
    Syncer(folder, FakeFtpClient(files), clock=lambda: NOW).sync(
        ["Inbox/Drafts", "Inbox"]
    )


def test_drafts_attach_and_create_provisional_tdocs(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    sync_files(
        folder,
        {
            "Inbox/Drafts/draft S3-264314-r1.docx": b"draft",
            "Inbox/Drafts/draft-S3-264163-r1-merger_of_S3-263756_S3-263845_S3-264163.docx": b"merge",
            "Inbox/Drafts/Meeting notes for Monday.docx": b"notes",
            "Inbox/S3-263915.zip": b"zip",
        },
    )

    result = FilenameIngestor(folder, clock=lambda: NOW).ingest()

    assert result.processed == 4
    assert result.attached == 3
    assert set(result.provisional) == {"S3-264314", "S3-264163", "S3-263915"}
    assert result.hints == 2
    assert len(result.unfiled) == 1

    artifacts = rows(folder, "SELECT * FROM artifact ORDER BY logical_path")
    attached = {
        row["filename"]: row["tdoc_number"]
        for row in artifacts
        if row["tdoc_number"] is not None
    }
    assert attached["draft S3-264314-r1.docx"] == "S3-264314"
    assert attached["S3-263915.zip"] == "S3-263915"

    tdocs = {row["tdoc_number"]: row for row in rows(folder, "SELECT * FROM tdoc")}
    assert tdocs["S3-264314"]["is_provisional"] == 1
    assert tdocs["S3-264314"]["state_source"] == "filename"

    ghost_edges = rows(
        folder,
        "SELECT * FROM assertion WHERE source = 'filename' ORDER BY id",
    )
    assert len(ghost_edges) == 2
    assert {row["subject_ref"] for row in ghost_edges} == {
        "S3-263756",
        "S3-263845",
    }
    assert all(row["object_ref"] == "S3-264163" for row in ghost_edges)
    assert all(row["predicate"] == "based_on" for row in ghost_edges)
    assert all(row["active"] == 0 for row in ghost_edges)
    assert all(row["verified"] == 0 for row in ghost_edges)

    new_numbers = {item.tdoc_number: item for item in result.new_numbers}
    assert set(new_numbers) == {"S3-264314", "S3-264163", "S3-263915"}
    assert new_numbers["S3-264163"].artifact_count == 1


def test_filename_ingest_is_idempotent(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    sync_files(
        folder,
        {
            "Inbox/Drafts/draft-S3-264163-r1-merger_of_S3-263756_S3-263845.docx": b"merge",
        },
    )

    first = FilenameIngestor(folder, clock=lambda: NOW).ingest()
    second = FilenameIngestor(folder, clock=lambda: NOW).ingest()

    assert first.hints == 2
    assert second.hints == 0
    assert second.provisional == ()
    assert len(rows(folder, "SELECT * FROM assertion")) == 2
    assert len(rows(folder, "SELECT * FROM tdoc")) == 1


def test_existing_official_tdoc_is_not_provisional(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    connection = folder.connect()
    try:
        connection.execute(
            "INSERT INTO tdoc(tdoc_number, title, is_provisional) "
            "VALUES ('S3-264314', 'Official', 0)"
        )
        connection.commit()
    finally:
        connection.close()
    sync_files(folder, {"Inbox/Drafts/draft S3-264314-r1.docx": b"draft"})

    result = FilenameIngestor(folder, clock=lambda: NOW).ingest()

    assert result.provisional == ()
    row = rows(folder, "SELECT * FROM tdoc WHERE tdoc_number = 'S3-264314'")[0]
    assert row["is_provisional"] == 0
    assert row["title"] == "Official"


def test_html_ingest_clears_provisional_flag(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    sync_files(folder, {"Inbox/Drafts/draft S3-264314-r1.docx": b"draft"})
    FilenameIngestor(folder, clock=lambda: NOW).ingest()

    html = (
        "<table><thead>"
        "<th>Agenda</th><th>Topic</th><th>TDoc</th><th>Title</th>"
        "<th>Source</th><th>Type</th><th>For</th><th>Avail</th>"
        "<th>Treated</th><th>Decision</th><th>Wdrn</th>"
        "<th>Replaced-by</th><th>Replaces</th>"
        "</thead><tr>"
        "<td>1</td><td>Topic</td><td>S3-264314</td><td>Official</td>"
        "<td>Source</td><td>CR</td><td>Approval</td><td>Yes</td>"
        "<td>No</td><td>agreed</td><td>No</td><td></td><td></td>"
        "</tr></table>"
    )
    AgendaIngestor(folder, clock=lambda: NOW).ingest(html)

    row = rows(folder, "SELECT * FROM tdoc WHERE tdoc_number = 'S3-264314'")[0]
    assert row["is_provisional"] == 0
    assert row["decision"] == "agreed"
    connection = folder.connect()
    try:
        assert discover_new_numbers(connection) == ()
    finally:
        connection.close()


def test_discover_new_numbers_aggregates_paths(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    sync_files(
        folder,
        {
            "Inbox/Drafts/draft S3-264314-r1.docx": b"one",
            "Inbox/Drafts/draft S3-264314-r2.docx": b"two",
        },
    )
    FilenameIngestor(folder, clock=lambda: NOW).ingest()

    connection = folder.connect()
    try:
        numbers = discover_new_numbers(connection)
    finally:
        connection.close()
    assert len(numbers) == 1
    assert numbers[0].tdoc_number == "S3-264314"
    assert numbers[0].artifact_count == 2
    assert numbers[0].filenames == (
        "draft S3-264314-r1.docx",
        "draft S3-264314-r2.docx",
    )
