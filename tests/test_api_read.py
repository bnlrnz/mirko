"""Contract tests for the read-model API."""

from __future__ import annotations

import mailbox
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mirko.api import create_app
from mirko.ftp import FakeFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.ingest.filename_ingest import FilenameIngestor
from mirko.ingest.mail_ingest import MailIngestor
from mirko.meeting_folder import MeetingFolder
from mirko.sync import Syncer

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

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


def minimal_config(mbox_path: Path) -> dict:
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
        "mail": {"kind": "mbox", "path": str(mbox_path)},
    }


def agenda_html() -> str:
    rows = [
        [
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
        ],
        [
            "5.3.1.3",
            "Topic",
            "S3-264203",
            "Revised",
            "Source",
            "CR",
            "Approval",
            "Yes",
            "No",
            "agreed",
            "No",
            "",
            "S3-264202",
        ],
    ]
    parts = ["<table><thead>"]
    parts += [f"<th>{header}</th>" for header in HEADER]
    parts.append("</thead>")
    for row in rows:
        parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def add_message(
    path: Path,
    *,
    message_id: str,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["Message-ID"] = f"<{message_id}>"
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.org>"
    message["To"] = "Bob <bob@example.org>"
    message["Date"] = format_datetime(NOW)
    message.set_content(body)
    box = mailbox.mbox(str(path))
    try:
        box.add(message)
        box.flush()
    finally:
        box.close()


@pytest.fixture()
def seeded_folder(tmp_path: Path) -> MeetingFolder:
    mbox_path = tmp_path / "mail.mbox"
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config(mbox_path))

    AgendaIngestor(folder, clock=lambda: NOW).ingest(agenda_html())
    Syncer(
        folder,
        FakeFtpClient(
            {
                "Inbox/Drafts/draft S3-264202-r1.docx": b"draft",
                "Inbox/Drafts/draft-S3-264999-r1-merger of S3-263700.docx": b"new",
                "Inbox/Drafts/Meeting notes for Monday.docx": b"notes",
            }
        ),
        clock=lambda: NOW,
    ).sync(["Inbox/Drafts"])
    FilenameIngestor(folder, clock=lambda: NOW).ingest()

    add_message(
        mbox_path,
        message_id="t1@example.org",
        subject="[SA3#130][S3-264202] CR on QUIC",
        body="Please review.",
    )
    add_message(
        mbox_path,
        message_id="t2@example.org",
        subject="[SA3#130][5.3.1.3] LS on security",
        body="No tdoc token in the subject.",
    )
    MailIngestor(folder, clock=lambda: NOW).ingest()

    connection = folder.connect()
    try:
        connection.execute(
            "UPDATE tdoc SET is_tracked = 1 WHERE tdoc_number = 'S3-264202'"
        )
        connection.execute(
            "INSERT INTO note(target_kind, target_ref, body, position_tag, "
            "author, source, created_at, updated_at) "
            "VALUES ('tdoc', 'S3-264202', 'Support this CR.', 'Support', "
            "'ben', 'user', ?, ?)",
            ("2026-10-16T13:00:00.000000Z", "2026-10-16T13:00:00.000000Z"),
        )
        connection.execute(
            "INSERT INTO conflict(predicate, subject_ref, assertion_ids, status) "
            "VALUES ('decision', 'S3-264202', '[]', 'open')"
        )
        connection.commit()
    finally:
        connection.close()
    return folder


@pytest.fixture()
def client(seeded_folder: MeetingFolder) -> TestClient:
    return TestClient(create_app(seeded_folder))


def test_list_tdocs_and_filters(client: TestClient) -> None:
    response = client.get("/api/tdocs")
    assert response.status_code == 200
    numbers = {item["tdoc_number"] for item in response.json()}
    assert {"S3-264202", "S3-264203", "S3-264999"} <= numbers

    tracked = client.get("/api/tdocs", params={"tracked": "true"}).json()
    assert [item["tdoc_number"] for item in tracked] == ["S3-264202"]

    agreed = client.get("/api/tdocs", params={"state": "agreed"}).json()
    assert [item["tdoc_number"] for item in agreed] == ["S3-264203"]

    agenda = client.get("/api/tdocs", params={"agenda": "5.3.1.3"}).json()
    assert {item["tdoc_number"] for item in agenda} == {"S3-264202", "S3-264203"}

    provisional = client.get(
        "/api/tdocs", params={"tracked": "false"}
    ).json()
    assert any(item["tdoc_number"] == "S3-264999" for item in provisional)


