"""Shared helpers for maintaining the ``tdoc`` projection."""

from __future__ import annotations

import json
import sqlite3

from mirko.ingest.agenda_html import canonical_tdoc


def normalize_tdoc(value: str | None) -> str | None:
    """Canonicalize a TDoc token, tolerating separators and casing."""
    return canonical_tdoc(value)


def ensure_tdoc(
    connection: sqlite3.Connection,
    tdoc_number: str,
    *,
    source: str,
    observed_at: str,
) -> bool:
    """Create a provisional TDoc row when one does not exist yet.

    Returns ``True`` when a new provisional row was inserted.
    """
    existing = connection.execute(
        "SELECT 1 FROM tdoc WHERE tdoc_number = ?", (tdoc_number,)
    ).fetchone()
    if existing is not None:
        return False
    connection.execute(
        "INSERT INTO tdoc("
        "tdoc_number, state_source, first_seen_at, last_seen_at, "
        "is_tracked, is_provisional, raw_meta"
        ") VALUES (?, ?, ?, ?, 0, 1, ?)",
        (
            tdoc_number,
            source,
            observed_at,
            observed_at,
            json.dumps({"discovered_by": source}, ensure_ascii=False),
        ),
    )
    return True
