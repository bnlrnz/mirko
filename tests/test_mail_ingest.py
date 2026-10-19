"""Integration tests for mbox/EML mail ingestion."""

from __future__ import annotations

import mailbox
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from mirko.ingest.mail_ingest import MailIngestor
from mirko.meeting_folder import MeetingFolder

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def base_config(mail: dict) -> dict:
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
        "mail": mail,
    }


def make_message(
    *,
    message_id: str,
    subject: str,
    body: str,
    references: str | None = None,
    date: datetime = NOW,
) -> EmailMessage:
    message = EmailMessage()
    message["Message-ID"] = f"<{message_id}>"
    message["Subject"] = subject
    message["From"] = "Alice <alice@example.org>"
    message["To"] = "Bob <bob@example.org>"
    message["Cc"] = "Carol <carol@example.org>"
    message["Date"] = format_datetime(date)
    if references:
        message["References"] = references
    message.set_content(body)
    return message


def write_mbox(path: Path, messages: list[EmailMessage]) -> None:
    path.unlink(missing_ok=True)
    box = mailbox.mbox(str(path))
    try:
        for message in messages:
            box.add(message)
        box.flush()
    finally:
        box.close()


def rows(folder: MeetingFolder, sql: str, params: tuple = ()):  # type: ignore[no-untyped-def]
    connection = folder.connect()
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def make_mbox_folder(tmp_path: Path) -> tuple[MeetingFolder, Path]:
    mbox_path = tmp_path / "sa3.mbox"
    folder = MeetingFolder.create(
        tmp_path / "SA3-130",
        base_config({"kind": "mbox", "path": str(mbox_path)}),
    )
    return folder, mbox_path


def test_mbox_ingest_mentions_blobs_and_fts(tmp_path: Path) -> None:
    folder, mbox_path = make_mbox_folder(tmp_path)
    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="msg1@example.org",
                subject="[SA3#130][S3-264202] CR on QUIC",
                body="Please review S3-264999 as well.",
            )
        ],
    )

    result = MailIngestor(folder, clock=lambda: NOW).ingest()

    assert result.kind == "mbox"
    assert result.examined == 1
    assert result.new_messages == 1
    assert result.mentions == 2
    assert set(result.provisional) == {"S3-264202", "S3-264999"}
    assert result.threads_created == 1

    email = rows(folder, "SELECT * FROM email")[0]
    assert email["message_id"] == "msg1@example.org"
    assert email["subject"].startswith("[SA3#130]")
    assert email["agenda_item"] is None
    assert email["meeting_id"] == "SA3#130"
    assert email["from_addr"] == "Alice <alice@example.org>"
    assert email["to_addrs"] == "Bob <bob@example.org>"
    assert email["cc_addrs"] == "Carol <carol@example.org>"
    assert email["date_utc"] == "2026-10-16T12:00:00.000000Z"

    blobs = {
        row["hash"] for row in rows(folder, "SELECT hash FROM blob")
    }
    assert email["raw_blob_hash"] in blobs
    assert email["body_blob_hash"] in blobs

    mentions = {
        (row["tdoc_number"], row["scope"], row["confidence"])
        for row in rows(folder, "SELECT * FROM email_mention")
    }
    assert mentions == {
        ("S3-264202", "subject", 0.9),
        ("S3-264999", "body", 0.5),
    }
    assert len(rows(folder, "SELECT * FROM email_fts WHERE email_fts MATCH 'QUIC'")) == 1

    tdocs = {row["tdoc_number"] for row in rows(folder, "SELECT * FROM tdoc")}
    assert tdocs == {"S3-264202", "S3-264999"}


