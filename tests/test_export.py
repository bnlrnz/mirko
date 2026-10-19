"""Markdown export and finalize/archive tests."""

from __future__ import annotations

import mailbox
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from fastapi.testclient import TestClient

from mirko.api import create_app
from mirko.export import finalize, materialize_mirror, render_markdown
from mirko.ftp import FakeFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.ingest.filename_ingest import FilenameIngestor
from mirko.ingest.mail_ingest import MailIngestor
from mirko.meeting_folder import MeetingFolder
from mirko.sync import Syncer

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)

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
            "Original CR",
            "Huawei",
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
            "Revised CR",
            "Huawei",
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


def add_message(path: Path) -> None:
    message = EmailMessage()
    message["Message-ID"] = "<t1@example.org>"
    message["Subject"] = "[SA3#130][S3-264202] CR on QUIC"
    message["From"] = "Alice <alice@example.org>"
    message["To"] = "Bob <bob@example.org>"
    message["Date"] = format_datetime(NOW)
    message.set_content("Please review.")
    box = mailbox.mbox(str(path))
    try:
        box.add(message)
        box.flush()
    finally:
        box.close()


def seeded_folder(tmp_path: Path) -> MeetingFolder:
    mbox_path = tmp_path / "mail.mbox"
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config(mbox_path))
    client = FakeFtpClient(
        {
            "AgendaWithTdocAllocation_2026-10-16_14h37.htm": agenda_html().encode(),
            "Inbox/Drafts/draft S3-264202-r1.docx": b"draft",
        }
    )
    Syncer(folder, client, clock=lambda: NOW).sync()
    AgendaIngestor(folder, clock=lambda: NOW).ingest(agenda_html())
    FilenameIngestor(folder, clock=lambda: NOW).ingest()
    add_message(mbox_path)
    MailIngestor(folder, clock=lambda: NOW).ingest()

    connection = folder.connect()
    try:
        connection.execute(
            "UPDATE tdoc SET is_tracked = 1 WHERE tdoc_number = 'S3-264202'"
        )
        connection.execute(
            "INSERT INTO note(target_kind, target_ref, body, position_tag, "
            "author, source) VALUES ('tdoc', 'S3-264202', "
            "'Support this CR.', 'Support', 'ben', 'user')"
        )
        connection.commit()
    finally:
        connection.close()
    return folder


def test_render_markdown_is_deterministic(tmp_path: Path) -> None:
    folder = seeded_folder(tmp_path)
    first = render_markdown(folder, generated_at=NOW)
    second = render_markdown(folder, generated_at=NOW)
    assert first == second

    assert first.startswith("# SA3#130 Prague")
    assert "Generated: 2026-10-16T15:00:00Z" in first
    assert "| S3-264202 | 5.3.1.3 | CR | revised | Huawei | 1 | yes |" in first
    assert "| S3-264203 | 5.3.1.3 | CR | agreed | Huawei | 0 | no |" in first
    assert "## S3-264202" in first
    assert "```mermaid" in first
    assert "graph LR" in first
    assert "revision_of" in first
    assert "[Support] Support this CR." in first
    assert "draft S3-264202-r1.docx" in first
    assert "_(ephemeral)_" in first
    assert "### Mail" not in first

    with_mail = render_markdown(folder, include_mail=True, generated_at=NOW)
    assert "### Mail" in with_mail
    assert "CR on QUIC" in with_mail


def test_render_lists_inactive_branches(tmp_path: Path) -> None:
    folder = seeded_folder(tmp_path)
    connection = folder.connect()
    try:
        connection.execute(
            "INSERT INTO assertion(subject_kind, subject_ref, predicate, "
            "object_kind, object_ref, source, confidence, active, muted) "
            "VALUES ('tdoc', 'S3-264203', 'merged_into', 'tdoc', "
            "'S3-264202', 'filename', 0.4, 0, 0)"
        )
        connection.commit()
    finally:
        connection.close()
    rendered = render_markdown(folder, generated_at=NOW)
    assert "Muted / inactive branches" in rendered
    assert "S3-264203 → S3-264202 (merged_into, inactive hint)" in rendered


def test_finalize_writes_export_mirror_and_flag(tmp_path: Path) -> None:
    folder = seeded_folder(tmp_path)
    result = finalize(folder, clock=lambda: NOW)

    export_path = folder.path / result["export_path"]
    assert export_path.is_file()
    assert export_path.name == "mirko-SA3-130-20261016T150000Z.md"
    assert result["status"] == "finalized"
    assert result["mirror_links"] >= 1

    mirror = folder.mirror_dir / "Inbox" / "Drafts" / "draft S3-264202-r1.docx"
    assert mirror.is_symlink()
    assert not mirror.readlink().is_absolute()

    connection = folder.connect()
    try:
        meta = dict(connection.execute("SELECT key, value FROM meeting_meta"))
    finally:
        connection.close()
    assert meta["finalized"] == "1"
    assert meta["export_path"] == result["export_path"]

    assert materialize_mirror(folder) >= 1
    assert finalize(folder, clock=lambda: NOW) == result


def test_export_api_and_finalize_endpoint(tmp_path: Path) -> None:
    folder = seeded_folder(tmp_path)
    client = TestClient(create_app(folder, clock=lambda: NOW))

    exported = client.get("/api/export/markdown")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/markdown")
    assert "attachment" in exported.headers["content-disposition"]
    assert "# SA3#130 Prague" in exported.text

    finalized = client.post("/api/finalize")
    assert finalized.status_code == 200
    payload = finalized.json()
    assert payload["status"] == "finalized"
    assert (folder.path / payload["export_path"]).is_file()
