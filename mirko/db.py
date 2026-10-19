"""SQLite connection setup and numbered schema migrations."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when migrations are missing, malformed, or fail to apply."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str


def discover_migrations(directory: str | Path | None = None) -> tuple[Migration, ...]:
    root = Path(directory) if directory is not None else MIGRATIONS_DIR
    if not root.is_dir():
        raise MigrationError(f"migration directory not found: {root}")

    migrations: list[Migration] = []
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_RE.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"invalid migration filename: {path.name}")
        migrations.append(
            Migration(
                version=int(match.group(1)),
                name=match.group(2),
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )

    migrations.sort(key=lambda migration: migration.version)
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"expected migration {expected:04d}, found {migration.path.name}"
            )
    return tuple(migrations)


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def apply_migrations(
    connection: sqlite3.Connection, directory: str | Path | None = None
) -> list[int]:
    migrations = discover_migrations(directory)
    current = schema_version(connection)
    if current > len(migrations):
        raise MigrationError(
            f"database schema version {current} is newer than the latest "
            f"migration {len(migrations)}"
        )

    applied: list[int] = []
    for migration in migrations:
        if migration.version <= current:
            continue
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql.rstrip()}\n"
            "INSERT INTO schema_migration(version, applied_at) "
            f"VALUES ({migration.version}, "
            "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));\n"
            f"PRAGMA user_version = {migration.version};\n"
            "COMMIT;\n"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise MigrationError(
                f"migration {migration.path.name} failed: {exc}"
            ) from exc
        current = migration.version
        applied.append(migration.version)
    return applied


def connect(
    path: str | Path,
    *,
    migrate: bool = True,
    migrations_dir: str | Path | None = None,
) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        if migrate:
            apply_migrations(connection, migrations_dir)
    except Exception:
        connection.close()
        raise
    return connection
