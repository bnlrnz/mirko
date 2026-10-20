"""Automatic polling for the meeting source."""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from zoneinfo import ZoneInfo

from mirko import repository
from mirko.config import MeetingConfig
from mirko.meeting_folder import MeetingFolder

logger = logging.getLogger(__name__)


def meeting_is_active(config: MeetingConfig, moment: datetime) -> bool:
    local = moment.astimezone(ZoneInfo(config.meeting.timezone))
    if local.date().isoformat() not in config.meeting.days:
        return False
    start = time.fromisoformat(config.meeting.hours.start)
    end = time.fromisoformat(config.meeting.hours.end)
    return start <= local.time() <= end


def current_interval_s(config: MeetingConfig, moment: datetime) -> tuple[int, str]:
    if meeting_is_active(config, moment):
        return config.poll.meeting_interval_s, "meeting"
    return config.poll.idle_interval_s, "idle"


def next_interval_s(
    config: MeetingConfig,
    moment: datetime,
    *,
    failures: int = 0,
    rng: Any | None = None,
) -> float:
    poll = config.poll
    base, _ = current_interval_s(config, moment)
    if failures > 0:
        base = min(base * (2 ** min(failures, 16)), poll.backoff_max_s)
    source = rng or random
    jitter = source.uniform(-poll.jitter, poll.jitter)
    return max(1.0, base * (1 + jitter))


class SyncScheduler:
    """Run the sync worker in the background on an adaptive schedule."""

    def __init__(
        self,
        folder: MeetingFolder,
        run: Callable[[], Any],
        *,
        clock: Callable[[], datetime] | None = None,
        rng: Any | None = None,
    ) -> None:
        self.folder = folder
        self.run = run
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.rng = rng
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="mirko-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _loop(self) -> None:
        failures = 0
        delay = 0.0
        while not self._stop.wait(delay):
            try:
                result = self.run()
                status = str(getattr(result, "status", "ok"))
            except Exception:  # noqa: BLE001 - keep polling after failures
                logger.exception("automatic sync failed")
                status = "error"
            failures = failures + 1 if status == "error" else 0
            now = self.clock()
            delay = next_interval_s(
                self.folder.config,
                now,
                failures=failures,
                rng=self.rng,
            )
            self._record_next_due(now + timedelta(seconds=delay))

    def _record_next_due(self, moment: datetime) -> None:
        endpoint_id = self.folder.config.source.endpoint_id
        next_due_at = moment.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        connection = self.folder.connect()
        try:
            repository.set_next_due(
                connection,
                endpoint_id=endpoint_id,
                next_due_at=next_due_at,
            )
        finally:
            connection.close()
