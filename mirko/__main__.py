"""Command-line entry point for the local Mirko server."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mirko.api import DEFAULT_PORT, run_server
from mirko.config import ConfigError
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.meeting_folder import MeetingFolder, MeetingFolderError
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
    parser.add_argument(
        "--import-excel",
        type=Path,
        metavar="PATH",
        help="ingest a local allocation workbook and exit",
    )
    args = parser.parse_args(argv)

    if not args.meeting:
        parser.error("a meeting folder is required")

    if args.import_excel is not None:
        return _import_excel(args.meeting, args.import_excel)

    try:
        run_server(args.meeting, port=args.port)
    except (ConfigError, MeetingFolderError, PreflightError) as exc:
        print(f"mirko: {exc}", file=sys.stderr)
        return 2
    return 0


def _import_excel(meeting: str, workbook: Path) -> int:
    try:
        folder = MeetingFolder.open(meeting)
        result = AgendaIngestor(folder).ingest_excel(
            workbook.read_bytes(), path=workbook.name
        )
    except (ConfigError, MeetingFolderError, OSError, ValueError) as exc:
        print(f"mirko: {exc}", file=sys.stderr)
        return 2
    print(
        f"{result.status}: {result.row_count} TDocs, "
        f"{result.edge_count} lineage edges"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
