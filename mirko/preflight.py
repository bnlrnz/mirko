"""Startup checks for required external tools."""

from __future__ import annotations

import os
import shutil
import subprocess


class PreflightError(RuntimeError):
    """Raised when a required runtime dependency is unavailable."""


MISSING_LFTP_MESSAGE = (
    "lftp is required but was not found on PATH; enter the Nix dev shell "
    "with 'nix develop' or install lftp"
)


def find_lftp() -> str | None:
    override = os.environ.get("MIRKO_LFTP")
    if override:
        return override
    return shutil.which("lftp")


def check_lftp(executable: str | None = None) -> str:
    path = executable or find_lftp()
    if not path:
        raise PreflightError(MISSING_LFTP_MESSAGE)
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"lftp could not be executed: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        raise PreflightError(f"lftp failed its version check{suffix}")
    return path
