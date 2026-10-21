"""Local FastAPI application for a single meeting folder."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mirko import __version__
from mirko import repository
from mirko.config import ConfigError
from mirko.export import export_markdown, finalize, render_markdown
from mirko.ftp import FtpClient, LftpFtpClient
from mirko.ingest.agenda_ingest import AgendaIngestor
from mirko.meeting_folder import MeetingFolder
from mirko.preflight import check_lftp
from mirko.scheduler import SyncScheduler, current_interval_s
from mirko.sync import Syncer
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
    bar_color: str


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
    remote_mtime: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None


class NoteSummary(BaseModel):
    id: int
    target_kind: str
    target_ref: str
    body: str
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
    node_status: str | None = None
    is_hidden: bool = False
    artifacts: list[ArtifactSummary] = []
    notes: list[NoteSummary] = []
    emails: list[MailSummary] = []
    assertions: list[AssertionSummary] = []


class DraftDetail(ArtifactSummary):
    tdoc_number: str
    title: str
    parent_title: str | None = None
    agenda_item: str | None = None
    node_status: str | None = None
    notes: list[NoteSummary] = []


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
    source: str | None = None
    is_tracked: bool = False
    is_provisional: bool = False
    first_seen_at: str | None = None
    notes_count: int = 0
    node_status: str | None = None
    is_hidden: bool = False
    node_kind: str = "tdoc"
    attached_to: str | None = None
    artifact_id: int | None = None
    logical_path: str | None = None
    status: str | None = None
    remote_mtime: str | None = None


class LineageEdge(BaseModel):
    source: str
    target: str
    kind: str
    confidence: float
    verified: bool
    source_ref: str | None = None
    active: bool = True
    muted: bool = False


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


class UserActionItem(BaseModel):
    id: int
    action: str
    target_kind: str | None = None
    target_ref: str | None = None
    detail: str | None = None
    created_at: str | None = None


class NotificationItem(BaseModel):
    kind: str
    ref: str
    title: str
    detail: str | None = None
    tdocs: list[str] = []
    tdoc_titles: dict[str, str] = {}
    agenda_item: str | None = None
    created_at: str | None = None
    action: Literal["track"] | None = None
    action_ref: str | None = None


class TrackResponse(BaseModel):
    tdoc_number: str
    is_tracked: bool


class NoteRequest(BaseModel):
    target_kind: str
    target_ref: str
    body: str


class NoteResponse(BaseModel):
    id: int
    target_kind: str
    target_ref: str
    body: str
    author: str | None = None
    source: str
    created_at: str
    updated_at: str


class NodeStatusRequest(BaseModel):
    target_kind: Literal["tdoc", "draft"]
    target_ref: str
    status: Literal["Support", "Object", "Clarify"] | None = None


class NodeStatusResponse(BaseModel):
    target_kind: str
    target_ref: str
    status: str | None = None


class NodeHiddenRequest(BaseModel):
    target_kind: Literal["tdoc", "draft"]
    target_ref: str
    hidden: bool


class NodeHiddenResponse(BaseModel):
    target_kind: str
    target_ref: str
    hidden: bool


class AssertionResponse(BaseModel):
    id: int
    subject_kind: str
    subject_ref: str
    predicate: str
    object_kind: str | None = None
    object_ref: str | None = None
    value: str | None = None
    source: str
    source_ref: str | None = None
    confidence: float
    verified: bool
    active: bool
    muted: bool
    superseded_by: int | None = None
    observed_at: str
    detail: Any = None


class ConflictResponse(BaseModel):
    id: int
    predicate: str
    subject_ref: str
    status: str
    resolution: str | None = None
    created_at: str
    resolved_at: str | None = None
    assertions: list[AssertionResponse] = []


class AssertionRequest(BaseModel):
    subject_kind: str = "tdoc"
    subject_ref: str
    predicate: str
    object_kind: str | None = None
    object_ref: str | None = None
    value: str | None = None
    confidence: float = 0.5
    detail: str | None = None


class AssertionPatch(BaseModel):
    active: bool | None = None
    muted: bool | None = None


class ConflictResolveRequest(BaseModel):
    resolution: Literal["accept_html", "keep_mine", "repair"]
    note: str | None = None


class NotePatch(BaseModel):
    body: str | None = None


class FinalizeResponse(BaseModel):
    status: str
    export_path: str
    mirror_links: int
    finalized_at: str


class SyncResponse(BaseModel):
    status: str
    fetched: int
    deferred: int = 0
    agenda: str | None = None
    drafts: dict[str, Any] | None = None
    mail: dict[str, Any] | None = None
    errors: list[str] = []


class SettingsSource(BaseModel):
    kind: str
    protocol: str
    host: str
    port: int | None = None
    base_path: str
    username: str | None = None
    password_set: bool = False
    password_env: str | None = None
    tls: str


class SettingsMail(BaseModel):
    kind: Literal["mbox", "eml"]
    path: str | None = None
    eml_dir: str | None = None


class SettingsResponse(BaseModel):
    source: SettingsSource
    mail: SettingsMail | None = None
    lazy_drafts: bool
    excel: str
    auto_sync: bool
    meeting_interval_s: int
    idle_interval_s: int
    bar_color: str


class SettingsUpdate(BaseModel):
    kind: str
    protocol: str
    host: str
    port: int | None = None
    base_path: str
    username: str | None = None
    password: str | None = None
    clear_password: bool = False
    tls: str = "none"
    mail: SettingsMail | None = None
    lazy_drafts: bool = True
    auto_sync: bool | None = None
    meeting_interval_s: int | None = None
    idle_interval_s: int | None = None
    bar_color: str | None = None


class ExcelImportResponse(BaseModel):
    status: str
    path: str
    row_count: int
    edge_count: int
    issue_count: int


class FetchResponse(BaseModel):
    tdoc_number: str
    fetched: int
    artifacts: list[str] = []
    failures: list[str] = []


class SyncStatusResponse(BaseModel):
    endpoint: str
    health: str
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    next_due_at: str | None = None
    last_error: str | None = None
    interval_s: int
    mode: str
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
    auto_sync: bool | None = None,
) -> FastAPI:
    folder = _as_folder(meeting)
    initial_auto_sync = (
        folder.config.poll.auto_sync if auto_sync is None else auto_sync
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started = True
        if initial_auto_sync:
            start_scheduler(app)
        try:
            yield
        finally:
            app.state.started = False
            stop_scheduler(app)

    app = FastAPI(title="Mirko", version=__version__, lifespan=lifespan)
    app.state.folder = folder
    app.state.ftp_client = ftp_client
    app.state.clock = clock
    app.state.scheduler = None
    app.state.started = False
    settings_lock = threading.Lock()
    sync_lock = threading.Lock()

    def start_scheduler(target: FastAPI) -> None:
        if not target.state.started:
            return
        if target.state.scheduler is None:
            target.state.scheduler = SyncScheduler(
                folder, target.state.run_sync, clock=clock
            )
        target.state.scheduler.start()

    def stop_scheduler(target: FastAPI, *, wait: bool = True) -> None:
        scheduler = target.state.scheduler
        if scheduler is None:
            return
        scheduler.stop(timeout=5.0 if wait else 0.0)

    app.state.start_scheduler = lambda: start_scheduler(app)
    app.state.stop_scheduler = lambda: stop_scheduler(app)

    def with_connection(call):
        connection = folder.connect()
        try:
            return call(connection)
        finally:
            connection.close()

    def run_sync():
        kwargs: dict[str, Any] = {}
        if app.state.ftp_client is not None:
            kwargs["client"] = app.state.ftp_client
        if app.state.clock is not None:
            kwargs["clock"] = app.state.clock
        with sync_lock:
            return SyncWorker(folder, **kwargs).run()

    app.state.run_sync = run_sync

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
            bar_color=config.ui.bar_color,
        )

    def settings_response() -> SettingsResponse:
        config = folder.config
        return SettingsResponse(
            source=SettingsSource(
                kind=config.source.kind,
                protocol=config.source.protocol,
                host=config.source.host,
                port=config.source.port,
                base_path=config.source.base_path,
                username=config.source.username,
                password_set=(
                    config.source.password is not None
                    or config.source.password_env is not None
                ),
                password_env=config.source.password_env,
                tls=config.source.tls,
            ),
            mail=(
                SettingsMail(
                    kind=config.mail.kind,
                    path=config.mail.path,
                    eml_dir=config.mail.eml_dir,
                )
                if config.mail is not None
                else None
            ),
            lazy_drafts=config.sync.lazy_drafts,
            excel=config.paths.excel,
            auto_sync=config.poll.auto_sync,
            meeting_interval_s=config.poll.meeting_interval_s,
            idle_interval_s=config.poll.idle_interval_s,
            bar_color=config.ui.bar_color,
        )

    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings() -> SettingsResponse:
        return settings_response()

    @app.put("/api/settings", response_model=SettingsResponse)
    def put_settings(payload: SettingsUpdate) -> SettingsResponse:
        with settings_lock:
            data = folder.config_document()
            source = data.setdefault("source", {})
            source.update(
                {
                    "kind": payload.kind,
                    "protocol": payload.protocol,
                    "host": payload.host,
                    "port": payload.port,
                    "base_path": payload.base_path,
                    "tls": payload.tls,
                }
            )
            if payload.username:
                source["username"] = payload.username
            else:
                source.pop("username", None)
            if payload.clear_password:
                source.pop("password", None)
                source.pop("password_env", None)
            elif payload.password:
                source["password"] = payload.password
                source.pop("password_env", None)
            if "mail" in payload.model_fields_set:
                if payload.mail is None:
                    data.pop("mail", None)
                else:
                    data["mail"] = {
                        "kind": payload.mail.kind,
                        "path": payload.mail.path,
                        "eml_dir": payload.mail.eml_dir,
                    }
            sync = data.setdefault("sync", {})
            sync["lazy_drafts"] = payload.lazy_drafts
            poll = data.setdefault("poll", {})
            if payload.auto_sync is not None:
                poll["auto_sync"] = payload.auto_sync
            if payload.meeting_interval_s is not None:
                poll["meeting_interval_s"] = payload.meeting_interval_s
            if payload.idle_interval_s is not None:
                poll["idle_interval_s"] = payload.idle_interval_s
            if payload.bar_color is not None:
                ui = data.setdefault("ui", {})
                ui["bar_color"] = payload.bar_color
            try:
                folder.update_config(data)
            except ConfigError as exc:
                raise HTTPException(
                    status_code=422, detail=list(exc.errors)
                ) from None
        if folder.config.poll.auto_sync:
            stop_scheduler(app)
            start_scheduler(app)
        else:
            stop_scheduler(app)
        return settings_response()

    @app.post("/api/import/excel", response_model=ExcelImportResponse)
    async def import_excel(
        request: Request,
        filename: str = Query(..., min_length=1),
        force: bool = Query(True),
    ) -> ExcelImportResponse:
        name = Path(filename.replace("\\", "/")).name
        if name != filename or not name.casefold().endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400,
                detail="filename must be a plain .xlsx or .xls name",
            )
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="empty workbook")
        folder.imports_dir.mkdir(parents=True, exist_ok=True)
        (folder.imports_dir / name).write_bytes(raw)
        try:
            result = AgendaIngestor(
                folder, clock=app.state.clock
            ).ingest_excel(raw, path=name, force=force)
        except Exception as exc:  # noqa: BLE001 - report parse errors to UI
            raise HTTPException(status_code=422, detail=str(exc)) from None
        with settings_lock:
            data = folder.config_document()
            data.setdefault("paths", {})["excel"] = name
            try:
                folder.update_config(data)
            except ConfigError as exc:
                raise HTTPException(
                    status_code=422, detail=list(exc.errors)
                ) from None
        return ExcelImportResponse(
            status=result.status,
            path=name,
            row_count=result.row_count,
            edge_count=result.edge_count,
            issue_count=result.issue_count,
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

    @app.get("/api/drafts/{artifact_id}", response_model=DraftDetail)
    def get_draft(artifact_id: int) -> dict:
        result = with_connection(
            lambda connection: repository.get_draft(connection, artifact_id)
        )
        if result is None:
            raise HTTPException(status_code=404, detail="draft not found")
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
    def get_lineage(
        tracked: bool = False,
        include_inactive: bool = False,
        include_drafts: bool = False,
    ) -> dict:
        return with_connection(
            lambda connection: repository.lineage(
                connection,
                tracked_only=tracked,
                include_inactive=include_inactive,
                include_drafts=include_drafts,
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

    @app.get("/api/log", response_model=list[UserActionItem])
    def get_log(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
        return with_connection(
            lambda connection: repository.user_actions(connection, limit=limit)
        )

    @app.get("/api/discovery", response_model=list[DiscoveryItem])
    def get_discovery() -> list[dict]:
        return with_connection(repository.discovery)

    @app.get("/api/notifications", response_model=list[NotificationItem])
    def get_notifications(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
        return with_connection(
            lambda connection: repository.notifications(
                connection, limit=limit
            )
        )

    @app.get("/api/sync/status", response_model=SyncStatusResponse)
    def get_sync_status() -> dict:
        now = app.state.clock() if app.state.clock is not None else datetime.now(
            timezone.utc
        )
        interval_s, mode = current_interval_s(folder.config, now)
        return with_connection(
            lambda connection: repository.sync_status(
                connection,
                endpoint_id=folder.config.source.endpoint_id,
                poll_interval_s=interval_s,
                poll_mode=mode,
                now=now,
            )
        )

    @app.post("/api/sync", response_model=SyncResponse)
    def post_sync() -> dict:
        return app.state.run_sync().as_dict()

    @app.post(
        "/api/tdocs/{tdoc_number}/fetch", response_model=FetchResponse
    )
    def fetch_tdoc(
        tdoc_number: str,
        lineage: bool = Query(True),
    ) -> FetchResponse:
        exists = with_connection(
            lambda connection: repository.get_tdoc(connection, tdoc_number)
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="tdoc not found")
        kwargs: dict[str, Any] = {}
        if app.state.ftp_client is not None:
            kwargs["client"] = app.state.ftp_client
        else:
            kwargs["client"] = LftpFtpClient(folder.config.source)
        if app.state.clock is not None:
            kwargs["clock"] = app.state.clock
        result = Syncer(folder, **kwargs).fetch_for_tdoc(
            tdoc_number, include_lineage=lineage
        )
        return FetchResponse(
            tdoc_number=tdoc_number,
            fetched=len(result.fetched),
            artifacts=list(result.fetched),
            failures=[
                f"{failure.path}: {failure.error}"
                for failure in result.failures
            ],
        )

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
        require_target(payload.target_kind, payload.target_ref)
        return with_connection(
            lambda connection: repository.add_note(
                connection,
                target_kind=payload.target_kind,
                target_ref=payload.target_ref,
                body=payload.body,
            )
        )

    def require_target(target_kind: str, target_ref: str) -> None:
        if target_kind == "tdoc":
            exists = with_connection(
                lambda connection: repository.get_tdoc(connection, target_ref)
            )
            if exists is None:
                raise HTTPException(status_code=404, detail="tdoc not found")
            return
        try:
            artifact_id = int(target_ref)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="draft target_ref must be an id"
            ) from None
        exists = with_connection(
            lambda connection: repository.get_draft(connection, artifact_id)
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="draft not found")

    @app.put("/api/status", response_model=NodeStatusResponse)
    def put_status(payload: NodeStatusRequest) -> dict:
        require_target(payload.target_kind, payload.target_ref)
        status = with_connection(
            lambda connection: repository.set_node_status(
                connection,
                target_kind=payload.target_kind,
                target_ref=payload.target_ref,
                status=payload.status,
            )
        )
        return {
            "target_kind": payload.target_kind,
            "target_ref": payload.target_ref,
            "status": status,
        }

    @app.put("/api/hidden", response_model=NodeHiddenResponse)
    def put_hidden(payload: NodeHiddenRequest) -> dict:
        require_target(payload.target_kind, payload.target_ref)
        hidden = with_connection(
            lambda connection: repository.set_node_hidden(
                connection,
                target_kind=payload.target_kind,
                target_ref=payload.target_ref,
                hidden=payload.hidden,
            )
        )
        return {
            "target_kind": payload.target_kind,
            "target_ref": payload.target_ref,
            "hidden": hidden,
        }

    @app.get("/api/conflicts", response_model=list[ConflictResponse])
    def get_conflicts(status: str | None = "open") -> list[dict]:
        return with_connection(
            lambda connection: repository.list_conflicts(
                connection, status=status
            )
        )

    @app.post(
        "/api/conflicts/{conflict_id}/resolve", response_model=ConflictResponse
    )
    def resolve_conflict(
        conflict_id: int, payload: ConflictResolveRequest
    ) -> dict:
        result = with_connection(
            lambda connection: repository.resolve_conflict(
                connection,
                conflict_id,
                resolution=payload.resolution,
                resolution_note=payload.note,
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="conflict not found")
        return result

    @app.post(
        "/api/assertions", response_model=AssertionResponse, status_code=201
    )
    def post_assertion(payload: AssertionRequest) -> dict:
        return with_connection(
            lambda connection: repository.add_assertion(
                connection,
                subject_kind=payload.subject_kind,
                subject_ref=payload.subject_ref,
                predicate=payload.predicate,
                object_kind=payload.object_kind,
                object_ref=payload.object_ref,
                value=payload.value,
                confidence=payload.confidence,
                detail=payload.detail,
            )
        )

    @app.patch(
        "/api/assertions/{assertion_id}", response_model=AssertionResponse
    )
    def patch_assertion(assertion_id: int, payload: AssertionPatch) -> dict:
        result = with_connection(
            lambda connection: repository.set_assertion_state(
                connection,
                assertion_id,
                active=payload.active,
                muted=payload.muted,
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="assertion not found")
        return result

    @app.patch("/api/notes/{note_id}", response_model=NoteResponse)
    def patch_note(note_id: int, payload: NotePatch) -> dict:
        result = with_connection(
            lambda connection: repository.update_note(
                connection,
                note_id,
                body=payload.body,
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="note not found")
        return result

    @app.delete("/api/notes/{note_id}", status_code=204)
    def remove_note(note_id: int) -> Response:
        deleted = with_connection(
            lambda connection: repository.delete_note(connection, note_id)
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="note not found")
        return Response(status_code=204)

    @app.get("/api/export/markdown", response_class=PlainTextResponse)
    def get_markdown(include_mail: bool = False) -> PlainTextResponse:
        content = render_markdown(folder, include_mail=include_mail)
        return PlainTextResponse(
            content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="mirko-export.md"'
            },
        )

    @app.post("/api/finalize", response_model=FinalizeResponse)
    def post_finalize(include_mail: bool = False) -> dict:
        return finalize(
            folder,
            include_mail=include_mail,
            clock=app.state.clock,
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
