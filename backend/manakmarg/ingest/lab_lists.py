"""BIS laboratory lists published as PDFs (plan Task 5.1).

* Group-1 — BIS recognised laboratories: Sl. No., name, state, status (ownership), OSL code, recognition valid
  up to, remarks.
* Group-2 — laboratories of national repute whose facilities BIS utilises: Sl. No., name, state, status,
  OSL code.

The input is PyMuPDF table extraction (``documents.pdf_pages``). Rows without a serial number continue the
previous laboratory's remarks across page breaks. Suspension or withdrawal is derived only from dated remark
events, and every decision keeps the quoted remark as its basis.
"""

import re
from dataclasses import dataclass
from datetime import date

from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.geo import normalize_state
from manakmarg.normalize.text import clean_ws, snippet

LISTED = "LISTED"
SUSPENDED = "SUSPENDED"
WITHDRAWN = "WITHDRAWN"
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"

_AS_OF = re.compile(r"\(\s*(?:as\s+on\s+)?(\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{4})\s*\)", re.IGNORECASE)
_HEADER = re.compile(r"^s\.?\s*(?:l\.?)?\s*no\b", re.IGNORECASE)
_DATE = r"(\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4})"
_WEF = r"w\.?\s*e\.?\s*f\.?\s*[:\-]?\s*"
_LIFTED = r"(?:revoked|cancell?ed|withdrawn|lifted)"
_EVENTS = (
    (LISTED, re.compile(r"suspension\s+" + _LIFTED + r"\s*" + _WEF + _DATE, re.IGNORECASE)),
    (
        WITHDRAWN,
        re.compile(
            r"(?<!suspension\s)\b(?:withdrawn|withdrawal|cancell?ed|cancellation|de-?recogni[sz]ed)\b"
            r"(?:(?!revok|suspen)[^;]){0,60}?" + _WEF + _DATE,
            re.IGNORECASE,
        ),
    ),
    (
        SUSPENDED,
        re.compile(
            r"suspen(?:ded|sion)(?!\s+" + _LIFTED + r")(?:(?!revok|suspen|withdraw)[^;]){0,80}?" + _WEF + _DATE,
            re.IGNORECASE,
        ),
    ),
)
_STATUS_WORDS = re.compile(r"suspen|withdraw|cancel|de-?recogni", re.IGNORECASE)
_OWNERSHIP = {"private": "Private", "priavate": "Private", "pvt": "Private", "govt": "Govt", "government": "Govt"}


@dataclass(frozen=True)
class LabListRecord:
    group_no: int
    sl_no: str
    name: str
    state: str | None
    state_raw: str | None
    ownership: str | None
    ownership_raw: str | None
    osl_code: str | None
    valid_upto: date | None
    valid_upto_raw: str | None
    remarks_raw: str | None
    derived_status: str
    status_basis: str
    locator: str


@dataclass(frozen=True)
class GroupList:
    group_no: int
    as_of: date | None
    as_of_raw: str | None
    records: list[LabListRecord]


def _append(text: str, more: str) -> str:
    """Join wrapped PDF lines; a hyphen at a line end followed by a digit or lower-case letter is a split word."""
    if not more:
        return text
    if not text:
        return more
    if text.endswith("-") and (more[0].isdigit() or more[0].islower()):
        return text + more
    return f"{text} {more}"


def _join_lines(value: str | None) -> str:
    joined = ""
    for part in str(value or "").split("\n"):
        joined = _append(joined, clean_ws(part))
    return joined


def derive_lab_status(remarks: str | None, list_label: str = "the BIS laboratory list") -> tuple[str, str]:
    """Status from the latest dated remark (suspended / suspension revoked / withdrawn) with a quoted basis."""
    text = clean_ws(remarks)
    if not text:
        return LISTED, f"Listed in {list_label}; no remarks are recorded against the laboratory."
    events = []
    for status, pattern in _EVENTS:
        for match in pattern.finditer(text):
            event_date = parse_date(match.group(1))
            if event_date is not None:
                events.append((event_date, -match.start(), status, clean_ws(match.group(0))))
    if not events:
        if _STATUS_WORDS.search(text):
            return (
                NEEDS_VERIFICATION,
                f"Remarks in {list_label} mention a status change without a readable date: \"{snippet(text, 200)}\"",
            )
        return LISTED, f"Listed in {list_label}; remarks record no suspension or withdrawal: \"{snippet(text, 200)}\""
    _, _, status, phrase = max(events)
    return status, f"Latest dated remark in {list_label}: \"{phrase}\""


def parse_group_list(pages: list[dict], group: int) -> GroupList:
    as_of = _AS_OF.search(pages[0].get("text") or "") if pages else None
    list_label = f"the BIS Group-{group} laboratory list"
    rows: list[dict] = []
    for page in pages:
        for table_number, table in enumerate(page.get("tables") or [], start=1):
            for row_number, raw_row in enumerate(table, start=1):
                cells = [_join_lines(value) for value in raw_row] + [""] * 7
                if not any(cells) or _HEADER.match(cells[0]) or cells[1].lower() == "name of lab":
                    continue
                serial = cells[0].rstrip(".").strip()
                if not serial:
                    if rows:
                        rows[-1]["name"] = _append(rows[-1]["name"], cells[1])
                        rows[-1]["remarks"] = _append(rows[-1]["remarks"], cells[6])
                    continue
                rows.append(
                    {
                        "sl_no": serial,
                        "name": cells[1],
                        "state_raw": cells[2],
                        "ownership_raw": cells[3],
                        "osl_code": cells[4],
                        "valid_upto_raw": cells[5],
                        "remarks": cells[6],
                        "locator": f"page-{page.get('page')}/table-{table_number}/row-{row_number}",
                    }
                )

    records = []
    for row in rows:
        remarks = row["remarks"] or None
        status, basis = derive_lab_status(remarks, list_label)
        ownership_raw = row["ownership_raw"] or None
        records.append(
            LabListRecord(
                group_no=group,
                sl_no=row["sl_no"],
                name=row["name"],
                state=normalize_state(row["state_raw"]),
                state_raw=row["state_raw"] or None,
                ownership=_OWNERSHIP.get(re.sub(r"[^a-z]", "", ownership_raw.lower()), ownership_raw)
                if ownership_raw
                else None,
                ownership_raw=ownership_raw,
                osl_code=row["osl_code"] or None,
                valid_upto=parse_date(row["valid_upto_raw"]),
                valid_upto_raw=row["valid_upto_raw"] or None,
                remarks_raw=remarks,
                derived_status=status,
                status_basis=basis,
                locator=row["locator"],
            )
        )
    return GroupList(
        group_no=group,
        as_of=parse_date(as_of.group(1)) if as_of else None,
        as_of_raw=clean_ws(as_of.group(0)) if as_of else None,
        records=records,
    )
