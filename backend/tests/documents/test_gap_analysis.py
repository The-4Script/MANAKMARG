"""Gap analysis: units, extraction, comparison statuses, the labelled demo session and upload safety."""

from datetime import datetime, timedelta, timezone

import pytest

from manakmarg.core import clock
from manakmarg.documents.compare import FAIL, INSUFFICIENT_EVIDENCE, PASS, POTENTIAL_GAP, UNKNOWN, compare, parameter_similarity
from manakmarg.documents.extract import extract_document
from manakmarg.documents.gap import DEMO_DIR, add_demo_files, analyze_session
from manakmarg.documents.requirements import ProductValue, Requirement, extract_requirements, extract_values
from manakmarg.documents.store import SessionNotFound, SessionStore, UploadRejected
from manakmarg.documents.units import compatible, parse_quantity, to_base


@pytest.mark.parametrize(
    "text, value, unit, dimension",
    [
        ("0.50 mm", 0.5, "mm", "length"),
        ("20.3 cm", 20.3, "cm", "length"),
        ("16 kgf", 16.0, "kgf", "force"),
        ("250 N/mm²", 250.0, "MPa", "pressure"),
        ("8,5 %", 8.5, "%", "percent"),
        ("0.8 μm", 0.8, "µm", "length"),
        ("72 GU", 72.0, None, None),
    ],
)
def test_parse_quantity(text, value, unit, dimension):
    quantity = parse_quantity(text)
    assert (quantity.value, quantity.unit, quantity.dimension) == (value, unit, dimension)


def test_unit_conversion_stays_within_a_dimension():
    assert to_base(20.3, "cm") == (pytest.approx(203.0), "mm")
    assert to_base(0.27, "kg") == (pytest.approx(270.0), "g")
    assert to_base(16, "kgf")[0] == pytest.approx(156.9064)
    assert compatible("cm", "mm") and not compatible("HV", "HRC") and not compatible("mm", "g")


def _requirement(operator="min", value=0.5, value_max=None, unit="mm", parameter="Wall thickness"):
    return Requirement(parameter, operator, value, value_max, unit, unit, "3.1", 1, "raw", "req.txt")


def _value(value, unit="mm", role="datasheet", parameter="Wall thickness", value_max=None):
    return ProductValue(parameter, value, value_max, unit, unit, 1, "raw", "doc.txt", role)


def test_comparison_statuses():
    assert compare(_requirement(), [_value(0.052, "cm")]).status == PASS
    assert compare(_requirement(), [_value(0.47, role="datasheet")]).status == POTENTIAL_GAP
    assert compare(_requirement(), [_value(0.47, role="test_report")]).status == FAIL
    assert compare(_requirement(), [_value(12, "g")]).status == UNKNOWN
    assert compare(_requirement(), []).status == INSUFFICIENT_EVIDENCE
    assert compare(_requirement("range", 16.0, 18.0, "%", "Chromium content"), [_value(17.2, "%", parameter="Chromium content")]).status == PASS
    measured_preferred = compare(_requirement(), [_value(0.52, role="datasheet"), _value(0.47, role="test_report")])
    assert (measured_preferred.status, measured_preferred.value.role) == (FAIL, "test_report")


def test_uncertain_parameter_match_is_never_a_pass():
    row = compare(_requirement(parameter="Wall thickness of bowl"), [_value(0.6, parameter="Thickness")])
    assert row.similarity is not None and row.status in (POTENTIAL_GAP, INSUFFICIENT_EVIDENCE)
    assert parameter_similarity("Surface hardness", "Surface hardness") == 1.0


def test_demo_files_extract_the_expected_requirements_and_values():
    requirements = extract_requirements(extract_document(DEMO_DIR / "DEMO_requirement_sheet_NOT_an_Indian_Standard.txt"))
    by_parameter = {requirement.parameter: requirement for requirement in requirements}
    assert len(requirements) == 11
    assert (by_parameter["Chromium content"].operator, by_parameter["Chromium content"].value, by_parameter["Chromium content"].value_max) == ("range", 16.0, 18.0)
    assert (by_parameter["Lid gap"].operator, by_parameter["Lid gap"].value, by_parameter["Lid gap"].clause) == ("max", 1.5, "3.3")
    assert (by_parameter["Surface roughness Ra"].operator, by_parameter["Surface roughness Ra"].unit) == ("max", "µm")
    datasheet = extract_values(extract_document(DEMO_DIR / "DEMO_fictional_product_datasheet.txt"), "datasheet")
    report = extract_values(extract_document(DEMO_DIR / "DEMO_fictional_test_report.txt"), "test_report")
    assert len(datasheet) == 9 and len(report) == 4
    assert {value.parameter for value in report} == {"Wall thickness", "Handle pull-out force", "Surface roughness Ra", "Nickel content"}


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "uploads", ttl_minutes=120, max_bytes=1024 * 1024)


def test_demo_session_gap_report(store):
    session = store.create()["session_id"]
    add_demo_files(store, session)
    report = analyze_session(store, session)
    statuses = {row.requirement.parameter: row.status for row in report.rows}
    assert statuses == {
        "Chromium content": PASS,
        "Nickel content": PASS,
        "Wall thickness": FAIL,
        "Rim diameter": PASS,
        "Lid gap": POTENTIAL_GAP,
        "Handle pull-out force": PASS,
        "Surface hardness": UNKNOWN,
        "Mass": PASS,
        "Capacity": INSUFFICIENT_EVIDENCE,
        "Surface roughness Ra": PASS,
        "Brightness (gloss)": PASS,
    }
    assert report.counts == {PASS: 7, FAIL: 1, POTENTIAL_GAP: 1, UNKNOWN: 1, INSUFFICIENT_EVIDENCE: 1}
    assert all(item["demo"] for item in report.files)


def test_uploads_are_validated(store):
    session = store.create()["session_id"]
    with pytest.raises(UploadRejected):
        store.add_file(session, "notes.exe", b"MZ", "datasheet")
    with pytest.raises(UploadRejected):
        store.add_file(session, "fake.pdf", b"not a pdf", "datasheet")
    with pytest.raises(UploadRejected):
        store.add_file(session, "big.txt", b"a" * (1024 * 1024 + 1), "datasheet")
    with pytest.raises(UploadRejected):
        store.add_file(session, "sheet.txt", b"text", "unknown-role")
    stored = store.add_file(session, "../../etc/passwd.txt", b"Lid gap: 1 mm", "datasheet")
    assert "/" not in stored.filename and ".." not in stored.filename.replace("_", "")
    with pytest.raises(SessionNotFound):
        store.files("../../outside")


def test_sessions_expire_and_are_deleted(store):
    session = store.create()["session_id"]
    store.add_file(session, "sheet.txt", b"Lid gap: 1 mm", "datasheet")
    clock_now = clock.now_utc
    try:
        clock.now_utc = lambda: datetime.now(timezone.utc) + timedelta(minutes=121)
        with pytest.raises(SessionNotFound):
            store.files(session)
    finally:
        clock.now_utc = clock_now
    assert not (store.root / session).exists()
    other = store.create()["session_id"]
    assert store.delete(other) and not (store.root / other).exists()
