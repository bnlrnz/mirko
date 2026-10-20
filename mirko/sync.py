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
    deferred: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    failures: tuple[SyncFailure, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ArtifactFetchResult:
    logical_path: str
    blob_hash: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.blob_hash is not None


@dataclass(frozen=True)
class FetchResult:
    fetched: tuple[str, ...] = ()
    failures: tuple[SyncFailure, ...] = ()


@dataclass(frozen=True)
class SyncReport:
    endpoint_id: str
    observed_at: str
    paths: tuple[PathSyncResult, ...]

    @property
    def fetched(self) -> int:
        return sum(len(path.new) + len(path.changed) for path in self.paths)

    @property
    def deferred(self) -> int:
        return sum(len(path.deferred) for path in self.paths)

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
        # Snapshot config so an in-flight sync is not affected by settings edits.
        config = folder.config
        self.source = config.source
        self.paths = config.paths
        self.settings = config.sync

    def _default_paths(self) -> tuple[str, ...]:
        candidates = [
            self.paths.drafts,
            self.paths.inbox,
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
        endpoint_id = self.source.endpoint_id
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
        lazy = self._is_lazy(directory)

        for missing in diff.missing:
            self._mark_missing(connection, directory, missing, observed_at)
        manifest.mark_missing(
            directory, diff.missing, observed_at=observed_at
        )

        new: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        deferred: list[str] = []
        failures: list[SyncFailure] = []

        to_fetch = list(diff.needs_fetch)
        if not lazy:
            to_fetch.extend(
                entry
                for entry in diff.unchanged
                if existing[entry.name].fetch_state == "pending"
            )
        fetch_names = {entry.name for entry in to_fetch}

        for entry in diff.unchanged:
            if entry.name in fetch_names:
                continue
            previous = existing[entry.name]
            pending = lazy and previous.fetch_state == "pending"
            blob_hash = None if pending else previous.last_blob_hash
            manifest.record(
                directory,
                entry,
                blob_hash=blob_hash,
                observed_at=observed_at,
                fetch_state="pending" if pending else "cached",
            )
            artifact_id, created = self._upsert_artifact(
                connection,
                directory,
                entry,
                blob_hash=blob_hash,
                status="remote" if pending else "present",
                observed_at=observed_at,
            )
            if previous.missing_since is not None:
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=blob_hash,
                    change_kind="returned",
                    observed_at=observed_at,
                )
            elif created:
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=blob_hash,
                    change_kind="created",
                    observed_at=observed_at,
                )
            unchanged.append(entry.name)

        for entry in to_fetch:
            remote_path = join_remote_path(directory, entry.name)
            previous = existing.get(entry.name)
            if lazy:
                manifest.record(
                    directory,
                    entry,
                    blob_hash=None,
                    observed_at=observed_at,
                    fetch_state="pending",
                )
                artifact_id, created = self._upsert_artifact(
                    connection,
                    directory,
                    entry,
                    blob_hash=None,
                    status="remote",
                    observed_at=observed_at,
                )
                if previous is None or previous.missing_since is not None:
                    self._observe(
                        connection,
                        artifact_id,
                        entry,
                        blob_hash=None,
                        change_kind="deferred",
                        observed_at=observed_at,
                    )
                deferred.append(entry.name)
                continue
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
            deferred=tuple(deferred),
            missing=tuple(entry.name for entry in diff.missing),
            failures=tuple(failures),
        )

    def _is_lazy(self, directory: str) -> bool:
        if not self.settings.lazy_drafts:
            return False
        drafts = normalize_remote_path(self.paths.drafts)
        return directory == drafts or directory.startswith(f"{drafts}/")

    def fetch_for_tdoc(
        self, tdoc_number: str, *, include_lineage: bool = True
    ) -> FetchResult:
        numbers = [tdoc_number]
        if include_lineage:
            numbers = self._lineage_component(tdoc_number)
        return self.fetch_missing_for_tdocs(numbers)

    def fetch_missing_for_tdocs(
        self, tdoc_numbers: Iterable[str]
    ) -> FetchResult:
        numbers = tuple(dict.fromkeys(tdoc_numbers))
        if not numbers:
            return FetchResult()
        placeholders = ", ".join("?" for _ in numbers)
        connection = self.folder.connect()
        try:
            rows = connection.execute(
                "SELECT id FROM artifact WHERE tdoc_number IN "
                f"({placeholders}) AND blob_hash IS NULL "
                "AND status IN ('remote', 'failed') ORDER BY logical_path",
                numbers,
            ).fetchall()
        finally:
            connection.close()

        fetched: list[str] = []
        failures: list[SyncFailure] = []
        for row in rows:
            result = self.fetch_artifact(int(row["id"]))
            if result is None:
                continue
            if result.ok:
                fetched.append(result.logical_path)
            else:
                failures.append(
                    SyncFailure(
                        path=result.logical_path,
                        error=result.error or "fetch failed",
                    )
                )
        return FetchResult(fetched=tuple(fetched), failures=tuple(failures))

    def _lineage_component(self, tdoc_number: str) -> list[str]:
        connection = self.folder.connect()
        try:
            edges = connection.execute(
                "SELECT source, target FROM edge_current"
            ).fetchall()
        finally:
            connection.close()
        neighbours: dict[str, set[str]] = {}
        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            neighbours.setdefault(source, set()).add(target)
            neighbours.setdefault(target, set()).add(source)
        seen = {tdoc_number}
        queue = [tdoc_number]
        while queue:
            current = queue.pop()
            for other in neighbours.get(current, ()):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        return sorted(seen)

    def fetch_artifact(self, artifact_id: int) -> ArtifactFetchResult | None:
        connection = self.folder.connect()
        observed_at = _timestamp(self.clock())
        temporary: Path | None = None
        try:
            row = connection.execute(
                "SELECT * FROM artifact WHERE id = ?", (artifact_id,)
            ).fetchone()
            if row is None or row["blob_hash"] is not None:
                return None
            logical_path = row["logical_path"]
            directory, _, name = logical_path.rpartition("/")
            if not name:
                return None
            entry = RemoteEntry(
                name=name,
                size=row["remote_size"],
                mtime=row["remote_mtime"],
            )
            endpoint_id = row["endpoint_id"] or self.source.endpoint_id
            temporary = self._fetch_target()
            try:
                self.client.fetch(logical_path, temporary)
                blob = self.blobs.add_file(temporary)
                connection.execute(
                    "INSERT OR IGNORE INTO blob(hash, size) VALUES (?, ?)",
                    (blob.hash, blob.size),
                )
                connection.execute(
                    "UPDATE artifact SET blob_hash = ?, status = 'present', "
                    "last_seen_at = ? WHERE id = ?",
                    (blob.hash, observed_at, artifact_id),
                )
                ManifestStore(connection, endpoint_id).record(
                    directory,
                    entry,
                    blob_hash=blob.hash,
                    observed_at=observed_at,
                )
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=blob.hash,
                    change_kind="created",
                    observed_at=observed_at,
                )
                connection.commit()
                return ArtifactFetchResult(
                    logical_path=logical_path, blob_hash=blob.hash
                )
            except FtpError as exc:
                connection.execute(
                    "UPDATE artifact SET status = 'failed' WHERE id = ?",
                    (artifact_id,),
                )
                self._observe(
                    connection,
                    artifact_id,
                    entry,
                    blob_hash=None,
                    change_kind="fetch_failed",
                    observed_at=observed_at,
                )
                connection.commit()
                return ArtifactFetchResult(
                    logical_path=logical_path, error=str(exc)
                )
        except Exception:
            connection.rollback()
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            connection.close()

    def _fetch_target(self) -> Path:
        self.folder.cache_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix="fetch-", dir=self.folder.cache_dir, delete=False
        )
        handle.close()
        target = Path(handle.name)
        # lftp refuses to overwrite an existing destination unless clobber is
        # enabled; remove the placeholder so the download creates the file.
        target.unlink(missing_ok=True)
        return target

    def _classify(
        self, logical_path: str, directory: str
    ) -> tuple[str, bool]:
        drafts = normalize_remote_path(self.paths.drafts)
        if directory == drafts or directory.startswith(f"{drafts}/"):
            return "working_draft", True
        if fnmatch.fnmatchcase(logical_path, self.paths.agenda_glob):
            return "agenda_html", False
        if fnmatch.fnmatchcase(logical_path, self.paths.excel):
            return "allocation_excel", False
        if (
            "/" not in logical_path
            and logical_path.casefold().endswith((".xlsx", ".xls"))
            and not logical_path.startswith("~$")
        ):
            # The published workbook name varies by meeting
            # (e.g. ``TDoc_List_Meeting_SA3#130.xlsx``), so treat any
            # root-level spreadsheet as the allocation source.
            return "allocation_excel", False
        inbox = normalize_remote_path(self.paths.inbox)
        if directory == inbox or directory.startswith(f"{inbox}/"):
            return "inbox_document", False
        return "remote_file", False

    def _artifact_id(
        self, connection: sqlite3.Connection, logical_path: str
    ) -> int | None:
        row = connection.execute(
            "SELECT id FROM artifact WHERE endpoint_id = ? AND logical_path = ? "
            "ORDER BY id LIMIT 1",
            (self.source.endpoint_id, logical_path),
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
                    self.source.kind,
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
                self.source.kind,
                self.source.endpoint_id,
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
