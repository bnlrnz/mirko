"""Manifest-diff synchronization and single-download caching."""

from __future__ import annotations

import fnmatch
import json
import logging
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from mirko.blob_store import BlobStore
from mirko.ftp import (
    FtpClient,
    FtpError,
    RemoteEntry,
    is_safe_remote_name,
    join_remote_path,
    normalize_remote_path,
)
from mirko.manifest import ManifestEntry, ManifestStore, diff_listing
from mirko.meeting_folder import MeetingFolder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncFailure:
    path: str
    error: str


@dataclass(frozen=True)
class PathSyncResult:
    path: str
    listed: int = 0
    new: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failures: tuple[SyncFailure, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class SyncReport:
    endpoint_id: str
    observed_at: str
    paths: tuple[PathSyncResult, ...]

    @property
    def fetched(self) -> int:
        return sum(len(path.new) + len(path.changed) for path in self.paths)

    @property
    def failures(self) -> tuple[SyncFailure, ...]:
        return tuple(
            failure for path in self.paths for failure in path.failures
        )


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Syncer:
    def __init__(
        self,
        folder: MeetingFolder,
        client: FtpClient,
        *,
        blobs: BlobStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.folder = folder
        self.client = client
        self.blobs = blobs or BlobStore(folder.blobs_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _default_paths(self) -> tuple[str, ...]:
        candidates = [
            self.folder.config.paths.drafts,
            self.folder.config.paths.inbox,
            "",
        ]
        normalized: list[str] = []
        for path in candidates:
            value = normalize_remote_path(path)
            if value not in normalized:
                normalized.append(value)
        return tuple(normalized)

    def sync(self, paths: Iterable[str] | None = None) -> SyncReport:
        if isinstance(paths, str):
            paths = [paths]
        directories = (
            tuple(normalize_remote_path(path) for path in paths)
            if paths is not None
            else self._default_paths()
        )
        observed_at = _timestamp(self.clock())
        endpoint_id = self.folder.config.source.endpoint_id
        connection = self.folder.connect()
        try:
            manifest = ManifestStore(connection, endpoint_id)
            results = [
                self._sync_path(connection, manifest, path, observed_at)
                for path in directories
            ]
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return SyncReport(
            endpoint_id=endpoint_id,
            observed_at=observed_at,
            paths=tuple(results),
        )

    def _sync_path(
        self,
        connection: sqlite3.Connection,
        manifest: ManifestStore,
        path: str,
        observed_at: str,
    ) -> PathSyncResult:
        directory = normalize_remote_path(path)
        try:
            listing = self.client.list(directory)
        except FtpError as exc:
            logger.warning("listing failed for %r: %s", directory, exc)
            return PathSyncResult(
                path=directory, error=str(exc)
            )

        files: list[RemoteEntry] = []
        for entry in listing:
            if entry.is_dir or entry.is_symlink:
                continue
            if not is_safe_remote_name(entry.name):
                logger.warning("unsafe remote filename skipped: %r", entry.name)
                continue
            files.append(entry)

        existing = manifest.load(directory)
        diff = diff_listing(existing, files)

        for missing in diff.missing:
            self._mark_missing(connection, directory, missing, observed_at)
        manifest.mark_missing(
            directory, diff.missing, observed_at=observed_at
        )

        new: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        failures: list[SyncFailure] = []

        for entry in diff.unchanged:
            previous = existing[entry.name]
            manifest.record(
                directory,
                entry,
                blob_hash=previous.last_blob_hash,
                observed_at=observed_at,
            )
            artifact_id, created = self._upsert_artifact(
                connection,
                directory,
                entry,
                blob_hash=previous.last_blob_hash,
                status="present",
                observed_at=observed_at,
            )
            if previous.missing_since is not None:
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=previous.last_blob_hash,
                    change_kind="returned",
                    observed_at=observed_at,
                )
            elif created:
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=previous.last_blob_hash,
                    change_kind="created",
                    observed_at=observed_at,
                )
            unchanged.append(entry.name)

        for entry in diff.needs_fetch:
            remote_path = join_remote_path(directory, entry.name)
            previous = existing.get(entry.name)
            temporary = self._fetch_target()
            try:
                self.client.fetch(remote_path, temporary)
                blob = self.blobs.add_file(temporary)
                connection.execute(
                    "INSERT OR IGNORE INTO blob(hash, size) VALUES (?, ?)",
                    (blob.hash, blob.size),
                )
                manifest.record(
                    directory,
                    entry,
                    blob_hash=blob.hash,
                    observed_at=observed_at,
                )
                if previous is None:
                    change_kind = "created"
                elif previous.last_blob_hash == blob.hash:
                    change_kind = "metadata_changed"
                else:
                    change_kind = "changed"
                artifact_id, _ = self._upsert_artifact(
                    connection,
                    directory,
                    entry,
                    blob_hash=blob.hash,
                    status="present",
                    observed_at=observed_at,
                )
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=blob.hash,
                    change_kind=change_kind,
                    observed_at=observed_at,
                )
                if previous is None:
                    new.append(entry.name)
                else:
                    changed.append(entry.name)
            except FtpError as exc:
                logger.warning("fetch failed for %r: %s", remote_path, exc)
                if previous is None:
                    artifact_id, _ = self._upsert_artifact(
                        connection,
                        directory,
                        entry,
                        blob_hash=None,
                        status="failed",
                        observed_at=observed_at,
                    )
                else:
                    existing_id = self._artifact_id(
                        connection, join_remote_path(directory, entry.name)
                    )
                    if existing_id is None:
                        artifact_id, _ = self._upsert_artifact(
                            connection,
                            directory,
                            entry,
                            blob_hash=previous.last_blob_hash,
                            status="failed",
                            observed_at=observed_at,
                        )
                    else:
                        artifact_id = existing_id
                        connection.execute(
                            "UPDATE artifact SET status = 'failed' WHERE id = ?",
                            (artifact_id,),
                        )
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=previous.last_blob_hash if previous else None,
                    change_kind="fetch_failed",
                    observed_at=observed_at,
                )
                failures.append(SyncFailure(path=remote_path, error=str(exc)))
            finally:
                temporary.unlink(missing_ok=True)

        return PathSyncResult(
            path=directory,
            listed=len(files),
            new=tuple(new),
            changed=tuple(changed),
            unchanged=tuple(unchanged),
            missing=tuple(entry.name for entry in diff.missing),
            failures=tuple(failures),
        )

    def _fetch_target(self) -> Path:
        self.folder.cache_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="fetch-", dir=self.folder.cache_dir, delete=False
        )
        handle.close()
        return Path(handle.name)

    def _classify(
        self, logical_path: str, directory: str
    ) -> tuple[str, bool]:
        config = self.folder.config
        drafts = normalize_remote_path(config.paths.drafts)
        if directory == drafts or directory.startswith(f"{drafts}/"):
            return "working_draft", True
        if fnmatch.fnmatchcase(logical_path, config.paths.agenda_glob):
            return "agenda_html", False
        if logical_path == config.paths.excel:
            return "allocation_excel", False
        inbox = normalize_remote_path(config.paths.inbox)
        if directory == inbox or directory.startswith(f"{inbox}/"):
            return "inbox_document", False
        return "remote_file", False

    def _artifact_id(
        self, connection: sqlite3.Connection, logical_path: str
    ) -> int | None:
        row = connection.execute(
            "SELECT id FROM artifact WHERE endpoint_id = ? AND logical_path = ? "
            "ORDER BY id LIMIT 1",
            (self.folder.config.source.endpoint_id, logical_path),
        ).fetchone()
        return int(row["id"]) if row else None

    def _upsert_artifact(
        self,
        connection: sqlite3.Connection,
        directory: str,
        entry: RemoteEntry,
        *,
        blob_hash: str | None,
        status: str,
        observed_at: str,
    ) -> tuple[int, bool]:
        logical_path = join_remote_path(directory, entry.name)
        kind, ephemeral = self._classify(logical_path, directory)
        raw_meta = json.dumps(
            {"remote_path": logical_path, "raw": entry.raw},
            ensure_ascii=False,
        )
        artifact_id = self._artifact_id(connection, logical_path)
        if artifact_id is not None:
            connection.execute(
                "UPDATE artifact SET kind = ?, filename = ?, blob_hash = ?, "
                "remote_size = ?, remote_mtime = ?, last_seen_at = ?, "
                "source_kind = ?, is_ephemeral = ?, status = ?, raw_meta = ? "
                "WHERE id = ?",
                (
                    kind,
                    entry.name,
                    blob_hash,
                    entry.size,
                    entry.mtime,
                    observed_at,
                    self.folder.config.source.kind,
                    int(ephemeral),
                    status,
                    raw_meta,
                    artifact_id,
                ),
            )
            return artifact_id, False

        cursor = connection.execute(
            "INSERT INTO artifact("
            "kind, logical_path, filename, blob_hash, remote_size, "
            "remote_mtime, first_seen_at, last_seen_at, source_kind, "
            "endpoint_id, is_ephemeral, status, raw_meta"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                logical_path,
                entry.name,
                blob_hash,
                entry.size,
                entry.mtime,
                observed_at,
                observed_at,
                self.folder.config.source.kind,
                self.folder.config.source.endpoint_id,
                int(ephemeral),
                status,
                raw_meta,
            ),
        )
        return int(cursor.lastrowid), True

    def _observe(
        self,
        connection: sqlite3.Connection,
        artifact_id: int,
        entry: RemoteEntry,
        *,
        blob_hash: str | None,
        change_kind: str,
        observed_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO artifact_observation("
            "artifact_id, observed_at, remote_size, remote_mtime, "
            "blob_hash, change_kind"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                observed_at,
                entry.size,
                entry.mtime,
                blob_hash,
                change_kind,
            ),
        )

    def _mark_missing(
        self,
        connection: sqlite3.Connection,
        directory: str,
        entry: ManifestEntry,
        observed_at: str,
    ) -> None:
        logical_path = join_remote_path(directory, entry.name)
        artifact_id = self._artifact_id(connection, logical_path)
        if artifact_id is None:
            return
        connection.execute(
            "UPDATE artifact SET status = 'missing' WHERE id = ?",
            (artifact_id,),
        )
        if entry.missing_since is None:
            self._observe(
                connection,
                artifact_id,
                RemoteEntry(name=entry.name, size=entry.size, mtime=entry.mtime),
                blob_hash=None,
                change_kind="missing",
                observed_at=observed_at,
            )
