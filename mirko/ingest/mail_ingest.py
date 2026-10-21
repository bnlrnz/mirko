"""Incremental ingestion of local mbox / EML mail into SQLite."""

from __future__ import annotations

import hashlib
import html
import json
import mailbox
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable

from mirko.blob_store import BlobStore
from mirko.ingest.mail_subject import SubjectInfo, normalize_subject, parse_subject
from mirko.ingest.tdoc_projection import ensure_tdoc
from mirko.meeting_folder import MeetingFolder

_CANON_RE = re.compile(r"(?<![A-Za-z0-9])S3[-_ ]?(\d{6})(?!\d)", re.IGNORECASE)
_MESSAGE_ID_RE = re.compile(r"<([^<>]+)>")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"[ \t]+")

MBOX_STATE_KEY = "mail.mbox.state"
EML_STATE_KEY = "mail.eml.state"


class MailError(RuntimeError):
    """Raised when the configured mail source cannot be read."""


@dataclass(frozen=True)
class MailIngestResult:
    kind: str | None
    path: str | None
    examined: int = 0
    new_messages: int = 0
    skipped: int = 0
    mentions: int = 0
    provisional: tuple[str, ...] = ()
    threads_created: int = 0
    errors: tuple[str, ...] = ()


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return _WHITESPACE.sub(" ", "".join(parts)).strip()


def clean_message_id(value: str | None) -> str | None:
    if not value:
        return None
    match = _MESSAGE_ID_RE.search(value)
    text = match.group(1) if match else value
    text = text.strip().strip("<>").strip()
    return text or None


def reference_ids(message: Message) -> tuple[str, ...]:
    found: list[str] = []
    for header in ("References", "In-Reply-To"):
        for value in message.get_all(header, []):
            for match in _MESSAGE_ID_RE.finditer(value):
                identifier = match.group(1).strip()
                if identifier and identifier not in found:
                    found.append(identifier)
            if "<" not in value:
                for token in value.split():
                    identifier = token.strip().strip("<>")
                    if "@" in identifier and identifier not in found:
                        found.append(identifier)
    return tuple(found)


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def extract_plain_text(message: Message) -> str:
    plain: list[str] = []
    markup: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain.append(_decode_part(part))
            elif content_type == "text/html":
                markup.append(_decode_part(part))
    else:
        if message.get_content_type() == "text/html":
            markup.append(_decode_part(message))
        else:
            plain.append(_decode_part(message))

    if plain:
        return "\n".join(text.strip() for text in plain if text.strip()).strip()
    raw_html = "\n".join(markup)
    text = _HTML_TAG_RE.sub(" ", raw_html)
    text = html.unescape(text)
    return _WHITESPACE.sub(" ", text).strip()


def _address_list(message: Message, header: str) -> str:
    values = [decode_header_value(value) for value in message.get_all(header, [])]
    addresses = [formataddr(pair) for pair in getaddresses(values) if pair[1]]
    return ", ".join(addresses)


def _message_date(message: Message) -> str | None:
    value = message.get("Date")
    if not value:
        return None
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    return _timestamp(moment)


def _body_tdocs(text: str, exclude: Iterable[str]) -> list[str]:
    seen = set(exclude)
    found: list[str] = []
    for match in _CANON_RE.finditer(text):
        tdoc = f"S3-{match.group(1)}"
        if tdoc not in seen:
            seen.add(tdoc)
            found.append(tdoc)
    return found