def test_mbox_reingest_is_skipped_by_identity(tmp_path: Path) -> None:
    folder, mbox_path = make_mbox_folder(tmp_path)
    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="msg1@example.org",
                subject="[SA3#130] Hello",
                body="No tdoc here.",
            )
        ],
    )
    ingestor = MailIngestor(folder, clock=lambda: NOW)

    first = ingestor.ingest()
    second = ingestor.ingest()

    assert first.new_messages == 1
    assert second.new_messages == 0
    assert second.examined == 0
    assert second.skipped == 1
    assert len(rows(folder, "SELECT * FROM email")) == 1
    assert len(rows(folder, "SELECT * FROM email_fts")) == 1


def test_message_id_dedup_when_mbox_changes(tmp_path: Path) -> None:
    folder, mbox_path = make_mbox_folder(tmp_path)
    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="same@example.org",
                subject="[SA3#130] Hello",
                body="First body.",
            )
        ],
    )
    MailIngestor(folder, clock=lambda: NOW).ingest()

    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="same@example.org",
                subject="[SA3#130] Hello",
                body="First body.",
            ),
            make_message(
                message_id="new@example.org",
                subject="Re: [SA3#130] Hello",
                body="Second body.",
            ),
        ],
    )
    result = MailIngestor(folder, clock=lambda: NOW).ingest()

    assert result.examined == 2
    assert result.new_messages == 1
    assert result.skipped == 1
    assert len(rows(folder, "SELECT * FROM email")) == 2
    threads = rows(folder, "SELECT * FROM email ORDER BY id")
    assert threads[0]["thread_id"] == threads[1]["thread_id"]


def test_threads_follow_references(tmp_path: Path) -> None:
    folder, mbox_path = make_mbox_folder(tmp_path)
    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="root@example.org",
                subject="[SA3#130] Original",
                body="Root.",
            ),
            make_message(
                message_id="reply@example.org",
                subject="Completely different subject",
                body="Reply.",
                references="<root@example.org>",
            ),
        ],
    )

    result = MailIngestor(folder, clock=lambda: NOW).ingest()

    assert result.threads_created == 1
    emails = rows(folder, "SELECT * FROM email ORDER BY id")
    assert emails[0]["thread_id"] == emails[1]["thread_id"]


def test_eml_directory_ingest_is_incremental(tmp_path: Path) -> None:
    eml_dir = tmp_path / "mail"
    eml_dir.mkdir()
    folder = MeetingFolder.create(
        tmp_path / "SA3-130",
        base_config({"kind": "eml", "eml_dir": str(eml_dir)}),
    )
    message = make_message(
        message_id="eml1@example.org",
        subject="[SA3#130][S3-264500] EML message",
        body="Body text.",
    )
    (eml_dir / "one.eml").write_bytes(message.as_bytes())
    ingestor = MailIngestor(folder, clock=lambda: NOW)

    first = ingestor.ingest()
    second = ingestor.ingest()

    assert first.kind == "eml"
    assert first.new_messages == 1
    assert first.mentions == 1
    assert second.new_messages == 0
    assert second.examined == 0
    assert len(rows(folder, "SELECT * FROM email")) == 1

    (eml_dir / "two.eml").write_bytes(
        make_message(
            message_id="eml2@example.org",
            subject="[SA3#130] Another",
            body="More.",
        ).as_bytes()
    )
    third = ingestor.ingest()
    assert third.examined == 1
    assert third.new_messages == 1


def test_bad_message_does_not_stop_ingest(tmp_path: Path) -> None:
    folder, mbox_path = make_mbox_folder(tmp_path)
    write_mbox(
        mbox_path,
        [
            make_message(
                message_id="good@example.org",
                subject="[SA3#130] Good",
                body="Good body.",
            )
        ],
    )
    connection = folder.connect()
    try:
        connection.execute(
            "INSERT INTO email(message_id, subject) VALUES ('good@example.org', 'x')"
        )
        connection.commit()
    finally:
        connection.close()

    result = MailIngestor(folder, clock=lambda: NOW).ingest()

    assert result.new_messages == 0
    assert result.skipped == 1
    assert result.errors == ()
