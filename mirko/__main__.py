"""Command-line entry point for the local Mirko server."""

from __future__ import annotations

import argparse
import os
import sys

from mirko.api import DEFAULT_PORT, run_server
from mirko.config import ConfigError
from mirko.meeting_folder import MeetingFolderError
from mirko.preflight import PreflightError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mirko")
    parser.add_argument(
        "meeting",
        nargs="?",
        default=os.environ.get("MIRKO_MEETING"),
        help="meeting folder (defaults to $MIRKO_MEETING)",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    if not args.meeting:
        parser.error("a meeting folder is required")

    try:
        run_server(args.meeting, port=args.port)
    except (ConfigError, MeetingFolderError, PreflightError) as exc:
        print(f"mirko: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
