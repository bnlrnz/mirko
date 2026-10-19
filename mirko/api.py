"""Local FastAPI application for a single meeting folder."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mirko import __version__
from mirko import repository
from mirko.ftp import FtpClient
from mirko.meeting_folder import MeetingFolder
from mirko.preflight import check_lftp
from mirko.worker import SyncWorker

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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


class TdocSummary(BaseModel):
    tdoc_number: str
    agenda_item: str | None = None
    topic: str | None = None
    title: str | None = None
    source: str | None = None
    type: str | None = None
    for_action: str | None = None
    release: str | None = None
    wi_code: str | None = None
    avail: bool | None = None
    treated: bool | None = None
    treated_note: str | None = None
    decision: str | None = None
    state_source: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    is_tracked: bool = False
    is_provisional: bool = False
    notes_count: int = 0
    artifact_count: int = 0
    mention_count: int = 0
    has_conflict: bool = False


class ArtifactSummary(BaseModel):
    id: int
    kind: str
    logical_path: str
    filename: str | None = None
    status: str
    is_ephemeral: bool
    blob_hash: str | None = None
    remote_size: int | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class NoteSummary(BaseModel):
    id: int
    target_kind: str
    target_ref: str
    body: str
    position_tag: str | None = None
    author: str | None = None
    source: str
    created_at: str
    updated_at: str


class MailSummary(BaseModel):
    id: int
    message_id: str
    thread_id: int | None = None
    subject: str | None = None
    from_addr: str | None = None
    to_addrs: str | None = None
    cc_addrs: str | None = None
    date_utc: str | None = None
    agenda_item: str | None = None
    meeting_id: str | None = None
    ingested_at: str
    inference: Any = None


class AssertionSummary(BaseModel):
    id: int
    predicate: str
    object_kind: str | None = None
    object_ref: str | None = None
    value: str | None = None
    source: str
    confidence: float
    verified: bool
    active: bool
    muted: bool
    superseded_by: int | None = None
    observed_at: str
    detail: Any = None


class TdocDetail(TdocSummary):
    raw_meta: Any = None
    artifacts: list[ArtifactSummary] = []
    notes: list[NoteSummary] = []
    emails: list[MailSummary] = []
    assertions: list[AssertionSummary] = []


class TimelineEvent(BaseModel):
    kind: str
    occurred_at: str | None = None
    title: str | None = None
    detail: str | None = None
    source: str | None = None
    artifact_id: int | None = None
    email_id: int | None = None
    ephemeral: bool = False
    sequence: int = 0


class LineageNode(BaseModel):
    tdoc_number: str
    title: str | None = None
    decision: str | None = None
    state_source: str | None = None
    agenda_item: str | None = None
    type: str | None = None
    is_tracked: bool = False
    is_provisional: bool = False
    first_seen_at: str | None = None


class LineageEdge(BaseModel):
    source: str
    target: str
    kind: str
    confidence: float
    verified: bool
    source_ref: str | None = None


class LineageResponse(BaseModel):
    nodes: list[LineageNode] = []
    edges: list[LineageEdge] = []


class DiscoveryItem(BaseModel):
    kind: str
    ref: str
    title: str
    detail: str | None = None
    tdocs: list[str] = []
    agenda_item: str | None = None
    confidence: float = 0.0
    created_at: str | None = None


class TrackResponse(BaseModel):
    tdoc_number: str
    is_tracked: bool


class NoteRequest(BaseModel):
    target_kind: str
    target_ref: str
    body: str
    position_tag: str | None = None


class NoteResponse(BaseModel):
    id: int
    target_kind: str
    target_ref: str
    body: str
    position_tag: str | None = None
    author: str | None = None
    source: str
    created_at: str
    updated_at: str


class SyncResponse(BaseModel):
    status: str
    fetched: int
    agenda: str | None = None
    drafts: dict[str, Any] | None = None
    mail: dict[str, Any] | None = None
    errors: list[str] = []


class SyncStatusResponse(BaseModel):
    endpoint: str
    health: str
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    next_due_at: str | None = None
    last_error: str | None = None
    interval_s: int
    stale: bool
    refresh: dict[str, str | None] = {}
    counts: dict[str, int] = {}
    server_time: str


def _as_folder(meeting: MeetingFolder | str | Path) -> MeetingFolder:
    if isinstance(meeting, MeetingFolder):
        return meeting
    return MeetingFolder.open(meeting)


def create_app(
    meeting: MeetingFolder | str | Path,
    *,
    ftp_client: FtpClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    folder = _as_folder(meeting)
    app = FastAPI(title="Mirko", version=__version__)
    app.state.folder = folder
    app.state.ftp_client = ftp_client
    app.state.clock = clock

    def with_connection(call):
        connection = folder.connect()
        try:
            return call(connection)
        finally:
            connection.close()

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

    @app.get("/api/tdocs", response_model=list[TdocSummary])
    def get_tdocs(
        agenda: str | None = None,
        type: str | None = None,
        release: str | None = None,
        wi: str | None = None,
        source: str | None = None,
        state: str | None = None,
        tracked: bool | None = None,
    ) -> list[dict]:
        return with_connection(
            lambda connection: repository.list_tdocs(
                connection,
                agenda=agenda,
                type=type,
                release=release,
                wi=wi,
                source=source,
                state=state,
                tracked=tracked,
            )
        )

    @app.get("/api/tdocs/{tdoc_number}", response_model=TdocDetail)
    def get_tdoc(tdoc_number: str) -> dict:
        result = with_connection(
            lambda connection: repository.get_tdoc(connection, tdoc_number)
        )
        if result is None:
            raise HTTPException(status_code=404, detail="tdoc not found")
        return result

    @app.get(
        "/api/tdocs/{tdoc_number}/timeline",
        response_model=list[TimelineEvent],
    )
    def get_timeline(tdoc_number: str) -> list[dict]:
        def query(connection):
            if repository.get_tdoc(connection, tdoc_number) is None:
                return None
            return repository.timeline(connection, tdoc_number)

        result = with_connection(query)
        if result is None:
            raise HTTPException(status_code=404, detail="tdoc not found")
        return result

    @app.get("/api/lineage", response_model=LineageResponse)
    def get_lineage(tracked: bool = False) -> dict:
        return with_connection(
            lambda connection: repository.lineage(
                connection, tracked_only=tracked
            )
        )

    @app.get("/api/mail", response_model=list[MailSummary])
    def get_mail(
        tdoc: str | None = None,
        agenda: str | None = None,
        q: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict]:
        return with_connection(
            lambda connection: repository.list_mail(
                connection, tdoc=tdoc, agenda=agenda, query=q, limit=limit
            )
        )

    @app.get("/api/discovery", response_model=list[DiscoveryItem])
    def get_discovery() -> list[dict]:
        return with_connection(repository.discovery)

    @app.get("/api/sync/status", response_model=SyncStatusResponse)
    def get_sync_status() -> dict:
        return with_connection(
            lambda connection: repository.sync_status(
                connection,
                endpoint_id=folder.config.source.endpoint_id,
                poll_interval_s=folder.config.poll.meeting_interval_s,
            )
        )

    @app.post("/api/sync", response_model=SyncResponse)
    def post_sync() -> dict:
        kwargs: dict[str, Any] = {}
        if app.state.ftp_client is not None:
            kwargs["client"] = app.state.ftp_client
        if app.state.clock is not None:
            kwargs["clock"] = app.state.clock
        return SyncWorker(folder, **kwargs).run().as_dict()

    @app.post(
        "/api/tdocs/{tdoc_number}/track", response_model=TrackResponse
    )
    def track_tdoc(tdoc_number: str) -> TrackResponse:
        result = with_connection(
            lambda connection: repository.set_tracked(
                connection, tdoc_number, True
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="tdoc not found")
        return TrackResponse(tdoc_number=tdoc_number, is_tracked=result)

    @app.delete(
        "/api/tdocs/{tdoc_number}/track", response_model=TrackResponse
    )
    def untrack_tdoc(tdoc_number: str) -> TrackResponse:
        result = with_connection(
            lambda connection: repository.set_tracked(
                connection, tdoc_number, False
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="tdoc not found")
        return TrackResponse(tdoc_number=tdoc_number, is_tracked=result)

    @app.post("/api/notes", response_model=NoteResponse, status_code=201)
    def post_note(payload: NoteRequest) -> dict:
        if not payload.body.strip():
            raise HTTPException(status_code=422, detail="note body is empty")
        if payload.target_kind == "tdoc":
            exists = with_connection(
                lambda connection: repository.get_tdoc(
                    connection, payload.target_ref
                )
            )
            if exists is None:
                raise HTTPException(status_code=404, detail="tdoc not found")
        return with_connection(
            lambda connection: repository.add_note(
                connection,
                target_kind=payload.target_kind,
                target_ref=payload.target_ref,
                body=payload.body,
                position_tag=payload.position_tag,
            )
        )

    @app.get("/api/events", include_in_schema=False)
    def get_events() -> Response:
        return Response(
            content="event: ready\ndata: {}\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    if not (FRONTEND_DIST / "index.html").is_file():
        return
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / path).resolve()
        try:
            inside = candidate.is_relative_to(FRONTEND_DIST.resolve())
        except AttributeError:  # pragma: no cover - Python < 3.9
            inside = str(candidate).startswith(str(FRONTEND_DIST.resolve()))
        if path and inside and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


def run_server(
    meeting: MeetingFolder | str | Path, *, port: int = DEFAULT_PORT
) -> None:
    check_lftp()
    app = create_app(meeting)

    import uvicorn

    uvicorn.run(app, host=LOOPBACK_HOST, port=port)
