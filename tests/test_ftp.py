"""Tests for the lftp adapter, listing parser, and fake client."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mirko.config import SourceSettings
from mirko.ftp import (
    FakeFtpClient,
    FakeRemoteFile,
    FtpError,
    LftpFtpClient,
    is_safe_remote_name,
    join_remote_path,
    normalize_remote_path,
    parse_ls_listing,
)

LISTING = """\
total 4
drwxr-xr-x    2 ftp      ftp          4096 Oct 16 14:37 Drafts
-rw-r--r--    1 ftp      ftp          1234 Oct 16 14:37 draft S3-264314-r1.docx
-rw-r--r--    1 ftp      ftp            99 2026-10-16 14:40 agenda.htm
lrwxrwxrwx    1 ftp      ftp            10 Oct 16 14:37 latest.docx -> target.docx
"""


def source(**overrides: object) -> SourceSettings:
    values = {
        "kind": "local",
        "protocol": "ftp",
        "host": "10.10.10.10",
        "port": 21,
        "base_path": "/ftp/SA/SA3",
        "username": "anonymous",
        "password": "s3cret",
        "tls": "none",
    }
    values.update(overrides)
    return SourceSettings(**values)


def test_parse_classic_and_iso_listing() -> None:
    entries, unparsed = parse_ls_listing(
        LISTING, now=datetime(2026, 10, 19, tzinfo=timezone.utc)
    )

    assert unparsed == []
    by_name = {entry.name: entry for entry in entries}
    assert by_name["Drafts"].is_dir is True
    assert by_name["draft S3-264314-r1.docx"].size == 1234
    assert by_name["draft S3-264314-r1.docx"].mtime == "2026-10-16T14:37:00"
    assert by_name["agenda.htm"].mtime == "2026-10-16T14:40:00"
    assert by_name["latest.docx"].is_symlink is True
    assert by_name["latest.docx"].size == 10


def test_parse_yearless_date_infers_previous_year() -> None:
    entries, _ = parse_ls_listing(
        "-rw-r--r-- 1 ftp ftp 10 Dec 31 23:00 old.txt",
        now=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert entries[0].mtime == "2025-12-31T23:00:00"


def test_parse_old_style_year() -> None:
    entries, _ = parse_ls_listing(
        "-rw-r--r-- 1 ftp ftp 10 Oct 16 2024 old.txt",
        now=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )

    assert entries[0].mtime == "2024-10-16T00:00:00"


def test_unparsed_lines_are_reported_without_aborting() -> None:
    entries, unparsed = parse_ls_listing(
        "garbage line\n"
        "-rw-r--r-- 1 ftp ftp 10 Oct 16 14:00 good.txt\n",
        now=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )

    assert [entry.name for entry in entries] == ["good.txt"]
    assert unparsed == ["garbage line"]


def test_directory_entries_with_spaces() -> None:
    entries, _ = parse_ls_listing(
        "-rw-r--r-- 1 ftp ftp 7 Oct 16 14:00 a b c.docx",
        now=datetime(2026, 10, 19, tzinfo=timezone.utc),
    )
    assert entries[0].name == "a b c.docx"


@pytest.mark.parametrize(
    "value", ["../etc", "Inbox/../Drafts", "/absolute", "a\nb", ""]
)
def test_unsafe_remote_paths_are_rejected(value: str) -> None:
    if value == "":
        assert normalize_remote_path(value) == ""
    else:
        with pytest.raises(FtpError):
            normalize_remote_path(value)


@pytest.mark.parametrize(
    "name", ["../x", "a/b", "a\\b", "-rf", "", ".", "..", "a\nb"]
)
def test_unsafe_remote_names_are_rejected(name: str) -> None:
    assert is_safe_remote_name(name) is False


def test_join_remote_path() -> None:
    assert join_remote_path("Inbox/Drafts", "a.docx") == "Inbox/Drafts/a.docx"
    assert join_remote_path("", "a.docx") == "a.docx"
    with pytest.raises(FtpError):
        join_remote_path("Inbox", "../x")


def test_fake_client_lists_only_direct_children() -> None:
    client = FakeFtpClient(
        {
            "Inbox/Drafts/a.docx": b"a",
            "Inbox/Drafts/b.docx": FakeRemoteFile(b"bb", "2026-10-17T10:00:00"),
            "Inbox/final.zip": b"zip",
        }
    )

    entries = client.list("Inbox/Drafts")

    assert [(entry.name, entry.size, entry.mtime) for entry in entries] == [
        ("a.docx", 1, "2026-10-16T14:37:00"),
        ("b.docx", 2, "2026-10-17T10:00:00"),
    ]
    assert client.list_calls == ["Inbox/Drafts"]


def test_fake_client_fetch_and_failures(tmp_path: Path) -> None:
    client = FakeFtpClient({"Drafts/a.docx": b"content"})
    dest = tmp_path / "a.docx"

    client.fetch("Drafts/a.docx", dest)
    assert dest.read_bytes() == b"content"
    assert client.fetch_calls == ["Drafts/a.docx"]

    client.fail_list.add("Drafts")
    with pytest.raises(FtpError):
        client.list("Drafts")

    client.fail_fetch.add("Drafts/a.docx")
    with pytest.raises(FtpError):
        client.fetch("Drafts/a.docx", dest)


def test_lftp_list_builds_safe_command(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout=LISTING, stderr="")

    monkeypatch.setattr("mirko.ftp.subprocess.run", fake_run)
    client = LftpFtpClient(source(), executable="/opt/lftp")

    entries = client.list("Drafts")

    assert "draft S3-264314-r1.docx" in {entry.name for entry in entries}
    assert captured["args"] == ["/opt/lftp"]
    assert "shell" not in captured["kwargs"]
    script = captured["kwargs"]["input"]
    assert 'open "ftp://anonymous:s3cret@10.10.10.10:21"' in script
    assert 'cd "/ftp/SA/SA3"' in script
    assert 'cls -l "Drafts"' in script
    assert "s3cret" not in captured["args"]


def test_lftp_fetch_builds_safe_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("mirko.ftp.subprocess.run", fake_run)
    client = LftpFtpClient(source(), executable="/opt/lftp")
    dest = tmp_path / "file name.docx"

    client.fetch("Drafts/file name.docx", dest)

    script = captured["kwargs"]["input"]
    assert 'get "Drafts/file name.docx"' in script
    assert f'-o "{dest}"' in script


def test_lftp_error_redacts_password(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, stdout="", stderr="auth failed for s3cret"
        )

    monkeypatch.setattr("mirko.ftp.subprocess.run", fake_run)
    client = LftpFtpClient(source(), executable="/opt/lftp")

    with pytest.raises(FtpError) as exc:
        client.list("Drafts")

    assert "s3cret" not in str(exc.value)
    assert "***" in str(exc.value)


def test_lftp_rejects_unsafe_path_before_running() -> None:
    client = LftpFtpClient(source(), executable="/opt/lftp")

    with pytest.raises(FtpError):
        client.list("../etc")
    with pytest.raises(FtpError):
        client.fetch("", Path("/tmp/x"))
