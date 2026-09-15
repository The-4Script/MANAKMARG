"""Saturday schedule: next run time, catch-up after downtime, and the run loop's safety."""

from datetime import datetime, timedelta, timezone

from manakmarg.core.clock import IST
from manakmarg.refresh.scheduler import RefreshScheduler, catch_up_due, next_run_after

SATURDAY = 5


def ist(*args):
    return datetime(*args, tzinfo=IST)


def test_next_run_is_the_coming_saturday_morning():
    assert next_run_after(ist(2026, 9, 18, 23, 0), weekday=SATURDAY, at="02:30") == ist(2026, 9, 19, 2, 30)  # Friday night
    assert next_run_after(ist(2026, 9, 19, 1, 0), weekday=SATURDAY, at="02:30") == ist(2026, 9, 19, 2, 30)  # Saturday, before
    assert next_run_after(ist(2026, 9, 19, 2, 30), weekday=SATURDAY, at="02:30") == ist(2026, 9, 26, 2, 30)  # exactly at the time
    assert next_run_after(ist(2026, 9, 20, 12, 0), weekday=SATURDAY, at="02:30") == ist(2026, 9, 26, 2, 30)  # Sunday
    utc = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)  # Saturday 01:30 IST
    assert next_run_after(utc, weekday=SATURDAY, at="02:30") == ist(2026, 9, 19, 2, 30)


def test_catch_up_only_after_a_missed_saturday_with_a_known_previous_run():
    now = ist(2026, 9, 21, 10, 0)  # Monday
    assert catch_up_due(ist(2026, 9, 12, 2, 31), now, weekday=SATURDAY, at="02:30")  # last ran the Saturday before
    assert not catch_up_due(ist(2026, 9, 19, 2, 31), now, weekday=SATURDAY, at="02:30")  # ran this Saturday
    assert not catch_up_due(None, now, weekday=SATURDAY, at="02:30")  # fresh install: wait for Saturday


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


def test_scheduler_runs_when_due_and_plans_the_next_week():
    clock = Clock(ist(2026, 9, 18, 12, 0))
    runs = []
    scheduler = RefreshScheduler(runs.append, weekday=SATURDAY, at="02:30", last_attempt=lambda: None, now=clock)
    scheduler.plan()
    assert scheduler.next_run_at == ist(2026, 9, 19, 2, 30) and not scheduler.tick() and runs == []
    clock.moment = ist(2026, 9, 19, 2, 30, 5)
    assert scheduler.tick() and runs == ["schedule"]
    assert scheduler.next_run_at == ist(2026, 9, 26, 2, 30)


def test_the_deployment_entry_point_schedules_the_refresh_and_the_dev_server_does_not():
    from manakmarg.__main__ import refresh_scheduled
    from manakmarg.core.config import Settings

    auto = Settings(_env_file=None)
    assert refresh_scheduled(auto, "start", None) and not refresh_scheduled(auto, "serve", None)
    assert refresh_scheduled(auto, "serve", "on") and not refresh_scheduled(auto, "start", "off")
    assert not refresh_scheduled(Settings(_env_file=None, refresh_schedule="off"), "start", None)


def test_scheduler_catches_up_after_downtime_and_survives_a_crashing_refresh():
    clock = Clock(ist(2026, 9, 21, 10, 0))

    def crash(trigger):
        raise RuntimeError(f"boom during {trigger}")

    scheduler = RefreshScheduler(crash, weekday=SATURDAY, at="02:30", last_attempt=lambda: ist(2026, 9, 12, 2, 31), startup_delay_s=60, now=clock)
    scheduler.plan()
    assert scheduler.next_trigger == "catch_up" and scheduler.next_run_at == clock.moment + timedelta(seconds=60)
    clock.moment += timedelta(minutes=2)
    assert scheduler.tick()  # the exception is logged, not raised
    assert scheduler.next_trigger == "schedule" and scheduler.next_run_at == ist(2026, 9, 26, 2, 30)
