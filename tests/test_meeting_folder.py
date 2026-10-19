"""Tests for portable meeting-folder lifecycle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from mirko.config import ConfigError
from mirko.db import schema_version
from mirko.meeting_folder import LAYOUT_DIRS, MeetingFolder, MeetingFolderError


def minimal_config() -> dict:
    return {
        "schema_version": 1,
        "meeting": {
            "id": "SA3#130",
            "title": "SA3#130 Prague",
            "timezone": "Europe/Prague",
            "days": ["2026-10-12", "2026-10-16"],
            "tdoc_series_prefix": "S3-26",
        },
        "source": {
            "kind": "local",
            "protocol": "ftp",
            "host": "10.10.10.10",
            "port": 21,
            "base_path": "/ftp/SA/SA3",
            "username": "anonymous",
        },
    }


def test_create_builds_portable_layout(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())

    for relative in LAYOUT_DIRS:
        assert (folder.path / relative).is_dir()
    assert folder.config_path.is_file()
    assert folder.database_path.is_file()
    assert folder.blobs_dir == folder.cache_dir / "blobs"
    assert folder.mirror_dir == folder.cache_dir / "mirror"
    assert folder.exports_dir.is_dir()
    assert folder.logs_dir.is_dir()


def test_create_writes_config_securely_and_returns_loaded_settings(
    tmp_path: Path,
) -> None:
    data = minimal_config()
    folder = MeetingFolder.create(tmp_path / "SA3-130", data)

    assert folder.config.path == folder.config_path
    assert folder.config.meeting.id == "SA3#130"
    assert json.loads(folder.config_path.read_text(encoding="utf-8")) == data
    assert folder.config_path.stat().st_mode & 0o777 == 0o600


def test_create_initializes_database(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    connection = folder.connect()
    try:
        assert schema_version(connection) == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migration"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_create_leaves_no_temporary_files(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    assert not any(
        entry.name.startswith(".meeting.") for entry in folder.path.iterdir()
    )


def test_create_rejects_non_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "SA3-130"
    root.mkdir()
    (root / "unrelated.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(MeetingFolderError, match="not empty"):
        MeetingFolder.create(root, minimal_config())

    assert not (root / "meeting.json").exists()
    assert (root / "unrelated.txt").read_text(encoding="utf-8") == "keep me"


def test_create_rejects_existing_meeting(tmp_path: Path) -> None:
    root = tmp_path / "SA3-130"
    MeetingFolder.create(root, minimal_config())

    with pytest.raises(MeetingFolderError, match="not empty"):
        MeetingFolder.create(root, minimal_config())


def test_create_rejects_file_path(tmp_path: Path) -> None:
    target = tmp_path / "not-a-folder"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(MeetingFolderError, match="not a directory"):
        MeetingFolder.create(target, minimal_config())


def test_create_validates_before_touching_disk(tmp_path: Path) -> None:
    data = minimal_config()
    data["schema_version"] = 99
    root = tmp_path / "SA3-130"

    with pytest.raises(ConfigError):
        MeetingFolder.create(root, data)

    assert not root.exists()


def test_open_existing_folder(tmp_path: Path) -> None:
    created = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())

    opened = MeetingFolder.open(created.path)

    assert opened.path == created.path
    assert opened.config.meeting.title == "SA3#130 Prague"
    assert opened.database_path.is_file()


def test_open_repairs_missing_layout_directories(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    shutil.rmtree(folder.blobs_dir)
    assert not folder.blobs_dir.exists()

    reopened = MeetingFolder.open(folder.path)

    assert reopened.blobs_dir.is_dir()


def test_open_is_idempotent_for_migrations(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    MeetingFolder.open(folder.path)

    connection = folder.connect()
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migration"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_open_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(MeetingFolderError, match="not found"):
        MeetingFolder.open(tmp_path / "missing")


def test_open_missing_config(tmp_path: Path) -> None:
    root = tmp_path / "SA3-130"
    root.mkdir()

    with pytest.raises(MeetingFolderError, match="missing meeting.json"):
        MeetingFolder.open(root)


def test_open_rejects_invalid_config(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    folder.config_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ConfigError):
        MeetingFolder.open(folder.path)
