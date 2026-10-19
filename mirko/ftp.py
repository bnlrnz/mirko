"""FTP access through ``lftp`` plus an in-memory fake for tests."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Protocol
from urllib.parse import quote

from mirko.config import SourceSettings

logger = logging.getLogger(__name__)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "mär": 3,
    "mrz": 3,
    "apr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "set": 9,
    "oct": 10,
    "okt": 10,
    "ott": 10,
    "nov": 11,
    "dec": 12,
    "dez": 12,
    "dic": 12,
    "ene": 1,
    "gen": 1,
    "abr": 4,
    "ago": 8,
}
_MONTH_TOKEN = r"[^\W\d_]{3,4}\.?"
_DATE_PATTERN = (
    r"(?:\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?"
    rf"|{_MONTH_TOKEN}\s+\d{{1,2}}\s+(?:\d{{2}}:\d{{2}}|\d{{4}}))"
)
_LS_RE = re.compile(
    rf"^(?P<perms>[bcdlps-][rwxStTs-]{{9}})\s+"
    r"\d+\s+"
    r"\S+\s+\S+\s+"
    r"(?P<size>\d+)\s+"
    rf"(?P<date>{_DATE_PATTERN})\s+"
    r"(?P<name>.+)$"
)
# Servers (e.g. localized IIS) may omit permissions/owner columns.
_SIZE_DATE_NAME_RE = re.compile(
    rf"^\s*(?P<size>\d+)\s+(?P<date>{_DATE_PATTERN})\s+(?P<name>.+?)\s*$"
)
_DATE_NAME_RE = re.compile(
    rf"^\s*(?P<date>{_DATE_PATTERN})\s+(?P<name>.+?)\s*$"
)


class FtpError(RuntimeError):
    """Raised when an FTP operation fails or a path is unsafe."""


class FtpClient(Protocol):
    def list(self, path: str) -> list[RemoteEntry]: ...

    def fetch(self, path: str, dest: Path) -> None: ...


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    size: int | None
    mtime: str | None
    is_dir: bool = False
    is_symlink: bool = False
    raw: str = ""


def normalize_remote_path(path: str) -> str:
    if _CONTROL_RE.search(path):
        raise FtpError(f"unsafe remote path: {path!r}")
    text = path.replace("\\", "/")
    if text.startswith("/"):
        raise FtpError(f"unsafe remote path: {path!r}")
    text = text.strip("/")
    if not text or text == ".":
        return ""
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise FtpError(f"unsafe remote path: {path!r}")
    return pure.as_posix()


def is_safe_remote_name(name: str) -> bool:
    return bool(
        name
        and name not in {".", ".."}
        and not name.startswith("-")
        and "/" not in name
        and "\\" not in name
        and not _CONTROL_RE.search(name)
    )


def join_remote_path(directory: str, name: str) -> str:
    base = normalize_remote_path(directory)
    if not is_safe_remote_name(name):
        raise FtpError(f"unsafe remote filename: {name!r}")
    return f"{base}/{name}" if base else name


def _quote_lftp(value: str) -> str:
    if _CONTROL_RE.search(value):
        raise FtpError("lftp arguments must not contain control characters")
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def _parse_mtime(value: str, now: datetime) -> str | None:
    iso = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?", value
    )
    if iso:
        year, month, day, hour, minute, second = iso.groups()
        return (
            f"{year}-{month}-{day}T{hour}:{minute}:{second or '00'}"
        )

    classic = re.fullmatch(
        rf"({_MONTH_TOKEN})\s+(\d{{1,2}})\s+(\d{{2}}):(\d{{2}})", value
    )
    if classic:
        month_name, day, hour, minute = classic.groups()
        month = _MONTHS.get(month_name.rstrip(".").lower())
        if month is None:
            return None
        year = now.year
        try:
            candidate = datetime(
                year,
                month,
                int(day),
                int(hour),
                int(minute),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
        if candidate > now + timedelta(days=1):
            year -= 1
        return f"{year:04d}-{month:02d}-{int(day):02d}T{hour}:{minute}:00"

    old = re.fullmatch(
        rf"({_MONTH_TOKEN})\s+(\d{{1,2}})\s+(\d{{4}})", value
    )
    if old:
        month_name, day, year = old.groups()
        month = _MONTHS.get(month_name.rstrip(".").lower())
        if month is None:
            return None
        return f"{int(year):04d}-{month:02d}-{int(day):02d}T00:00:00"
    return None


def parse_ls_listing(
    text: str, *, now: datetime | None = None
) -> tuple[list[RemoteEntry], list[str]]:
    reference = now or datetime.now(timezone.utc)
    entries: list[RemoteEntry] = []
    unparsed: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip() or line.startswith("total "):
            continue
        match = _LS_RE.match(line)
        if match is not None:
            name = match.group("name").strip()
            size: int | None = int(match.group("size"))
            date = match.group("date")
            is_dir = match.group("perms").startswith("d")
            is_symlink = match.group("perms").startswith("l")
        else:
            fallback = _SIZE_DATE_NAME_RE.match(line)
            if fallback is not None:
                size = int(fallback.group("size"))
                date = fallback.group("date")
            else:
                fallback = _DATE_NAME_RE.match(line)
                if fallback is None:
                    unparsed.append(line)
                    continue
                size = None
                date = fallback.group("date")
            name = fallback.group("name").strip()
            is_symlink = False
            is_dir = name.endswith("/")

        if is_symlink:
            name = name.split(" -> ", 1)[0].strip()
        if name.endswith("/"):
            name = name.rstrip("/")
        if not name or _CONTROL_RE.search(name):
            unparsed.append(line)
            continue

        entries.append(
            RemoteEntry(
                name=name,
                size=size,
                mtime=_parse_mtime(date, reference),
                is_dir=is_dir,
                is_symlink=is_symlink,
                raw=line,
            )
        )

    return entries, unparsed


class LftpFtpClient:
    def __init__(
        self,
        source: SourceSettings,
        *,
        executable: str = "lftp",
        timeout: float = 60.0,
    ) -> None:
        self.source = source
        self.executable = executable
        self.timeout = timeout
        self._password = source.resolve_password()

    def _url(self) -> str:
        host = self.source.host.strip()
        if "://" in host:
            return host

        scheme = self.source.protocol
        netloc = host
        if self.source.port is not None:
            netloc = f"{netloc}:{self.source.port}"
        if self.source.username:
            password = self._password
            if password is None and self.source.username.casefold() == "anonymous":
                password = "anonymous"
            credentials = quote(self.source.username, safe="")
            if password is not None:
                credentials += ":" + quote(password, safe="")
            netloc = f"{credentials}@{netloc}"
        return f"{scheme}://{netloc}"

    def _open_commands(self) -> list[str]:
        commands: list[str] = []
        if self.source.protocol == "ftps" or self.source.tls != "none":
            commands.append("set ftp:ssl-force true")
            commands.append("set ftp:ssl-protect-data true")
        commands.append(f"open {_quote_lftp(self._url())}")
        commands.append(f"cd {_quote_lftp(self.source.base_path)}")
        return commands

    def _script(self, commands: Iterable[str]) -> str:
        lines = [
            "set cmd:fail-exit yes",
            f"set net:timeout {max(1, int(self.timeout))}",
            "set net:max-retries 1",
            *self._open_commands(),
            *commands,
            "bye",
        ]
        return "\n".join(lines) + "\n"

    def _run(self, script: str) -> str:
        environment = dict(os.environ)
        environment.setdefault("LC_ALL", "C")
        environment.setdefault("LANG", "C")
        try:
            result = subprocess.run(
                [self.executable],
                input=script,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FtpError(f"lftp failed to run: {exc}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            detail = self._redact(detail)
            suffix = f": {detail}" if detail else ""
            raise FtpError(
                f"lftp exited with status {result.returncode}{suffix}"
            )
        return result.stdout

    def _redact(self, text: str) -> str:
        if self._password:
            return text.replace(self._password, "***")
        return text

    def list(self, path: str) -> list[RemoteEntry]:
        relative = normalize_remote_path(path)
        target = f" {_quote_lftp(relative)}" if relative else ""
        script = self._script([f"cls -l{target}"])
        entries, unparsed = parse_ls_listing(self._run(script))
        for line in unparsed[:5]:
            logger.warning("unparsed lftp listing line: %s", line)

        safe: list[RemoteEntry] = []
        for entry in entries:
            name = entry.name
            if relative:
                prefix = relative + "/"
                if name == relative:
                    continue
                if name.startswith(prefix):
                    name = name[len(prefix) :]
            if not name:
                continue
            if not is_safe_remote_name(name):
                logger.warning("unsafe remote filename skipped: %r", name)
                continue
            safe.append(entry if name == entry.name else replace(entry, name=name))
        return safe

    def fetch(self, path: str, dest: Path) -> None:
        relative = normalize_remote_path(path)
        if not relative:
            raise FtpError("cannot fetch an empty remote path")
        script = self._script(
            [
                "set xfer:clobber on",
                f"get {_quote_lftp(relative)} "
                f"-o {_quote_lftp(str(Path(dest)))}",
            ]
        )
        self._run(script)


@dataclass(frozen=True)
class FakeRemoteFile:
    content: bytes
    mtime: str = "2026-10-16T14:37:00"


class FakeFtpClient:
    def __init__(
        self, files: Mapping[str, bytes | FakeRemoteFile] | None = None
    ) -> None:
        self._files: dict[str, FakeRemoteFile] = {}
        self.list_calls: list[str] = []
        self.fetch_calls: list[str] = []
        self.fail_list: set[str] = set()
        self.fail_fetch: set[str] = set()
        for path, value in (files or {}).items():
            self.add(path, value)

    @staticmethod
    def _normalize(path: str) -> str:
        return normalize_remote_path(path)

    def add(
        self,
        path: str,
        content: bytes | FakeRemoteFile,
        *,
        mtime: str | None = None,
    ) -> None:
        normalized = self._normalize(path)
        if isinstance(content, FakeRemoteFile):
            file = content
        else:
            file = FakeRemoteFile(content, mtime or "2026-10-16T14:37:00")
        self._files[normalized] = file

    def remove(self, path: str) -> None:
        self._files.pop(self._normalize(path), None)

    def list(self, path: str) -> list[RemoteEntry]:
        directory = self._normalize(path)
        self.list_calls.append(directory)
        if directory in self.fail_list:
            raise FtpError(f"fake listing failure: {directory}")
        entries: list[RemoteEntry] = []
        for remote_path, file in sorted(self._files.items()):
            parent, _, name = remote_path.rpartition("/")
            if parent == directory:
                entries.append(
                    RemoteEntry(
                        name=name,
                        size=len(file.content),
                        mtime=file.mtime,
                    )
                )
        return entries

    def fetch(self, path: str, dest: Path) -> None:
        remote_path = self._normalize(path)
        self.fetch_calls.append(remote_path)
        if remote_path in self.fail_fetch:
            raise FtpError(f"fake fetch failure: {remote_path}")
        try:
            file = self._files[remote_path]
        except KeyError:
            raise FtpError(f"fake file not found: {remote_path}") from None
        Path(dest).write_bytes(file.content)
