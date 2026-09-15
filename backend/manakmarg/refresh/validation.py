"""Checks on a downloaded BIS export before it can reach the database.

A file passes only when it is a readable .xlsx workbook with the expected columns and heading, holds data rows, and
its designations parse. Anything else is a problem and the whole refresh stops; small differences (a row count a
little off the portal's count) are recorded as warnings.
"""

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from manakmarg.ingest.excel_standards import classify_export, read_export
from manakmarg.normalize.is_number import parse_designation
from manakmarg.normalize.text import clean_ws

# The data columns of every Published Standards export (the leading "Sl#" is optional).
REQUIRED_COLUMNS = ("Standard Number", "Date of Publish", "Title", "Type of Standard", "Degree of Equivalence")
XLSX_SIGNATURE = b"PK\x03\x04"
MAX_UNPARSEABLE_RATIO = 0.01


@dataclass
class FileCheck:
    file: str
    kind: str
    ok: bool = False
    rows: int = 0
    title: str | None = None
    generated_on: str | None = None
    classification: str | None = None
    unparseable: int = 0
    repeated_rows: int = 0
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _header_columns(path: Path) -> set[str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for row in workbook.worksheets[0].iter_rows(min_row=1, max_row=10, values_only=True):
            names = {clean_ws(str(cell)) for cell in row if cell is not None and clean_ws(str(cell))}
            if "Standard Number" in names:
                return names
    finally:
        workbook.close()
    return set()


def _same_name(left: str, right: str) -> bool:
    return clean_ws(left).casefold() == clean_ws(right).casefold()


def check_export(
    path: Path,
    *,
    kind: str,
    expected_title: str | None = None,
    expected_rows: int | None = None,
    min_row_ratio: float = 0.9,
) -> FileCheck:
    """Validate one export. ``kind`` is ``total`` (heading must be "Total") or ``ministry`` (heading = ministry name)."""
    path = Path(path)
    check = FileCheck(file=path.name, kind=kind)
    try:
        with open(path, "rb") as handle:
            signature = handle.read(4)
    except OSError as exc:
        check.problems.append(f"file cannot be read: {exc}")
        return check
    if signature != XLSX_SIGNATURE:
        check.problems.append("not an Excel .xlsx workbook")
        return check
    try:
        columns = _header_columns(path)
        export = read_export(path)
    except ValueError as exc:
        check.problems.append(f"missing header row: {exc}")
        return check
    except Exception as exc:  # openpyxl raises several unrelated exception types for damaged workbooks
        check.problems.append(f"corrupt workbook: {type(exc).__name__}: {exc}")
        return check

    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        check.problems.append(f"missing columns: {', '.join(missing)}")
    check.rows = len(export.rows)
    check.title = export.title_cell
    check.generated_on = export.generated_on.isoformat() if export.generated_on else None
    check.classification = classify_export(export)
    if not export.rows:
        check.problems.append("no data rows")

    if kind == "total" and check.classification != "total_export":
        check.problems.append(f"heading is {export.title_cell!r}, expected 'Total'")
    elif kind == "ministry":
        if not export.title_cell:
            check.problems.append("heading is empty; expected the ministry name")
        elif expected_title and not _same_name(export.title_cell, expected_title):
            check.problems.append(f"heading {export.title_cell!r} does not match the ministry {expected_title!r}")

    if expected_rows is not None and export.rows:
        if check.rows < expected_rows * min_row_ratio:
            check.problems.append(f"{check.rows} rows, but the portal lists {expected_rows} standards")
        elif check.rows != expected_rows:
            check.warnings.append(f"{check.rows} rows; the portal lists {expected_rows} standards")

    designations = [row.designation_raw for row in export.rows]
    check.unparseable = sum(1 for raw in designations if parse_designation(raw) is None)
    if designations and check.unparseable / len(designations) > MAX_UNPARSEABLE_RATIO:
        check.problems.append(f"{check.unparseable} of {len(designations)} standard numbers cannot be parsed")
    elif check.unparseable:
        check.warnings.append(f"{check.unparseable} standard number(s) cannot be parsed and will be rejected")
    check.repeated_rows = len(designations) - len(set(designations))
    check.ok = not check.problems
    return check
