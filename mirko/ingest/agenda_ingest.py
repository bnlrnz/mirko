"""Persist agenda/allocation HTML into documents, assertions, and views."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable, Iterable, Literal

from mirko.ingest.agenda_html import (
    AgendaParseResult,
    AgendaRow,
    LineageIssue,
    parse_agenda_html,
    timestamp_from_filename,
)
from mirko.meeting_folder import MeetingFolder

LINEAGE_PREDICATES = ("revision_of", "merged_into", "based_on")
INGEST_KIND = "agenda_html"


@dataclass(frozen=True)
class AgendaIngestResult:
    status: Literal["ingested", "unchanged"]
    ingest_run_id: int
    content_hash: str
    row_count: int
    edge_count: int
    issue_count: int
    source_timestamp: str | None
    issues: tuple[LineageIssue, ...] = ()


def _utc_timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def select_latest_agenda(
    names: Iterable[str],
    pattern: str = "AgendaWithTdocAllocation_*.htm",
) -> str | None:
    matches: list[str] = []
    for name in names:
        if fnmatch.fnmatchcase(PurePosixPath(name).name, pattern):
            matches.append(name)
    if not matches:
        return None
    return max(
        matches,
        key=lambda name: (
            timestamp_from_filename(PurePosixPath(name).name) or "",
            name,
        ),
    )


def _assertion_key(
    subject_ref: str,
    predicate: str,
    object_kind: str | None,
    object_ref: str | None,
    value: str | None,
) -> tuple[str, str, str, str, str]:
    return (
        subject_ref,
        predicate,
        object_kind or "",
        object_ref or "",
        value or "",
    )


def _state_source(row: AgendaRow) -> str:
    raw_decision = (row.raw.get("decision") or "").strip()
    return "html" if raw_decision else "inferred"


class AgendaIngestor:
    def __init__(
        self,
        folder: MeetingFolder,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.folder = folder
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(self, html: str | bytes, *, path: str | None = None) -> AgendaIngestResult:
        if isinstance(html, str):
            raw = html.encode("utf-8")
            parsed = parse_agenda_html(html)
        else:
            raw = bytes(html)
            parsed = parse_agenda_html(raw)
        content_hash = hashlib.sha256(raw).hexdigest()
        observed_at = _utc_timestamp(self.clock())

        connection = self.folder.connect()
        try:
            previous = self._latest_run(connection)
            if previous is not None and previous["content_hash"] == content_hash:
                return AgendaIngestResult(
                    status="unchanged",
                    ingest_run_id=int(previous["id"]),
                    content_hash=content_hash,
                    row_count=int(previous["row_count"] or 0),
                    edge_count=len(parsed.edges),
                    issue_count=len(parsed.issues),
                    source_timestamp=parsed.source_timestamp,
                    issues=tuple(parsed.issues),
                )

            run_id = self._start_run(
                connection,
                path=path,
                observed_at=observed_at,
                content_hash=content_hash,
                row_count=len(parsed.rows),
            )
            self._upsert_documents(
                connection,
                parsed,
                run_id=run_id,
                observed_at=observed_at,
            )
            self._sync_lineage(
                connection,
                parsed,
                path=path,
                content_hash=content_hash,
                observed_at=observed_at,
            )
            self._sync_decisions(
                connection,
                parsed,
                path=path,
                content_hash=content_hash,
                observed_at=observed_at,
            )
            self._reconcile_conflicts(
                connection, parsed, observed_at=observed_at
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return AgendaIngestResult(
            status="ingested",
            ingest_run_id=run_id,
            content_hash=content_hash,
            row_count=len(parsed.rows),
            edge_count=len(parsed.edges),
            issue_count=len(parsed.issues),
            source_timestamp=parsed.source_timestamp,
            issues=tuple(parsed.issues),
        )

    def _latest_run(self, connection: sqlite3.Connection):
        return connection.execute(
            "SELECT id, content_hash, row_count FROM ingest_run "
            "WHERE kind = ? AND status IN ('success', 'unchanged') "
            "ORDER BY id DESC LIMIT 1",
            (INGEST_KIND,),
        ).fetchone()

    def _start_run(
        self,
        connection: sqlite3.Connection,
        *,
        path: str | None,
        observed_at: str,
        content_hash: str,
        row_count: int,
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO ingest_run("
            "kind, endpoint_id, path, fetched_at, content_hash, row_count, status"
            ") VALUES (?, ?, ?, ?, ?, ?, 'success')",
            (
                INGEST_KIND,
                self.folder.config.source.endpoint_id,
                path,
                observed_at,
                content_hash,
                row_count,
            ),
        )
        return int(cursor.lastrowid)

    def _upsert_documents(
        self,
        connection: sqlite3.Connection,
        parsed: AgendaParseResult,
        *,
        run_id: int,
        observed_at: str,
    ) -> None:
        for row in parsed.rows:
            state_source = _state_source(row)
            raw_meta = json.dumps(
                {
                    "raw": row.raw,
                    "zip_path": row.zip_path,
                    "ingest_run_id": run_id,
                    "source_timestamp": parsed.source_timestamp,
                },
                ensure_ascii=False,
            )
            connection.execute(
                "INSERT INTO tdoc("
                "tdoc_number, agenda_item, topic, title, source, type, "
                "for_action, avail, treated, treated_note, decision, "
                "state_source, first_seen_at, last_seen_at, is_tracked, "
                "is_provisional, raw_meta"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?) "
                "ON CONFLICT(tdoc_number) DO UPDATE SET "
                "agenda_item = COALESCE(NULLIF(excluded.agenda_item, ''), "
                "tdoc.agenda_item), "
                "topic = COALESCE(NULLIF(excluded.topic, ''), tdoc.topic), "
                "title = COALESCE(NULLIF(excluded.title, ''), tdoc.title), "
                "source = COALESCE(NULLIF(excluded.source, ''), tdoc.source), "
                "type = COALESCE(NULLIF(excluded.type, ''), tdoc.type), "
                "for_action = COALESCE(NULLIF(excluded.for_action, ''), "
                "tdoc.for_action), "
                "avail = COALESCE(excluded.avail, tdoc.avail), "
                "treated = COALESCE(excluded.treated, tdoc.treated), "
                "treated_note = COALESCE(NULLIF(excluded.treated_note, ''), "
                "tdoc.treated_note), "
                "decision = excluded.decision, "
                "state_source = excluded.state_source, "
                "last_seen_at = excluded.last_seen_at, "
                "is_provisional = 0, "
                "raw_meta = excluded.raw_meta",
                (
                    row.tdoc,
                    row.agenda_item,
                    row.topic,
                    row.title,
                    row.source,
                    row.type,
                    row.for_action,
                    None if row.avail is None else int(row.avail),
                    None if row.treated is None else int(row.treated),
                    row.treated_note,
                    row.decision,
                    state_source,
                    observed_at,
                    observed_at,
                    raw_meta,
                ),
            )

    def _sync_lineage(
        self,
        connection: sqlite3.Connection,
        parsed: AgendaParseResult,
        *,
        path: str | None,
        content_hash: str,
        observed_at: str,
    ) -> None:
        desired: dict[tuple[str, str, str, str, str], dict] = {}
        for edge in parsed.edges:
            key = _assertion_key(
                edge.source, edge.kind, "tdoc", edge.target, None
            )
            desired[key] = {
                "subject_ref": edge.source,
                "predicate": edge.kind,
                "object_kind": "tdoc",
                "object_ref": edge.target,
                "value": None,
                "confidence": edge.confidence,
                "verified": edge.verified,
                "detail": json.dumps(
                    {
                        "reason": edge.reason,
                        "content_hash": content_hash,
                        "source_timestamp": parsed.source_timestamp,
                    },
                    ensure_ascii=False,
                ),
            }
        self._sync_assertions(
            connection,
            desired,
            predicates=LINEAGE_PREDICATES,
            source_ref=path or content_hash,
            observed_at=observed_at,
        )

    def _sync_decisions(
        self,
        connection: sqlite3.Connection,
        parsed: AgendaParseResult,
        *,
        path: str | None,
        content_hash: str,
        observed_at: str,
    ) -> None:
        desired: dict[tuple[str, str, str, str, str], dict] = {}
        for row in parsed.rows:
            state_source = _state_source(row)
            verified = state_source == "html"
            decision = row.decision or "open"
            key = _assertion_key(row.tdoc, "decision", None, None, decision)
            desired[key] = {
                "subject_ref": row.tdoc,
                "predicate": "decision",
                "object_kind": None,
                "object_ref": None,
                "value": decision,
                "confidence": 1.0 if verified else 0.5,
                "verified": verified,
                "detail": json.dumps(
                    {
                        "state_source": state_source,
                        "content_hash": content_hash,
                        "source_timestamp": parsed.source_timestamp,
                    },
                    ensure_ascii=False,
                ),
            }
        self._sync_assertions(
            connection,
            desired,
            predicates=("decision",),
            source_ref=path or content_hash,
            observed_at=observed_at,
        )

    def _reconcile_conflicts(
        self,
        connection: sqlite3.Connection,
        parsed: AgendaParseResult,
        *,
        observed_at: str,
    ) -> None:
        html_rows = connection.execute(
            "SELECT id, subject_ref, value FROM assertion "
            "WHERE source = 'html' AND predicate = 'decision' "
            "AND active = 1 AND muted = 0"
        ).fetchall()
        html_by_subject = {
            row["subject_ref"]: (int(row["id"]), row["value"])
            for row in html_rows
        }
        user_rows = connection.execute(
            "SELECT id, subject_ref, value FROM assertion "
            "WHERE source = 'user' AND predicate = 'decision' "
            "AND active = 1 AND muted = 0"
        ).fetchall()
        for user in user_rows:
            subject = user["subject_ref"]
            if subject not in html_by_subject:
                continue
            html_id, html_value = html_by_subject[subject]
            if html_value == user["value"]:
                connection.execute(
                    "UPDATE assertion SET verified = 1 WHERE id = ?",
                    (int(user["id"]),),
                )
                self._close_conflict(
                    connection,
                    "decision",
                    subject,
                    resolution="html_agrees",
                    observed_at=observed_at,
                )
            else:
                self._open_conflict(
                    connection,
                    "decision",
                    subject,
                    (int(user["id"]), html_id),
                    observed_at=observed_at,
                    detail=f"html={html_value!r} user={user['value']!r}",
                )

        for issue in parsed.issues:
            if issue.tdoc is None:
                continue
            predicate = (
                "lineage"
                if issue.kind in {"missing_replaced_by", "revision_conflict"}
                else issue.kind
            )
            self._open_conflict(
                connection,
                predicate,
                issue.tdoc,
                (),
                observed_at=observed_at,
                detail=issue.detail,
            )

    def _open_conflict(
        self,
        connection: sqlite3.Connection,
        predicate: str,
        subject_ref: str,
        assertion_ids: tuple[int, ...],
        *,
        observed_at: str,
        detail: str,
    ) -> None:
        existing = connection.execute(
            "SELECT id, assertion_ids FROM conflict "
            "WHERE predicate = ? AND subject_ref = ? AND status = 'open'",
            (predicate, subject_ref),
        ).fetchone()
        merged_ids: list[int] = []
        if existing is not None:
            try:
                merged_ids = [
                    int(value)
                    for value in json.loads(existing["assertion_ids"] or "[]")
                ]
            except (ValueError, TypeError):
                merged_ids = []
        for assertion_id in assertion_ids:
            if assertion_id not in merged_ids:
                merged_ids.append(assertion_id)
        payload = json.dumps(merged_ids)
        if existing is not None:
            connection.execute(
                "UPDATE conflict SET assertion_ids = ? WHERE id = ?",
                (payload, int(existing["id"])),
            )
            return
        connection.execute(
            "INSERT INTO conflict("
            "predicate, subject_ref, assertion_ids, status, created_at"
            ") VALUES (?, ?, ?, 'open', ?)",
            (predicate, subject_ref, payload, observed_at),
        )

    def _close_conflict(
        self,
        connection: sqlite3.Connection,
        predicate: str,
        subject_ref: str,
        *,
        resolution: str,
        observed_at: str,
    ) -> None:
        connection.execute(
            "UPDATE conflict SET status = 'resolved', resolution = ?, "
            "resolved_at = ? "
            "WHERE predicate = ? AND subject_ref = ? AND status = 'open'",
            (resolution, observed_at, predicate, subject_ref),
        )

    def _sync_assertions(
        self,
        connection: sqlite3.Connection,
        desired: dict[tuple[str, str, str, str, str], dict],
        *,
        predicates: tuple[str, ...],
        source_ref: str,
        observed_at: str,
    ) -> None:
        placeholders = ", ".join("?" for _ in predicates)
        rows = connection.execute(
            "SELECT id, subject_ref, predicate, object_kind, object_ref, value "
            "FROM assertion WHERE source = 'html' AND subject_kind = 'tdoc' "
            "AND active = 1 AND muted = 0 "
            f"AND predicate IN ({placeholders})",
            predicates,
        ).fetchall()

        existing: dict[tuple[str, str, str, str, str], int] = {}
        for row in rows:
            key = _assertion_key(
                row["subject_ref"],
                row["predicate"],
                row["object_kind"],
                row["object_ref"],
                row["value"],
            )
            existing[key] = int(row["id"])

        inserted: dict[tuple[str, str, str, str, str], int] = {}
        for key, spec in desired.items():
            if key in existing:
                continue
            cursor = connection.execute(
                "INSERT INTO assertion("
                "subject_kind, subject_ref, predicate, object_kind, object_ref, "
                "value, source, source_ref, confidence, verified, active, muted, "
                "observed_at, detail"
                ") VALUES ('tdoc', ?, ?, ?, ?, ?, 'html', ?, ?, ?, 1, 0, ?, ?)",
                (
                    spec["subject_ref"],
                    spec["predicate"],
                    spec["object_kind"],
                    spec["object_ref"],
                    spec["value"],
                    source_ref,
                    spec["confidence"],
                    int(bool(spec["verified"])),
                    observed_at,
                    spec["detail"],
                ),
            )
            inserted[key] = int(cursor.lastrowid)

        for key, assertion_id in existing.items():
            if key in desired:
                continue
            replacements = [
                new_id
                for new_key, new_id in inserted.items()
                if new_key[0] == key[0] and new_key[1] == key[1]
            ]
            superseded_by = replacements[0] if len(replacements) == 1 else None
            connection.execute(
                "UPDATE assertion SET active = 0, muted = 1, superseded_by = ? "
                "WHERE id = ?",
                (superseded_by, assertion_id),
            )
