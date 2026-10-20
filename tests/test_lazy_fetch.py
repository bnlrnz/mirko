"""Tests for deferred draft downloads and on-demand fetching."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mirko.ftp import FakeFtpClient
from mirko.ingest.filename_ingest import FilenameIngestor
from mirko.meeting_folder import MeetingFolder
from mirko.sync import Syncer

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)


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
            "base_path": "/Meetings_3GPP_SYNC/SA3",
            "username": "anonymous",
        },
        "sync": {"lazy_drafts": True},
    }


def make_folder(tmp_path: Path) -> MeetingFolder:
    return MeetingFolder.create(tmp_path / "SA3-130", minimal_config())


def rows(folder: MeetingFolder, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
    connection = folder.connect()
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def test_drafts_are_deferred_until_requested(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient(
        {
            "Inbox/Drafts/draft S3-264314-r1.docx": b"draft",
            "Inbox/S3-264314.zip": b"zip",
        }
    )
    syncer = Syncer(folder, client, clock=lambda: NOW)

    report = syncer.sync()

    assert report.deferred == 1
    assert report.fetched == 1
    assert client.fetch_calls == ["Inbox/S3-264314.zip"]
    draft = rows(
        folder,
        "SELECT * FROM artifact WHERE logical_path = ?",
        ("Inbox/Drafts/draft S3-264314-r1.docx",),
    )[0]
    assert draft["status"] == "remote"
    assert draft["blob_hash"] is None
    manifest = rows(
        folder,
        "SELECT * FROM remote_entry WHERE path = ?",
        ("Inbox/Drafts",),
    )[0]
    assert manifest["fetch_state"] == "pending"

    FilenameIngestor(folder, clock=lambda: NOW).ingest()
    fetched = syncer.fetch_for_tdoc("S3-264314", include_lineage=False)

    assert fetched.failures == ()
    assert fetched.fetched == ("Inbox/Drafts/draft S3-264314-r1.docx",)
    assert client.fetch_calls == [
        "Inbox/S3-264314.zip",
        "Inbox/Drafts/draft S3-264314-r1.docx",
    ]
    draft = rows(
        folder,
        "SELECT * FROM artifact WHERE logical_path = ?",
        ("Inbox/Drafts/draft S3-264314-r1.docx",),
    )[0]
    assert draft["status"] == "present"
    assert draft["blob_hash"] is not None

    client.fetch_calls.clear()
    assert syncer.fetch_for_tdoc("S3-264314", include_lineage=False).fetched == ()
    assert client.fetch_calls == []


def test_second_sync_keeps_deferred_entries_pending(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient({"Inbox/Drafts/a.docx": b"draft"})
    syncer = Syncer(folder, client, clock=lambda: NOW)

    first = syncer.sync()
    client.fetch_calls.clear()
    second = syncer.sync()

    assert first.deferred == 1
    assert second.deferred == 0
    assert client.fetch_calls == []
    assert rows(folder, "SELECT * FROM blob") == []
    assert len(rows(folder, "SELECT * FROM artifact_observation")) == 1


def test_failed_on_demand_fetch_can_be_retried(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/draft S3-264314-r1.docx"
    client = FakeFtpClient({path: b"draft"})
    client.fail_fetch.add(path)
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    FilenameIngestor(folder, clock=lambda: NOW).ingest()

    failed = syncer.fetch_for_tdoc("S3-264314", include_lineage=False)

    assert [failure.path for failure in failed.failures] == [path]
    assert rows(folder, "SELECT status FROM artifact WHERE logical_path = ?", (path,))[0][
        "status"
    ] == "failed"

    client.fail_fetch.clear()
    retried = syncer.fetch_for_tdoc("S3-264314", include_lineage=False)

    assert retried.fetched == (path,)
    assert rows(folder, "SELECT status FROM artifact WHERE logical_path = ?", (path,))[0][
        "status"
    ] == "present"


def test_tracking_fetches_lineage_neighbours(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient(
        {
            "Inbox/Drafts/draft S3-264314-r1.docx": b"first",
            "Inbox/Drafts/draft S3-264315-r1.docx": b"second",
        }
    )
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    FilenameIngestor(folder, clock=lambda: NOW).ingest()

    connection = folder.connect()
    try:
        connection.execute(
            "INSERT INTO assertion(subject_kind, subject_ref, predicate, "
            "object_kind, object_ref, source, confidence, verified, active, "
            "muted, observed_at) VALUES ('tdoc', 'S3-264314', 'revision_of', "
            "'tdoc', 'S3-264315', 'manual', 1.0, 1, 1, 0, ?)",
            ("2026-10-16T15:00:00.000000Z",),
        )
        connection.commit()
    finally:
        connection.close()

    fetched = syncer.fetch_for_tdoc("S3-264314")

    assert sorted(fetched.fetched) == [
        "Inbox/Drafts/draft S3-264314-r1.docx",
        "Inbox/Drafts/draft S3-264315-r1.docx",
    ]
