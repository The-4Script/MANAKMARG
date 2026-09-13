"""Gap report for one upload session: extract, compare, summarise. Files are read in place and never logged."""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from manakmarg.core import clock
from manakmarg.documents.compare import GapRow, compare_all
from manakmarg.documents.extract import extract_document
from manakmarg.documents.requirements import extract_requirements, extract_values
from manakmarg.documents.store import SessionStore

DEMO_DIR = Path(__file__).resolve().parents[1] / "demo" / "samples"
DEMO_FILES = (
    ("DEMO_requirement_sheet_NOT_an_Indian_Standard.txt", "requirement"),
    ("DEMO_fictional_product_datasheet.txt", "datasheet"),
    ("DEMO_fictional_test_report.txt", "test_report"),
)


@dataclass
class GapReport:
    session_id: str
    generated_at: str
    files: list[dict]
    requirement_count: int
    value_count: int
    rows: list[GapRow]
    counts: dict[str, int]
    notes: list[str] = field(default_factory=list)


def add_demo_files(store: SessionStore, session_id: str) -> list[dict]:
    """Add the labelled demo files once per session: a demo file already present is reused, not added again, so a
    refreshed ``?demo=1`` page does not duplicate requirements. User uploads are untouched."""
    existing = {(stored.filename, stored.role): stored for stored, _ in store.files(session_id) if stored.demo}
    files = []
    for name, role in DEMO_FILES:
        stored = existing.get((name, role)) or store.add_file(session_id, name, (DEMO_DIR / name).read_bytes(), role, demo=True)
        files.append({"file_id": stored.file_id, "filename": stored.filename, "role": role, "demo": True})
    return files


def analyze_session(store: SessionStore, session_id: str) -> GapReport:
    files = store.files(session_id)
    requirements, values, described, notes = [], [], [], []
    for stored, path in files:
        try:
            doc = extract_document(path, stored.filename)
        except Exception:  # damaged or unreadable upload; reported without exposing content
            notes.append(f"unreadable:{stored.filename}")
            continue
        if stored.role == "requirement":
            found = extract_requirements(doc)
            requirements.extend(found)
            described.append({"filename": stored.filename, "role": stored.role, "demo": stored.demo, "pages": len(doc.pages), "requirements": len(found)})
        else:
            found = extract_values(doc, stored.role)
            values.extend(found)
            described.append({"filename": stored.filename, "role": stored.role, "demo": stored.demo, "pages": len(doc.pages), "values": len(found)})
    if not any(stored.role == "requirement" for stored, _ in files):
        notes.append("no_requirement_source")
    elif not requirements:
        notes.append("no_requirements_found")
    if not any(stored.role in ("datasheet", "test_report") for stored, _ in files):
        notes.append("no_product_documents")
    rows = compare_all(requirements, values)
    return GapReport(
        session_id=session_id,
        generated_at=clock.now_utc().isoformat(),
        files=described,
        requirement_count=len(requirements),
        value_count=len(values),
        rows=rows,
        counts=dict(Counter(row.status for row in rows)),
        notes=notes,
    )
