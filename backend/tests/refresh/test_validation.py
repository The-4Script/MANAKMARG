"""Downloaded exports are checked before anything reaches the database."""

from manakmarg.refresh import validation
from manakmarg.refresh.validation import check_export
from tests.refresh.exports import HEADERS, rows_for, write_export

ROWS = rows_for(["IS 269:2015", "IS 14543:2024", "IS 13688:2020"])


def test_a_complete_overall_export_passes(tmp_path):
    check = check_export(write_export(tmp_path / "total.xlsx", "Total", ROWS), kind="total")
    assert check.ok and check.rows == 3 and check.classification == "total_export" and check.generated_on
    assert check.problems == []


def test_wrong_heading_missing_columns_and_empty_files_fail(tmp_path):
    assert "expected 'Total'" in check_export(write_export(tmp_path / "a.xlsx", "Ministry of Coal", ROWS), kind="total").problems[0]
    missing = check_export(write_export(tmp_path / "b.xlsx", "Total", ROWS, headers=HEADERS[:-1]), kind="total")
    assert not missing.ok and any("Degree of Equivalence" in problem for problem in missing.problems)
    empty = check_export(write_export(tmp_path / "c.xlsx", "Total", []), kind="total")
    assert not empty.ok and "no data rows" in empty.problems


def test_corrupt_or_non_excel_files_fail(tmp_path):
    html = tmp_path / "page.xlsx"
    html.write_bytes(b"<html>Service unavailable</html>")
    assert check_export(html, kind="total").problems == ["not an Excel .xlsx workbook"]
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"PK\x03\x04 truncated")
    assert check_export(broken, kind="total").problems[0].startswith("corrupt workbook")


def test_ministry_export_must_be_for_that_ministry_and_near_its_count(tmp_path):
    path = write_export(tmp_path / "m.xlsx", "Ministry of Coal", ROWS)
    assert check_export(path, kind="ministry", expected_title="ministry of  COAL", expected_rows=3).ok
    mismatch = check_export(path, kind="ministry", expected_title="Ministry of Mines", expected_rows=3)
    assert not mismatch.ok and "does not match" in mismatch.problems[0]
    short = check_export(path, kind="ministry", expected_title="Ministry of Coal", expected_rows=40)
    assert not short.ok and "portal lists 40" in short.problems[0]
    close = check_export(path, kind="ministry", expected_title="Ministry of Coal", expected_rows=3.2)
    assert close.ok and close.warnings


def test_too_many_unparseable_standard_numbers_fail(tmp_path, monkeypatch):
    real = validation.parse_designation
    monkeypatch.setattr(validation, "parse_designation", lambda raw: None if raw == "IS 269:2015" else real(raw))
    check = check_export(write_export(tmp_path / "t.xlsx", "Total", ROWS), kind="total")
    assert not check.ok and "cannot be parsed" in check.problems[0]