def test_tdoc_detail_has_related_data(client: TestClient) -> None:
    response = client.get("/api/tdocs/S3-264202")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Original"
    assert data["decision"] == "revised"
    assert data["is_tracked"] is True
    assert data["has_conflict"] is True
    assert data["notes_count"] == 1
    assert len(data["artifacts"]) == 1
    assert len(data["notes"]) == 1
    assert len(data["emails"]) == 1
    predicates = {item["predicate"] for item in data["assertions"]}
    assert {"decision", "revision_of"} <= predicates
    assert client.get("/api/tdocs/S3-999999").status_code == 404


def test_timeline_aggregates_events(client: TestClient) -> None:
    response = client.get("/api/tdocs/S3-264202/timeline")
    assert response.status_code == 200
    events = response.json()
    kinds = {event["kind"] for event in events}
    assert {"discovered", "artifact", "email", "note", "state", "lineage"} <= kinds
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert any(event["ephemeral"] for event in events) is True
    assert client.get("/api/tdocs/S3-999999/timeline").status_code == 404


def test_lineage_tracked_and_full(client: TestClient) -> None:
    tracked = client.get("/api/lineage", params={"tracked": "true"}).json()
    assert {node["tdoc_number"] for node in tracked["nodes"]} == {
        "S3-264202",
        "S3-264203",
    }
    assert len(tracked["edges"]) == 1
    assert tracked["edges"][0]["kind"] == "revision_of"

    full = client.get("/api/lineage").json()
    assert any(node["tdoc_number"] == "S3-264999" for node in full["nodes"])


def test_mail_filters_and_search(client: TestClient) -> None:
    by_tdoc = client.get("/api/mail", params={"tdoc": "S3-264202"}).json()
    assert len(by_tdoc) == 1
    assert by_tdoc[0]["message_id"] == "t1@example.org"

    searched = client.get("/api/mail", params={"q": "QUIC"}).json()
    assert [item["message_id"] for item in searched] == ["t1@example.org"]

    by_agenda = client.get("/api/mail", params={"agenda": "5.3.1.3"}).json()
    assert [item["message_id"] for item in by_agenda] == ["t2@example.org"]


def test_discovery_lists_new_numbers_hints_and_agenda_mail(
    client: TestClient,
) -> None:
    items = client.get("/api/discovery").json()
    kinds = {item["kind"] for item in items}
    assert {"provisional_tdoc", "filename_hint", "agenda_mail"} <= kinds
    provisional = [
        item for item in items if item["kind"] == "provisional_tdoc"
    ]
    assert {item["ref"] for item in provisional} == {"S3-264999"}


def test_sync_status_exposes_freshness_and_counts(client: TestClient) -> None:
    response = client.get("/api/sync/status")
    assert response.status_code == 200
    data = response.json()
    assert data["endpoint"] == "ftp://10.10.10.10:21/ftp/SA/SA3"
    assert data["interval_s"] == 45
    assert data["counts"]["tdocs"] >= 3
    assert data["counts"]["emails"] == 2
    assert data["counts"]["open_conflicts"] == 1
    assert data["refresh"]["agenda"] is not None
    assert data["refresh"]["drafts"] is not None
    assert data["refresh"]["mail"] is not None


def test_events_endpoint_is_sse(client: TestClient) -> None:
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: ready" in response.text


def test_openapi_contains_read_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/tdocs",
        "/api/tdocs/{tdoc_number}",
        "/api/tdocs/{tdoc_number}/timeline",
        "/api/lineage",
        "/api/mail",
        "/api/discovery",
        "/api/sync/status",
    ):
        assert path in paths
