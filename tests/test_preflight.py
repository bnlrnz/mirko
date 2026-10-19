"""Tests for startup preflight checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from mirko.__main__ import main
from mirko.meeting_folder import MeetingFolder
from mirko.preflight import PreflightError, check_lftp


def write_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


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
            "base_path": "/Meetings_3GPP_SYNC/SA3",
            "username": "anonymous",
        },
    }


def test_missing_lftp_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIRKO_LFTP", raising=False)
    monkeypatch.setenv("PATH", "")

    with pytest.raises(PreflightError, match="nix develop"):
        check_lftp()


def test_lftp_override_must_be_executable(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    with pytest.raises(PreflightError, match="could not be executed"):
        check_lftp(str(missing))


def test_lftp_version_check_succeeds(tmp_path: Path) -> None:
    lftp = write_executable(tmp_path / "lftp", "echo 'LFTP 4.9.3'")

    assert check_lftp(str(lftp)) == str(lftp)


def test_lftp_version_check_failure_is_reported(tmp_path: Path) -> None:
    lftp = write_executable(
        tmp_path / "lftp", "echo 'broken install' >&2\nexit 1"
    )

    with pytest.raises(PreflightError, match="broken install"):
        check_lftp(str(lftp))


def test_cli_fails_cleanly_when_lftp_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    monkeypatch.delenv("MIRKO_LFTP", raising=False)
    monkeypatch.setenv("PATH", "")

    assert main([str(folder.path)]) == 2
    assert "lftp is required" in capsys.readouterr().err


def test_cli_requires_a_meeting_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MIRKO_MEETING", raising=False)

    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
