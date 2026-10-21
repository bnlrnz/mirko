"""Conflict, assertion, and annotation endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from mirko.api import create_app
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
            "base_path": "/Meetings_3GPP_SYNC/SA3",
            "username": "anonymous",
        },
    }


def agenda_html(
    *,
    decision: str = "agreed",
    replaced_by: str = "",
    tdoc: str = "S3-264202",
) -> str:
    row = [
        "5.3.1.3",
        "Topic",
        tdoc,
        "Original",
        "Source",
        "CR",
        "Approval",
        "Yes",
        "No",
        decision,
        "No",
        replaced_by,
        "",
    ]
    parts = ["<table><thead>"]
    parts += [f"<th>{header}</th>" for header in HEADER]
    parts.append("</thead>")
    parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def make_client(tmp_path: Path, html: str) -> TestClient:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    AgendaIngestor(folder, clock=lambda: NOW).ingest(html)
    return TestClient(create_app(folder))


def test_manual_decision_conflicts_with_html(tmp_path: Path) -> None:
    client = make_client(tmp_path, agenda_html(decision="agreed"))

    created = client.post(
        "/api/assertions",
        json={
            "subject_ref": "S3-264202",
            "predicate": "decision",
            "value": "revised",
            "detail": "my read",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    conflicts = client.get("/api/conflicts").json()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["predicate"] == "decision"
    assert conflict["subject_ref"] == "S3-264202"
    assert conflict["status"] == "open"
    sources = {item["source"] for item in conflict["assertions"]}
    assert sources == {"html", "user"}

    resolved = client.post(
        f"/api/conflicts/{conflict['id']}/resolve",
        json={"resolution": "keep_mine", "note": "SA3 agreed to revise"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    assert client.get("/api/conflicts").json() == []
    detail = client.get("/api/tdocs/S3-264202").json()
    user = next(a for a in detail["assertions"] if a["id"] == user_id)
    html = next(a for a in detail["assertions"] if a["source"] == "html")
    assert user["active"] is True and user["muted"] is False
    assert user["verified"] is True
    assert html["active"] is False and html["muted"] is True


def test_manual_assertion_agreeing_is_verified(tmp_path: Path) -> None:
    client = make_client(tmp_path, agenda_html(decision="agreed"))
    created = client.post(
        "/api/assertions",
        json={
            "subject_ref": "S3-264202",
            "predicate": "decision",
            "value": "agreed",
        },
    )
    assert created.status_code == 201
    assert created.json()["verified"] is True
    assert client.get("/api/conflicts").json() == []


def test_missing_replaced_by_opens_lineage_conflict(tmp_path: Path) -> None:
    client = make_client(tmp_path, agenda_html(decision="revised"))
    conflicts = client.get("/api/conflicts").json()
    assert any(
        item["predicate"] == "lineage" and item["subject_ref"] == "S3-264202"
        for item in conflicts
    )
    conflict = next(
        item for item in conflicts if item["predicate"] == "lineage"
    )
    resolved = client.post(
        f"/api/conflicts/{conflict['id']}/resolve",
        json={"resolution": "repair", "note": "linked manually"},
    )
    assert resolved.status_code == 200


def test_assertion_patch_and_note_lifecycle(tmp_path: Path) -> None:
    client = make_client(tmp_path, agenda_html(decision="agreed"))
    assertion = client.post(
        "/api/assertions",
        json={
            "subject_ref": "S3-264202",
            "predicate": "decision",
            "value": "agreed",
        },
    ).json()

    muted = client.patch(
        f"/api/assertions/{assertion['id']}", json={"muted": True}
    )
    assert muted.status_code == 200
    assert muted.json()["muted"] is True
    assert (
        client.patch("/api/assertions/999999", json={"active": False}).status_code
        == 404
    )

    note = client.post(
        "/api/notes",
        json={
            "target_kind": "tdoc",
            "target_ref": "S3-264202",
            "body": "Original",
        },
    ).json()
    updated = client.patch(
        f"/api/notes/{note['id']}",
        json={"body": "Edited"},
    )
    assert updated.status_code == 200
    assert updated.json()["body"] == "Edited"

    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get("/api/tdocs/S3-264202").json()["notes_count"] == 0
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404

    log = client.get("/api/log").json()
    assert [item["action"] for item in log[:3]] == [
        "note_deleted",
        "note_updated",
        "note_created",
    ]
