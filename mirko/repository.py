"""Read-model queries used by the local JSON API."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from mirko.ingest.filename_ingest import discover_new_numbers


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _summary_columns() -> str:
    return (
        "t.tdoc_number, t.agenda_item, t.topic, t.title, t.source, t.type, "
        "t.for_action, t.release, t.wi_code, t.avail, t.treated, "
        "t.treated_note, t.decision, t.state_source, t.first_seen_at, "
        "t.last_seen_at, t.is_tracked, t.is_provisional, "
        "(SELECT COUNT(*) FROM note n WHERE n.target_kind = 'tdoc' "
        "AND n.target_ref = t.tdoc_number) AS notes_count, "
        "(SELECT COUNT(*) FROM artifact a WHERE a.tdoc_number = t.tdoc_number) "
        "AS artifact_count, "
        "(SELECT COUNT(*) FROM email_mention m "
        "WHERE m.tdoc_number = t.tdoc_number) AS mention_count, "
        "EXISTS(SELECT 1 FROM conflict c WHERE c.subject_ref = t.tdoc_number "
        "AND c.status = 'open') AS has_conflict"
    )


def _tdoc_row(row: sqlite3.Row) -> dict:
    return {
        "tdoc_number": row["tdoc_number"],
        "agenda_item": row["agenda_item"],
        "topic": row["topic"],
        "title": row["title"],
        "source": row["source"],
        "type": row["type"],
        "for_action": row["for_action"],
        "release": row["release"],
        "wi_code": row["wi_code"],
        "avail": _bool(row["avail"]),
        "treated": _bool(row["treated"]),
        "treated_note": row["treated_note"],
        "decision": row["decision"],
        "state_source": row["state_source"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "is_tracked": bool(row["is_tracked"]),
        "is_provisional": bool(row["is_provisional"]),
        "notes_count": int(row["notes_count"]),
        "artifact_count": int(row["artifact_count"]),
        "mention_count": int(row["mention_count"]),
        "has_conflict": bool(row["has_conflict"]),
    }


def list_tdocs(
    connection: sqlite3.Connection,
    *,
    agenda: str | None = None,
    type: str | None = None,
    release: str | None = None,
    wi: str | None = None,
    source: str | None = None,
    state: str | None = None,
    tracked: bool | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("t.agenda_item", agenda),
        ("t.type", type),
        ("t.release", release),
        ("t.wi_code", wi),
        ("t.source", source),
        ("t.decision", state),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if tracked is not None:
        clauses.append("t.is_tracked = ?")
        params.append(int(tracked))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"SELECT {_summary_columns()} FROM tdoc t{where} "
        "ORDER BY t.is_tracked DESC, t.agenda_item, t.tdoc_number",
        params,
    ).fetchall()
    return [_tdoc_row(row) for row in rows]


def get_tdoc(connection: sqlite3.Connection, tdoc_number: str) -> dict | None:
    row = connection.execute(
        f"SELECT {_summary_columns()}, t.raw_meta FROM tdoc t "
        "WHERE t.tdoc_number = ?",
        (tdoc_number,),
    ).fetchone()
    if row is None:
        return None
    data = _tdoc_row(row)
    data["raw_meta"] = _json(row["raw_meta"])
    data["artifacts"] = [
        {
            "id": artifact["id"],
            "kind": artifact["kind"],
            "logical_path": artifact["logical_path"],
            "filename": artifact["filename"],
            "status": artifact["status"],
            "is_ephemeral": bool(artifact["is_ephemeral"]),
            "blob_hash": artifact["blob_hash"],
            "remote_size": artifact["remote_size"],
            "first_seen_at": artifact["first_seen_at"],
            "last_seen_at": artifact["last_seen_at"],
        }
        for artifact in connection.execute(
            "SELECT * FROM artifact WHERE tdoc_number = ? ORDER BY logical_path",
            (tdoc_number,),
        )
    ]
    data["notes"] = [
        _note_row(note)
        for note in connection.execute(
            "SELECT * FROM note WHERE target_kind = 'tdoc' AND target_ref = ? "
            "ORDER BY created_at, id",
            (tdoc_number,),
        )
    ]
    data["emails"] = [
        _mail_row(mail)
        for mail in connection.execute(
            "SELECT e.* FROM email e JOIN email_mention m ON m.email_id = e.id "
            "WHERE m.tdoc_number = ? ORDER BY e.date_utc DESC, e.id DESC",
            (tdoc_number,),
        )
    ]
    data["assertions"] = [
        {
            "id": assertion["id"],
            "predicate": assertion["predicate"],
            "object_kind": assertion["object_kind"],
            "object_ref": assertion["object_ref"],
            "value": assertion["value"],
            "source": assertion["source"],
            "confidence": assertion["confidence"],
            "verified": bool(assertion["verified"]),
            "active": bool(assertion["active"]),
            "muted": bool(assertion["muted"]),
            "superseded_by": assertion["superseded_by"],
            "observed_at": assertion["observed_at"],
            "detail": _json(assertion["detail"]),
        }
        for assertion in connection.execute(
            "SELECT * FROM assertion WHERE subject_kind = 'tdoc' "
            "AND subject_ref = ? ORDER BY id",
            (tdoc_number,),
        )
    ]
    return data


def _note_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "target_kind": row["target_kind"],
        "target_ref": row["target_ref"],
        "body": row["body"],
        "position_tag": row["position_tag"],
        "author": row["author"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _mail_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "subject": row["subject"],
        "from_addr": row["from_addr"],
        "to_addrs": row["to_addrs"],
        "cc_addrs": row["cc_addrs"],
        "date_utc": row["date_utc"],
        "agenda_item": row["agenda_item"],
        "meeting_id": row["meeting_id"],
        "ingested_at": row["ingested_at"],
        "inference": _json(row["inference"]),
    }


def timeline(connection: sqlite3.Connection, tdoc_number: str) -> list[dict]:
    events: list[dict] = []

    row = connection.execute(
        "SELECT tdoc_number, first_seen_at, decision, state_source FROM tdoc "
        "WHERE tdoc_number = ?",
        (tdoc_number,),
    ).fetchone()
    if row is None:
        return []
    events.append(
        {
            "kind": "discovered",
            "occurred_at": row["first_seen_at"],
            "title": f"{tdoc_number} first seen",
            "detail": None,
            "source": row["state_source"],
            "artifact_id": None,
            "email_id": None,
            "ephemeral": False,
        }
    )

    artifact_rows = connection.execute(
        "SELECT * FROM artifact WHERE tdoc_number = ? ORDER BY id",
        (tdoc_number,),
    ).fetchall()
    for artifact in artifact_rows:
        observations = connection.execute(
            "SELECT * FROM artifact_observation WHERE artifact_id = ? "
            "ORDER BY observed_at, id",
            (artifact["id"],),
        ).fetchall()
        if not observations:
            events.append(
                {
                    "kind": "artifact",
                    "occurred_at": artifact["first_seen_at"],
                    "title": artifact["filename"] or artifact["logical_path"],
                    "detail": artifact["status"],
                    "source": artifact["kind"],
                    "artifact_id": artifact["id"],
                    "email_id": None,
                    "ephemeral": bool(artifact["is_ephemeral"]),
                }
            )
            continue
        for observation in observations:
            events.append(
                {
                    "kind": "artifact",
                    "occurred_at": observation["observed_at"],
                    "title": artifact["filename"] or artifact["logical_path"],
                    "detail": observation["change_kind"],
                    "source": artifact["kind"],
                    "artifact_id": artifact["id"],
                    "email_id": None,
                    "ephemeral": bool(artifact["is_ephemeral"]),
                }
            )

    for mail in connection.execute(
        "SELECT e.*, m.scope AS mention_scope, m.confidence AS mention_confidence "
        "FROM email e JOIN email_mention m ON m.email_id = e.id "
        "WHERE m.tdoc_number = ? ORDER BY e.id",
        (tdoc_number,),
    ):
        events.append(
            {
                "kind": "email",
                "occurred_at": mail["date_utc"] or mail["ingested_at"],
                "title": mail["subject"],
                "detail": (
                    f"{mail['from_addr']} (scope={mail['mention_scope']}, "
                    f"confidence={mail['mention_confidence']})"
                ),
                "source": "email",
                "artifact_id": None,
                "email_id": mail["id"],
                "ephemeral": False,
            }
        )

    for note in connection.execute(
        "SELECT * FROM note WHERE target_kind = 'tdoc' AND target_ref = ?",
        (tdoc_number,),
    ):
        events.append(
            {
                "kind": "note",
                "occurred_at": note["created_at"],
                "title": note["position_tag"] or "Note",
                "detail": note["body"],
                "source": note["source"],
                "artifact_id": None,
                "email_id": None,
                "ephemeral": False,
            }
        )

    for assertion in connection.execute(
        "SELECT * FROM assertion WHERE subject_kind = 'tdoc' "
        "AND subject_ref = ? AND predicate IN ('decision', 'revision_of', "
        "'merged_into', 'based_on') ORDER BY observed_at, id",
        (tdoc_number,),
    ):
        events.append(
            {
                "kind": "state" if assertion["predicate"] == "decision" else "lineage",
                "occurred_at": assertion["observed_at"],
                "title": (
                    assertion["value"]
                    if assertion["predicate"] == "decision"
                    else f"{assertion['predicate']} {assertion['object_ref']}"
                ),
                "detail": f"source={assertion['source']} "
                f"verified={bool(assertion['verified'])} "
                f"active={bool(assertion['active'])}",
                "source": assertion["source"],
                "artifact_id": None,
                "email_id": None,
                "ephemeral": False,
            }
        )

    events.sort(
        key=lambda event: (
            event["occurred_at"] or "",
            event["kind"],
            event["title"] or "",
        )
    )
    for index, event in enumerate(events):
        event["sequence"] = index
    return events


def lineage(
    connection: sqlite3.Connection, *, tracked_only: bool = False
) -> dict:
    tracked = {
        row["tdoc_number"]
        for row in connection.execute(
            "SELECT tdoc_number FROM tdoc WHERE is_tracked = 1"
        )
    }
    if tracked_only and tracked:
        edges = [
            dict(row)
            for row in connection.execute(
                "SELECT source, target, kind, confidence, verified, source_ref "
                "FROM edge_current ORDER BY target, source, kind"
            )
            if row["source"] in tracked or row["target"] in tracked
        ]
        node_ids = set(tracked)
        for edge in edges:
            node_ids.add(edge["source"])
            node_ids.add(edge["target"])
    else:
        edges = [
            dict(row)
            for row in connection.execute(
                "SELECT source, target, kind, confidence, verified, source_ref "
                "FROM edge_current ORDER BY target, source, kind"
            )
        ]
        node_ids = {
            row["tdoc_number"]
            for row in connection.execute("SELECT tdoc_number FROM tdoc")
        }

    nodes = []
    if node_ids:
        placeholders = ", ".join("?" for _ in node_ids)
        rows = connection.execute(
            "SELECT tdoc_number, title, decision, state_source, agenda_item, "
            "type, is_tracked, is_provisional, first_seen_at "
            f"FROM tdoc WHERE tdoc_number IN ({placeholders}) "
            "ORDER BY COALESCE(agenda_item, ''), tdoc_number",
            tuple(node_ids),
        )
        nodes = [
            {
                "tdoc_number": row["tdoc_number"],
                "title": row["title"],
                "decision": row["decision"],
                "state_source": row["state_source"],
                "agenda_item": row["agenda_item"],
                "type": row["type"],
                "is_tracked": bool(row["is_tracked"]),
                "is_provisional": bool(row["is_provisional"]),
                "first_seen_at": row["first_seen_at"],
            }
            for row in rows
        ]
    return {"nodes": nodes, "edges": edges}


def list_mail(
    connection: sqlite3.Connection,
    *,
    tdoc: str | None = None,
    agenda: str | None = None,
    query: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    join = ""
    if tdoc is not None:
        join += " JOIN email_mention m ON m.email_id = e.id"
        clauses.append("m.tdoc_number = ?")
        params.append(tdoc)
    if agenda is not None:
        clauses.append("e.agenda_item = ?")
        params.append(agenda)
    if query:
        join += (
            " JOIN email_fts f ON f.message_id = e.message_id"
            " AND email_fts MATCH ?"
        )
        params.append(_fts_query(query))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = connection.execute(
        f"SELECT DISTINCT e.* FROM email e{join}{where} "
        "ORDER BY e.date_utc DESC, e.id DESC LIMIT ?",
        params,
    ).fetchall()
    return [_mail_row(row) for row in rows]


def _fts_query(text: str) -> str:
    cleaned = text.replace('"', '""').strip()
    return f'"{cleaned}"'


def discovery(connection: sqlite3.Connection) -> list[dict]:
    items: list[dict] = []
    for number in discover_new_numbers(connection):
        items.append(
            {
                "kind": "provisional_tdoc",
                "ref": number.tdoc_number,
                "title": f"{number.tdoc_number} (provisional)",
                "detail": ", ".join(number.filenames),
                "tdocs": [number.tdoc_number],
                "agenda_item": None,
                "confidence": 0.7,
                "created_at": number.first_seen_at,
            }
        )

    for hint in connection.execute(
        "SELECT * FROM assertion WHERE source = 'filename' AND active = 0 "
        "ORDER BY observed_at DESC, id DESC"
    ):
        items.append(
            {
                "kind": "filename_hint",
                "ref": hint["source_ref"] or str(hint["id"]),
                "title": f"{hint['subject_ref']} → {hint['object_ref']}",
                "detail": hint["detail"],
                "tdocs": [hint["subject_ref"], hint["object_ref"]],
                "agenda_item": None,
                "confidence": hint["confidence"],
                "created_at": hint["observed_at"],
            }
        )

    for mail in connection.execute(
        "SELECT e.* FROM email e WHERE e.agenda_item IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM email_mention m WHERE m.email_id = e.id "
        "AND m.scope = 'subject') ORDER BY e.date_utc DESC, e.id DESC"
    ):
        items.append(
            {
                "kind": "agenda_mail",
                "ref": str(mail["id"]),
                "title": mail["subject"],
                "detail": mail["from_addr"],
                "tdocs": [],
                "agenda_item": mail["agenda_item"],
                "confidence": 0.4,
                "created_at": mail["date_utc"] or mail["ingested_at"],
            }
        )
    items.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return items


def sync_status(
    connection: sqlite3.Connection,
    *,
    endpoint_id: str,
    poll_interval_s: int,
    now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(timezone.utc)
    state = connection.execute(
        "SELECT * FROM sync_state WHERE endpoint_id = ?", (endpoint_id,)
    ).fetchone()
    refresh = {
        "drafts": _max_timestamp(
            connection,
            "SELECT MAX(observed_at) FROM artifact_observation o "
            "JOIN artifact a ON a.id = o.artifact_id "
            "WHERE a.kind = 'working_draft'",
        ),
        "inbox": _max_timestamp(
            connection,
            "SELECT MAX(observed_at) FROM artifact_observation o "
            "JOIN artifact a ON a.id = o.artifact_id "
            "WHERE a.kind = 'inbox_document'",
        ),
        "agenda": _max_timestamp(
            connection,
            "SELECT MAX(fetched_at) FROM ingest_run WHERE kind = 'agenda_html'",
        ),
        "mail": _max_timestamp(connection, "SELECT MAX(ingested_at) FROM email"),
    }
    last_sync = _max_timestamp(
        connection,
        "SELECT MAX(observed_at) FROM artifact_observation",
    )
    next_due = None
    if last_sync is not None:
        try:
            next_due = (
                datetime.strptime(last_sync, "%Y-%m-%dT%H:%M:%S.%fZ")
                .replace(tzinfo=timezone.utc)
                + timedelta(seconds=poll_interval_s)
            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            next_due = None
    if state is not None:
        health = state["health"]
        last_attempt = state["last_attempt_at"]
        last_success = state["last_success_at"]
        last_error = state["last_error"]
        stored_next = state["next_due_at"]
        if stored_next:
            next_due = stored_next
    else:
        health = "ok" if last_sync else "unknown"
        last_attempt = None
        last_success = last_sync
        last_error = None
    return {
        "endpoint": endpoint_id,
        "health": health,
        "last_attempt_at": last_attempt,
        "last_success_at": last_success,
        "next_due_at": next_due,
        "last_error": last_error,
        "interval_s": poll_interval_s,
        "stale": last_sync is None,
        "refresh": refresh,
        "counts": {
            "tdocs": _count(connection, "tdoc"),
            "artifacts": _count(connection, "artifact"),
            "emails": _count(connection, "email"),
            "open_conflicts": _count(
                connection, "conflict", "status = 'open'"
            ),
        },
        "server_time": moment.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
    }


def _max_timestamp(connection: sqlite3.Connection, sql: str) -> str | None:
    row = connection.execute(sql).fetchone()
    return row[0] if row is not None else None


def _count(
    connection: sqlite3.Connection, table: str, where: str | None = None
) -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(connection.execute(sql).fetchone()[0])


def set_tracked(
    connection: sqlite3.Connection, tdoc_number: str, tracked: bool
) -> bool | None:
    row = connection.execute(
        "SELECT is_tracked FROM tdoc WHERE tdoc_number = ?", (tdoc_number,)
    ).fetchone()
    if row is None:
        return None
    value = 1 if tracked else 0
    connection.execute(
        "UPDATE tdoc SET is_tracked = ? WHERE tdoc_number = ?",
        (value, tdoc_number),
    )
    if tracked:
        connection.execute(
            "INSERT INTO tracked_tdoc(tdoc_number, added_by, origin) "
            "VALUES (?, 'user', 'manual') "
            "ON CONFLICT(tdoc_number) DO NOTHING",
            (tdoc_number,),
        )
    else:
        connection.execute(
            "DELETE FROM tracked_tdoc WHERE tdoc_number = ?", (tdoc_number,)
        )
    connection.commit()
    return bool(value)


def add_note(
    connection: sqlite3.Connection,
    *,
    target_kind: str,
    target_ref: str,
    body: str,
    position_tag: str | None = None,
    author: str | None = None,
    source: str = "user",
) -> dict:
    cursor = connection.execute(
        "INSERT INTO note(target_kind, target_ref, body, position_tag, author, "
        "source) VALUES (?, ?, ?, ?, ?, ?)",
        (target_kind, target_ref, body, position_tag, author, source),
    )
    connection.commit()
    row = connection.execute(
        "SELECT id, target_kind, target_ref, body, position_tag, author, "
        "source, created_at, updated_at FROM note WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return _note_row(row)
