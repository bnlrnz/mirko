"""Deterministic whole-meeting Markdown export and finalization."""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from mirko import repository
from mirko.blob_store import BlobStore
from mirko.ingest.agenda_ingest import AgendaIngestor, select_latest_agenda
from mirko.meeting_folder import MeetingFolder


def _stamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _node_id(tdoc: str) -> str:
    return "T_" + re.sub(r"[^A-Za-z0-9_]", "_", tdoc)


def _label(value: str | None) -> str:
    text = (value or "").replace('"', "'").replace("|", "/")
    return text.replace("\n", "<br/>")


def _mermaid(connection: sqlite3.Connection) -> tuple[list[str], list[str]]:
    graph = repository.lineage(connection, include_inactive=True)
    lines = ["```mermaid", "graph LR"]
    for node in graph["nodes"]:
        title = _label(node["title"])
        lines.append(
            f'  {_node_id(node["tdoc_number"])}["'
            f'{node["tdoc_number"]}<br/>{title}"]'
        )
    inactive: list[str] = []
    muted_nodes: set[str] = set()
    for edge in graph["edges"]:
        source = _node_id(edge["source"])
        target = _node_id(edge["target"])
        label = _label(edge["kind"])
        inactive_edge = not edge.get("active", True) or bool(
            edge.get("muted")
        )
        arrow = "-.->" if inactive_edge else "-->"
        lines.append(f"  {source} {arrow}|{label}| {target}")
        if inactive_edge:
            inactive.append(
                f"- {edge['source']} → {edge['target']} ({edge['kind']}, "
                "inactive hint)"
            )
            muted_nodes.update({source, target})
    if muted_nodes:
        lines.append(
            "  classDef muted stroke-dasharray: 4 4,stroke:#999,color:#777"
        )
        lines.append(f"  class {','.join(sorted(muted_nodes))} muted")
    lines.append("```")
    return lines, inactive


