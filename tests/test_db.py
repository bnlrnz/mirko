"""Tests for SQLite setup and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mirko.db import (
    MigrationError,
    apply_migrations,
    connect,
    discover_migrations,
    schema_version,
)

EXPECTED_TABLES = {
    "schema_migration",
    "meeting_meta",
    "sync_state",
    "remote_entry",
    "blob",
    "artifact",
    "artifact_observation",
    "ingest_run",
    "tdoc",
    "tracked_tdoc",
    "assertion",
    "conflict",
    "note",
    "thread",
    "email",
    "email_mention",
    "user_action",
    "node_status",
}

EXPECTED_INDICES = {
    "idx_tdoc_agenda_item",
    "idx_artifact_tdoc",
    "idx_artifact_ephemeral",
    "idx_artifact_logical_path",
    "idx_artifact_observation_artifact",
    "idx_assertion_subject",
    "idx_assertion_object",
    "idx_conflict_subject",
    "idx_note_target",
    "idx_email_date",
    "idx_email_thread",
    "idx_email_mention_tdoc",
    "idx_remote_entry_path",
    "idx_sync_state_due",
    "idx_user_action_created",
    "idx_user_action_target",
    "idx_node_status_target",
}


def names(connection: sqlite3.Connection, kind: str) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
    ).fetchall()
    return {row["name"] for row in rows}


def test_discover_migrations_is_numbered_and_ordered() -> None:
    migrations = discover_migrations()
    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5]
    assert [migration.name for migration in migrations] == [
        "initial",
        "projection_views",
        "lazy_manifest",
        "user_action",
        "node_status",
    ]


def test_apply_migrations_on_empty_database(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite", migrate=False)
    try:
        assert schema_version(connection) == 0
        assert apply_migrations(connection) == [1, 2, 3, 4, 5]
        assert schema_version(connection) == 5
        rows = connection.execute(
            "SELECT version, applied_at FROM schema_migration ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in rows] == [1, 2, 3, 4, 5]
        assert all(row["applied_at"] for row in rows)
    finally:
        connection.close()


def test_node_status_migration_extracts_latest_note_tag(tmp_path: Path) -> None:
    migrations = discover_migrations()
    directory = tmp_path / "migrations"
    directory.mkdir()
    for migration in migrations:
        if migration.version <= 4:
            (directory / migration.path.name).write_text(
                migration.sql, encoding="utf-8"
            )

    connection = connect(tmp_path / "mirko.sqlite", migrate=False)
    try:
        assert apply_migrations(connection, directory) == [1, 2, 3, 4]
        connection.execute(
            "INSERT INTO note(target_kind, target_ref, body, position_tag, "
            "author, source, created_at, updated_at) VALUES "
            "('tdoc', 'S3-264202', 'Older.', 'Clarify', 'ben', 'user', "
            "'2026-10-16T13:00:00.000000Z', '2026-10-16T13:00:00.000000Z')"
        )
        connection.execute(
            "INSERT INTO note(target_kind, target_ref, body, position_tag, "
            "author, source, created_at, updated_at) VALUES "
            "('tdoc', 'S3-264202', 'Latest.', 'Support', 'ben', 'user', "
            "'2026-10-16T14:00:00.000000Z', '2026-10-16T14:00:00.000000Z')"
        )
        connection.commit()

        assert apply_migrations(connection) == [5]
        status = connection.execute(
            "SELECT status FROM node_status WHERE target_kind = 'tdoc' "
            "AND target_ref = 'S3-264202'"
        ).fetchone()
        assert status["status"] == "Support"
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(note)")
        }
        assert "position_tag" not in columns
    finally:
        connection.close()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        assert apply_migrations(connection) == []
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migration"
        ).fetchone()[0] == 5
    finally:
        connection.close()


def test_connect_sets_pragmas_and_schema(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert schema_version(connection) == 5
    finally:
        connection.close()


def test_expected_tables_and_indices_exist(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        tables = names(connection, "table")
        assert EXPECTED_TABLES.issubset(tables)
        assert {"email_fts", "tdoc_fts"}.issubset(tables)
        assert EXPECTED_INDICES.issubset(names(connection, "index"))
        assert {"edge_current", "tdoc_current"}.issubset(
            names(connection, "view")
        )
    finally:
        connection.close()


def test_fts_tables_search(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        connection.execute(
            "INSERT INTO tdoc_fts(tdoc_number, title) VALUES (?, ?)",
            ("S3-264481", "NTN security discussion"),
        )
        row = connection.execute(
            "SELECT tdoc_number FROM tdoc_fts WHERE tdoc_fts MATCH ?",
            ("security",),
        ).fetchone()
        assert row["tdoc_number"] == "S3-264481"
    finally:
        connection.close()


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO artifact(kind, logical_path, filename, "
                "source_kind, tdoc_number) VALUES (?, ?, ?, ?, ?)",
                ("draft", "Inbox/Drafts/a.docx", "a.docx", "ftp", "S3-000000"),
            )
    finally:
        connection.close()


def test_newer_database_schema_is_rejected(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite", migrate=False)
    try:
        connection.execute("PRAGMA user_version = 99")
        with pytest.raises(MigrationError, match="newer"):
            apply_migrations(connection)
    finally:
        connection.close()


def test_migration_gap_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    (directory / "0003_three.sql").write_text("SELECT 3;", encoding="utf-8")

    with pytest.raises(MigrationError, match="expected migration 0002"):
        discover_migrations(directory)


def test_invalid_migration_filename_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "initial.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover_migrations(directory)


def test_failed_migration_is_rolled_back_atomically(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_good.sql").write_text(
        "CREATE TABLE schema_migration (version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL);\n"
        "CREATE TABLE good (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    (directory / "0002_bad.sql").write_text(
        "CREATE TABLE bad (id INTEGER PRIMARY KEY);\n"
        "THIS IS NOT VALID SQL;\n",
        encoding="utf-8",
    )

    connection = connect(tmp_path / "mirko.sqlite", migrate=False)
    try:
        with pytest.raises(MigrationError, match="0002_bad.sql"):
            apply_migrations(connection, directory)
        assert schema_version(connection) == 1
        tables = names(connection, "table")
        assert "good" in tables
        assert "bad" not in tables
        assert connection.execute(
            "SELECT version FROM schema_migration"
        ).fetchall()[0]["version"] == 1
    finally:
        connection.close()
