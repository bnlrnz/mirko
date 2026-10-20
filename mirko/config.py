"""Loading and validation for a meeting folder's ``meeting.json``."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 1

DEFAULT_DRAFTS_PATH = "Inbox/Drafts"
DEFAULT_INBOX_PATH = "Inbox"
DEFAULT_AGENDA_GLOB = "AgendaWithTdocAllocation_*.htm"
DEFAULT_EXCEL_PATH = "S3-26_meeting_allocation.xlsx"

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "meeting",
        "source",
        "mail",
        "paths",
        "poll",
        "sync",
        "tracked_seed",
        "ui",
    }
)
_MEETING_KEYS = frozenset(
    {"id", "title", "timezone", "days", "hours", "tdoc_series_prefix"}
)
_HOURS_KEYS = frozenset({"start", "end"})
_SOURCE_KEYS = frozenset(
    {
        "kind",
        "protocol",
        "host",
        "port",
        "base_path",
        "username",
        "password",
        "password_env",
        "tls",
    }
)
_MAIL_KEYS = frozenset({"kind", "path", "eml_dir"})
_PATHS_KEYS = frozenset({"drafts", "inbox", "agenda_glob", "excel"})
_POLL_KEYS = frozenset(
    {
        "meeting_interval_s",
        "idle_interval_s",
        "mail_interval_s",
        "backoff_max_s",
        "jitter",
    }
)
_SYNC_KEYS = frozenset({"lazy_drafts"})
_UI_KEYS = frozenset({"default_mode"})

_SOURCE_KINDS = frozenset({"local", "remote", "public"})
_PROTOCOLS = frozenset({"ftp", "ftps", "https"})
_TLS_MODES = frozenset({"none", "explicit", "implicit"})
_MAIL_KINDS = frozenset({"mbox", "eml"})
_UI_MODES = frozenset({"auto", "lineage", "table"})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TDOC_SEED_RE = re.compile(r"^S3-\d{6}$", re.IGNORECASE)
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SERIES_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+-\d{2,4}$")

_MISSING = object()


class ConfigError(ValueError):
    """Raised when a meeting configuration is missing or invalid."""

    def __init__(self, errors: list[str] | tuple[str, ...]) -> None:
        self.errors = tuple(errors)
        detail = "\n".join(f"  - {message}" for message in self.errors)
        super().__init__(f"invalid meeting configuration:\n{detail}")


@dataclass(frozen=True)
class Hours:
    start: str = "09:00"
    end: str = "18:00"


@dataclass(frozen=True)
class MeetingSettings:
    id: str
    title: str
    timezone: str
    days: tuple[str, ...]
    hours: Hours
    tdoc_series_prefix: str


@dataclass(frozen=True)
class SourceSettings:
    kind: str
    protocol: str
    host: str
    port: int | None
    base_path: str
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    password_env: str | None = None
    tls: str = "none"

    def effective_port(self) -> int:
        if self.port is not None:
            return self.port
        return 443 if self.protocol == "https" else 21

    @property
    def endpoint_id(self) -> str:
        return (
            f"{self.protocol}://{self.host}:{self.effective_port()}{self.base_path}"
        )

    def resolve_password(self) -> str | None:
        if self.password is not None:
            return self.password
        if self.password_env is None:
            return None
        value = os.environ.get(self.password_env)
        if value is None:
            raise ConfigError(
                [
                    "source.password_env: environment variable "
                    f"{self.password_env!r} is not set"
                ]
            )
        return value


@dataclass(frozen=True)
class MailSettings:
    kind: str
    path: str | None = None
    eml_dir: str | None = None


@dataclass(frozen=True)
class PathSettings:
    drafts: str = DEFAULT_DRAFTS_PATH
    inbox: str = DEFAULT_INBOX_PATH
    agenda_glob: str = DEFAULT_AGENDA_GLOB
    excel: str = DEFAULT_EXCEL_PATH


@dataclass(frozen=True)
class PollSettings:
    meeting_interval_s: int = 45
    idle_interval_s: int = 600
    mail_interval_s: int = 120
    backoff_max_s: int = 900
    jitter: float = 0.2


@dataclass(frozen=True)
class SyncSettings:
    lazy_drafts: bool = True


@dataclass(frozen=True)
class UiSettings:
    default_mode: str = "auto"


@dataclass(frozen=True)
class MeetingConfig:
    schema_version: int
    meeting: MeetingSettings
    source: SourceSettings
    mail: MailSettings | None
    paths: PathSettings
    poll: PollSettings
    sync: SyncSettings
    tracked_seed: tuple[str, ...]
    ui: UiSettings
    warnings: tuple[str, ...] = ()
    path: Path | None = field(default=None, compare=False, repr=False)


class _Issues:
    def __init__(self, warnings: list[str] | None = None) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = list(warnings or ())

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}" if path else message)

    def warning(self, path: str, message: str) -> None:
        self.warnings.append(f"{path}: {message}" if path else message)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _unknown_keys(
    data: Mapping[str, Any], path: str, allowed: frozenset[str], issues: _Issues
) -> None:
    for key in data:
        if key not in allowed:
            issues.warning(_join(path, str(key)), "unknown key ignored")


def _object(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    required: bool = False,
    allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            issues.error(full, "is required")
        return {}
    if not isinstance(value, dict):
        issues.error(full, "must be an object")
        return {}
    if allowed is not None:
        _unknown_keys(value, full, allowed, issues)
    return value


def _string(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    required: bool = False,
    default: str | None = None,
    allow_empty: bool = False,
    control_safe: bool = False,
) -> str | None:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            issues.error(full, "is required")
        return default
    if not isinstance(value, str):
        issues.error(full, "must be a string")
        return default
    if not allow_empty and not value.strip():
        if required:
            issues.error(full, "must not be empty")
        return default
    if control_safe and _CONTROL_RE.search(value):
        issues.error(full, "must not contain control characters")
        return default
    return value


def _integer(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        issues.error(full, "must be an integer")
        return default
    if minimum is not None and value < minimum:
        issues.error(full, f"must be >= {minimum}")
        return default
    if maximum is not None and value > maximum:
        issues.error(full, f"must be <= {maximum}")
        return default
    return value


def _boolean(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    default: bool,
) -> bool:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        issues.error(full, "must be true or false")
        return default
    return value


def _number(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.error(full, "must be a number")
        return default
    if minimum is not None and value < minimum:
        issues.error(full, f"must be >= {minimum}")
        return default
    if maximum is not None and value > maximum:
        issues.error(full, f"must be <= {maximum}")
        return default
    return float(value)


def _string_list(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    required: bool = False,
) -> list[str]:
    full = _join(path, key)
    value = data.get(key, _MISSING)
    if value is _MISSING or value is None:
        if required:
            issues.error(full, "is required")
        return []
    if not isinstance(value, list):
        issues.error(full, "must be an array of strings")
        return []
    if required and not value:
        issues.error(full, "must not be empty")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.error(f"{full}[{index}]", "must be a non-empty string")
            continue
        result.append(item.strip())
    return result


def _relative_path(
    data: Mapping[str, Any],
    key: str,
    path: str,
    issues: _Issues,
    *,
    default: str,
) -> str:
    value = _string(
        data, key, path, issues, default=default, control_safe=True
    )
    assert value is not None
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or value.startswith("~"):
        issues.error(_join(path, key), "must be relative to the meeting folder")
        return default
    if ".." in pure.parts:
        issues.error(_join(path, key), "must not contain '..'")
        return default
    return value


def _validate_meeting(data: Mapping[str, Any], issues: _Issues) -> MeetingSettings:
    meeting_id = _string(
        data, "id", "meeting", issues, required=True, control_safe=True
    )
    title = _string(
        data, "title", "meeting", issues, required=True, control_safe=True
    )
    timezone = _string(
        data, "timezone", "meeting", issues, required=True, control_safe=True
    )
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            issues.error("meeting.timezone", f"unknown timezone {timezone!r}")

    days = _string_list(data, "days", "meeting", issues, required=True)
    seen_days: set[str] = set()
    for index, value in enumerate(days):
        try:
            date.fromisoformat(value)
        except ValueError:
            issues.error(
                f"meeting.days[{index}]", f"not an ISO date: {value!r}"
            )
        if value in seen_days:
            issues.warning(f"meeting.days[{index}]", "duplicate date")
        seen_days.add(value)

    hours_data = _object(
        data, "hours", "meeting", issues, allowed=_HOURS_KEYS
    )
    start = _string(
        hours_data, "start", "meeting.hours", issues, default="09:00"
    )
    end = _string(hours_data, "end", "meeting.hours", issues, default="18:00")
    assert start is not None and end is not None
    for key, value in (("start", start), ("end", end)):
        if not _TIME_RE.fullmatch(value):
            issues.error(
                f"meeting.hours.{key}", f"must be HH:MM, got {value!r}"
            )
    if (
        _TIME_RE.fullmatch(start)
        and _TIME_RE.fullmatch(end)
        and start >= end
    ):
        issues.error("meeting.hours", "start must be before end")

    prefix = _string(
        data,
        "tdoc_series_prefix",
        "meeting",
        issues,
        required=True,
        control_safe=True,
    )
    if prefix and not _SERIES_PREFIX_RE.fullmatch(prefix):
        issues.error(
            "meeting.tdoc_series_prefix",
            f"must look like 'S3-26', got {prefix!r}",
        )

    return MeetingSettings(
        id=meeting_id or "",
        title=title or "",
        timezone=timezone or "",
        days=tuple(days),
        hours=Hours(start=start, end=end),
        tdoc_series_prefix=prefix or "",
    )


def _validate_source(data: Mapping[str, Any], issues: _Issues) -> SourceSettings:
    kind = _string(
        data, "kind", "source", issues, required=True, control_safe=True
    )
    if kind and kind not in _SOURCE_KINDS:
        issues.error(
            "source.kind",
            "must be one of " + ", ".join(sorted(_SOURCE_KINDS)),
        )

    protocol = _string(data, "protocol", "source", issues, default="ftp")
    assert protocol is not None
    protocol = protocol.casefold()
    if protocol not in _PROTOCOLS:
        issues.error(
            "source.protocol",
            "must be one of " + ", ".join(sorted(_PROTOCOLS)),
        )

    host = _string(
        data, "host", "source", issues, required=True, control_safe=True
    )
    if host and re.search(r"\s", host):
        issues.error("source.host", "must not contain whitespace")

    base_path = _string(
        data, "base_path", "source", issues, required=True, control_safe=True
    )
    if base_path:
        if not base_path.startswith("/"):
            issues.error("source.base_path", "must start with '/'")
        if ".." in PurePosixPath(base_path.replace("\\", "/")).parts:
            issues.error("source.base_path", "must not contain '..'")

    port_raw = data.get("port", _MISSING)
    if port_raw is _MISSING or port_raw is None:
        port: int | None = None
    elif not isinstance(port_raw, int) or isinstance(port_raw, bool):
        issues.error("source.port", "must be an integer")
        port = None
    elif not 1 <= port_raw <= 65535:
        issues.error("source.port", "must be between 1 and 65535")
        port = None
    else:
        port = port_raw

    username = _string(
        data, "username", "source", issues, control_safe=True
    )
    password = _string(
        data,
        "password",
        "source",
        issues,
        allow_empty=True,
        control_safe=False,
    )
    password_env = _string(
        data, "password_env", "source", issues, control_safe=True
    )
    if password is not None and password_env is not None:
        issues.error(
            "source.password_env",
            "use either 'password' or 'password_env', not both",
        )
    if password_env and not _ENV_NAME_RE.fullmatch(password_env):
        issues.error(
            "source.password_env", "must be a valid environment variable name"
        )

    tls = _string(data, "tls", "source", issues, default="none")
    assert tls is not None
    tls = tls.casefold()
    if tls not in _TLS_MODES:
        issues.error(
            "source.tls", "must be one of " + ", ".join(sorted(_TLS_MODES))
        )

    return SourceSettings(
        kind=kind or "",
        protocol=protocol,
        host=host or "",
        port=port,
        base_path=base_path or "",
        username=username,
        password=password,
        password_env=password_env,
        tls=tls,
    )


def _validate_mail(data: Mapping[str, Any], issues: _Issues) -> MailSettings | None:
    value = data.get("mail", _MISSING)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, dict):
        issues.error("mail", "must be an object")
        return None
    _unknown_keys(value, "mail", _MAIL_KEYS, issues)

    kind = _string(value, "kind", "mail", issues, required=True, control_safe=True)
    if kind and kind not in _MAIL_KINDS:
        issues.error(
            "mail.kind", "must be one of " + ", ".join(sorted(_MAIL_KINDS))
        )

    path = _string(value, "path", "mail", issues, control_safe=True)
    eml_dir = _string(value, "eml_dir", "mail", issues, control_safe=True)

    if kind == "mbox":
        if not path:
            issues.error("mail.path", "is required when kind is 'mbox'")
        if eml_dir:
            issues.warning("mail.eml_dir", "ignored when kind is 'mbox'")
    elif kind == "eml":
        if not eml_dir:
            issues.error("mail.eml_dir", "is required when kind is 'eml'")
        if path:
            issues.warning("mail.path", "ignored when kind is 'eml'")

    return MailSettings(kind=kind or "", path=path, eml_dir=eml_dir)


def _validate_paths(data: Mapping[str, Any], issues: _Issues) -> PathSettings:
    value = _object(data, "paths", "", issues, allowed=_PATHS_KEYS)
    return PathSettings(
        drafts=_relative_path(
            value, "drafts", "paths", issues, default=DEFAULT_DRAFTS_PATH
        ),
        inbox=_relative_path(
            value, "inbox", "paths", issues, default=DEFAULT_INBOX_PATH
        ),
        agenda_glob=_relative_path(
            value, "agenda_glob", "paths", issues, default=DEFAULT_AGENDA_GLOB
        ),
        excel=_relative_path(
            value, "excel", "paths", issues, default=DEFAULT_EXCEL_PATH
        ),
    )


def _validate_poll(data: Mapping[str, Any], issues: _Issues) -> PollSettings:
    value = _object(data, "poll", "", issues, allowed=_POLL_KEYS)
    return PollSettings(
        meeting_interval_s=_integer(
            value, "meeting_interval_s", "poll", issues, default=45, minimum=1
        ),
        idle_interval_s=_integer(
            value, "idle_interval_s", "poll", issues, default=600, minimum=1
        ),
        mail_interval_s=_integer(
            value, "mail_interval_s", "poll", issues, default=120, minimum=1
        ),
        backoff_max_s=_integer(
            value, "backoff_max_s", "poll", issues, default=900, minimum=1
        ),
        jitter=_number(
            value, "jitter", "poll", issues, default=0.2, minimum=0, maximum=1
        ),
    )


def _validate_tracked_seed(
    data: Mapping[str, Any], issues: _Issues
) -> tuple[str, ...]:
    values = _string_list(data, "tracked_seed", "", issues)
    result: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not _TDOC_SEED_RE.fullmatch(value):
            issues.error(
                f"tracked_seed[{index}]",
                f"must be a canonical TDoc like 'S3-264481', got {value!r}",
            )
            continue
        canonical = f"S3-{value.split('-', 1)[1]}"
        if canonical in seen:
            issues.warning(f"tracked_seed[{index}]", "duplicate TDoc ignored")
            continue
        seen.add(canonical)
        result.append(canonical)
    return tuple(result)


def _validate_sync(
    data: Mapping[str, Any], issues: _Issues
) -> SyncSettings:
    value = _object(data, "sync", "", issues, allowed=_SYNC_KEYS)
    return SyncSettings(
        lazy_drafts=_boolean(
            value, "lazy_drafts", "sync", issues, default=True
        )
    )


def _validate_ui(data: Mapping[str, Any], issues: _Issues) -> UiSettings:
    value = _object(data, "ui", "", issues, allowed=_UI_KEYS)
    mode = _string(value, "default_mode", "ui", issues, default="auto")
    assert mode is not None
    if mode not in _UI_MODES:
        issues.error(
            "ui.default_mode",
            "must be one of " + ", ".join(sorted(_UI_MODES)),
        )
    return UiSettings(default_mode=mode)


def _validate(
    data: Mapping[str, Any], extra_warnings: list[str] | None = None
) -> MeetingConfig:
    issues = _Issues(extra_warnings)

    version = data.get("schema_version", _MISSING)
    if version is _MISSING:
        issues.error("schema_version", "is required")
    elif not isinstance(version, int) or isinstance(version, bool):
        issues.error("schema_version", "must be an integer")
    elif version != SCHEMA_VERSION:
        issues.error(
            "schema_version",
            f"unsupported version {version}; expected {SCHEMA_VERSION}",
        )

    _unknown_keys(data, "", _ROOT_KEYS, issues)

    meeting_data = _object(
        data, "meeting", "", issues, required=True, allowed=_MEETING_KEYS
    )
    source_data = _object(
        data, "source", "", issues, required=True, allowed=_SOURCE_KEYS
    )

    config = MeetingConfig(
        schema_version=version if isinstance(version, int) else 0,
        meeting=_validate_meeting(meeting_data, issues),
        source=_validate_source(source_data, issues),
        mail=_validate_mail(data, issues),
        paths=_validate_paths(data, issues),
        poll=_validate_poll(data, issues),
        sync=_validate_sync(data, issues),
        tracked_seed=_validate_tracked_seed(data, issues),
        ui=_validate_ui(data, issues),
        warnings=tuple(issues.warnings),
    )

    if issues.errors:
        raise ConfigError(issues.errors)
    return config


def validate_config(data: Mapping[str, Any]) -> MeetingConfig:
    """Validate a parsed configuration object and return typed settings."""
    if not isinstance(data, Mapping):
        raise ConfigError(["configuration root must be an object"])
    return _validate(data)


def _literal_password_present(data: Mapping[str, Any]) -> bool:
    source = data.get("source")
    return isinstance(source, dict) and source.get("password") is not None


def load_config(path: str | Path) -> MeetingConfig:
    """Read and validate ``meeting.json`` from ``path``."""
    config_path = Path(path)
    try:
        raw = config_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError([f"{config_path}: file not found"]) from None
    except UnicodeDecodeError:
        raise ConfigError([f"{config_path}: file is not valid UTF-8"]) from None
    except OSError as exc:
        raise ConfigError([f"{config_path}: cannot read file: {exc}"]) from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            [
                f"{config_path}: invalid JSON at line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}"
            ]
        ) from None

    if not isinstance(data, dict):
        raise ConfigError([f"{config_path}: configuration root must be an object"])

    extra_warnings: list[str] = []
    if _literal_password_present(data):
        mode = stat.S_IMODE(config_path.stat().st_mode)
        if mode & 0o077:
            extra_warnings.append(
                f"{config_path}: contains a literal password but mode is "
                f"{mode:04o}; restrict it with 'chmod 600'"
            )

    config = _validate(data, extra_warnings)
    return MeetingConfig(
        schema_version=config.schema_version,
        meeting=config.meeting,
        source=config.source,
        mail=config.mail,
        paths=config.paths,
        poll=config.poll,
        sync=config.sync,
        tracked_seed=config.tracked_seed,
        ui=config.ui,
        warnings=config.warnings,
        path=config_path,
    )
