"""Manifest diffing and persistence for remote entries."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Mapping

from mirko.ftp import RemoteEntry, normalize_remote_path


@dataclass(frozen=True)
class ManifestEntry:
    endpoint_id: str
    path: str
    name: str
    size: int | None
    mtime: str | None
    last_blob_hash: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    missing_since: str | None
    fetch_state: str = "cached"


@dataclass(frozen=True)
class ManifestDiff:
    new: tuple[RemoteEntry, ...] = ()
    changed: tuple[RemoteEntry, ...] = ()
    unchanged: tuple[RemoteEntry, ...] = ()
    missing: tuple[ManifestEntry, ...] = ()

    @property
    def needs_fetch(self) -> tuple[RemoteEntry, ...]:
        return self.new + self.changed


def _identity_changed(existing: ManifestEntry, listed: RemoteEntry) -> bool:
    if existing.size != listed.size:
        return True
    if existing.mtime and listed.mtime and existing.mtime != listed.mtime:
        return True
    if existing.fetch_state == "pending":
        # The content hash is intentionally unknown for deferred downloads;
        # matching size/mtime means there is nothing new to record.
        return False
    if existing.last_blob_hash is None:
        return True
    return False


def diff_listing(
    existing: Mapping[str, ManifestEntry], listing: Iterable[RemoteEntry]
) -> ManifestDiff:
    new: list[RemoteEntry] = []
    changed: list[RemoteEntry] = []
    unchanged: list[RemoteEntry] = []
    seen: set[str] = set()

    for entry in listing:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        previous = existing.get(entry.name)
        if previous is None:
            new.append(entry)
        elif _identity_changed(previous, entry):
            changed.append(entry)
        else:
            unchanged.append(entry)

    missing = tuple(
        sorted(
            (entry for name, entry in existing.items() if name not in seen),
            key=lambda entry: entry.name,
        )
    )
    return ManifestDiff(
        new=tuple(new),
        changed=tuple(changed),
        unchanged=tuple(unchanged),
        missing=missing,
    )


class ManifestStore:
    def __init__(self, connection: sqlite3.Connection, endpoint_id: str) -> None:
        self.connection = connection
        self.endpoint_id = endpoint_id

    def load(self, path: str) -> dict[str, ManifestEntry]:
        directory = normalize_remote_path(path)
        rows = self.connection.execute(
            "SELECT endpoint_id, path, name, size, mtime, last_blob_hash, "
            "first_seen_at, last_seen_at, missing_since, fetch_state "
            "FROM remote_entry WHERE endpoint_id = ? AND path = ?",
            (self.endpoint_id, directory),
        ).fetchall()
        return {
            row["name"]: ManifestEntry(
                endpoint_id=row["endpoint_id"],
                path=row["path"],
                name=row["name"],
                size=row["size"],
                mtime=row["mtime"],
                last_blob_hash=row["last_blob_hash"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                missing_since=row["missing_since"],
                fetch_state=row["fetch_state"],
            )
            for row in rows
        }

    def diff(self, path: str, listing: Iterable[RemoteEntry]) -> ManifestDiff:
        return diff_listing(self.load(path), listing)

    def record(
        self,
        path: str,
        entry: RemoteEntry,
        *,
        blob_hash: str | None,
        observed_at: str,
        fetch_state: str = "cached",
    ) -> None:
        directory = normalize_remote_path(path)
        self.connection.execute(
            "INSERT INTO remote_entry("
            "endpoint_id, path, name, size, mtime, first_seen_at, "
            "last_seen_at, last_blob_hash, missing_since, fetch_state"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?) "
            "ON CONFLICT(endpoint_id, path, name) DO UPDATE SET "
            "size = excluded.size, "
            "mtime = excluded.mtime, "
            "last_seen_at = excluded.last_seen_at, "
            "last_blob_hash = excluded.last_blob_hash, "
            "missing_since = NULL, "
            "fetch_state = excluded.fetch_state",
            (
                self.endpoint_id,
                directory,
                entry.name,
                entry.size,
                entry.mtime,
                observed_at,
                observed_at,
                blob_hash,
                fetch_state,
            ),
        )

    def mark_missing(
        self,
        path: str,
        entries: Iterable[ManifestEntry],
        *,
        observed_at: str,
    ) -> None:
        directory = normalize_remote_path(path)
        for entry in entries:
            self.connection.execute(
                "UPDATE remote_entry SET missing_since = COALESCE(missing_since, ?) "
                "WHERE endpoint_id = ? AND path = ? AND name = ?",
                (observed_at, self.endpoint_id, directory, entry.name),
            )
