"""HSN master workbook → ``hsn_code`` rows.

The workbook is found by content, not by file name: the first ``.xlsx`` in the data directory with a sheet whose
header row is ``HSN_CD`` / ``HSN_Description``. Codes are kept exactly as written (as text, so leading zeros and the
occasional internal space survive) plus a digits-only form for lookup. Descriptions are stored verbatim — never
cleaned, reclassified or enriched — and nothing that is not in the workbook (tax rate, chapter name, ministry…) is
derived. The workbook itself is only read, never modified.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from sqlalchemy.engine import Engine

from manakmarg.ingest.runs import RunRecorder

SOURCE_ID = "hsn_master_workbook"
CODE_HEADER = "HSN_CD"
DESCRIPTION_HEADER = "HSN_Description"
_NON_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class HsnRecord:
    code: str
    code_digits: str
    description: str
    sheet_row: int


@dataclass
class HsnWorkbook:
    path: Path
    sheet_name: str
    records: list[HsnRecord]
    rejected: list[tuple[int, str]] = field(default_factory=list)
    duplicates: int = 0


def _header(row) -> tuple[str | None, str | None]:
    cells = [str(cell).strip() if cell is not None else None for cell in (row or ())[:2]]
    return (cells + [None, None])[0], (cells + [None, None])[1]


def find_hsn_workbook(data_dir: Path) -> tuple[Path, str] | None:
    """(workbook path, sheet name) of the HSN master in ``data_dir``, or ``None`` when no sheet has the HSN header."""
    for path in sorted(Path(data_dir).glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        try:
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception:  # unreadable or not a workbook; other ingestion reports those files
            continue
        try:
            for sheet in workbook.worksheets:
                first = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
                if _header(first) == (CODE_HEADER, DESCRIPTION_HEADER):
                    return path, sheet.title
        finally:
            workbook.close()
    return None


def read_hsn_workbook(path: Path, sheet_name: str) -> HsnWorkbook:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name]
        result = HsnWorkbook(Path(path), sheet_name, [])
        seen: set[str] = set()
        for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            raw_code = row[0] if row else None
            raw_description = row[1] if row and len(row) > 1 else None
            if raw_code is None and raw_description is None:
                continue
            code = str(raw_code).strip() if raw_code is not None else ""
            if isinstance(raw_code, int):  # a numeric cell would have lost its leading zero; keep what is shown
                code = str(raw_code)
            digits = _NON_DIGIT.sub("", code)
            description = raw_description if isinstance(raw_description, str) else (None if raw_description is None else str(raw_description))
            if not digits or not (2 <= len(digits) <= 8) or not code.replace(" ", "").isdigit():
                result.rejected.append((index, "code is not 2-8 digits"))
                continue
            if description is None or not description.strip():
                result.rejected.append((index, "empty description"))
                continue
            if code in seen:
                result.duplicates += 1
                continue
            seen.add(code)
            result.records.append(HsnRecord(code=code, code_digits=digits, description=description, sheet_row=index))
        return result
    finally:
        workbook.close()


def ingest_hsn(engine: Engine, data_dir: Path) -> dict:
    """Load the HSN master found in ``data_dir``; returns counts. Rows missing from a later workbook are retired."""
    found = find_hsn_workbook(data_dir)
    if found is None:
        return {"status": "not_found", "reason": "no .xlsx sheet with an HSN_CD / HSN_Description header"}
    path, sheet_name = found
    parsed = read_hsn_workbook(path, sheet_name)
    with RunRecorder(engine, SOURCE_ID, notes=f"{path.name}!{sheet_name}") as run:
        for record in parsed.records:
            run.upsert(
                "hsn_code",
                key={"code": record.code},
                values={
                    "code_digits": record.code_digits,
                    "code_length": len(record.code_digits),
                    "description": record.description,
                    "sheet_row": record.sheet_row,
                },
                locator=f"{path.name}!{sheet_name}!R{record.sheet_row}",
            )
        for row_number, reason in parsed.rejected:
            run.reject(f"{path.name}!{sheet_name}!R{row_number}", reason)
        run.retire_unseen("hsn_code")
    return {
        "file": path.name,
        "sheet": sheet_name,
        "records": len(parsed.records),
        "rejected": len(parsed.rejected),
        "duplicates_skipped": parsed.duplicates,
        **{key: run.stats[key] for key in ("inserted", "updated", "unchanged", "retired")},
        "run_id": run.run_id,
    }
