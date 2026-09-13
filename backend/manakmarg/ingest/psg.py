"""Product Specific Guidelines page parser (plan Task 4.1).

The official page is one table of IS-wise documents (IS No., title, size, format, view/download link).
BIS lists them as Product Manuals; grouping guidelines and the Scheme of Inspection and Testing usually
sit inside a manual as annexes, so the document kind is only refined when the official file name says so.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from manakmarg.ingest.html_grid import distinct_cells, table_to_grid

_HEADER_FIRST_CELL = re.compile(r"S(?:r|l)\.?\s*No\.?", re.IGNORECASE)
_SIT_TOKEN = re.compile(r"(?<![a-z])sit(?![a-z])")


@dataclass(frozen=True)
class GuidelineRecord:
    sr_no_raw: str | None
    is_ref_raw: str
    title: str
    size_text: str | None
    format_text: str | None
    url: str
    doc_kind: str
    locator: str


def classify_guideline(url: str, title: str | None) -> str:
    file_name = unquote(PurePosixPath(urlsplit(url).path).name).lower().replace("_", "-")
    if "amend" in file_name:
        return "PRODUCT_MANUAL_AMENDMENT"
    if "grouping" in file_name:
        return "GROUPING_GUIDELINE"
    if _SIT_TOKEN.search(file_name) or "scheme of inspection" in (title or "").lower():
        return "PRODUCT_MANUAL_WITH_SIT"
    return "PRODUCT_MANUAL"


def parse_psg(html: bytes | str, page_url: str) -> list[GuidelineRecord]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="myTable") or soup.find("table")
    if table is None:
        return []
    records: list[GuidelineRecord] = []
    for row_index, row in enumerate(table_to_grid(table)):
        cells = distinct_cells(row)
        if not cells or _HEADER_FIRST_CELL.fullmatch(cells[0].text):
            continue
        serial, reference, title, size, file_format, view, download = (list(row) + [None] * 7)[:7]
        link = next(
            (
                candidate
                for cell in (view, download)
                if cell is not None
                for candidate in cell.links
                if candidate.href and not candidate.href.startswith("#")
            ),
            None,
        )
        if link is None or reference is None or not reference.text:
            continue
        url = urljoin(page_url, link.href)
        title_text = title.text if title is not None else ""
        records.append(
            GuidelineRecord(
                sr_no_raw=(serial.text or None) if serial is not None else None,
                is_ref_raw=reference.text,
                title=title_text,
                size_text=(size.text or None) if size is not None else None,
                format_text=(file_format.text or None) if file_format is not None else None,
                url=url,
                doc_kind=classify_guideline(url, title_text),
                locator=f"table!row{row_index}",
            )
        )
    return records
