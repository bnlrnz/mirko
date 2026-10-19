"""Tests for meeting configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mirko.config import (
    ConfigError,
    Hours,
    MailSettings,
    PathSettings,
    PollSettings,
    UiSettings,
    load_config,
    validate_config,
)


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


def error_text(exc: pytest.ExceptionInfo[ConfigError]) -> str:
    return "\n".join(exc.value.errors)


def test_minimal_config_uses_defaults() -> None:
    config = validate_config(minimal_config())

    assert config.schema_version == 1
    assert config.meeting.hours == Hours("09:00", "18:00")
    assert config.mail is None
    assert config.paths == PathSettings()
    assert config.poll == PollSettings()
    assert config.ui == UiSettings()
    assert config.tracked_seed == ()
    assert config.warnings == ()
    assert config.source.endpoint_id == "ftp://10.10.10.10:21/Meetings_3GPP_SYNC/SA3"


def test_full_config_maps_all_sections() -> None:
    data = minimal_config()
    data["source"].update(
        {
            "password_env": "MIRKO_FTP_PASSWORD",
            "tls": "explicit",
        }
    )
    data["mail"] = {"kind": "mbox", "path": "/home/ben/mail/sa3-130.mbox"}
    data["paths"] = {
        "drafts": "Inbox/Drafts",
        "inbox": "Inbox",
        "agenda_glob": "AgendaWithTdocAllocation_*.htm",
        "excel": "S3-26_meeting_allocation.xlsx",
    }
    data["poll"] = {
        "meeting_interval_s": 30,
        "idle_interval_s": 300,
        "mail_interval_s": 60,
        "backoff_max_s": 120,
        "jitter": 0.1,
    }
    data["tracked_seed"] = ["S3-264481", "s3-264388"]
    data["ui"] = {"default_mode": "lineage"}

    config = validate_config(data)

    assert config.source.password_env == "MIRKO_FTP_PASSWORD"
    assert config.source.tls == "explicit"
    assert config.mail == MailSettings(
        kind="mbox", path="/home/ben/mail/sa3-130.mbox"
    )
    assert config.poll.jitter == pytest.approx(0.1)
    assert config.tracked_seed == ("S3-264481", "S3-264388")
    assert config.ui.default_mode == "lineage"
    assert config.warnings == ()


def test_unknown_keys_warn_at_every_level() -> None:
    data = minimal_config()
    data["unexpected"] = True
    data["meeting"]["subtitle"] = "x"
    data["meeting"]["hours"] = {"start": "09:00", "end": "17:00", "lunch": True}
    data["source"]["proxy"] = "none"
    data["paths"] = {"drafts": "Drafts", "extra": "x"}
    data["poll"] = {"meeting_interval_s": 30, "unknown": 1}
    data["ui"] = {"default_mode": "auto", "theme": "dark"}

    config = validate_config(data)
    warnings = "\n".join(config.warnings)

    for needle in (
        "unexpected",
        "meeting.subtitle",
        "meeting.hours.lunch",
        "source.proxy",
        "paths.extra",
        "poll.unknown",
        "ui.theme",
    ):
        assert needle in warnings


@pytest.mark.parametrize(
    "data, expected",
    [
        ({}, "schema_version"),
        ({"schema_version": 2}, "unsupported version"),
        ({"schema_version": "1"}, "must be an integer"),
        ({"schema_version": True}, "must be an integer"),
    ],
)
def test_schema_version_errors(data: dict, expected: str) -> None:
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert expected in error_text(exc)


def test_required_sections() -> None:
    with pytest.raises(ConfigError) as exc:
        validate_config({"schema_version": 1})
    text = error_text(exc)
    assert "meeting: is required" in text
    assert "source: is required" in text


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("id", "", "meeting.id"),
        ("title", "", "meeting.title"),
        ("timezone", "Mars/Olympus", "unknown timezone"),
        ("days", ["not-a-date"], "not an ISO date"),
        ("days", [], "meeting.days"),
        ("tdoc_series_prefix", "banana", "must look like"),
        ("tdoc_series_prefix", "S3 26", "must look like"),
    ],
)
def test_meeting_field_errors(field: str, value: object, expected: str) -> None:
    data = minimal_config()
    data["meeting"][field] = value
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert expected in error_text(exc)


def test_hours_validation() -> None:
    data = minimal_config()
    data["meeting"]["hours"] = {"start": "25:00", "end": "18:00"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "HH:MM" in error_text(exc)

    data["meeting"]["hours"] = {"start": "18:00", "end": "09:00"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "start must be before end" in error_text(exc)


def test_duplicate_meeting_days_warn() -> None:
    data = minimal_config()
    data["meeting"]["days"] = ["2026-10-12", "2026-10-12"]
    config = validate_config(data)
    assert any("duplicate date" in warning for warning in config.warnings)


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("kind", "sneakernet", "source.kind"),
        ("protocol", "gopher", "source.protocol"),
        ("host", "", "source.host"),
        ("host", "ftp.example.org\nEVIL", "control characters"),
        ("base_path", "relative/path", "must start with '/'"),
        ("base_path", "/Meetings_3GPP_SYNC/../etc", "must not contain '..'"),
        ("tls", "maybe", "source.tls"),
        ("port", 0, "between 1 and 65535"),
        ("port", 70000, "between 1 and 65535"),
        ("port", "21", "must be an integer"),
    ],
)
def test_source_field_errors(field: str, value: object, expected: str) -> None:
    data = minimal_config()
    data["source"][field] = value
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert expected in error_text(exc)


def test_source_host_rejects_whitespace() -> None:
    data = minimal_config()
    data["source"]["host"] = "ftp example"
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "must not contain whitespace" in error_text(exc)


def test_password_and_password_env_are_mutually_exclusive() -> None:
    data = minimal_config()
    data["source"]["password"] = "secret"
    data["source"]["password_env"] = "MIRKO_PASSWORD"
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "not both" in error_text(exc)


def test_password_env_name_is_validated() -> None:
    data = minimal_config()
    data["source"]["password_env"] = "NOT-VALID"
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "valid environment variable" in error_text(exc)


def test_literal_password_is_resolved_and_hidden_from_repr() -> None:
    data = minimal_config()
    data["source"]["password"] = "s3cret"
    config = validate_config(data)

    assert config.source.resolve_password() == "s3cret"
    assert "s3cret" not in repr(config.source)
    assert "s3cret" not in repr(config)


def test_password_env_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIRKO_TEST_PASSWORD", "from-env")
    data = minimal_config()
    data["source"]["password_env"] = "MIRKO_TEST_PASSWORD"

    config = validate_config(data)
    assert config.source.resolve_password() == "from-env"

    monkeypatch.delenv("MIRKO_TEST_PASSWORD")
    with pytest.raises(ConfigError) as exc:
        config.source.resolve_password()
    assert "is not set" in error_text(exc)


def test_anonymous_source_has_no_password() -> None:
    config = validate_config(minimal_config())
    assert config.source.resolve_password() is None


def test_endpoint_id_uses_protocol_default_port() -> None:
    data = minimal_config()
    data["source"]["protocol"] = "https"
    data["source"].pop("port")
    config = validate_config(data)
    assert config.source.effective_port() == 443
    assert config.source.endpoint_id == "https://10.10.10.10:443/Meetings_3GPP_SYNC/SA3"


def test_mail_validation() -> None:
    data = minimal_config()
    data["mail"] = {"kind": "mbox"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "mail.path" in error_text(exc)

    data["mail"] = {"kind": "eml"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "mail.eml_dir" in error_text(exc)

    data["mail"] = {"kind": "carrier-pigeon"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "mail.kind" in error_text(exc)


def test_mail_kind_specific_keys_warn() -> None:
    data = minimal_config()
    data["mail"] = {
        "kind": "mbox",
        "path": "/tmp/mail.mbox",
        "eml_dir": "/tmp/mail",
    }
    config = validate_config(data)
    assert any("ignored when kind is 'mbox'" in warning for warning in config.warnings)


@pytest.mark.parametrize("value", ["/absolute/path", "../escape", "~/mail"])
def test_paths_must_stay_inside_meeting_folder(value: str) -> None:
    data = minimal_config()
    data["paths"] = {"drafts": value}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    text = error_text(exc)
    assert "must be relative" in text or "must not contain '..'" in text


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("meeting_interval_s", 0, ">= 1"),
        ("idle_interval_s", -1, ">= 1"),
        ("mail_interval_s", 1.5, "must be an integer"),
        ("jitter", -0.1, ">= 0"),
        ("jitter", 1.5, "<= 1"),
        ("jitter", "0.2", "must be a number"),
    ],
)
def test_poll_validation(field: str, value: object, expected: str) -> None:
    data = minimal_config()
    data["poll"] = {field: value}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert expected in error_text(exc)


def test_tracked_seed_validation_and_duplicates() -> None:
    data = minimal_config()
    data["tracked_seed"] = ["S3-264481", "S3-26abcd", "s3-264388"]
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "tracked_seed[1]" in error_text(exc)

    data["tracked_seed"] = ["S3-264481", "S3-264481", "S3-264388"]
    config = validate_config(data)
    assert config.tracked_seed == ("S3-264481", "S3-264388")
    assert any("duplicate TDoc" in warning for warning in config.warnings)


def test_ui_mode_validation() -> None:
    data = minimal_config()
    data["ui"] = {"default_mode": "hologram"}
    with pytest.raises(ConfigError) as exc:
        validate_config(data)
    assert "ui.default_mode" in error_text(exc)


def test_load_config_from_file(tmp_path: Path) -> None:
    path = tmp_path / "meeting.json"
    path.write_text(json.dumps(minimal_config()), encoding="utf-8")

    config = load_config(path)

    assert config.path == path
    assert config.meeting.id == "SA3#130"
    assert config.warnings == ()


def test_load_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "missing.json")
    assert "file not found" in error_text(exc)


def test_load_config_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "meeting.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "invalid JSON" in error_text(exc)


def test_load_config_rejects_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "meeting.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "root must be an object" in error_text(exc)


def test_load_config_warns_when_literal_password_is_world_readable(
    tmp_path: Path,
) -> None:
    data = minimal_config()
    data["source"]["password"] = "s3cret"
    path = tmp_path / "meeting.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o644)

    config = load_config(path)
    assert any("chmod 600" in warning for warning in config.warnings)

    path.chmod(0o600)
    config = load_config(path)
    assert not any("chmod 600" in warning for warning in config.warnings)
