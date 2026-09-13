"""Product Manual parsing (plan Task 4.1).

BIS Product Manuals follow a common template: a numbered summary (product, sampling guidelines, test
equipment, Scheme of Inspection and Testing, tests per day, scope of licence, other guidelines) that
refers to annexes A–E. The parser splits a manual into keyed sections with page ranges and extracts the
tables used by compliance journeys:

* test equipment rows with the clause references of each test;
* the Scheme of Inspection and Testing (levels of control) — cells that are visually merged across rows
  in the PDF are carried forward and flagged ``merged_from_previous``; blanks are never guessed otherwise;
* scope-of-licence fields.

Official wording is kept as-is; nothing is summarised or invented.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from manakmarg.ingest.documents import pdf_pages
from manakmarg.normalize.is_number import extract_designations
from manakmarg.normalize.text import clean_ws

_PRIVATE_USE = re.compile("[-]")
_DOCUMENT_NO = re.compile(r"PM\s*/\s*IS\s*([0-9][^/\n]*?)\s*/\s*(\d+)\s*/\s*([A-Za-z]+\s*\d{4})")
_PAGE_HEADER = re.compile(r"^(?:Doc(?:ument)?\s*(?:No\.?)?\s*[:.-]?\s*)?PM\s*/\s*IS\b.*\d{4}\s*$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
_ANNEX_HEADING = re.compile(r"^ANNEX\s*[-–—]?\s*([A-Z])\s*$")
_ANNEX_REFERENCE = re.compile(r"ANNEX\s*[-–—]?\s*([A-Z])\b", re.IGNORECASE)
_ANNEX_IN_TEXT = re.compile(r"\bAnnex\s+([A-Z])\b")
_FOOTER = re.compile(r"\bBUREAU OF INDIAN\b")
_CLAUSE = re.compile(r"Cl\.\s*(\d+(?:\.\d+)*)(?:\s*(?:&|and)\s*(\d+(?:\.\d+)*))?", re.IGNORECASE)
_SERIAL = re.compile(r"^(\d{1,3})\.?$")

_SUMMARY_LABELS = (
    ("product", r"1\.\s*Product\s*:"),
    ("title", r"\bTitle\s*:"),
    ("amendments", r"No\.?\s*of\s*Amendments?\s*:"),
    ("sampling_guidelines", r"2\.\s*Sampling\s+Guidelines\s*:?"),
    ("raw_material", r"a\)\s*Raw\s+materials?\s*:"),
    ("grouping_guidelines", r"b\)\s*Grouping\s+guidelines\s*:"),
    ("sample_size", r"c\)\s*Sample\s+Size\s*:"),
    ("test_equipment", r"3\.\s*List\s+of\s+Test\s+Equipment\s*:"),
    ("scheme_of_inspection_and_testing", r"4\.\s*Scheme\s+of\s+Inspection\s+and\s+Testing\s*:"),
    ("tests_per_day", r"5\.\s*Possible\s+tests\s+in\s+a\s+day\s*:"),
    ("scope_of_licence", r"6\.\s*Scope\s+of\s+the\s+Licen[cs]e\s*:"),
    ("other_guidelines", r"7\.\s*Any\s+other\s+product\s+specific\s+guidelines\s*:"),
)
_SECTION_BY_SUMMARY_KEY = {
    "grouping_guidelines": "grouping",
    "test_equipment": "test_equipment",
    "scheme_of_inspection_and_testing": "sit",
    "scope_of_licence": "scope_of_licence",
    "other_guidelines": "other_guidelines",
}
_SECTION_BY_TITLE = (
    ("grouping", "grouping"),
    ("test equipment", "test_equipment"),
    ("inspection", "sit"),
    ("scope of licen", "scope_of_licence"),
)
_JOINING_WORDS = frozenset({"with", "of", "for", "and", "or", "per", "from", "a", "an", "the", "to", "in", "on", "by", "IS"})


@dataclass(frozen=True)
class ManualPage:
    number: int
    text: str
    tables: list = field(default_factory=list)


@dataclass(frozen=True)
class ManualSection:
    section_key: str
    heading: str
    page_start: int
    page_end: int
    text: str
    structured: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedManual:
    document_no: str | None
    product_standard: str | None
    product_title: str | None
    amendments: str | None
    summary: dict
    sections: list[ManualSection]


def pages_from_pdf(source: Path | bytes) -> list[ManualPage]:
    return [ManualPage(number=page["page"], text=page["text"], tables=page["tables"]) for page in pdf_pages(source)]


# --------------------------------------------------------------------------- helpers


def _cell(value) -> str:
    return clean_ws(_PRIVATE_USE.sub(" ", value or ""))


def _page_lines(page: ManualPage) -> list[str]:
    lines = []
    for raw_line in page.text.splitlines():
        line = clean_ws(_PRIVATE_USE.sub("•", raw_line))
        if not line or _PAGE_HEADER.match(line) or _PAGE_NUMBER.match(line):
            continue
        lines.append(line)
    return lines


def _document_no(pages: list[ManualPage]) -> str | None:
    for page in pages:
        match = _DOCUMENT_NO.search(page.text)
        if match:
            number, revision, dated = (clean_ws(group) for group in match.groups())
            return f"PM/IS {number}/{revision}/{dated}"
    return None


def _summary_values(text: str) -> dict[str, str]:
    found = []
    position = 0
    for key, pattern in _SUMMARY_LABELS:
        match = re.compile(pattern, re.IGNORECASE).search(text, position)
        if match:
            found.append((key, match.start(), match.end()))
            position = match.end()
    values = {}
    for index, (key, _start, end) in enumerate(found):
        stop = found[index + 1][1] if index + 1 < len(found) else len(text)
        value = text[end:stop]
        footer = _FOOTER.search(value)
        if footer:
            value = value[: footer.start()]
        value = value.strip(" :•")
        if value:
            values[key] = value
    return values


def _summary(pages: list[ManualPage]) -> tuple[int | None, str, dict[str, str]]:
    for page in pages:
        text = clean_ws(_PRIVATE_USE.sub("•", page.text))
        if re.search(_SUMMARY_LABELS[0][1], text, re.IGNORECASE):
            return page.number, text, _summary_values(text)
    return None, "", {}


def _equipment_items(value: str | None) -> list[str]:
    items: list[str] = []
    for part in _PRIVATE_USE.sub(" ", value or "").split("\n"):
        line = clean_ws(part)
        if not line:
            continue
        previous_words = items[-1].split() if items else []
        if items and (
            items[-1].endswith(",") or previous_words[-1] in _JOINING_WORDS or line[0].islower() or line[0].isdigit()
        ):
            items[-1] = f"{items[-1]} {line}"
        else:
            items.append(line)
    return [item.strip(" ,") for item in items]


def _tables_between(pages: list[ManualPage], first: int, last: int):
    for page in pages:
        if first <= page.number <= last:
            yield from page.tables


def _test_equipment(tables) -> dict:
    tests = []
    for table in tables:
        for raw_row in table:
            if len(raw_row) != 3:
                continue
            cells = [_cell(value) for value in raw_row]
            serial = _SERIAL.match(cells[0])
            if not serial:
                continue
            description = cells[1]
            tests.append(
                {
                    "sl": serial.group(1),
                    "test": re.split(r",?\s*Cl\.", description, maxsplit=1)[0].strip(" ,"),
                    "clauses": [value for match in _CLAUSE.finditer(description) for value in match.groups() if value],
                    "equipment": _equipment_items(raw_row[2]),
                    "standards": [designation.std_key for designation in extract_designations(description)],
                    "annexes": _ANNEX_IN_TEXT.findall(description),
                }
            )
    return {"tests": tests}


def _is_sit_header(cells: list[str]) -> bool:
    return (
        cells[0] in {"(1)", "Cl.", "Test Details"}
        or (not cells[0] and not cells[1] and cells[2] == "Clause")
        or "No. of Sample" in cells
    )


def _scheme_of_inspection(tables) -> dict:
    rows: list[dict] = []
    group = None
    last_clause = last_requirement = None
    previous: dict | None = None
    for table in tables:
        for raw_row in table:
            if len(raw_row) < 8:
                continue
            cells = [_cell(value) for value in raw_row]
            if _is_sit_header(cells):
                continue
            clause, requirement, method, reference, code, samples = cells[:6]
            if len(cells) >= 9:
                frequency = cells[6] or cells[7]
                remarks = cells[8]
            else:
                frequency, remarks = cells[6], cells[7]
            if not (method or reference or code):
                if requirement:
                    group = requirement
                    last_clause = clause or last_clause
                continue
            clause = clause or last_clause
            requirement = requirement or last_requirement
            merged = False
            if not samples and not frequency and previous is not None:
                samples, frequency = previous["samples"], previous["frequency"]
                remarks = remarks or previous["remarks"]
                merged = True
            row = {
                "clause": clause,
                "requirement": requirement,
                "test_method_clause": method,
                "reference": reference,
                "equipment_requirement": code,
                "samples": samples,
                "frequency": frequency,
                "remarks": remarks,
                "group": group,
                "merged_from_previous": merged,
            }
            rows.append(row)
            previous = row
            last_clause, last_requirement = clause, requirement
    return {"rows": rows}


def _scope_of_licence(tables) -> dict:
    fields: list[str] = []
    values: dict[str, str] = {}
    for table in tables:
        for raw_row in table:
            cells = [_cell(value) for value in raw_row]
            if len(cells) < 2 or not cells[0]:
                continue
            if re.search(r"licen[cs]e is granted", cells[0], re.IGNORECASE):
                continue
            fields.append(cells[0])
            if cells[1]:
                values[cells[0]] = cells[1]
    return {"fields": fields, "values": values}


_STRUCTURED = {
    "test_equipment": _test_equipment,
    "sit": _scheme_of_inspection,
    "scope_of_licence": _scope_of_licence,
}


def _key_from_title(title: str) -> str:
    lowered = title.lower()
    for needle, key in _SECTION_BY_TITLE:
        if needle in lowered:
            return key
    return "other_guidelines"


# --------------------------------------------------------------------------- public API


def parse_product_manual(pages: list[ManualPage]) -> ParsedManual:
    summary_page, summary_text, summary = _summary(pages)

    flat = [(page.number, line) for page in pages for line in _page_lines(page)]
    headings = []
    for index, (page_number, line) in enumerate(flat):
        match = _ANNEX_HEADING.match(line)
        if match:
            title = next((candidate for _, candidate in flat[index + 1 : index + 4] if not _ANNEX_HEADING.match(candidate)), "")
            headings.append((match.group(1), index, page_number, title))

    letter_to_key: dict[str, str] = {}
    for summary_key, section_key in _SECTION_BY_SUMMARY_KEY.items():
        reference = _ANNEX_REFERENCE.search(summary.get(summary_key, ""))
        if reference:
            letter_to_key.setdefault(reference.group(1).upper(), section_key)

    sections: list[ManualSection] = []
    if summary_page is not None:
        sections.append(
            ManualSection("summary", "Product manual summary", summary_page, summary_page, summary_text, dict(summary))
        )
    for number, (letter, start_index, page_start, title) in enumerate(headings):
        end_index = headings[number + 1][1] if number + 1 < len(headings) else len(flat)
        body = flat[start_index + 1 : end_index]
        key = letter_to_key.get(letter) or _key_from_title(title)
        page_end = body[-1][0] if body else page_start
        builder = _STRUCTURED.get(key)
        structured = builder(list(_tables_between(pages, page_start, page_end))) if builder else {}
        sections.append(
            ManualSection(
                section_key=key,
                heading=title,
                page_start=page_start,
                page_end=page_end,
                text="\n".join(line for _, line in body),
                structured=structured,
            )
        )

    return ParsedManual(
        document_no=_document_no(pages),
        product_standard=summary.get("product"),
        product_title=summary.get("title"),
        amendments=summary.get("amendments"),
        summary=summary,
        sections=sections,
    )
