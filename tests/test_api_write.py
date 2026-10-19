"""Contract tests for the write/sync API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from mirko.api import create_app
from mirko.ftp import FakeFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
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
    assert payload["fetched"] == 2
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
