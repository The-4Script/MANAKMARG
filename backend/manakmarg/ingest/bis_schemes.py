"""Parsers for the BIS compulsory-certification listing pages (plan Task 3.2).

Each parser turns one official page into ``CoverageRecord`` objects: one per listed product line, plus
``illustrative_item`` records for the example lists that some rows carry (e.g. the appliances under
IS 302 (Part 1)). Listing status comes from ``classify_listing`` with the quoted page text as basis;
orders come from the links in the notification cell. Parsers never infer a standard, product or status
that the page does not state.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup, Comment, Declaration, Doctype, ProcessingInstruction, Tag

from manakmarg.ingest.html_grid import GridCell, distinct_cells, origin_cells, table_to_grid
from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.is_number import extract_designations
from manakmarg.normalize.orders import OrderRef, parse_order_links
from manakmarg.normalize.status_rules import classify_listing
from manakmarg.normalize.text import clean_ws

LISTING = "listing"
ILLUSTRATIVE_ITEM = "illustrative_item"

_HEADER_FIRST_CELL = re.compile(r"S(?:r|l)\.?\s*No\.?", re.IGNORECASE)
_NON_CONTENT_STRINGS = (Comment, Declaration, Doctype, ProcessingInstruction)
_DASHES_ONLY = re.compile(r"[-–—\s]+")


@dataclass
class CoverageRecord:
    page_kind: str
    scheme_id: str | None
    product_name: str
    listing_status: str
    status_basis: str
    locator: str
    section_label: str | None = None
    category: str | None = None
    sr_no_raw: str | None = None
    standard_ref_raw: str | None = None
    standard_title_raw: str | None = None
    product_category: str | None = None
    essential_requirement: str | None = None
    specific_requirement: str | None = None
    notification_text: str | None = None
    orders: list[OrderRef] = field(default_factory=list)
    standard_refs: list[tuple[str, str]] = field(default_factory=list)
    refs_assume_is_prefix: bool = False
    ministry_department: str | None = None
    enforcement_date: date | None = None
    enforcement_date_raw: str | None = None
    notes: str | None = None
    item_kind: str = LISTING
    parent_locator: str | None = None


# --------------------------------------------------------------------------- helpers


def _soup(html: bytes | str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(cell: GridCell | None) -> str | None:
    return cell.text or None if cell is not None else None


_LEADING_ENUMERATION = re.compile(r"^\s*\d{1,3}\s*[.)]\s*")
_HAS_WORD = re.compile(r"[A-Za-z]{3}")


def _link_contexts(cell: GridCell) -> list[tuple[str, str, str | None]]:
    """Pair each link with its context: text before it on the same line, else the closest preceding
    line of the cell that holds no link (typically the order name written above the S.O. link)."""
    pending = list(cell.links)
    paired: list[tuple[str, str, str | None]] = []
    context: str | None = None
    for line in cell.lines:
        offset = 0
        matched = False
        while pending:
            link = pending[0]
            if not link.text:
                paired.append((link.text, link.href, context))
                pending.pop(0)
                continue
            position = line.find(link.text, offset)
            if position < 0:
                break
            before = _LEADING_ENUMERATION.sub("", line[offset:position]).strip(" ,;:–-")
            paired.append((link.text, link.href, before if _HAS_WORD.search(before) else context))
            offset = position + len(link.text)
            pending.pop(0)
            matched = True
        if not matched:
            context = line
    paired.extend((link.text, link.href, context) for link in pending)
    return paired


def _orders(cell: GridCell | None, page_url: str) -> list[OrderRef]:
    if cell is None:
        return []
    return parse_order_links(_link_contexts(cell), page_url)


def _positions(row: list[GridCell | None], count: int) -> list[GridCell | None]:
    return (list(row) + [None] * count)[:count]


def _is_header_row(cells: list[GridCell]) -> bool:
    return bool(cells) and bool(_HEADER_FIRST_CELL.fullmatch(cells[0].text))


def _top_level_tables(soup: BeautifulSoup) -> list[Tag]:
    return [table for table in soup.find_all("table") if table.find_parent("table") is None]


def _category_text(cells: list[GridCell], width: int, row_index: int) -> str | None:
    """Text of a category row: one cell spanning (nearly) the whole table, other cells empty."""
    first = cells[0]
    if first.origin_row != row_index or first.colspan < max(width - 1, 2):
        return None
    if any(cell.text for cell in cells[1:]):
        return None
    return first.text or None


def _section_label(table: Tag) -> str | None:
    """Closest text before ``table`` that is not inside another table (e.g. a scheme sub-list heading)."""
    for string in table.find_all_previous(string=True):
        if isinstance(string, _NON_CONTENT_STRINGS):
            continue
        text = clean_ws(str(string))
        if not text or _DASHES_ONLY.fullmatch(text):
            continue
        if string.find_parent("table") is not None:
            return None
        block = string.find_parent(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"])
        label = clean_ws(block.get_text(" ")) if block is not None and block.find("table") is None else text
        label = label.strip("-–— ")
        if label:
            return label
    return None


def _specified_refs(cell: GridCell | None) -> list[tuple[str, str]]:
    return [(cell.text, "specified")] if cell is not None and cell.text else []


def _attach_note(records: list[CoverageRecord], category: str | None, note: str) -> None:
    in_category = []
    for record in reversed(records):
        if record.category != category:
            break
        in_category.append(record)
    starred = [
        record
        for record in in_category
        if "*" in (record.product_name or "") or "*" in (record.standard_ref_raw or "")
    ]
    for record in starred or in_category[:1]:
        record.notes = f"{record.notes} {note}".strip() if record.notes else note


# --------------------------------------------------------------------------- Scheme I


def parse_scheme_i(html: bytes | str, page_url: str) -> list[CoverageRecord]:
    soup = _soup(html)
    table = soup.select_one("div.schdesktop table") or soup.find("table")
    if table is None:
        return []
    grid = table_to_grid(table)
    width = max((len(row) for row in grid), default=0)
    records: list[CoverageRecord] = []
    category = None

    for row_index, row in enumerate(grid):
        cells = distinct_cells(row)
        if not cells or _is_header_row(cells):
            continue
        category_text = _category_text(cells, width, row_index)
        if category_text is not None:
            if category_text.startswith("*"):
                _attach_note(records, category, category_text)
            else:
                category = category_text
            continue

        serial, standard, product, notification = _positions(row, 4)
        product_name = _text(product)
        if not product_name:
            continue
        origins = origin_cells(grid, row_index)
        illustrative = (
            len(origins) == 1 and origins[0] is product and standard is not None and standard.origin_row < row_index
        )
        notification_text = _text(notification)
        decision = classify_listing("scheme_i", category, product_name, notification_text)
        records.append(
            CoverageRecord(
                page_kind="scheme_i",
                scheme_id="SCHEME_I",
                product_name=product_name,
                listing_status=decision.status,
                status_basis=decision.basis,
                locator=f"desktop_table!row{row_index}",
                category=category,
                sr_no_raw=_text(serial),
                standard_ref_raw=_text(standard),
                notification_text=notification_text,
                orders=_orders(notification, page_url),
                standard_refs=_specified_refs(standard),
                item_kind=ILLUSTRATIVE_ITEM if illustrative else LISTING,
                parent_locator=f"desktop_table!row{standard.origin_row}" if illustrative else None,
            )
        )
    return records


# --------------------------------------------------------------------------- Scheme II


def parse_scheme_ii(html: bytes | str, page_url: str) -> list[CoverageRecord]:
    soup = _soup(html)
    records: list[CoverageRecord] = []
    for table_index, table in enumerate(_top_level_tables(soup)):
        section = _section_label(table)
        grid = table_to_grid(table)
        for row_index, row in enumerate(grid):
            cells = distinct_cells(row)
            if not cells or _is_header_row(cells):
                continue
            serial, standard, title, product, notification = _positions(row, 5)
            product_name = _text(product)
            if not product_name:
                continue
            notification_text = _text(notification)
            decision = classify_listing("scheme_ii", section, product_name, notification_text)
            records.append(
                CoverageRecord(
                    page_kind="scheme_ii",
                    scheme_id="SCHEME_II",
                    product_name=product_name,
                    listing_status=decision.status,
                    status_basis=decision.basis,
                    locator=f"table{table_index}!row{row_index}",
                    section_label=section,
                    sr_no_raw=_text(serial),
                    standard_ref_raw=_text(standard),
                    standard_title_raw=_text(title),
                    product_category=product_name,
                    notification_text=notification_text,
                    orders=_orders(notification, page_url),
                    standard_refs=_specified_refs(standard),
                )
            )
    return records


# --------------------------------------------------------------------------- Scheme IV


def parse_scheme_iv(html: bytes | str, page_url: str) -> list[CoverageRecord]:
    soup = _soup(html)
    table = soup.select_one("div.schdesktop table") or soup.find("table")
    if table is None:
        return []
    grid = table_to_grid(table)
    records: list[CoverageRecord] = []
    for row_index, row in enumerate(grid):
        cells = distinct_cells(row)
        if not cells or _is_header_row(cells):
            continue
        serial, product, requirement, notification = _positions(row, 4)
        product_name = _text(product)
        if not product_name:
            continue
        requirement_text = _text(requirement)
        notification_text = _text(notification)
        decision = classify_listing("scheme_iv", None, product_name, notification_text)
        records.append(
            CoverageRecord(
                page_kind="scheme_iv",
                scheme_id="SCHEME_IV",
                product_name=product_name,
                listing_status=decision.status,
                status_basis=decision.basis,
                locator=f"desktop_table!row{row_index}",
                sr_no_raw=_text(serial),
                essential_requirement=requirement_text,
                notification_text=notification_text,
                orders=_orders(notification, page_url),
                standard_refs=[(requirement_text, "referenced_in_requirement")] if requirement_text else [],
            )
        )
    return records


# --------------------------------------------------------------------------- Scheme X


def _scheme_x_detailed_row(row, section, table_index, row_index, page_url) -> CoverageRecord | None:
    serial, standard, title, product, requirement, notification = _positions(row, 6)
    product_name = _text(product)
    if not product_name:
        return None
    notification_text = _text(notification)
    decision = classify_listing("scheme_x", section, product_name, notification_text)
    return CoverageRecord(
        page_kind="scheme_x",
        scheme_id="SCHEME_X",
        product_name=product_name,
        listing_status=decision.status,
        status_basis=decision.basis,
        locator=f"table{table_index}!row{row_index}",
        section_label=section,
        sr_no_raw=_text(serial),
        standard_ref_raw=_text(standard),
        standard_title_raw=_text(title),
        product_category=product_name,
        specific_requirement=_text(requirement),
        notification_text=notification_text,
        orders=_orders(notification, page_url),
        standard_refs=_specified_refs(standard),
    )


def _scheme_x_description_row(row, section, table_index, row_index, page_url) -> CoverageRecord | None:
    serial, description, standards = _positions(row, 3)
    product_name = _text(description)
    if not product_name:
        return None
    standards_text = _text(standards)
    requirement = standards.lines[0] if standards is not None and standards.lines else None
    role = "type_a" if requirement and re.search(r"\btype\s+a\b", requirement, re.IGNORECASE) else "specified"
    references = [(designation.raw, role) for designation in extract_designations(requirement)] if requirement else []
    decision = classify_listing("scheme_x", section, product_name, standards_text)
    return CoverageRecord(
        page_kind="scheme_x",
        scheme_id="SCHEME_X",
        product_name=product_name,
        listing_status=decision.status,
        status_basis=decision.basis,
        locator=f"table{table_index}!row{row_index}",
        section_label=section,
        sr_no_raw=_text(serial),
        specific_requirement=requirement,
        notification_text=standards_text,
        orders=_orders(standards, page_url),
        standard_refs=references,
    )


def parse_scheme_x(html: bytes | str, page_url: str) -> list[CoverageRecord]:
    soup = _soup(html)
    records: list[CoverageRecord] = []
    for table_index, table in enumerate(_top_level_tables(soup)):
        section = _section_label(table)
        grid = table_to_grid(table)
        width = max((len(row) for row in grid), default=0)
        build = _scheme_x_detailed_row if width >= 6 else _scheme_x_description_row
        for row_index, row in enumerate(grid):
            cells = distinct_cells(row)
            if not cells or _is_header_row(cells):
                continue
            record = build(row, section, table_index, row_index, page_url)
            if record is not None:
                records.append(record)
    return records


# --------------------------------------------------------------------------- Upcoming QCOs


def parse_upcoming_qcos(html: bytes | str, page_url: str) -> list[CoverageRecord]:
    soup = _soup(html)
    table = soup.find("table", id="myTable") or soup.find("table")
    if table is None:
        return []
    grid = table_to_grid(table)
    records: list[CoverageRecord] = []
    for row_index, row in enumerate(grid):
        cells = distinct_cells(row)
        if len(cells) < 5 or _is_header_row(cells):
            continue
        serial, ministry, product, standard, enforcement = cells[:5]
        product_name = product.text
        if not product_name:
            continue
        origins = origin_cells(grid, row_index)
        illustrative = len(origins) == 1 and origins[0] is product and serial.origin_row < row_index
        date_raw = enforcement.text or None
        decision = classify_listing("upcoming_qco", None, product_name, None)
        records.append(
            CoverageRecord(
                page_kind="upcoming_qco",
                scheme_id=None,
                product_name=product_name,
                listing_status=decision.status,
                status_basis=decision.basis,
                locator=f"table!row{row_index}",
                sr_no_raw=serial.text or None,
                standard_ref_raw=standard.text or None,
                ministry_department=ministry.text or None,
                enforcement_date=parse_date(date_raw),
                enforcement_date_raw=date_raw,
                standard_refs=[(standard.text, "specified")] if standard.text else [],
                refs_assume_is_prefix=True,
                item_kind=ILLUSTRATIVE_ITEM if illustrative else LISTING,
                parent_locator=f"table!row{serial.origin_row}" if illustrative else None,
            )
        )
    return records
