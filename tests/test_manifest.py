"""Tests for manifest diffing and remote-entry persistence."""

from __future__ import annotations

from pathlib import Path

from mirko.db import connect
from mirko.ftp import RemoteEntry
from mirko.manifest import ManifestEntry, ManifestStore, diff_listing


def manifest_entry(
    name: str,
    *,
    size: int | None = 10,
    mtime: str | None = "2026-10-16T14:00:00",
    blob_hash: str | None = "a" * 64,
    missing_since: str | None = None,
) -> ManifestEntry:
    return ManifestEntry(
        endpoint_id="ftp://example",
        path="Inbox/Drafts",
        name=name,
        size=size,
        mtime=mtime,
        last_blob_hash=blob_hash,
        first_seen_at="2026-10-16T13:00:00",
        last_seen_at="2026-10-16T14:00:00",
        missing_since=missing_since,
    )


def remote(name: str, size: int = 10, mtime: str = "2026-10-16T14:00:00"):
    return RemoteEntry(name=name, size=size, mtime=mtime)


def test_diff_classifies_new_changed_unchanged_and_missing() -> None:
    existing = {
        "same.docx": manifest_entry("same.docx"),
        "size.docx": manifest_entry("size.docx"),
        "mtime.docx": manifest_entry("mtime.docx"),
        "gone.docx": manifest_entry("gone.docx"),
    }
    listing = [
        remote("same.docx"),
        remote("size.docx", size=11),
        remote("mtime.docx", mtime="2026-10-17T09:00:00"),
        remote("new.docx"),
    ]

    diff = diff_listing(existing, listing)

    assert [entry.name for entry in diff.new] == ["new.docx"]
    assert [entry.name for entry in diff.changed] == ["size.docx", "mtime.docx"]
    assert [entry.name for entry in diff.unchanged] == ["same.docx"]
    assert [entry.name for entry in diff.missing] == ["gone.docx"]
    assert [entry.name for entry in diff.needs_fetch] == [
        "new.docx",
        "size.docx",
        "mtime.docx",
    ]


def test_missing_blob_hash_forces_fetch() -> None:
    existing = {"a.docx": manifest_entry("a.docx", blob_hash=None)}
    diff = diff_listing(existing, [remote("a.docx")])
    assert [entry.name for entry in diff.changed] == ["a.docx"]


def test_missing_mtime_does_not_force_fetch_if_size_matches() -> None:
    existing = {"a.docx": manifest_entry("a.docx", mtime=None)}
    diff = diff_listing(existing, [remote("a.docx", mtime=None)])
    assert [entry.name for entry in diff.unchanged] == ["a.docx"]


def test_duplicate_listing_names_are_deduplicated() -> None:
    diff = diff_listing({}, [remote("a.docx"), remote("a.docx")])
    assert [entry.name for entry in diff.new] == ["a.docx"]


def test_store_records_and_updates_entries(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        store = ManifestStore(connection, "ftp://example")
        store.record(
            "Inbox/Drafts",
            remote("a.docx", size=10),
            blob_hash="a" * 64,
            observed_at="2026-10-16T13:00:00",
        )
        store.record(
            "Inbox/Drafts",
            remote("a.docx", size=12, mtime="2026-10-17T08:00:00"),
            blob_hash="b" * 64,
            observed_at="2026-10-17T08:00:00",
        )

        entries = store.load("Inbox/Drafts")
        assert set(entries) == {"a.docx"}
        entry = entries["a.docx"]
        assert entry.size == 12
        assert entry.mtime == "2026-10-17T08:00:00"
        assert entry.last_blob_hash == "b" * 64
        assert entry.first_seen_at == "2026-10-16T13:00:00"
        assert entry.last_seen_at == "2026-10-17T08:00:00"
        assert entry.missing_since is None
    finally:
        connection.close()


def test_store_marks_missing_and_clears_on_return(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        store = ManifestStore(connection, "ftp://example")
        entry = remote("a.docx")
        store.record(
            "Inbox/Drafts",
            entry,
            blob_hash="a" * 64,
            observed_at="2026-10-16T13:00:00",
        )

        missing = store.load("Inbox/Drafts")["a.docx"]
        store.mark_missing(
            "Inbox/Drafts", [missing], observed_at="2026-10-17T09:00:00"
        )
        assert (
            store.load("Inbox/Drafts")["a.docx"].missing_since
            == "2026-10-17T09:00:00"
        )

        store.mark_missing(
            "Inbox/Drafts", [missing], observed_at="2026-10-18T09:00:00"
        )
        assert (
            store.load("Inbox/Drafts")["a.docx"].missing_since
            == "2026-10-17T09:00:00"
        )

        store.record(
            "Inbox/Drafts",
            entry,
            blob_hash="a" * 64,
            observed_at="2026-10-19T09:00:00",
        )
        assert store.load("Inbox/Drafts")["a.docx"].missing_since is None
    finally:
        connection.close()


def test_store_isolated_by_endpoint_and_path(tmp_path: Path) -> None:
    connection = connect(tmp_path / "mirko.sqlite")
    try:
        first = ManifestStore(connection, "ftp://one")
        second = ManifestStore(connection, "ftp://two")
        first.record(
            "Inbox/Drafts",
            remote("a.docx"),
            blob_hash="a" * 64,
            observed_at="2026-10-16T13:00:00",
        )

        assert first.load("Inbox/Drafts")
        assert second.load("Inbox/Drafts") == {}
        assert first.load("Inbox") == {}
    finally:
        connection.close()
