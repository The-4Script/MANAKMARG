"""Dates in the formats used by BIS, LIMS, Manakonline and Gazette sources (spec §6.2).

Numeric dates are read day-first (DD/MM/YYYY, DD.MM.YYYY, DD-MM-YYYY) because every source uses that
order; nothing is guessed from locale.
"""

import re
from datetime import date

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_ALTERNATION = "|".join(sorted(_MONTHS, key=len, reverse=True))

_TEXTUAL = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*(?:st|nd|rd|th)?\.?\s+(?P<month>" + _MONTH_ALTERNATION + r")\.?,?\s+(?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)
_TEXTUAL_MONTH_FIRST = re.compile(
    r"(?<![A-Za-z])(?P<month>" + _MONTH_ALTERNATION + r")\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)
_NUMERIC = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s*(?P<sep>[./-])\s*(?P<month>\d{1,2})\s*(?P=sep)\s*(?P<year>\d{4})(?!\d)"
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str | None) -> list[date]:
    """Every valid date in ``text``, in order of appearance."""
    if not text:
        return []
    found: list[tuple[int, date]] = []
    for pattern in (_TEXTUAL, _TEXTUAL_MONTH_FIRST):
        for match in pattern.finditer(text):
            parsed = _safe_date(int(match["year"]), _MONTHS[match["month"].lower()], int(match["day"]))
            if parsed:
                found.append((match.start(), parsed))
    for match in _NUMERIC.finditer(text):
        parsed = _safe_date(int(match["year"]), int(match["month"]), int(match["day"]))
        if parsed:
            found.append((match.start(), parsed))
    return [parsed for _, parsed in sorted(found, key=lambda item: item[0])]


def parse_date(text: str | None) -> date | None:
    """The first valid date in ``text``, or ``None``."""
    dates = find_dates(text.strip()) if text else []
    return dates[0] if dates else None
