"""Contract tests for the write/sync API endpoints."""

from __future__ import annotations

import io
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from mirko.api import create_app
from mirko.ftp import FakeFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.ingest.tdoc_projection import ensure_tdoc
from mirko.meeting_folder import MeetingFolder

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
            "base_path": "/Meetings_3GPP_SYNC/SA3",
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


def test_sync_endpoint_runs_worker(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    app = create_app(
        folder,
        ftp_client=FakeFtpClient(
            {
                "AgendaWithTdocAllocation_2026-10-16_14h37.htm": agenda_html().encode(),
                "Inbox/Drafts/draft S3-264202-r1.docx": b"draft",
            }
        ),
        clock=lambda: NOW,
    )
    client = TestClient(app)

    response = client.post("/api/sync")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["fetched"] == 1
    assert payload["deferred"] == 1
    assert payload["agenda"] in {"ingested", "unchanged"}

    tdocs = client.get("/api/tdocs").json()
    assert {item["tdoc_number"] for item in tdocs} >= {"S3-264202"}

    status = client.get("/api/sync/status").json()
    assert status["health"] == "ok"
    assert status["last_success_at"] == "2026-10-16T14:37:00.000000Z"


def test_track_and_note_endpoints(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    AgendaIngestor(folder, clock=lambda: NOW).ingest(agenda_html())
    client = TestClient(create_app(folder))

    tracked = client.post("/api/tdocs/S3-264202/track")
    assert tracked.status_code == 200
    assert tracked.json() == {"tdoc_number": "S3-264202", "is_tracked": True}
    assert client.get("/api/tdocs/S3-264202").json()["is_tracked"] is True

    untracked = client.delete("/api/tdocs/S3-264202/track")
    assert untracked.json() == {"tdoc_number": "S3-264202", "is_tracked": False}

    note = client.post(
        "/api/notes",
        json={
            "target_kind": "tdoc",
            "target_ref": "S3-264202",
            "body": "Support this CR.",
            "position_tag": "Support",
        },
    )
    assert note.status_code == 201
    assert note.json()["id"] >= 1
    assert client.get("/api/tdocs/S3-264202").json()["notes_count"] == 1

    log = client.get("/api/log").json()
    assert [(item["action"], item["target_ref"]) for item in log[:3]] == [
        ("note_created", "S3-264202"),
        ("untrack", "S3-264202"),
        ("track", "S3-264202"),
    ]
    assert log[0]["detail"] == "[Support] Support this CR."

    assert client.post("/api/tdocs/S3-999999/track").status_code == 404
    assert client.delete("/api/tdocs/S3-999999/track").status_code == 404
    assert (
        client.post(
            "/api/notes",
            json={
                "target_kind": "tdoc",
                "target_ref": "S3-999999",
                "body": "nope",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/notes",
            json={
                "target_kind": "tdoc",
                "target_ref": "S3-264202",
                "body": "   ",
            },
        ).status_code
        == 422
    )


def workbook_bytes(tdoc: str = "S3-264202") -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "TDoc_List"
    sheet.append(
        ["TDoc", "Title", "Source", "Type", "For", "Agenda item", "TDoc Status"]
    )
    sheet.append([tdoc, "Excel title", "Excel source", "CR", "Approval", "5.3", "agreed"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_settings_roundtrip_preserves_unknown_keys(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    data = json.loads(folder.config_path.read_text())
    data["custom"] = {"keep": True}
    folder.update_config(data)
    client = TestClient(create_app(folder))

    current = client.get("/api/settings").json()
    assert current["source"]["host"] == "10.10.10.10"
    assert current["source"]["password_set"] is False
    assert current["lazy_drafts"] is True
    assert current["excel"] == "S3-26_meeting_allocation.xlsx"

    updated = client.put(
        "/api/settings",
        json={
            "kind": "local",
            "protocol": "ftp",
            "host": "10.10.10.11",
            "port": 2121,
            "base_path": "/Meetings_3GPP_SYNC/SA3/",
            "username": "mirko",
            "password": "secret",
            "tls": "none",
            "lazy_drafts": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["source"]["host"] == "10.10.10.11"
    assert updated.json()["source"]["password_set"] is True
    assert updated.json()["lazy_drafts"] is False

    saved = json.loads(folder.config_path.read_text())
    assert saved["custom"] == {"keep": True}
    assert saved["source"]["password"] == "secret"
    assert saved["sync"]["lazy_drafts"] is False
    assert stat.S_IMODE(folder.config_path.stat().st_mode) == 0o600
    assert folder.config.source.endpoint_id == (
        "ftp://10.10.10.11:2121/Meetings_3GPP_SYNC/SA3/"
    )

    invalid = client.put(
        "/api/settings",
        json={
            "kind": "local",
            "protocol": "ftp",
            "host": "bad host",
            "port": 21,
            "base_path": "/Meetings_3GPP_SYNC/SA3",
            "username": "mirko",
            "tls": "none",
            "lazy_drafts": True,
        },
    )
    assert invalid.status_code == 422
    assert "source.host" in invalid.text


def test_fetch_endpoint_downloads_deferred_draft(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    draft = "Inbox/Drafts/draft S3-264202-r1.docx"
    app = create_app(
        folder,
        ftp_client=FakeFtpClient(
            {
                "AgendaWithTdocAllocation_2026-10-16_14h37.htm": agenda_html().encode(),
                draft: b"draft",
            }
        ),
        clock=lambda: NOW,
    )
    client = TestClient(app)
    assert client.post("/api/sync").status_code == 200

    detail = client.get("/api/tdocs/S3-264202").json()
    artifact = next(item for item in detail["artifacts"] if item["logical_path"] == draft)
    assert artifact["blob_hash"] is None

    fetched = client.post("/api/tdocs/S3-264202/fetch?lineage=false")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["fetched"] == 1

    detail = client.get("/api/tdocs/S3-264202").json()
    artifact = next(item for item in detail["artifacts"] if item["logical_path"] == draft)
    assert artifact["blob_hash"] is not None
    assert artifact["status"] == "present"


def test_excel_upload_ingests_and_updates_config(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    client = TestClient(create_app(folder, clock=lambda: NOW))
    raw = workbook_bytes()

    response = client.post(
        "/api/import/excel?filename=TDoc_List_Meeting_SA3%23130.xlsx",
        content=raw,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ingested"
    assert payload["row_count"] == 1
    assert json.loads(folder.config_path.read_text())["paths"]["excel"] == (
        "TDoc_List_Meeting_SA3#130.xlsx"
    )
    assert (folder.imports_dir / "TDoc_List_Meeting_SA3#130.xlsx").read_bytes() == raw
    assert client.get("/api/tdocs/S3-264202").json()["title"] == "Excel title"

    forced = client.post(
        "/api/import/excel?filename=TDoc_List_Meeting_SA3%23130.xlsx&force=true",
        content=raw,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "ingested"

    bad = client.post(
        "/api/import/excel?filename=../evil.xlsx",
        content=raw,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert bad.status_code == 400


def test_track_expands_lineage_and_notifications(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    AgendaIngestor(folder, clock=lambda: NOW).ingest(agenda_html())
    connection = folder.connect()
    try:
        ensure_tdoc(
            connection,
            "S3-264203",
            source="filename",
            observed_at="2026-10-16T14:00:00.000000Z",
        )
        connection.commit()
    finally:
        connection.close()
    client = TestClient(create_app(folder, clock=lambda: NOW))

    assert client.post("/api/tdocs/S3-264202/track").status_code == 200
    tdocs = {
        row["tdoc_number"]: row
        for row in client.get("/api/tdocs").json()
    }
    assert tdocs["S3-264202"]["is_tracked"] is True
    assert tdocs["S3-264203"]["is_tracked"] is True

    future = "2099-01-01T00:00:00.000000Z"
    connection = folder.connect()
    try:
        ensure_tdoc(
            connection,
            "S3-264999",
            source="filename",
            observed_at=future,
        )
        connection.execute(
            "INSERT INTO assertion(subject_kind, subject_ref, predicate, "
            "object_kind, object_ref, source, confidence, verified, active, "
            "muted, observed_at) VALUES "
            "('tdoc', 'S3-264202', 'revision_of', 'tdoc', 'S3-264999', "
            "'html', 1.0, 1, 1, 0, ?)",
            (future,),
        )
        connection.execute(
            "INSERT INTO artifact(kind, logical_path, filename, tdoc_number, "
            "first_seen_at, last_seen_at, source_kind, endpoint_id, status) "
            "VALUES ('working_draft', 'Inbox/Drafts/new.docx', 'new.docx', "
            "'S3-264202', ?, ?, 'local', ?, 'remote')",
            (future, future, folder.config.source.endpoint_id),
        )
        connection.execute(
            "INSERT INTO assertion(subject_kind, subject_ref, predicate, "
            "value, source, confidence, verified, active, muted, observed_at) "
            "VALUES ('tdoc', 'S3-264202', 'decision', 'agreed', 'html', 1.0, "
            "1, 1, 0, ?)",
            (future,),
        )
        connection.commit()
    finally:
        connection.close()

    items = client.get("/api/notifications").json()
    kinds = {item["kind"] for item in items}
    assert {"lineage", "artifact", "decision"} <= kinds
    lineage = next(item for item in items if item["kind"] == "lineage")
    assert lineage["action"] == "track"
    assert lineage["action_ref"] == "S3-264999"
    assert "S3-264999" in lineage["tdocs"]
