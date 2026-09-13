"""Deterministic listing-status rules for compulsory-certification pages (spec §6.5).

A status is derived only from what the official page itself says, and the quoted phrase is kept as
the basis so the UI can show why an entry is marked the way it is.
"""

import re
from dataclasses import dataclass
from datetime import date

from manakmarg.normalize.text import snippet

LISTED_COMPULSORY = "LISTED_COMPULSORY"
DENOTIFIED = "DENOTIFIED"
RESCINDED = "RESCINDED"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
UPCOMING = "UPCOMING"

PAGE_TITLES = {
    "scheme_i": "Scheme – I (ISI Mark Scheme)",
    "scheme_ii": "Scheme – II (Registration Scheme)",
    "scheme_iv": "Scheme – IV (Grant of Certificate of Conformity)",
    "scheme_x": "Scheme – X (Certification)",
    "upcoming_qco": "Upcoming QCOs – notified and due for implementation",
}

_DENOTIFIED = re.compile(r"de-?\s?notified[^.;()]*", re.IGNORECASE)
_RESCIND = re.compile(r"\brescind", re.IGNORECASE)
_DEFERMENT = re.compile(r"\bdeferment\b|\bdeferred\b", re.IGNORECASE)


@dataclass(frozen=True)
class ListingDecision:
    status: str
    basis: str


def classify_listing(page_kind: str, category: str | None, product: str | None, notification: str | None) -> ListingDecision:
    """Precedence: de-notified > rescinded > deferment (needs verification) > upcoming > listed."""
    title = PAGE_TITLES.get(page_kind, page_kind)

    for text in (category or "", product or ""):
        match = _DENOTIFIED.search(text)
        if match:
            phrase = match.group(0).strip()
            return ListingDecision(DENOTIFIED, f"BIS page '{title}' marks this entry \"{phrase}\"")

    notification = notification or ""
    match = _RESCIND.search(notification)
    if match:
        quote = snippet(notification[match.start():], 220)
        return ListingDecision(RESCINDED, f"Notification listed on BIS page '{title}': \"{quote}\"")

    match = _DEFERMENT.search(notification)
    if match:
        quote = snippet(notification[match.start():], 220)
        return ListingDecision(
            NEEDS_VERIFICATION, f"Notification listed on BIS page '{title}' mentions a deferment: \"{quote}\""
        )

    if page_kind == "upcoming_qco":
        return ListingDecision(UPCOMING, f"Listed on BIS page '{title}'")
    return ListingDecision(LISTED_COMPULSORY, f"Listed on BIS page '{title}'")


def upcoming_effect(enforcement_date: date | None, *, today: date) -> str:
    """Whether an upcoming QCO's enforcement date has been reached — computed, never assumed."""
    if enforcement_date is None:
        return "DATE_UNKNOWN"
    return "NOT_YET_IN_FORCE" if enforcement_date > today else "ENFORCEMENT_DATE_REACHED"
