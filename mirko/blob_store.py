"""Content-addressed blob storage under a meeting folder."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_SIZE = 1024 * 1024


class BlobError(RuntimeError):
    """Raised when a blob path or write is invalid."""


@dataclass(frozen=True)
class BlobInfo:
    hash: str
    size: int
    created: bool


class BlobStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, digest: str) -> Path:
        if not _HASH_RE.fullmatch(digest):
            raise BlobError(f"invalid blob hash: {digest!r}")
        return self.root / digest

    def has(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def _temporary_file(self) -> tuple[int, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(
            prefix=".blob.", suffix=".tmp", dir=self.root
        )
        return fd, Path(name)

    def add_file(self, source: str | Path) -> BlobInfo:
        source_path = Path(source)
        fd, temporary = self._temporary_file()
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(fd, "wb") as output, source_path.open("rb") as handle:
                while chunk := handle.read(_CHUNK_SIZE):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            key = digest.hexdigest()
            target = self.path_for(key)
            if target.is_file():
                temporary.unlink(missing_ok=True)
                return BlobInfo(hash=key, size=size, created=False)

            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            return BlobInfo(hash=key, size=size, created=True)
        finally:
            temporary.unlink(missing_ok=True)

    def add_bytes(self, data: bytes) -> BlobInfo:
        key = hashlib.sha256(data).hexdigest()
        target = self.path_for(key)
        if target.is_file():
            return BlobInfo(hash=key, size=len(data), created=False)

        fd, temporary = self._temporary_file()
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            return BlobInfo(hash=key, size=len(data), created=True)
        finally:
            temporary.unlink(missing_ok=True)
