"""Attach fetched draft/inbox artifacts to TDocs using filename heuristics."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable

from mirko.ingest.filename import FilenameInfo, parse_filename
from mirko.ingest.tdoc_projection import ensure_tdoc
from mirko.meeting_folder import MeetingFolder

ARTIFACT_KINDS = ("working_draft", "inbox_document")


@dataclass(frozen=True)
class NewNumber:
    tdoc_number: str
    first_seen_at: str
    artifact_count: int
    filenames: tuple[str, ...]


@dataclass(frozen=True)
class FilenameIngestResult:
    processed: int
    attached: int
    provisional: tuple[str, ...]
    hints: int
    unfiled: tuple[str, ...]
    new_numbers: tuple[NewNumber, ...]
    issues: tuple[str, ...] = ()


def _timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def discover_new_numbers(connection: sqlite3.Connection) -> tuple[NewNumber, ...]:
    rows = connection.execute(
        "SELECT t.tdoc_number, t.first_seen_at, COUNT(a.id) AS artifact_count, "
        "GROUP_CONCAT(a.logical_path, '\n') AS paths "
        "FROM tdoc t JOIN artifact a ON a.tdoc_number = t.tdoc_number "
        "WHERE t.is_provisional = 1 "
        "GROUP BY t.tdoc_number, t.first_seen_at "
        "ORDER BY t.first_seen_at, t.tdoc_number"
    ).fetchall()
    return tuple(
        NewNumber(
            tdoc_number=row["tdoc_number"],
            first_seen_at=row["first_seen_at"],
            artifact_count=int(row["artifact_count"]),
            filenames=tuple(
                sorted(
                    PurePosixPath(path).name
                    for path in (row["paths"] or "").split("\n")
                    if path
                )
            ),
        )
        for row in rows
    )


class FilenameIngestor:
    def __init__(
        self,
        folder: MeetingFolder,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.folder = folder
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(self) -> FilenameIngestResult:
        observed_at = _timestamp(self.clock())
        prefix = self.folder.config.meeting.tdoc_series_prefix
        connection = self.folder.connect()
        provisional: list[str] = []
        unfiled: list[str] = []
        issues: list[str] = []
        attached = 0
        hints = 0
        try:
            rows = connection.execute(
                "SELECT id, logical_path, filename, raw_meta FROM artifact "
                "WHERE kind IN (?, ?) ORDER BY id",
                ARTIFACT_KINDS,
            ).fetchall()
            for row in rows:
                logical_path = row["logical_path"]
                name = row["filename"] or PurePosixPath(logical_path).name
                info = parse_filename(name, series_prefix=prefix)
                issues.extend(
                    f"{logical_path}: {issue}" for issue in info.issues
                )
                self._record_parse(connection, row["id"], row["raw_meta"], info)

                if info.primary_tdoc is None:
                    unfiled.append(logical_path)
                    continue

                created = ensure_tdoc(
                    connection,
                    info.primary_tdoc,
                    source="filename",
                    observed_at=observed_at,
                )
                if created:
                    provisional.append(info.primary_tdoc)
                connection.execute(
                    "UPDATE artifact SET tdoc_number = ? WHERE id = ?",
                    (info.primary_tdoc, row["id"]),
                )
                attached += 1
                for source in info.source_hints:
                    if self._insert_hint(
                        connection,
                        source=source,
                        target=info.primary_tdoc,
                        info=info,
                        source_ref=logical_path,
                        observed_at=observed_at,
                    ):
                        hints += 1
            new_numbers = discover_new_numbers(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return FilenameIngestResult(
            processed=len(rows),
            attached=attached,
            provisional=tuple(dict.fromkeys(provisional)),
            hints=hints,
            unfiled=tuple(unfiled),
            new_numbers=new_numbers,
            issues=tuple(issues),
        )

    def _record_parse(
        self,
        connection: sqlite3.Connection,
        artifact_id: int,
        raw_meta: str | None,
        info: FilenameInfo,
    ) -> None:
        try:
            metadata = json.loads(raw_meta) if raw_meta else {}
        except json.JSONDecodeError:
            metadata = {"unparsed_raw_meta": raw_meta}
        metadata["filename_parse"] = asdict(info)
        connection.execute(
            "UPDATE artifact SET raw_meta = ? WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=False), artifact_id),
        )

    def _insert_hint(
        self,
        connection: sqlite3.Connection,
        *,
        source: str,
        target: str,
        info: FilenameInfo,
        source_ref: str,
        observed_at: str,
    ) -> bool:
        existing = connection.execute(
            "SELECT 1 FROM assertion WHERE subject_kind = 'tdoc' "
            "AND subject_ref = ? AND predicate = 'based_on' "
            "AND object_kind = 'tdoc' AND object_ref = ? "
            "AND source = 'filename' AND source_ref = ?",
            (source, target, source_ref),
        ).fetchone()
        if existing is not None:
            return False
        connection.execute(
            "INSERT INTO assertion("
            "subject_kind, subject_ref, predicate, object_kind, object_ref, "
            "value, source, source_ref, confidence, verified, active, muted, "
            "observed_at, detail"
            ") VALUES ('tdoc', ?, 'based_on', 'tdoc', ?, NULL, 'filename', ?, "
            "?, 0, 0, 0, ?, ?)",
            (
                source,
                target,
                source_ref,
                min(0.7, info.confidence),
                observed_at,
                json.dumps(
                    {
                        "hint_kind": info.hint_kind,
                        "working_rev": info.working_rev,
                        "tier": info.tier,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        return True
