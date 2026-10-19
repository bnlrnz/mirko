"""Tests for the content-addressed blob store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mirko.blob_store import BlobError, BlobStore


def test_add_file_uses_content_hash(tmp_path: Path) -> None:
    source = tmp_path / "draft.docx"
    source.write_bytes(b"hello mirko")
    store = BlobStore(tmp_path / "blobs")

    info = store.add_file(source)

    expected = hashlib.sha256(b"hello mirko").hexdigest()
    assert info.hash == expected
    assert info.size == len(b"hello mirko")
    assert info.created is True
    assert store.has(expected) is True
    assert store.path_for(expected).read_bytes() == b"hello mirko"


def test_identical_content_is_stored_once(tmp_path: Path) -> None:
    first = tmp_path / "first.docx"
    second = tmp_path / "renamed.docx"
    first.write_bytes(b"same content")
    second.write_bytes(b"same content")
    store = BlobStore(tmp_path / "blobs")

    one = store.add_file(first)
    two = store.add_file(second)

    assert one.created is True
    assert two.created is False
    assert one.hash == two.hash
    assert [path.name for path in store.root.iterdir()] == [one.hash]


def test_add_bytes_deduplicates(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")

    first = store.add_bytes(b"abc")
    second = store.add_bytes(b"abc")

    assert first.created is True
    assert second.created is False
    assert first.hash == hashlib.sha256(b"abc").hexdigest()
    assert store.path_for(first.hash).read_bytes() == b"abc"


def test_no_temporary_files_remain(tmp_path: Path) -> None:
    source = tmp_path / "file.bin"
    source.write_bytes(b"x" * 10)
    store = BlobStore(tmp_path / "blobs")

    store.add_file(source)
    store.add_bytes(b"y")

    assert not any(path.name.startswith(".blob.") for path in store.root.iterdir())


@pytest.mark.parametrize(
    "digest", ["../escape", "ABC", "a" * 63, "g" * 64, ""]
)
def test_invalid_hashes_are_rejected(tmp_path: Path, digest: str) -> None:
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobError):
        store.path_for(digest)
