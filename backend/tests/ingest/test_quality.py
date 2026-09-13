import json
from datetime import date

import pytest

from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.excel_standards import ingest_standard_exports
from manakmarg.ingest.quality import run_quality_checks, write_quality_report
from tests.workbooks import build_sample_exports


@pytest.fixture
def engine(tmp_path):
    eng = get_engine(tmp_path / "quality.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
    ingest_standard_exports(eng, build_sample_exports(tmp_path / "data"))
    yield eng
    eng.dispose()


@pytest.fixture
def findings(engine):
    with engine.connect() as conn:
        return {finding.check: finding for finding in run_quality_checks(conn, today=date(2026, 9, 13))}


def test_provenance_is_complete(findings):
    assert findings["missing_provenance"].count == 0
    assert findings["missing_provenance"].severity == "error"


def test_ministry_only_standards_are_reported(findings):
    assert findings["ministry_only_standards"].count == 1
    assert "IS 7328:2020" in findings["ministry_only_standards"].examples


def test_standard_value_gaps_are_counted(findings):
    assert findings["missing_publication_date"].count == 1
    assert findings["type_unspecified"].count == 1
    assert findings["equivalence_unspecified"].count == 1


def test_run_level_checks(findings):
    assert findings["canonical_collisions"].count == 0
    assert findings["rejected_records"].count == 0
    assert findings["future_publication_dates"].count == 0


def test_every_finding_has_a_note(findings):
    for finding in findings.values():
        assert finding.severity in {"info", "warning", "error"}
        assert finding.note


def test_write_quality_report(tmp_path, engine):
    with engine.connect() as conn:
        report = run_quality_checks(conn, today=date(2026, 9, 13))
    json_path = tmp_path / "out" / "data_quality.json"
    markdown_path = tmp_path / "out" / "DATA_QUALITY.md"
    write_quality_report(report, json_path, markdown_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert {item["check"] for item in payload["findings"]} >= {"missing_provenance", "ministry_only_standards"}
    assert "ministry_only_standards" in markdown_path.read_text(encoding="utf-8")
