"""Local FastAPI application for a single meeting folder."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from mirko import __version__
from mirko.meeting_folder import MeetingFolder
from mirko.preflight import check_lftp

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class HoursResponse(BaseModel):
    start: str
    end: str


class MeetingResponse(BaseModel):
    schema_version: int
    id: str
    title: str
    timezone: str
    days: list[str]
    hours: HoursResponse
    tdoc_series_prefix: str
    source_kind: str
    endpoint: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    meeting_id: str
    schema_version: int
    database: Literal["ok"]


def _as_folder(meeting: MeetingFolder | str | Path) -> MeetingFolder:
    if isinstance(meeting, MeetingFolder):
        return meeting
    return MeetingFolder.open(meeting)


def create_app(meeting: MeetingFolder | str | Path) -> FastAPI:
    folder = _as_folder(meeting)
    app = FastAPI(title="Mirko", version=__version__)
    app.state.folder = folder

    @app.get("/api/meeting", response_model=MeetingResponse)
    def get_meeting() -> MeetingResponse:
        config = folder.config
        return MeetingResponse(
            schema_version=config.schema_version,
            id=config.meeting.id,
            title=config.meeting.title,
            timezone=config.meeting.timezone,
            days=list(config.meeting.days),
            hours=HoursResponse(
                start=config.meeting.hours.start,
                end=config.meeting.hours.end,
            ),
            tdoc_series_prefix=config.meeting.tdoc_series_prefix,
            source_kind=config.source.kind,
            endpoint=config.source.endpoint_id,
        )

    @app.get("/api/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        connection = folder.connect()
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return HealthResponse(
            status="ok",
            meeting_id=folder.config.meeting.id,
            schema_version=folder.config.schema_version,
            database="ok",
        )

    return app


def run_server(
    meeting: MeetingFolder | str | Path, *, port: int = DEFAULT_PORT
) -> None:
    check_lftp()
    app = create_app(meeting)

    import uvicorn

    uvicorn.run(app, host=LOOPBACK_HOST, port=port)
