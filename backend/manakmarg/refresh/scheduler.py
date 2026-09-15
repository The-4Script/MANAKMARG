"""Saturday schedule for the BIS data refresh, running inside the server process (no external cron or worker).

The refresh runs every ``refresh_weekday`` (Saturday) at ``refresh_time_ist``. If the server was down at the last
scheduled time and the refresh log shows no attempt since then, one catch-up run starts shortly after start-up. A
fresh installation with no log waits for the next Saturday instead, so restarts never trigger repeated downloads.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from manakmarg.core import clock
from manakmarg.core.clock import IST

log = logging.getLogger(__name__)

ACTIVE_SCHEDULER: "RefreshScheduler | None" = None


def _parse_time(text: str) -> tuple[int, int]:
    hour, _, minute = text.strip().partition(":")
    hour_value, minute_value = int(hour), int(minute or 0)
    if not (0 <= hour_value < 24 and 0 <= minute_value < 60):
        raise ValueError(f"invalid refresh time {text!r}; use HH:MM")
    return hour_value, minute_value


def next_run_after(moment: datetime, *, weekday: int, at: str) -> datetime:
    """The first scheduled time strictly after ``moment`` (IST)."""
    local = moment.astimezone(IST)
    hour, minute = _parse_time(at)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=(weekday - local.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


def last_slot_at_or_before(moment: datetime, *, weekday: int, at: str) -> datetime:
    return next_run_after(moment, weekday=weekday, at=at) - timedelta(days=7)


def catch_up_due(last_attempt: datetime | None, now: datetime, *, weekday: int, at: str) -> bool:
    """True when a refresh has run before but none since the most recent scheduled time."""
    return last_attempt is not None and last_attempt < last_slot_at_or_before(now, weekday=weekday, at=at)


class RefreshScheduler:
    def __init__(
        self,
        run: Callable[[str], object],
        *,
        weekday: int,
        at: str,
        last_attempt: Callable[[], datetime | None],
        catch_up: bool = True,
        startup_delay_s: float = 600.0,
        now: Callable[[], datetime] = clock.now_utc,
    ):
        self.run = run
        self.weekday = weekday
        self.at = at
        self.last_attempt = last_attempt
        self.catch_up = catch_up
        self.startup_delay_s = startup_delay_s
        self._now = now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.next_run_at: datetime | None = None
        self.next_trigger = "schedule"

    def plan(self) -> None:
        now = self._now()
        if self.catch_up and catch_up_due(self.last_attempt(), now, weekday=self.weekday, at=self.at):
            self.next_run_at, self.next_trigger = now + timedelta(seconds=self.startup_delay_s), "catch_up"
        else:
            self.next_run_at, self.next_trigger = next_run_after(now, weekday=self.weekday, at=self.at), "schedule"

    def tick(self) -> bool:
        """Run the refresh if it is due; returns True when it ran."""
        if self.next_run_at is None:
            self.plan()
        if self._now() < self.next_run_at:
            return False
        try:
            self.run(self.next_trigger)
        except Exception:  # the refresh records its own failures; this only protects the server process
            log.exception("scheduled BIS data refresh crashed; the active dataset is unchanged")
        self.next_trigger = "schedule"
        self.next_run_at = next_run_after(self._now(), weekday=self.weekday, at=self.at)
        return True

    def start(self) -> "RefreshScheduler":
        self.plan()
        self._thread = threading.Thread(target=self._loop, name="manakmarg-data-refresh", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.tick():
                continue
            remaining = (self.next_run_at - self._now()).total_seconds()
            self._stop.wait(max(1.0, min(remaining, 3600.0)))  # wake at least hourly, so clock changes are noticed


def start_refresh_scheduler(settings) -> RefreshScheduler:
    """Start the weekly refresh in a background thread of the running server."""
    global ACTIVE_SCHEDULER
    from manakmarg.api import deps
    from manakmarg.refresh import log as refresh_log
    from manakmarg.refresh.pipeline import run_refresh

    def run(trigger: str) -> None:
        run_refresh(settings, trigger=trigger, before_swap=deps.release_state, after_swap=deps.reload_state)

    ACTIVE_SCHEDULER = RefreshScheduler(
        run,
        weekday=settings.refresh_weekday,
        at=settings.refresh_time_ist,
        last_attempt=lambda: refresh_log.last_attempt_at(settings.refresh_dir),
        catch_up=settings.refresh_catch_up,
    ).start()
    return ACTIVE_SCHEDULER
