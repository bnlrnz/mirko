"""One serial synchronization + ingestion cycle."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from mirko.blob_store import BlobStore
from mirko.ftp import FtpClient, LftpFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor, select_latest_agenda
from mirko.ingest.filename_ingest import FilenameIngestResult, FilenameIngestor
from mirko.ingest.mail_ingest import MailIngestResult, MailIngestor
from mirko.meeting_folder import MeetingFolder
from mirko.sync import SyncReport, Syncer


@dataclass(frozen=True)
class SyncCycleResult:
    status: str
    sync: SyncReport | None = None
    excel: str | None = None
    agenda: str | None = None
    drafts: FilenameIngestResult | None = None
    mail: MailIngestResult | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fetched(self) -> int:
        return self.sync.fetched if self.sync is not None else 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "fetched": self.fetched,
            "deferred": self.sync.deferred if self.sync is not None else 0,
            "excel": self.excel,
            "agenda": self.agenda,
            "drafts": {
                "processed": self.drafts.processed,
                "attached": self.drafts.attached,
                "provisional": list(self.drafts.provisional),
                "hints": self.drafts.hints,
                "unfiled": len(self.drafts.unfiled),
            }
            if self.drafts is not None
            else None,
            "mail": {
                "kind": self.mail.kind,
                "new_messages": self.mail.new_messages,
                "skipped": self.mail.skipped,
                "mentions": self.mail.mentions,
                "provisional": list(self.mail.provisional),
            }
            if self.mail is not None
            else None,
            "errors": list(self.errors),
        }


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SyncWorker:
    def __init__(
        self,
        folder: MeetingFolder,
        *,
        client: FtpClient | None = None,
        blobs: BlobStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.folder = folder
        self.client = client or LftpFtpClient(folder.config.source)
        self.blobs = blobs or BlobStore(folder.blobs_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> SyncCycleResult:
        attempted_at = _timestamp(self.clock())
        errors: list[str] = []
        report: SyncReport | None = None
        excel_status: str | None = None
        agenda_status: str | None = None
        drafts: FilenameIngestResult | None = None
        mail: MailIngestResult | None = None

        try:
            report = Syncer(
                self.folder, self.client, blobs=self.blobs, clock=self.clock
            ).sync()
            errors.extend(
                f"{failure.path}: {failure.error}"
                for failure in report.failures
            )
            errors.extend(
                f"{path.path}: {path.error}"
                for path in report.paths
                if path.error
            )
        except Exception as exc:  # noqa: BLE001 - keep last-known data
            errors.append(str(exc))
            self._record_state(attempted_at, str(exc), failed=True)
            return SyncCycleResult(status="error", errors=tuple(errors))

        try:
            excel_status = self._ingest_excel()
        except Exception as exc:  # noqa: BLE001 - keep previous projection
            errors.append(f"excel: {exc}")
            excel_status = "stale"

        try:
            agenda_status = self._ingest_latest_agenda()
        except Exception as exc:  # noqa: BLE001 - keep previous projection
            errors.append(f"agenda: {exc}")
            agenda_status = "stale"

        try:
            drafts = FilenameIngestor(self.folder, clock=self.clock).ingest()
            errors.extend(drafts.issues)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"drafts: {exc}")

        try:
            mail = MailIngestor(
                self.folder, blobs=self.blobs, clock=self.clock
            ).ingest()
            errors.extend(mail.errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"mail: {exc}")

        status = "degraded" if errors else "ok"
        if not errors:
            self._record_state(attempted_at, None, failed=False)
        else:
            self._record_state(attempted_at, "; ".join(errors), failed=True)
        return SyncCycleResult(
            status=status,
            sync=report,
            excel=excel_status,
            agenda=agenda_status,
            drafts=drafts,
            mail=mail,
            errors=tuple(errors),
        )

    def _ingest_excel(self) -> str | None:
        connection = self.folder.connect()
        try:
            artifact = connection.execute(
                "SELECT logical_path, filename, blob_hash FROM artifact "
                "WHERE kind = 'allocation_excel' AND blob_hash IS NOT NULL "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        if artifact is None:
            return None
        raw = self.blobs.path_for(artifact["blob_hash"]).read_bytes()
        result = AgendaIngestor(self.folder, clock=self.clock).ingest_excel(
            raw, path=artifact["logical_path"]
        )
        return result.status

    def _ingest_latest_agenda(self) -> str | None:
        connection = self.folder.connect()
        try:
            artifacts = connection.execute(
                "SELECT logical_path, filename, blob_hash FROM artifact "
                "WHERE kind = 'agenda_html' AND blob_hash IS NOT NULL "
                "ORDER BY id DESC"
            ).fetchall()
        finally:
            connection.close()
        if not artifacts:
            return None

        by_name = {
            row["filename"] or row["logical_path"]: row for row in artifacts
        }
        latest = select_latest_agenda(by_name)
        if latest is None:
            return None
        artifact = by_name[latest]
        raw = self.blobs.path_for(artifact["blob_hash"]).read_bytes()
        result = AgendaIngestor(self.folder, clock=self.clock).ingest(
            raw, path=artifact["logical_path"]
        )
        return result.status

    def _record_state(
        self, attempted_at: str, error: str | None, *, failed: bool
    ) -> None:
        config = self.folder.config
        connection = self.folder.connect()
        try:
            existing = connection.execute(
                "SELECT last_success_at FROM sync_state "
                "WHERE source_kind = ? AND endpoint_id = ?",
                (config.source.kind, config.source.endpoint_id),
            ).fetchone()
            last_success = (
                existing["last_success_at"] if existing is not None else None
            )
            if not failed:
                last_success = attempted_at
            connection.execute(
                "INSERT INTO sync_state("
                "source_kind, endpoint_id, last_attempt_at, last_success_at, "
                "last_error, next_due_at, health"
                ") VALUES (?, ?, ?, ?, ?, NULL, ?) "
                "ON CONFLICT(source_kind, endpoint_id) DO UPDATE SET "
                "last_attempt_at = excluded.last_attempt_at, "
                "last_success_at = excluded.last_success_at, "
                "last_error = excluded.last_error, "
                "health = excluded.health",
                (
                    config.source.kind,
                    config.source.endpoint_id,
                    attempted_at,
                    last_success,
                    error,
                    "degraded" if failed else "ok",
                ),
            )
            connection.commit()
        finally:
            connection.close()
