"""Hallmarking sources (plan Task 6.1): AHC list, suspended/cancelled AHCs, district coverage, Gazette check.

* AHC details on Manakonline are label-structured. Contact-person names are not captured; the published
  organisation phone and e-mail are.
* ``effective_ahc_status`` decides operability by deterministic rules. A cancellation or suspension on either
  official list, or an expired or missing validity date, means a centre is never presented as operative.
* Districts come from BIS's phase-wise coverage PDF and are cross-checked against the district annex of the
  latest Hallmarking Order amendment published in the Gazette.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from bs4 import BeautifulSoup, Comment, Tag

from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.geo import Address, norm_district, normalize_state, parse_ahc_address
from manakmarg.normalize.text import clean_ws

OPERATIVE = "OPERATIVE"
SUSPENDED = "SUSPENDED"
SUSPENDED_GOLD_ONLY = "SUSPENDED_GOLD_ONLY"
NOT_OPERATIVE = "NOT_OPERATIVE"
CANCELLED = "CANCELLED"
EXPIRED_VALIDITY = "EXPIRED_VALIDITY"
VALIDITY_UNKNOWN = "VALIDITY_UNKNOWN"
UNKNOWN = "UNKNOWN"

_LIST_STATUSES = {
    "operative": OPERATIVE,
    "under suspension": SUSPENDED,
    "under suspension(gold only)": SUSPENDED_GOLD_ONLY,
    "deferred": NOT_OPERATIVE,
    "deferment letter generated": NOT_OPERATIVE,
}

# Well-known official renamings/spellings used only to pair the phase-wise list with the Gazette annex
# (registry source ``curated_geography``). Keys and values are compact lower-case names.
DISTRICT_RENAMES = {
    "allahabad": "prayagraj",
    "gurgaon": "gurugram",
    "belgaum": "belagavi",
    "pondichery": "puducherry",
    "pondicherry": "puducherry",
    "ntr": "srinandamuritarakaramaraogaru",
}
_MIN_VARIANT_SCORE = 0.72

_RECOGNITION = re.compile(r"^Recognition\s*No\.?\s*:?\s*(?P<value>\S.*)$", re.IGNORECASE)
_VALIDITY = re.compile(r"^Validity\s*:?\s*(?P<value>.*)$", re.IGNORECASE)
_SCOPE = re.compile(r"^Recogni[sz]ed\s+for\b", re.IGNORECASE)
_PHONE = re.compile(r"^Tel(?:ephone)?\s*[:.]?\s*(?P<value>.*)$", re.IGNORECASE)
_EMAIL = re.compile(r"^E-?mail\s*:?\s*(?P<value>.*)$", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"^[\s_\-–—.]*$")
_REGION = re.compile(r"^([A-Z]{2,4})/")

_PHASE_HEADING = re.compile(r"^List of\b.*\bphase\b", re.IGNORECASE)
_PHASE_NUMBER = re.compile(r"\bin\s+the\s+(\w+)\s+phase\b", re.IGNORECASE)
_PHASE_DECLARED = re.compile(r"^List of\s+(?:additional\s+)?(\d+)\s+districts\b", re.IGNORECASE)
_PHASE_DATED = re.compile(r"^(?:Order\s+)?Dated\b", re.IGNORECASE)
_ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
}

_ANNEX_START = re.compile(r"^[“\"]?\s*ANNEXURE\s*$")
_ANNEX_STOP = re.compile(r"^\[?\s*F\.\s*No\b|^Note\s*:", re.IGNORECASE)
_ANNEX_NOISE = re.compile(
    r"GAZETTE OF INDIA|^\[PART\b|^\(\d+\)$|^Sl\.?\s*No\.?$|^State\s*/\s*Union\s+territory$|^District$|^\d+$",
    re.IGNORECASE,
)
_DEVANAGARI = re.compile("[ऀ-ॿ]")
_STATE_SERIAL = re.compile(r"^\d{1,2}\.$")
_DISTRICT_LINE = re.compile(r"^\d{1,3}\.\s*(?P<name>\S.*)$")
_CLOSING_QUOTE = re.compile(r"\s*[”\"’]+\s*\.?\s*$")


@dataclass(frozen=True)
class AhcRecord:
    recognition_no: str
    region_code: str | None
    name: str | None
    address_raw: str | None
    address: Address
    scope_text: str | None
    gold: bool | None
    silver: bool | None
    validity_date: date | None
    validity_raw: str | None
    list_status_raw: str | None
    org_phone: str | None
    org_email: str | None
    sl_no_raw: str | None
    locator: str


@dataclass(frozen=True)
class AhcEventRecord:
    recognition_no: str
    status: str
    event_date: date | None
    event_date_raw: str | None
    region: str | None
    center_type: str | None
    name_address_raw: str | None
    locator: str


@dataclass(frozen=True)
class DistrictRecord:
    sr_no: int
    state: str | None
    state_raw: str
    district: str
    district_raw: str
    district_norm: str
    phase_no: int | None
    phase_label: str | None
    phase_declared_count: int | None
    phase_order_date: date | None
    phase_order_date_raw: str | None
    locator: str


@dataclass(frozen=True)
class GazetteValidation:
    matched: int
    matched_pairs: frozenset
    variants: tuple
    missing_in_gazette: tuple
    extra_in_gazette: tuple
    notes: dict = field(default_factory=dict)


def _field(value: str | None) -> str | None:
    text = clean_ws(value)
    return None if _PLACEHOLDER.match(text) else text


def _labels(cell: Tag) -> list[str]:
    return [clean_ws(label.get_text(" ")) for label in cell.find_all("label")]


# --------------------------------------------------------------------------- AHC list and events


def parse_ahc_list(html: bytes | str, page_url: str) -> list[AhcRecord]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="ahcDetailsTbl")
    records: list[AhcRecord] = []
    if table is None:
        return records
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        recognition = validity_raw = scope = None
        others: list[str] = []
        for text in _labels(cells[1]):
            if recognition is None and (match := _RECOGNITION.match(text)):
                recognition = match["value"].strip()
            elif validity_raw is None and (match := _VALIDITY.match(text)):
                validity_raw = _field(match["value"])
            elif scope is None and _SCOPE.match(text):
                scope = text
            else:
                others.append(text)
        if not recognition:
            continue
        phone = email = None
        for text in _labels(cells[2]):
            if match := _PHONE.match(text):
                phone = _field(match["value"])
            elif match := _EMAIL.match(text):
                email = _field(match["value"])
        address_raw = _field(", ".join(part for part in others[1:] if _field(part)))
        region = _REGION.match(recognition)
        records.append(
            AhcRecord(
                recognition_no=recognition,
                region_code=region.group(1) if region else None,
                name=_field(others[0]) if others else None,
                address_raw=address_raw,
                address=parse_ahc_address(address_raw),
                scope_text=scope,
                gold=bool(re.search(r"\bgold\b", scope, re.IGNORECASE)) if scope else None,
                silver=bool(re.search(r"\bsilver\b", scope, re.IGNORECASE)) if scope else None,
                validity_date=parse_date(validity_raw),
                validity_raw=validity_raw,
                list_status_raw=_field(cells[3].get_text(" ")),
                org_phone=phone,
                org_email=email,
                sl_no_raw=_field(cells[0].get_text(" ")),
                locator=f"ahc-{recognition}",
            )
        )
    return records


def _cell_value(cells: list[Tag], index: int | None) -> str | None:
    return _field(cells[index].get_text(" ")) if index is not None and index < len(cells) else None


def parse_ahc_events(html: bytes | str, page_url: str) -> list[AhcEventRecord]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="ahcDetailsTbl")
    events: list[AhcEventRecord] = []
    if table is None:
        return events
    header = next((row for row in table.find_all("tr") if row.find("th", recursive=False)), None)
    headers = [clean_ws(cell.get_text(" ")).lower() for cell in header.find_all("th", recursive=False)] if header else []

    def column(*prefixes: str) -> int | None:
        return next((index for index, text in enumerate(headers) if text.startswith(prefixes)), None)

    recognition_index, status_index = column("recognition"), column("current status", "status")
    name_index, region_index = column("ahc name", "name"), column("region")
    type_index, date_index = column("center type", "centre type"), column("suspended", "cancelled", "date")
    if recognition_index is None or status_index is None:
        return events

    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        recognition, status = _cell_value(cells, recognition_index), _cell_value(cells, status_index)
        if not recognition or not status:
            continue
        name_address = None
        if name_index is not None and name_index < len(cells):
            name_cell = cells[name_index]
            label = name_cell.find("label")
            direct_text = (
                str(node) for node in name_cell.find_all(string=True, recursive=False) if not isinstance(node, Comment)
            )
            parts = (clean_ws(label.get_text(" ")) if label else "", clean_ws(" ".join(direct_text)))
            name_address = "\n".join(part for part in parts if part) or None
        date_raw = _cell_value(cells, date_index)
        events.append(
            AhcEventRecord(
                recognition_no=recognition,
                status=status.upper(),
                event_date=parse_date(date_raw),
                event_date_raw=date_raw,
                region=_cell_value(cells, region_index),
                center_type=_cell_value(cells, type_index),
                name_address_raw=name_address,
                locator=f"event-{recognition}-{date_raw or 'undated'}",
            )
        )
    return events


def _status_key(value: str) -> str:
    return re.sub(r"\s*\(\s*", "(", value.lower())


def effective_ahc_status(
    list_status: str | None, validity_date: date | None, events: list[AhcEventRecord], *, today: date
) -> tuple[str, list[str]]:
    """Operability of an AHC from both official lists and its validity date, with the reasons used."""
    raw = clean_ws(list_status)
    reasons = [f'Manakonline AHC list status: "{raw}"' if raw else "Manakonline AHC list shows no status"]
    listed = _LIST_STATUSES.get(_status_key(raw), UNKNOWN) if raw else UNKNOWN

    cancellations = [event for event in events if "CANCEL" in event.status.upper()]
    suspensions = [event for event in events if "SUSPEN" in event.status.upper()]
    for event in cancellations + suspensions:
        when = event.event_date.isoformat() if event.event_date else (event.event_date_raw or "date not published")
        reasons.append(f'Suspended/cancelled AHC list: "{event.status}" ({when})')

    if cancellations:
        if listed == OPERATIVE:
            reasons.append("The two official lists disagree; a cancellation is never overridden.")
        return CANCELLED, reasons
    if listed in (SUSPENDED, SUSPENDED_GOLD_ONLY, NOT_OPERATIVE):
        return listed, reasons
    if suspensions:
        if listed == OPERATIVE:
            reasons.append("The two official lists disagree; a suspension is never overridden.")
        return SUSPENDED, reasons
    if listed == UNKNOWN:
        reasons.append("The list status is not a recognised value, so operability cannot be confirmed.")
        return UNKNOWN, reasons
    if validity_date is None:
        reasons.append("No recognition validity date is published.")
        return VALIDITY_UNKNOWN, reasons
    if validity_date < today:
        reasons.append(f"Recognition validity ended on {validity_date.isoformat()} (checked on {today.isoformat()}).")
        return EXPIRED_VALIDITY, reasons
    reasons.append(f"Recognition valid until {validity_date.isoformat()} (checked on {today.isoformat()}).")
    return OPERATIVE, reasons


# --------------------------------------------------------------------------- districts


def _phase_number(heading: str) -> int | None:
    match = _PHASE_NUMBER.search(heading)
    if not match:
        return None
    word = match.group(1).lower()
    if word in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[word]
    digits = re.match(r"^(\d+)(?:st|nd|rd|th)?$", word)
    return int(digits.group(1)) if digits else None


def parse_phasewise_districts(page_texts: list[str]) -> list[DistrictRecord]:
    """Rows of the phase-wise coverage PDF: serial, state/UT and district under each phase heading."""
    records: list[DistrictRecord] = []
    phase_label = phase_date_raw = None
    phase_no = declared = None
    pending_sr: int | None = None
    pending_state: str | None = None
    for page_number, text in enumerate(page_texts, start=1):
        for raw_line in (text or "").splitlines():
            line = clean_ws(raw_line)
            if not line:
                continue
            if pending_sr is None:
                if line.isdigit():
                    pending_sr = int(line)
                elif _PHASE_HEADING.match(line):
                    phase_label, phase_no, phase_date_raw = line, _phase_number(line), None
                    declared_match = _PHASE_DECLARED.match(line)
                    declared = int(declared_match.group(1)) if declared_match else None
                elif _PHASE_DATED.match(line):
                    phase_date_raw = line
                continue
            if pending_state is None:
                pending_state = line
                continue
            records.append(
                DistrictRecord(
                    sr_no=pending_sr,
                    state=normalize_state(pending_state),
                    state_raw=pending_state,
                    district=line.title() if line.isupper() else line,
                    district_raw=line,
                    district_norm=norm_district(line),
                    phase_no=phase_no,
                    phase_label=phase_label,
                    phase_declared_count=declared,
                    phase_order_date=parse_date(phase_date_raw),
                    phase_order_date_raw=phase_date_raw,
                    locator=f"page-{page_number}#sr-{pending_sr}",
                )
            )
            pending_sr = pending_state = None
    return records


def parse_gazette_annex(page_texts: list[str]) -> list[tuple[str, str]]:
    """(state, district) pairs from the Gazette order's ANNEXURE, in the order printed."""
    entries: list[tuple[str, str]] = []
    started = expecting_state = False
    state: str | None = None
    for text in page_texts:
        for raw_line in (text or "").splitlines():
            line = clean_ws(raw_line)
            if not line:
                continue
            if not started:
                started = bool(_ANNEX_START.match(line))
                continue
            if _ANNEX_STOP.match(line):
                return entries
            if _DEVANAGARI.search(line) or _ANNEX_NOISE.search(line):
                continue
            if _STATE_SERIAL.match(line):
                expecting_state = True
                continue
            if expecting_state:
                state, expecting_state = normalize_state(line) or line, False
                continue
            match = _DISTRICT_LINE.match(line)
            if match and state:
                name = _CLOSING_QUOTE.sub("", match["name"]).strip()
                if name:
                    entries.append((state, name))
    return entries


