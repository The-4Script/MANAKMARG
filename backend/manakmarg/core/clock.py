"""Injectable clock.

Anything that depends on "today" — lab validity, AHC validity, whether an upcoming QCO is in force —
must read the date from here so tests and demos can pin it.
"""

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

_frozen_today: date | None = None


def freeze(day: date | None) -> None:
    global _frozen_today
    _frozen_today = day


def today() -> date:
    if _frozen_today is not None:
        return _frozen_today
    return datetime.now(IST).date()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
