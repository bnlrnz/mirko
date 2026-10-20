"""Portable meeting-folder creation, opening, and layout."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from mirko.config import MeetingConfig, load_config, validate_config
from mirko.db import connect

CONFIG_FILENAME = "meeting.json"
DATABASE_FILENAME = "mirko.sqlite"
LAYOUT_DIRS = (
    "cache/blobs",
    "cache/mirror",
    "exports",
    "imports",
    "logs",
)


class MeetingFolderError(RuntimeError):
    """Raised when a meeting folder cannot be created or opened."""


def _ensure_layout(root: Path) -> None:
    for relative in LAYOUT_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def _write_config(path: Path, data: Mapping[str, Any]) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(
        prefix=".meeting.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass
class MeetingFolder:
    path: Path
    config: MeetingConfig

    @classmethod
    def create(
        cls, path: str | Path, config_data: Mapping[str, Any]
    ) -> MeetingFolder:
        root = Path(path)
        if root.exists():
            if not root.is_dir():
                raise MeetingFolderError(f"not a directory: {root}")
            if any(root.iterdir()):
                raise MeetingFolderError(f"directory is not empty: {root}")

        validate_config(config_data)
        root.mkdir(parents=True, exist_ok=True)
        _ensure_layout(root)
        _write_config(root / CONFIG_FILENAME, config_data)

        folder = cls(root, load_config(root / CONFIG_FILENAME))
        folder.initialize_database()
        return folder

    @classmethod
    def open(cls, path: str | Path) -> MeetingFolder:
        root = Path(path)
        if not root.exists():
            raise MeetingFolderError(f"meeting folder not found: {root}")
        if not root.is_dir():
            raise MeetingFolderError(f"not a directory: {root}")

        config_path = root / CONFIG_FILENAME
        if not config_path.is_file():
            raise MeetingFolderError(f"missing {CONFIG_FILENAME}: {root}")

        config = load_config(config_path)
        _ensure_layout(root)
        folder = cls(root, config)
        folder.initialize_database()
        return folder

    @property
    def config_path(self) -> Path:
        return self.path / CONFIG_FILENAME

    @property
    def imports_dir(self) -> Path:
        return self.path / "imports"

    def config_document(self) -> dict[str, Any]:
        return json.loads(self.config_path.read_text(encoding="utf-8-sig"))

    def update_config(self, data: Mapping[str, Any]) -> MeetingConfig:
        validate_config(data)
        _write_config(self.config_path, data)
        self.config = load_config(self.config_path)
        return self.config

    @property
    def database_path(self) -> Path:
        return self.path / DATABASE_FILENAME

    @property
    def cache_dir(self) -> Path:
        return self.path / "cache"

    @property
    def blobs_dir(self) -> Path:
        return self.cache_dir / "blobs"

    @property
    def mirror_dir(self) -> Path:
        return self.cache_dir / "mirror"

    @property
    def exports_dir(self) -> Path:
        return self.path / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.path / "logs"

    def connect(self, *, migrate: bool = False) -> sqlite3.Connection:
        return connect(self.database_path, migrate=migrate)

    def initialize_database(self) -> None:
        connection = self.connect(migrate=True)
        connection.close()