def render_markdown(
    folder: MeetingFolder,
    *,
    include_mail: bool = False,
    generated_at: datetime | None = None,
) -> str:
    moment = generated_at or datetime.now(timezone.utc)
    connection = folder.connect()
    try:
        summaries = repository.list_tdocs(connection)
        tracked = [item for item in summaries if item["is_tracked"]]
        state = connection.execute(
            "SELECT last_success_at, last_error FROM sync_state "
            "WHERE endpoint_id = ?",
            (folder.config.source.endpoint_id,),
        ).fetchone()
        graph = repository.lineage(connection, include_inactive=True)
        lines: list[str] = []
        lines.append(f"# {folder.config.meeting.title}")
        lines.append("")
        lines.append(f"- Meeting: `{folder.config.meeting.id}`")
        lines.append(f"- Generated: {_stamp(moment)}")
        lines.append(f"- Endpoint: `{folder.config.source.endpoint_id}`")
        if state is None:
            lines.append("- Freshness: never synced")
        else:
            lines.append(f"- Last sync: {state['last_success_at'] or 'never'}")
            if state["last_error"]:
                lines.append(f"- Last sync error: {state['last_error']}")
        lines.append(
            f"- Counts: {len(summaries)} TDocs, {len(tracked)} tracked, "
            f"{len(graph['edges'])} lineage edges"
        )
        lines.append("")

        lines.append("## Summary")
        lines.append("")
        lines.append(
            "| TDoc | Agenda | Type | State | Source | Notes | Tracked |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for item in summaries:
            lines.append(
                "| {tdoc} | {agenda} | {type} | {state} | {source} | "
                "{notes} | {tracked} |".format(
                    tdoc=_cell(item["tdoc_number"]),
                    agenda=_cell(item["agenda_item"]),
                    type=_cell(item["type"]),
                    state=_cell(item["decision"]),
                    source=_cell(item["source"]),
                    notes=item["notes_count"],
                    tracked="yes" if item["is_tracked"] else "no",
                )
            )
        lines.append("")

        lines.append("## Lineage")
        lines.append("")
        mermaid_lines, inactive = _mermaid(connection)
        lines.extend(mermaid_lines)
        lines.append("")
        if inactive:
            lines.append("Muted / inactive branches:")
            lines.append("")
            lines.extend(inactive)
            lines.append("")

        for summary in tracked:
            detail = repository.get_tdoc(connection, summary["tdoc_number"])
            if detail is None:
                continue
            lines.append(f"## {detail['tdoc_number']}")
            lines.append("")
            if detail["title"]:
                lines.append(f"**{detail['title']}**")
                lines.append("")
            lines.append(f"- Agenda: {_cell(detail['agenda_item'])}")
            lines.append(f"- Type: {_cell(detail['type'])}")
            lines.append(f"- State: {_cell(detail['decision'])}")
            if detail["node_status"]:
                lines.append(f"- Status: {_cell(detail['node_status'])}")
            lines.append(f"- Source: {_cell(detail['source'])}")
            lines.append(f"- For: {_cell(detail['for_action'])}")
            lines.append(
                f"- Release / WI: {_cell(detail['release'])} / "
                f"{_cell(detail['wi_code'])}"
            )
            if detail["treated_note"]:
                lines.append(f"- Meeting note: {_cell(detail['treated_note'])}")
            lines.append("")

            lines.append("### Timeline")
            lines.append("")
            events = repository.timeline(connection, detail["tdoc_number"])
            if not events:
                lines.append("_No events._")
            for event in events:
                when = event.get("occurred_at") or "unknown"
                suffix = " _(ephemeral)_" if event.get("ephemeral") else ""
                detail_text = event.get("detail")
                extra = f" — {detail_text}" if detail_text else ""
                lines.append(
                    f"- {when} · {event.get('kind')}: "
                    f"{event.get('title') or ''}{extra}{suffix}"
                )
            lines.append("")

            lines.append("### Artifacts")
            lines.append("")
            if not detail["artifacts"]:
                lines.append("_No cached artifacts._")
            for artifact in detail["artifacts"]:
                suffix = " _(ephemeral)_" if artifact["is_ephemeral"] else ""
                lines.append(
                    f"- `{artifact['logical_path']}` "
                    f"({artifact['kind']}, {artifact['status']}){suffix}"
                )
            lines.append("")

            lines.append("### Notes")
            lines.append("")
            if not detail["notes"]:
                lines.append("_No notes._")
            for note in detail["notes"]:
                lines.append(f"- {note['body']}")
            lines.append("")

            if include_mail:
                lines.append("### Mail")
                lines.append("")
                if not detail["emails"]:
                    lines.append("_No linked mail._")
                for mail in detail["emails"]:
                    lines.append(
                        f"- {mail['date_utc'] or mail['ingested_at']} · "
                        f"{mail['from_addr'] or 'unknown'} · "
                        f"{mail['subject'] or '(no subject)'}"
                    )
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"
    finally:
        connection.close()


def export_markdown(
    folder: MeetingFolder,
    *,
    include_mail: bool = False,
    generated_at: datetime | None = None,
) -> Path:
    moment = generated_at or datetime.now(timezone.utc)
    folder.exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = (
        moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if moment.tzinfo
        else moment.strftime("%Y%m%dT%H%M%SZ")
    )
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", folder.config.meeting.id)
    target = folder.exports_dir / f"mirko-{slug}-{stamp}.md"
    target.write_text(
        render_markdown(
            folder, include_mail=include_mail, generated_at=moment
        ),
        encoding="utf-8",
    )
    return target


def _reingest_latest_agenda(folder: MeetingFolder, *, clock) -> None:
    connection = folder.connect()
    try:
        artifacts = connection.execute(
            "SELECT logical_path, filename, blob_hash FROM artifact "
            "WHERE kind = 'agenda_html' AND blob_hash IS NOT NULL "
            "ORDER BY id DESC"
        ).fetchall()
    finally:
        connection.close()
    if not artifacts:
        return
    by_name = {row["filename"] or row["logical_path"]: row for row in artifacts}
    latest = select_latest_agenda(by_name)
    if latest is None:
        return
    artifact = by_name[latest]
    blobs = BlobStore(folder.blobs_dir)
    raw = blobs.path_for(artifact["blob_hash"]).read_bytes()
    AgendaIngestor(folder, clock=clock).ingest(raw, path=artifact["logical_path"])


def materialize_mirror(folder: MeetingFolder) -> int:
    connection = folder.connect()
    try:
        rows = connection.execute(
            "SELECT logical_path, blob_hash FROM artifact "
            "WHERE blob_hash IS NOT NULL ORDER BY logical_path"
        ).fetchall()
    finally:
        connection.close()
    blobs = BlobStore(folder.blobs_dir)
    root = folder.mirror_dir.resolve()
    linked = 0
    for row in rows:
        relative = PurePosixPath(row["logical_path"])
        if relative.is_absolute() or ".." in relative.parts:
            continue
        target = folder.mirror_dir / Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        parent = target.parent.resolve()
        try:
            inside = parent.is_relative_to(root)
        except AttributeError:  # pragma: no cover - Python < 3.9
            inside = str(parent).startswith(str(root))
        if not inside:
            continue
        source = blobs.path_for(row["blob_hash"])
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(os.path.relpath(source, target.parent))
        linked += 1
    return linked


def finalize(
    folder: MeetingFolder,
    *,
    include_mail: bool = False,
    clock: Callable[[], datetime] | None = None,
    mirror: bool = True,
) -> dict:
    clock = clock or (lambda: datetime.now(timezone.utc))
    moment = clock()
    _reingest_latest_agenda(folder, clock=clock)
    target = export_markdown(
        folder, include_mail=include_mail, generated_at=moment
    )
    linked = materialize_mirror(folder) if mirror else 0
    connection = folder.connect()
    try:
        connection.execute(
            "INSERT INTO meeting_meta(key, value) VALUES ('finalized', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        connection.execute(
            "INSERT INTO meeting_meta(key, value) VALUES ('finalized_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_stamp(moment),),
        )
        connection.execute(
            "INSERT INTO meeting_meta(key, value) VALUES ('export_path', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(target.relative_to(folder.path)),),
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "status": "finalized",
        "export_path": str(target.relative_to(folder.path)),
        "mirror_links": linked,
        "finalized_at": _stamp(moment),
    }
