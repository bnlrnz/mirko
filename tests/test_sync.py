"""Integration tests for manifest sync, blob caching, and observations."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mirko.ftp import FakeFtpClient, FtpError
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
    }


def make_folder(tmp_path: Path) -> MeetingFolder:
    return MeetingFolder.create(tmp_path / "SA3-130", minimal_config())


def rows(folder: MeetingFolder, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
    connection = folder.connect()
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def artifact_by_path(folder: MeetingFolder, logical_path: str):
    found = rows(
        folder,
        "SELECT * FROM artifact WHERE logical_path = ?",
        (logical_path,),
    )
    assert len(found) == 1
    return found[0]


def test_first_sync_fetches_all_listed_files(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient(
        {
            "Inbox/Drafts/draft S3-264314-r1.docx": b"draft",
            "Inbox/S3-264314.zip": b"zip",
            "AgendaWithTdocAllocation_2026-10-16_14h37.htm": b"<html>",
        }
    )
    syncer = Syncer(folder, client, clock=lambda: NOW)

    report = syncer.sync()

    assert client.list_calls == ["Inbox/Drafts", "Inbox", ""]
    assert sorted(client.fetch_calls) == [
        "AgendaWithTdocAllocation_2026-10-16_14h37.htm",
        "Inbox/Drafts/draft S3-264314-r1.docx",
        "Inbox/S3-264314.zip",
    ]
    assert report.fetched == 3
    assert report.failures == ()
    assert [path.path for path in report.paths] == [
        "Inbox/Drafts",
        "Inbox",
        "",
    ]
    assert len(list(folder.blobs_dir.iterdir())) == 3
    assert len(rows(folder, "SELECT * FROM blob")) == 3
    assert len(rows(folder, "SELECT * FROM remote_entry")) == 3
    assert len(rows(folder, "SELECT * FROM artifact")) == 3
    assert len(rows(folder, "SELECT * FROM artifact_observation")) == 3


def test_artifact_classification_and_provenance(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient(
        {
            "Inbox/Drafts/draft.docx": b"draft",
            "Inbox/final.zip": b"zip",
            "AgendaWithTdocAllocation_2026-10-16_14h37.htm": b"<html>",
            "S3-26_meeting_allocation.xlsx": b"excel",
        }
    )

    Syncer(folder, client, clock=lambda: NOW).sync()

    draft = artifact_by_path(folder, "Inbox/Drafts/draft.docx")
    assert draft["kind"] == "working_draft"
    assert draft["is_ephemeral"] == 1
    assert draft["status"] == "present"
    assert draft["source_kind"] == "local"
    assert draft["endpoint_id"] == "ftp://10.10.10.10:21/Meetings_3GPP_SYNC/SA3"

    inbox = artifact_by_path(folder, "Inbox/final.zip")
    assert inbox["kind"] == "inbox_document"
    assert inbox["is_ephemeral"] == 0

    agenda = artifact_by_path(
        folder, "AgendaWithTdocAllocation_2026-10-16_14h37.htm"
    )
    assert agenda["kind"] == "agenda_html"

    excel = artifact_by_path(folder, "S3-26_meeting_allocation.xlsx")
    assert excel["kind"] == "allocation_excel"


def test_second_sync_does_not_refetch(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient({"Inbox/Drafts/a.docx": b"content"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    client.fetch_calls.clear()

    report = syncer.sync()

    assert report.fetched == 0
    assert client.fetch_calls == []
    assert len(rows(folder, "SELECT * FROM blob")) == 1
    assert len(rows(folder, "SELECT * FROM artifact_observation")) == 1


def test_changed_content_creates_new_blob_and_observation(
    tmp_path: Path,
) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/a.docx"
    client = FakeFtpClient({path: b"first"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()

    client.add(path, b"second", mtime="2026-10-16T15:30:00")
    report = syncer.sync()

    assert report.fetched == 1
    assert [path.changed for path in report.paths if path.path == "Inbox/Drafts"] == [
        ("a.docx",)
    ]
    assert len(rows(folder, "SELECT * FROM blob")) == 2
    assert len(rows(folder, "SELECT * FROM artifact_observation")) == 2
    artifact = artifact_by_path(folder, path)
    assert artifact["remote_mtime"] == "2026-10-16T15:30:00"
    observations = rows(
        folder,
        "SELECT change_kind FROM artifact_observation ORDER BY id",
    )
    assert [row["change_kind"] for row in observations] == ["created", "changed"]


def test_changed_identity_with_same_content_dedupes_blob(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/a.docx"
    client = FakeFtpClient({path: b"same"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()

    client.add(path, b"same", mtime="2026-10-16T16:00:00")
    syncer.sync()

    assert len(list(folder.blobs_dir.iterdir())) == 1
    assert len(rows(folder, "SELECT * FROM blob")) == 1
    kinds = [
        row["change_kind"]
        for row in rows(folder, "SELECT change_kind FROM artifact_observation ORDER BY id")
    ]
    assert kinds == ["created", "metadata_changed"]


def test_missing_file_is_retained_then_marked_returned(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/a.docx"
    client = FakeFtpClient({path: b"content"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    blob_count = len(rows(folder, "SELECT * FROM blob"))

    client.remove(path)
    report = syncer.sync()

    assert [path.missing for path in report.paths if path.path == "Inbox/Drafts"] == [
        ("a.docx",)
    ]
    entry = rows(folder, "SELECT * FROM remote_entry")[0]
    assert entry["missing_since"] == "2026-10-16T15:00:00.000000Z"
    assert artifact_by_path(folder, path)["status"] == "missing"
    assert len(rows(folder, "SELECT * FROM blob")) == blob_count
    assert folder.blobs_dir.is_dir()

    client.add(path, b"content")
    syncer.sync()

    entry = rows(folder, "SELECT * FROM remote_entry")[0]
    assert entry["missing_since"] is None
    assert artifact_by_path(folder, path)["status"] == "present"
    kinds = [
        row["change_kind"]
        for row in rows(folder, "SELECT change_kind FROM artifact_observation ORDER BY id")
    ]
    assert kinds == ["created", "missing", "returned"]


def test_fetch_failure_is_reported_and_retried(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/a.docx"
    client = FakeFtpClient({path: b"content"})
    client.fail_fetch.add(path)
    syncer = Syncer(folder, client, clock=lambda: NOW)

    report = syncer.sync()

    assert len(report.failures) == 1
    assert report.failures[0].path == path
    assert rows(folder, "SELECT * FROM remote_entry") == []
    assert rows(folder, "SELECT * FROM blob") == []
    assert artifact_by_path(folder, path)["status"] == "failed"

    client.fail_fetch.clear()
    report = syncer.sync()

    assert report.failures == ()
    assert artifact_by_path(folder, path)["status"] == "present"
    assert len(rows(folder, "SELECT * FROM remote_entry")) == 1
    assert len(rows(folder, "SELECT * FROM blob")) == 1


def test_changed_fetch_failure_keeps_previous_blob(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    path = "Inbox/Drafts/a.docx"
    client = FakeFtpClient({path: b"old"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    old_hash = artifact_by_path(folder, path)["blob_hash"]
    old_size = artifact_by_path(folder, path)["remote_size"]

    client.add(path, b"new content", mtime="2026-10-16T16:00:00")
    client.fail_fetch.add(path)
    report = syncer.sync()

    assert len(report.failures) == 1
    artifact = artifact_by_path(folder, path)
    assert artifact["status"] == "failed"
    assert artifact["blob_hash"] == old_hash
    assert artifact["remote_size"] == old_size
    assert len(rows(folder, "SELECT * FROM blob")) == 1


def test_listing_failure_keeps_previous_manifest(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient({"Inbox/Drafts/a.docx": b"content"})
    syncer = Syncer(folder, client, clock=lambda: NOW)
    syncer.sync()
    manifest_before = rows(folder, "SELECT * FROM remote_entry")

    client.fail_list.add("Inbox/Drafts")
    report = syncer.sync()

    failed = [path for path in report.paths if path.path == "Inbox/Drafts"][0]
    assert failed.error is not None
    assert rows(folder, "SELECT * FROM remote_entry") == manifest_before


def test_unsafe_names_are_not_fetched(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient({"Inbox/Drafts/-rf": b"junk"})
    syncer = Syncer(folder, client, clock=lambda: NOW)

    report = syncer.sync()

    assert report.fetched == 0
    assert client.fetch_calls == []
    assert rows(folder, "SELECT * FROM remote_entry") == []


def test_explicit_paths_are_supported(tmp_path: Path) -> None:
    folder = make_folder(tmp_path)
    client = FakeFtpClient(
        {
            "Inbox/Drafts/a.docx": b"a",
            "Inbox/final.zip": b"zip",
        }
    )
    syncer = Syncer(folder, client, clock=lambda: NOW)

    report = syncer.sync(["Inbox/Drafts"])

    assert client.list_calls == ["Inbox/Drafts"]
    assert report.fetched == 1
    assert report.paths[0].path == "Inbox/Drafts"