class MailIngestor:
    def __init__(
        self,
        folder: MeetingFolder,
        *,
        blobs: BlobStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.folder = folder
        self.blobs = blobs or BlobStore(folder.blobs_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(self) -> MailIngestResult:
        mail = self.folder.config.mail
        if mail is None:
            return MailIngestResult(kind=None, path=None)
        if mail.kind == "mbox":
            if not mail.path:
                raise MailError("mail.path is required for an mbox source")
            return self.ingest_mbox(Path(mail.path))
        if mail.kind == "eml":
            if not mail.eml_dir:
                raise MailError("mail.eml_dir is required for an eml source")
            return self.ingest_eml_dir(Path(mail.eml_dir))
        raise MailError(f"unsupported mail kind: {mail.kind}")

    def ingest_mbox(self, path: Path) -> MailIngestResult:
        if not path.is_file():
            raise MailError(f"mbox not found: {path}")
        stat = path.stat()
        observed_at = _timestamp(self.clock())
        connection = self.folder.connect()
        try:
            state = self._read_state(connection, MBOX_STATE_KEY)
            if state == {"size": stat.st_size, "mtime": stat.st_mtime}:
                return MailIngestResult(
                    kind="mbox", path=str(path), skipped=self._count(connection)
                )
            box = mailbox.mbox(str(path), create=False)
            try:
                messages = [
                    (key, box.get_message(key)) for key in box.keys()
                ]
            finally:
                box.close()
            result = self._ingest_messages(
                connection,
                ((key, message, message.as_bytes()) for key, message in messages),
                observed_at=observed_at,
            )
            self._write_state(
                connection,
                MBOX_STATE_KEY,
                {"size": stat.st_size, "mtime": stat.st_mtime},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return MailIngestResult(kind="mbox", path=str(path), **result)

    def ingest_eml_dir(self, directory: Path) -> MailIngestResult:
        if directory.is_file():
            if directory.suffix.lower() != ".eml":
                raise MailError(f"not an .eml file: {directory}")
            candidates = [(directory.name, directory)]
        elif directory.is_dir():
            candidates = [
                (path.relative_to(directory).as_posix(), path)
                for path in sorted(directory.rglob("*.eml"))
                if path.is_file()
            ]
        else:
            raise MailError(f"eml file or directory not found: {directory}")
        observed_at = _timestamp(self.clock())
        connection = self.folder.connect()
        try:
            state = self._read_state(connection, EML_STATE_KEY)
            next_state: dict[str, list[float]] = {}
            selected: list[tuple[str, bytes]] = []
            for relative, path in candidates:
                stat = path.stat()
                next_state[relative] = [stat.st_mtime, stat.st_size]
                if state.get(relative) == next_state[relative]:
                    continue
                selected.append((relative, path.read_bytes()))

            if not selected:
                return MailIngestResult(
                    kind="eml", path=str(directory), skipped=self._count(connection)
                )
            result = self._ingest_messages(
                connection,
                (
                    (relative, None, raw)
                    for relative, raw in selected
                ),
                observed_at=observed_at,
            )
            self._write_state(connection, EML_STATE_KEY, next_state)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return MailIngestResult(kind="eml", path=str(directory), **result)

    def _ingest_messages(
        self,
        connection: sqlite3.Connection,
        messages: Iterable[tuple[str, Message | None, bytes]],
        *,
        observed_at: str,
    ) -> dict:
        from email import message_from_bytes

        examined = 0
        new_messages = 0
        skipped = 0
        mentions = 0
        threads_created = 0
        provisional: list[str] = []
        errors: list[str] = []

        for key, message, raw in messages:
            examined += 1
            try:
                parsed_message = message or message_from_bytes(raw)
                outcome = self._ingest_message(
                    connection,
                    parsed_message,
                    raw,
                    observed_at=observed_at,
                )
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop ingest
                errors.append(f"{key}: {exc}")
                continue
            if outcome is None:
                skipped += 1
                continue
            new_messages += 1
            mentions += outcome["mentions"]
            threads_created += int(outcome["thread_created"])
            provisional.extend(outcome["provisional"])

        return {
            "examined": examined,
            "new_messages": new_messages,
            "skipped": skipped,
            "mentions": mentions,
            "provisional": tuple(dict.fromkeys(provisional)),
            "threads_created": threads_created,
            "errors": tuple(errors),
        }

    def _ingest_message(
        self,
        connection: sqlite3.Connection,
        message: Message,
        raw: bytes,
        *,
        observed_at: str,
    ) -> dict | None:
        digest = hashlib.sha256(raw).hexdigest()
        message_id = clean_message_id(message.get("Message-ID")) or (
            f"mirko-{digest}@local"
        )
        existing = connection.execute(
            "SELECT id FROM email WHERE message_id = ?", (message_id,)
        ).fetchone()
        if existing is not None:
            return None

        subject = decode_header_value(message.get("Subject"))
        parsed: SubjectInfo = parse_subject(
            subject,
            series_prefix=self.folder.config.meeting.tdoc_series_prefix,
        )
        body = extract_plain_text(message)
        normalized = normalize_subject(subject) or message_id
        references = reference_ids(message)
        thread_id, thread_created = self._resolve_thread(
            connection, message_id, references, normalized
        )

        raw_blob = self.blobs.add_bytes(raw)
        body_blob = self.blobs.add_bytes(body.encode("utf-8"))
        for blob in (raw_blob, body_blob):
            connection.execute(
                "INSERT OR IGNORE INTO blob(hash, size) VALUES (?, ?)",
                (blob.hash, blob.size),
            )

        provisional: list[str] = []
        mention_rows: dict[tuple[str, str], float] = {
            (tdoc, "subject"): 0.9 for tdoc in parsed.tdocs
        }
        for tdoc in _body_tdocs(body, parsed.tdocs):
            mention_rows[(tdoc, "body")] = 0.5

        inference = dict(parsed.inference)
        inference["references"] = list(references)
        inference["message_id"] = message_id
        cursor = connection.execute(
            "INSERT INTO email("
            "message_id, thread_id, subject, from_addr, to_addrs, cc_addrs, "
            "date_utc, agenda_item, meeting_id, body_blob_hash, raw_blob_hash, "
            "ingested_at, inference"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                thread_id,
                subject,
                _address_list(message, "From"),
                _address_list(message, "To"),
                _address_list(message, "Cc"),
                _message_date(message),
                parsed.agenda_item,
                parsed.meeting_id or self.folder.config.meeting.id,
                body_blob.hash,
                raw_blob.hash,
                observed_at,
                json.dumps(inference, ensure_ascii=False),
            ),
        )
        email_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT INTO email_fts(message_id, body) VALUES (?, ?)",
            (message_id, f"{subject}\n{body}"),
        )

        for (tdoc, scope), confidence in mention_rows.items():
            if ensure_tdoc(
                connection,
                tdoc,
                source="email",
                observed_at=observed_at,
            ):
                provisional.append(tdoc)
            connection.execute(
                "INSERT OR IGNORE INTO email_mention("
                "email_id, tdoc_number, scope, confidence"
                ") VALUES (?, ?, ?, ?)",
                (email_id, tdoc, scope, confidence),
            )

        return {
            "mentions": len(mention_rows),
            "thread_created": thread_created,
            "provisional": provisional,
        }

    def _resolve_thread(
        self,
        connection: sqlite3.Connection,
        message_id: str,
        references: tuple[str, ...],
        normalized_subject: str,
    ) -> tuple[int, bool]:
        for reference in references:
            row = connection.execute(
                "SELECT thread_id FROM email WHERE message_id = ?", (reference,)
            ).fetchone()
            if row is not None and row["thread_id"] is not None:
                return int(row["thread_id"]), False

        row = connection.execute(
            "SELECT id FROM thread WHERE normalized_subject = ? "
            "ORDER BY id LIMIT 1",
            (normalized_subject,),
        ).fetchone()
        if row is not None:
            return int(row["id"]), False

        cursor = connection.execute(
            "INSERT INTO thread(root_message_id, normalized_subject) VALUES (?, ?)",
            (message_id, normalized_subject),
        )
        return int(cursor.lastrowid), True

    def _count(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute("SELECT COUNT(*) FROM email").fetchone()[0])

    def _read_state(
        self, connection: sqlite3.Connection, key: str
    ) -> dict:
        row = connection.execute(
            "SELECT value FROM meeting_meta WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return {}
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return {}

    def _write_state(
        self, connection: sqlite3.Connection, key: str, value: dict
    ) -> None:
        connection.execute(
            "INSERT INTO meeting_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, sort_keys=True)),
        )
