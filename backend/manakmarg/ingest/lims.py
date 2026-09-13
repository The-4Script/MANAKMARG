"""LIMS (lims.bis.gov.in) laboratory directories and Indian Standard-wise scope search (plan Task 5.1).

Only public listing pages are read: no login, CAPTCHA or undocumented API. The directory's contact-person
column is deliberately not captured; the organisation phone number and e-mail published for each laboratory
are. A laboratory is linked to an Indian Standard only through a scope-search row that LIMS itself publishes.
"""

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from manakmarg.ingest.html_grid import cell_lines
from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.geo import Address, parse_lims_address
from manakmarg.normalize.text import clean_ws

_EMPTY = {"-", "--", "none", "null", "n/a", "na"}
_ONLY_PUNCTUATION = re.compile(r"^[\s.\-_–—]*$")
_RESULTS = re.compile(r"^\s*(\d[\d,]*)\s+Results?\s*$", re.IGNORECASE)
_LAB_ID = re.compile(r"/home_lab_scope/(\d+)/?")
_ROW_ID = re.compile(r"^tr_(\d+)$")
_IS_REF = re.compile(r"^(?P<designation>.+?)\s*\(\s*(?P<year>\d{4})\s*\)\s*$")
_AMOUNT = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
_EXCLUSION = re.compile(r"\bExclusions?\s*[:\-–]\s*(?P<text>.+)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class LabRecord:
    category: str
    lims_lab_id: int | None
    osl_code: str | None
    name: str
    address_raw: str | None
    address: Address
    org_phone: str | None
    org_email: str | None
    validity_date: date | None
    validity_raw: str | None
    scope_url: str | None
    locator: str


@dataclass(frozen=True)
class LimsPage:
    labs: list[LabRecord]
    total_results: int | None
    total_pages: int
    page_urls: list[str]


@dataclass(frozen=True)
class ScopeItem:
    clause: str | None
    parameter: str | None
    exclusion: str | None
    charge: float | None
    charge_raw: str | None
    effective_date_raw: str | None
    remark: str | None


@dataclass(frozen=True)
class ScopeRecord:
    lims_row_id: int | None
    lab_name_raw: str
    osl_code_raw: str | None
    is_ref_raw: str
    designation_text: str
    version_year: int | None
    product: str | None
    grade_type: str | None
    charges_total: float | None
    charges_raw: str | None
    validity_date: date | None
    validity_raw: str | None
    remark_raw: str | None
    exclusions_text: str | None
    scope_file_url: str | None
    items: tuple[ScopeItem, ...]
    locator: str


@dataclass(frozen=True)
class ScopePage:
    rows: list[ScopeRecord]
    total_results: int | None
    total_pages: int
    page_urls: list[str]


# --------------------------------------------------------------------------- helpers


def _value(text: str | None) -> str | None:
    value = clean_ws(text)
    if value.lower() in _EMPTY or _ONLY_PUNCTUATION.match(value):
        return None
    return value


def _amount(text: str | None) -> float | None:
    value = _value(text)
    if value is None or not _AMOUNT.match(value):
        return None
    return float(value.replace(",", ""))


def _data_table(soup: BeautifulSoup) -> Tag | None:
    return soup.find("table", id="dataTable")


def _headers(table: Tag) -> list[str]:
    head = table.find("thead")
    return [clean_ws(cell.get_text(" ")).lower() for cell in head.find_all("th")] if head else []


def _column(headers: list[str], *prefixes: str) -> int | None:
    for index, header in enumerate(headers):
        if header.startswith(prefixes):
            return index
    return None


def _body_rows(table: Tag) -> list[Tag]:
    body = table.find("tbody") or table
    return [row for row in body.find_all("tr", recursive=False) if row.find("td", recursive=False)]


def _cell(cells: list[Tag], index: int | None) -> Tag | None:
    return cells[index] if index is not None and index < len(cells) else None


def _text(cell: Tag | None) -> str:
    return clean_ws(cell.get_text(" ")) if cell is not None else ""


def _with_page(url: str, number: int) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "page"]
    query.append(("page", str(number)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _pagination(soup: BeautifulSoup, page_url: str) -> tuple[int, list[str]]:
    """Total page count and the URLs of pages 2..N, built from the pagination links."""
    pages: dict[int, str] = {}
    for anchor in soup.select("ul.pagination a[href]"):
        url = urljoin(page_url, anchor["href"])
        number = dict(parse_qsl(urlsplit(url).query)).get("page", "")
        if number.isdigit():
            pages[int(number)] = url
    if not pages:
        return 1, []
    total = max(pages)
    return total, [_with_page(pages[total], number) for number in range(2, total + 1)]


def _total_results(soup: BeautifulSoup) -> int | None:
    for node in soup.find_all(string=_RESULTS):
        return int(_RESULTS.match(node).group(1).replace(",", ""))
    return None


def _direct_text_before_link(cell: Tag | None) -> str:
    parts: list[str] = []
    for child in cell.children if cell is not None else ():
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name in ("a", "br", "div", "table"):
            break
    return clean_ws(" ".join(parts))


def split_clause(text: str | None) -> tuple[str | None, str | None]:
    """``Cl-8.1 & 8.4, Table 7 (Tensile Strength)`` → (``Cl-8.1 & 8.4, Table 7``, ``Tensile Strength``)."""
    value = clean_ws(text)
    if not value:
        return None, None
    if value.endswith(")"):
        depth = 0
        for index in range(len(value) - 1, -1, -1):
            if value[index] == ")":
                depth += 1
            elif value[index] == "(":
                depth -= 1
                if depth == 0:
                    return value[:index].strip() or None, value[index + 1 : -1].strip() or None
    return value, None


def _breakup_items(cell: Tag | None) -> tuple[ScopeItem, ...]:
    table = cell.find("table") if cell is not None else None
    if table is None:
        return ()
    items = []
    for row in (table.find("tbody") or table).find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        clause, parameter = split_clause(cells[0].get_text(" "))
        charge_raw = _value(cells[2].get_text(" "))
        items.append(
            ScopeItem(
                clause=clause,
                parameter=parameter,
                exclusion=_value(cells[1].get_text(" ")),
                charge=_amount(charge_raw),
                charge_raw=charge_raw,
                effective_date_raw=_value(cells[3].get_text(" ")),
                remark=_value(cells[4].get_text(" ")),
            )
        )
    return tuple(items)


def exclusions_from_remark(remark: str | None) -> str | None:
    match = _EXCLUSION.search(remark or "")
    if not match:
        return None
    return clean_ws(match["text"]).strip(" ,;") or None


# --------------------------------------------------------------------------- public API


def parse_lims_directory(html: bytes | str, category: str, page_url: str) -> LimsPage:
    soup = BeautifulSoup(html, "lxml")
    table = _data_table(soup)
    labs: list[LabRecord] = []
    if table is not None:
        headers = _headers(table)
        code_index = _column(headers, "lab code", "osl")
        name_index = _column(headers, "lab name")
        address_index = _column(headers, "address")
        phone_index = _column(headers, "contact number", "phone")
        email_index = _column(headers, "email", "e-mail")
        validity_index = _column(headers, "validity")
        scope_index = _column(headers, "view scope")
        for row_number, row in enumerate(_body_rows(table), start=1):
            cells = row.find_all("td", recursive=False)
            name = _value(_text(_cell(cells, name_index)))
            if not name:
                continue
            scope_cell = _cell(cells, scope_index)
            anchor = scope_cell.find("a", href=True) if scope_cell is not None else None
            scope_url = urljoin(page_url, anchor["href"]) if anchor else None
            lab_id_match = _LAB_ID.search(scope_url or "") or _ROW_ID.match(row.get("id", ""))
            lab_id = int(lab_id_match.group(1)) if lab_id_match else None
            address_raw = _value(_text(_cell(cells, address_index)))
            validity_raw = _value(_text(_cell(cells, validity_index)))
            labs.append(
                LabRecord(
                    category=category,
                    lims_lab_id=lab_id,
                    osl_code=_value(_text(_cell(cells, code_index))),
                    name=name,
                    address_raw=address_raw,
                    address=parse_lims_address(address_raw),
                    org_phone=_value(_text(_cell(cells, phone_index))),
                    org_email=_value(_text(_cell(cells, email_index))),
                    validity_date=parse_date(validity_raw),
                    validity_raw=validity_raw,
                    scope_url=scope_url,
                    locator=f"lab-{lab_id}" if lab_id is not None else f"row-{row_number}",
                )
            )
    total_pages, page_urls = _pagination(soup, page_url)
    return LimsPage(labs=labs, total_results=_total_results(soup), total_pages=total_pages, page_urls=page_urls)


def parse_lims_scope_search(html: bytes | str, page_url: str) -> ScopePage:
    soup = BeautifulSoup(html, "lxml")
    table = _data_table(soup)
    rows: list[ScopeRecord] = []
    if table is not None:
        headers = _headers(table)
        lab_index = _column(headers, "lab name")
        osl_index = _column(headers, "osl")
        is_index = _column(headers, "indian standard")
        product_index = _column(headers, "product")
        grade_index = _column(headers, "grade")
        charges_index = _column(headers, "testing charges")
        validity_index = _column(headers, "validity")
        remark_index = _column(headers, "remark")
        for row_number, row in enumerate(_body_rows(table), start=1):
            cells = row.find_all("td", recursive=False)
            lab_name = _value(_text(_cell(cells, lab_index)))
            is_ref_raw = _value(_text(_cell(cells, is_index)))
            if not lab_name or not is_ref_raw:
                continue
            reference = _IS_REF.match(is_ref_raw)
            charges_cell = _cell(cells, charges_index)
            charges_raw = _value(_direct_text_before_link(charges_cell))
            remark_cell = _cell(cells, remark_index)
            remark_lines = [line for line in (cell_lines(remark_cell) if remark_cell is not None else ()) if _value(line)]
            remark_raw = " ".join(remark_lines) or None
            scope_anchor = remark_cell.find("a", href=True) if remark_cell is not None else None
            validity_raw = _value(_text(_cell(cells, validity_index)))
            row_id_match = _ROW_ID.match(row.get("id", ""))
            row_id = int(row_id_match.group(1)) if row_id_match else None
            rows.append(
                ScopeRecord(
                    lims_row_id=row_id,
                    lab_name_raw=lab_name,
                    osl_code_raw=_value(_text(_cell(cells, osl_index))),
                    is_ref_raw=is_ref_raw,
                    designation_text=reference["designation"] if reference else is_ref_raw,
                    version_year=int(reference["year"]) if reference else None,
                    product=_value(_text(_cell(cells, product_index))),
                    grade_type=_value(_text(_cell(cells, grade_index))),
                    charges_total=_amount(charges_raw),
                    charges_raw=charges_raw,
                    validity_date=parse_date(validity_raw),
                    validity_raw=validity_raw,
                    remark_raw=remark_raw,
                    exclusions_text=exclusions_from_remark(remark_raw),
                    scope_file_url=urljoin(page_url, scope_anchor["href"]) if scope_anchor else None,
                    items=_breakup_items(charges_cell),
                    locator=f"row-{row_id}" if row_id is not None else f"position-{row_number}",
                )
            )
    total_pages, page_urls = _pagination(soup, page_url)
    return ScopePage(rows=rows, total_results=_total_results(soup), total_pages=total_pages, page_urls=page_urls)