def _compact(name: str) -> str:
    return norm_district(name).replace(" ", "")


def _variant_score(left: str, right: str) -> tuple[float, str]:
    if DISTRICT_RENAMES.get(left) == right or DISTRICT_RENAMES.get(right) == left:
        return 1.0, "curated_rename"
    if min(len(left), len(right)) >= 4 and (left.startswith(right) or right.startswith(left)):
        return 0.9, "abbreviation"
    return SequenceMatcher(None, left, right).ratio(), "spelling_variant"


def validate_against_gazette(records: list[DistrictRecord], annex: list[tuple[str, str]]) -> GazetteValidation:
    """Pair phase-wise districts with the Gazette annex: exact names first, then renames/spelling variants
    within the same state. Unpaired entries on either side are reported, never dropped."""
    by_state: dict[str | None, list[tuple[int, str]]] = defaultdict(list)
    for index, (state, name) in enumerate(annex):
        by_state[state].append((index, name))
    used: set[int] = set()
    matched_pairs: set[tuple[str | None, str]] = set()
    notes: dict[int, str] = {}
    unmatched: list[DistrictRecord] = []

    for record in records:
        compact = _compact(record.district)
        hit = next((index for index, name in by_state[record.state] if index not in used and _compact(name) == compact), None)
        if hit is None:
            unmatched.append(record)
            continue
        used.add(hit)
        matched_pairs.add((record.state, record.district))
        notes[record.sr_no] = "Listed in the Gazette annex."

    candidates = []
    for record in unmatched:
        for index, name in by_state[record.state]:
            if index in used:
                continue
            score, basis = _variant_score(_compact(record.district), _compact(name))
            if score >= _MIN_VARIANT_SCORE:
                candidates.append((score, record, index, name, basis))
    variants = []
    paired: set[int] = set()
    for score, record, index, name, basis in sorted(candidates, key=lambda candidate: -candidate[0]):
        if record.sr_no in paired or index in used:
            continue
        paired.add(record.sr_no)
        used.add(index)
        variants.append((record.state, record.district, name, basis))
        matched_pairs.add((record.state, record.district))
        notes[record.sr_no] = f"Gazette annex lists this district as '{name}' ({basis.replace('_', ' ')})."

    missing = []
    for record in unmatched:
        if record.sr_no not in paired:
            missing.append((record.state, record.district))
            notes[record.sr_no] = "Not found in the Gazette annex."
    return GazetteValidation(
        matched=len(records) - len(missing),
        matched_pairs=frozenset(matched_pairs),
        variants=tuple(variants),
        missing_in_gazette=tuple(missing),
        extra_in_gazette=tuple(annex[index] for index in range(len(annex)) if index not in used),
        notes=notes,
    )
