"""Ingestion of BIS "Published Standards" Excel exports (spec §2.1; plan Task 2.3).

Every supplied workbook has one sheet: row 1 holds the classification title cell (C1:E1) and a
"Generated On" timestamp, row 2 holds the headers, data follows. The title cell decides how a file is
used:

* ``Total``                              → master list          (source ``bis_std_export_total``)
* empty                                  → second full export   (source ``bis_std_export_second``)
* ``Ministry of …`` / ``Department of …`` → ministry node        (source ``bis_std_exports_ministry``)
* anything else                          → reported and skipped (e.g. a future Department/Group export)

Standards are never merged across different canonical keys; two raw designations that collapse to
one key inside a file are rejected as ``canonical_collision`` for review.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import openpyxl
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from manakmarg.core.clock import IST
from manakmarg.db import schema
from manakmarg.ingest.runs import RunRecorder
from manakmarg.normalize.dates import parse_date
from manakmarg.normalize.is_number import Designation, parse_designation
from manakmarg.normalize.text import clean_ws, split_title

SOURCE_TOTAL = "bis_std_export_total"
SOURCE_SECOND = "bis_std_export_second"
SOURCE_MINISTRY = "bis_std_exports_ministry"

_REQUIRED_HEADERS = ("Standard Number", "Title")
_GENERATED_ON = re.compile(r"generated on:?\s*(.+)$", re.IGNORECASE)
_MINISTRY_TITLE = re.compile(r"^(?:Ministry|Department) of\b", re.IGNORECASE)
_UNSPECIFIED = {"-", "NULL"}


@dataclass(frozen=True)
class ExportRow:
    sheet_row: int
    sl_no: str | None
    designation_raw: str
    publish_date_raw: str | None
    title: str
    standard_type: str | None
    degree: str | None


@dataclass(frozen=True)
class ExportFile:
    path: Path
    sheet_name: str
    title_cell: str | None
    generated_on: datetime | None
    rows: list[ExportRow]


def _text(value) -> str | None:
    if value is None:
        return None
    text = clean_ws(str(value))
    return text or None


def _specified(value: str | None) -> str | None:
    return None if value is None or value in _UNSPECIFIED else value


def _parse_generated_on(text: str) -> datetime | None:
    match = _GENERATED_ON.search(text)
    stamp = clean_ws(match.group(1)) if match else text
    for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def read_export(path: Path) -> ExportFile:
    path = Path(path)
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        sheet_name = sheet.title
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    header_index = next(
        (
            index
            for index, row in enumerate(rows[:10])
            if row and all(name in {_text(cell) for cell in row} for name in _REQUIRED_HEADERS)
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path.name}: no header row with 'Standard Number' and 'Title'")
    columns = {_text(cell): index for index, cell in enumerate(rows[header_index]) if _text(cell)}

    title_cell = None
    generated_on = None
    for row in rows[:header_index]:
        for cell in row:
            text = _text(cell)
            if not text:
                continue
            if text.lower().startswith("generated on"):
                generated_on = _parse_generated_on(text)
            elif title_cell is None:
                title_cell = text

    def value(row, header):
        index = columns.get(header)
        return _text(row[index]) if index is not None and index < len(row) else None

    parsed = []
    for sheet_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        designation = value(row, "Standard Number")
        if not designation:
            continue
        parsed.append(
            ExportRow(
                sheet_row=sheet_row,
                sl_no=value(row, "Sl#"),
                designation_raw=designation,
                publish_date_raw=_specified(value(row, "Date of Publish")),
                title=value(row, "Title") or "",
                standard_type=_specified(value(row, "Type of Standard")),
                degree=_specified(value(row, "Degree of Equivalence")),
            )
        )
    return ExportFile(path=path, sheet_name=sheet_name, title_cell=title_cell, generated_on=generated_on, rows=parsed)


def classify_export(export: ExportFile) -> str:
    title = export.title_cell
    if title is None:
        return "untitled_export"
    if title.strip().lower() == "total":
        return "total_export"
    if _MINISTRY_TITLE.match(title):
        return "ministry_node"
    return "unknown_node"


# --------------------------------------------------------------------------- record building


def _locator(export: ExportFile, row: ExportRow) -> str:
    return f"{export.path.name}!{export.sheet_name}!R{row.sheet_row}"


def _standard_values(designation: Designation, row: ExportRow, listing_status: str, *, in_master: bool) -> dict:
    title = split_title(row.title)
    publication_date = parse_date(row.publish_date_raw)
    flags = set(designation.flags)
    if row.publish_date_raw is None:
        flags.add("missing_publication_date")
    elif publication_date is None:
        flags.add("unparsed_publication_date")
    if row.standard_type is None:
        flags.add("type_unspecified")
    if row.degree is None:
        flags.add("equivalence_unspecified")
    if not row.title:
        flags.add("missing_title")
    return {
        "family_key": designation.family_key,
        "match_key": designation.match_key,
        "number_key": designation.number_key,
        "designation_raw": row.designation_raw,
        "prefix": designation.prefix,
        "number": designation.number,
        "part": designation.part,
        "section": designation.section,
        "subsection": designation.subsection,
        "year": designation.year,
        "suffix": designation.suffix,
        "title": row.title,
        "title_clean": title.title_clean,
        "revision_label": title.revision_label,
        "amendment_label": title.amendment_label,
        "publication_date": publication_date,
        "publication_date_raw": row.publish_date_raw,
        "standard_type": row.standard_type,
        "degree_of_equivalence": row.degree,
        "listing_status": listing_status,
        "in_master_export": in_master,
        "quality_flags": json.dumps(sorted(flags)) if flags else None,
    }


def _record_alias(run: RunRecorder, designation: Designation, raw: str, context: str, standard_id, locator, retrieved_at):
    if raw == designation.std_key:
        return
    run.upsert(
        "standard_alias",
        key={"raw_text": raw, "context": context},
        values={
            "normalized_key": designation.std_key,
            "resolution": "exact_version",
            "standard_id": standard_id,
            "family_key": designation.family_key,
        },
        locator=locator,
        retrieved_at=retrieved_at,
    )


def _existing_standard(conn, std_key: str):
    table = schema.standard
    return conn.execute(
        sa.select(table.c.standard_id, table.c.source_id, table.c.is_current).where(table.c.std_key == std_key)
    ).first()


def _notes(exports: list[ExportFile]) -> str:
    return "; ".join(
        f"{export.path.name} (generated {export.generated_on.isoformat() if export.generated_on else 'unknown'})"
        for export in exports
    )


# --------------------------------------------------------------------------- runs


def _ingest_master(engine: Engine, exports: list[ExportFile], summary: dict) -> dict:
    with RunRecorder(engine, SOURCE_TOTAL, notes=_notes(exports)) as run:
        seen: dict[str, str] = {}
        for export in exports:
            duplicates = 0
            for row in export.rows:
                locator = _locator(export, row)
                designation = parse_designation(row.designation_raw)
                if designation is None:
                    run.reject(locator, f"unparseable designation {row.designation_raw!r}")
                    continue
                key = designation.std_key
                if key in seen:
                    if seen[key] == row.designation_raw:
                        duplicates += 1
                    else:
                        run.reject(
                            locator,
                            f"canonical_collision: {row.designation_raw!r} and {seen[key]!r} both map to {key!r}",
                        )
                    continue
                seen[key] = row.designation_raw
                result = run.upsert(
                    "standard",
                    key={"std_key": key},
                    values=_standard_values(designation, row, "published_export", in_master=True),
                    locator=locator,
                    retrieved_at=export.generated_on,
                )
                _record_alias(run, designation, row.designation_raw, "excel_total", result.pk, locator, export.generated_on)
            if duplicates:
                summary["duplicates_skipped"][export.path.name] = duplicates
        run.retire_unseen("standard", where={"listing_status": "published_export"})
        run.retire_unseen("standard_alias")
    return {**run.stats, "run_id": run.run_id}


def _ingest_second(engine: Engine, exports: list[ExportFile], summary: dict) -> dict:
    table = schema.standard
    with RunRecorder(engine, SOURCE_SECOND, notes=_notes(exports)) as run:
        run.conn.execute(table.update().where(table.c.in_second_export.is_(True)).values(in_second_export=False))
        seen: set[str] = set()
        for export in exports:
            duplicates = 0
            for row in export.rows:
                locator = _locator(export, row)
                designation = parse_designation(row.designation_raw)
                if designation is None:
                    run.reject(locator, f"unparseable designation {row.designation_raw!r}")
                    continue
                key = designation.std_key
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                existing = _existing_standard(run.conn, key)
                if existing is not None and existing.source_id == SOURCE_TOTAL and existing.is_current:
                    standard_id = existing.standard_id
                else:
                    standard_id = run.upsert(
                        "standard",
                        key={"std_key": key},
                        values=_standard_values(designation, row, "published_export", in_master=False),
                        locator=locator,
                        retrieved_at=export.generated_on,
                    ).pk
                run.conn.execute(table.update().where(table.c.standard_id == standard_id).values(in_second_export=True))
                _record_alias(run, designation, row.designation_raw, "excel_second", standard_id, locator, export.generated_on)
            if duplicates:
                summary["duplicates_skipped"][export.path.name] = duplicates
        run.retire_unseen("standard")
        run.retire_unseen("standard_alias")
    return {**run.stats, "run_id": run.run_id}


def _split_ministry_title(title: str) -> tuple[str | None, str]:
    if " - " in title:
        parent, child = title.split(" - ", 1)
        return clean_ws(parent), clean_ws(child)
    return None, clean_ws(title)


def _ingest_ministries(engine: Engine, exports: list[ExportFile], summary: dict) -> dict:
    parents_first = sorted(exports, key=lambda export: (" - " in (export.title_cell or ""), export.path.name))
    with RunRecorder(engine, SOURCE_MINISTRY, notes=_notes(parents_first)) as run:
        for export in parents_first:
            title_locator = f"{export.path.name}!{export.sheet_name}!C1"
            parent_label, name = _split_ministry_title(export.title_cell)
            parent_id = None
            if parent_label:
                parent_id = run.upsert(
                    "classification_node",
                    key={"dimension": "ministry", "export_label": parent_label},
                    values={"name": parent_label, "parent_node_id": None},
                    locator=title_locator,
                    retrieved_at=export.generated_on,
                ).pk
            node_id = run.upsert(
                "classification_node",
                key={"dimension": "ministry", "export_label": export.title_cell},
                values={"name": name, "parent_node_id": parent_id},
                locator=title_locator,
                retrieved_at=export.generated_on,
            ).pk

            seen_in_file: set[str] = set()
            duplicates = 0
            for row in export.rows:
                locator = _locator(export, row)
                designation = parse_designation(row.designation_raw)
                if designation is None:
                    run.reject(locator, f"unparseable designation {row.designation_raw!r}")
                    continue
                key = designation.std_key
                if key in seen_in_file:
                    duplicates += 1
                    continue
                seen_in_file.add(key)
                existing = _existing_standard(run.conn, key)
                if existing is not None and existing.source_id != SOURCE_MINISTRY and existing.is_current:
                    standard_id = existing.standard_id
                else:
                    standard_id = run.upsert(
                        "standard",
                        key={"std_key": key},
                        values=_standard_values(designation, row, "ministry_export_only", in_master=False),
                        locator=locator,
                        retrieved_at=export.generated_on,
                    ).pk
                run.upsert(
                    "standard_classification",
                    key={"standard_id": standard_id, "node_id": node_id},
                    values={},
                    locator=locator,
                    retrieved_at=export.generated_on,
                )
                _record_alias(run, designation, row.designation_raw, "excel_ministry", standard_id, locator, export.generated_on)
            if duplicates:
                summary["duplicates_skipped"][export.path.name] = duplicates
        for table_name in ("standard_classification", "classification_node", "standard", "standard_alias"):
            run.retire_unseen(table_name)
    return {**run.stats, "run_id": run.run_id}


def ingest_standard_exports(engine: Engine, data_dir: Path) -> dict:
    """Ingest every supplied export in ``data_dir``; returns a per-file and per-run summary."""
    summary: dict = {"files": [], "skipped_files": [], "runs": {}, "duplicates_skipped": {}}
    grouped: dict[str, list[ExportFile]] = {"total_export": [], "untitled_export": [], "ministry_node": []}

    for path in sorted(Path(data_dir).glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        try:
            export = read_export(path)
        except ValueError:
            summary["skipped_files"].append(path.name)
            continue
        classification = classify_export(export)
        summary["files"].append(
            {
                "file": path.name,
                "classification": classification,
                "title": export.title_cell,
                "rows": len(export.rows),
                "generated_on": export.generated_on.isoformat() if export.generated_on else None,
            }
        )
        if classification == "unknown_node":
            summary["skipped_files"].append(path.name)
            continue
        grouped[classification].append(export)

    if grouped["total_export"]:
        summary["runs"][SOURCE_TOTAL] = _ingest_master(engine, grouped["total_export"], summary)
    if grouped["untitled_export"]:
        summary["runs"][SOURCE_SECOND] = _ingest_second(engine, grouped["untitled_export"], summary)
    if grouped["ministry_node"]:
        summary["runs"][SOURCE_MINISTRY] = _ingest_ministries(engine, grouped["ministry_node"], summary)
    return summary
