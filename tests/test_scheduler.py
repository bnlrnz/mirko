"""Tests for adaptive background sync scheduling."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from mirko.api import create_app
from mirko.ftp import FakeFtpClient
from mirko.meeting_folder import MeetingFolder
from mirko.scheduler import (
    SyncScheduler,
    current_interval_s,
    next_interval_s,
)

NOW = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


class NoJitter:
    def uniform(self, _start: float, _end: float) -> float:
        return 0.0


def minimal_config() -> dict:
    return {
        "schema_version": 1,
        "meeting": {
            "id": "SA3#130",
            "title": "SA3#130 Prague",
            "timezone": "Europe/Prague",
            "days": ["2026-10-12", "2026-10-16"],
            "hours": {"start": "09:00", "end": "18:00"},
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


def test_interval_is_adaptive_and_backs_off(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    config = folder.config
    rng = NoJitter()

    assert current_interval_s(config, NOW) == (45, "meeting")
    assert next_interval_s(config, NOW, rng=rng) == 45.0
    assert next_interval_s(config, NOW, failures=2, rng=rng) == 180.0
    assert next_interval_s(config, NOW, failures=10, rng=rng) == 900.0
    idle = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    assert current_interval_s(config, idle) == (600, "idle")
    assert next_interval_s(config, idle, rng=rng) == 600.0


def test_scheduler_runs_immediately_and_stops(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    ran = threading.Event()
    calls: list[int] = []

    def run() -> SimpleNamespace:
        calls.append(1)
        ran.set()
        return SimpleNamespace(status="error")

    scheduler = SyncScheduler(
        folder,
        run,
        clock=lambda: NOW,
        rng=NoJitter(),
    )
    scheduler.start()
    assert ran.wait(1)
    scheduler.stop()

    assert calls == [1]
    assert not scheduler.running


def test_app_starts_sync_in_the_background(tmp_path: Path) -> None:
    folder = MeetingFolder.create(tmp_path / "SA3-130", minimal_config())
    app = create_app(
        folder,
        ftp_client=FakeFtpClient(),
        clock=lambda: NOW,
        auto_sync=True,
    )

    with TestClient(app) as client:
        deadline = time.monotonic() + 2
        status = client.get("/api/sync/status").json()
        while (
            status["last_attempt_at"] is None or status["next_due_at"] is None
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
            status = client.get("/api/sync/status").json()

    assert status["last_attempt_at"] == "2026-10-16T10:00:00.000000Z"
    assert status["next_due_at"] is not None
    assert status["health"] == "ok"
    assert app.state.scheduler is not None
    assert not app.state.scheduler.running


def test_settings_toggle_and_interval_control_scheduler(tmp_path: Path) -> None:
    data = minimal_config()
    data["poll"] = {
        "auto_sync": False,
        "meeting_interval_s": 30,
        "idle_interval_s": 90,
    }
    folder = MeetingFolder.create(tmp_path / "SA3-130", data)
    app = create_app(
        folder,
        ftp_client=FakeFtpClient(),
        clock=lambda: NOW,
    )

    with TestClient(app) as client:
        assert app.state.scheduler is None
        current = client.get("/api/settings").json()
        assert current["auto_sync"] is False
        assert current["meeting_interval_s"] == 30
        assert current["idle_interval_s"] == 90

        payload = {
            "kind": current["source"]["kind"],
            "protocol": current["source"]["protocol"],
            "host": current["source"]["host"],
            "port": current["source"]["port"],
            "base_path": current["source"]["base_path"],
            "username": current["source"]["username"],
            "tls": current["source"]["tls"],
            "lazy_drafts": current["lazy_drafts"],
            "auto_sync": True,
            "meeting_interval_s": 20,
            "idle_interval_s": 80,
        }
        updated = client.put("/api/settings", json=payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["auto_sync"] is True
        assert updated.json()["meeting_interval_s"] == 20
        assert app.state.scheduler is not None
        assert app.state.scheduler.running

        payload["auto_sync"] = False
        disabled = client.put("/api/settings", json=payload)
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["auto_sync"] is False
        assert not app.state.scheduler.running
