"""QCO / notification references parsed from compulsory-certification page cells (spec §6.5).

Each link in a notification cell becomes an ``OrderRef``: title, absolute URL, kind (order,
amendment, extension, deferment, rescission, …), S.O./G.S.R. number and date.

On BIS pages the order name is often written on its own line and the link on the next line carries
only the notification number and date (``Cement (Quality Control)Order, 2003`` / ``S.O. No. 191(E)
Dt. 17 Feb 2003``). Callers therefore pass the closest preceding plain line as ``context``; it is used
when the anchor text alone does not say what kind of order the link is.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

from manakmarg.normalize.dates import find_dates
from manakmarg.normalize.text import clean_ws

_SO_NUMBER = re.compile(r"\bS\.?\s*O\.?\s*(?:No\.?\s*)?(\d{1,5})\s*\(\s*E\s*\)", re.IGNORECASE)
_SO_IN_FILE_NAME = re.compile(r"\bS\.?O[-_ .]*No[-_ .]*(\d{1,5})\s*\(?\s*E\s*\)?", re.IGNORECASE)
_GSR_NUMBER = re.compile(r"\bG\.?\s*S\.?\s*R\.?\s*(?:No\.?\s*)?(\d{1,5})\s*\(\s*E\s*\)", re.IGNORECASE)
_ENUMERATION = re.compile(r"^\s*\d{1,3}\s*[.)]\s*")

_KIND_RULES = (
    ("rescission", re.compile(r"\brescind", re.IGNORECASE)),
    ("corrigendum", re.compile(r"\bcorrigendum", re.IGNORECASE)),
    ("deferment", re.compile(r"\bdefer(?:ment|red|ring)?\b", re.IGNORECASE)),
    ("extension", re.compile(r"\bextension\b", re.IGNORECASE)),
    ("superseding_order", re.compile(r"\bsuperseded\s+by\b", re.IGNORECASE)),
    ("amendment", re.compile(r"\bamendments?\b", re.IGNORECASE)),
    ("rules", re.compile(r"\brules\b", re.IGNORECASE)),
    ("regulation", re.compile(r"\bregulations?\b", re.IGNORECASE)),
    ("notification", re.compile(r"\bnotification\b", re.IGNORECASE)),
    ("qco", re.compile(r"\border\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class OrderRef:
    title: str
    url: str
    kind: str
    so_number: str | None
    gsr_number: str | None
    order_date: date | None
    raw_text: str
    context: str | None = None


def extract_so_number(text: str | None) -> str | None:
    match = _SO_NUMBER.search(text or "")
    return f"S.O. {match.group(1)}(E)" if match else None


def extract_gsr_number(text: str | None) -> str | None:
    match = _GSR_NUMBER.search(text or "")
    return f"G.S.R. {match.group(1)}(E)" if match else None


def _so_number_from_file_name(file_name: str) -> str | None:
    match = _SO_IN_FILE_NAME.search(file_name)
    return f"S.O. {match.group(1)}(E)" if match else None


def order_identity(url: str, so_number: str | None, gsr_number: str | None) -> str:
    """Key of one regulatory order. BIS pages sometimes link different notifications to the same PDF (for example a
    pressure-cooker amendment and the cables QCO both pointing at ``Cables_28012020.pdf``); the notification number
    keeps such orders apart, while references without a number stay keyed by their URL."""
    number = so_number or gsr_number
    return f"{url}#{number}" if number else url


def classify_order_kind(text: str | None) -> str:
    for kind, pattern in _KIND_RULES:
        if pattern.search(text or ""):
            return kind
    return "other"


def parse_order_links(links: list[tuple], page_url: str) -> list[OrderRef]:
    """Order references from ``(anchor text, href)`` or ``(anchor text, href, context line)`` items.

    Links are resolved against ``page_url`` and de-duplicated by URL; a repeated URL is kept only when it carries a
    different notification number (a different order that shares the PDF link).
    """
    refs: list[OrderRef] = []
    seen: dict[str, set[str | None]] = {}
    for item in links:
        text, href = item[0], item[1]
        context_raw = item[2] if len(item) > 2 else None
        href = (href or "").strip()
        if not href or href.startswith("#") or href.lower().startswith(("javascript:", "mailto:")):
            continue
        url = urljoin(page_url, href)
        numbers = seen.setdefault(url, set())
        link_number = extract_so_number(text) or extract_gsr_number(text)
        if numbers and (link_number is None or link_number in numbers):
            continue
        numbers.add(link_number)

        raw = clean_ws(text)
        anchor = _ENUMERATION.sub("", raw).strip()
        file_name = unquote(PurePosixPath(urlsplit(url).path).name)
        context = _ENUMERATION.sub("", clean_ws(context_raw)).strip().rstrip(":").strip() if context_raw else ""

        kind = classify_order_kind(anchor)
        if kind == "other" and context:
            kind = classify_order_kind(f"{context} {anchor}")
            title = f"{context} — {anchor}" if anchor else context
        else:
            title = anchor or file_name

        dates = find_dates(anchor) or find_dates(context)
        refs.append(
            OrderRef(
                title=title,
                url=url,
                kind=kind,
                so_number=extract_so_number(anchor) or extract_so_number(context) or _so_number_from_file_name(file_name),
                gsr_number=extract_gsr_number(anchor) or extract_gsr_number(context),
                order_date=dates[0] if dates else None,
                raw_text=raw,
                context=context or None,
            )
        )
    return refs
