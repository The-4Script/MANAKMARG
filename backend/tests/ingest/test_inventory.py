import json

from manakmarg.ingest.inventory import build_inventory, write_inventory
from tests.workbooks import build_sample_exports

HEADERS = ["Sl#", "Standard Number", "Date of Publish", "Title", "Type of Standard", "Degree of Equivalence"]
MINISTRY_FILE = "File_Published_Standards_List_2026-09-12_203745.xlsx"


def test_inventory_describes_each_workbook_sheet(tmp_path):
    inventory = build_inventory(build_sample_exports(tmp_path / "data"))
    by_file = {workbook["file"]: workbook for workbook in inventory["workbooks"]}
    assert set(by_file) == {"1.xlsx", "2.xlsx", MINISTRY_FILE}
    assert by_file["1.xlsx"]["bytes"] > 0

    total = by_file["1.xlsx"]["sheets"][0]
    assert total["sheet"] == "Published Standards"
    assert total["state"] == "visible"
    assert total["header_row"] == 2
    assert total["headers"] == HEADERS
    assert total["row_count"] == 3
    assert total["column_count"] == 6
    assert total["title_cell"] == "Total"
    assert total["generated_on"].startswith("2026-09-12T20:17")
    assert total["classification"] == "total_export"
    assert total["source_id"] == "bis_std_export_total"
    assert total["authority_level"] == "official_primary"
    assert total["source_type"] == "excel_export"
    assert total["candidate_key"].startswith("Standard Number")
    assert total["data_quality_issues"]["null_publish_dates"] == 1
    assert total["data_quality_issues"]["type_unspecified"] == 1
    assert total["data_quality_issues"]["equivalence_unspecified"] == 1
    assert total["duplicate_characteristics"]["repeated_designations"] == 0
    for field in ("domain", "description", "important_columns", "relationship_to_other_data", "notes"):
        assert total[field], field


def test_inventory_reports_duplicates_and_cross_file_overlap(tmp_path):
    inventory = build_inventory(build_sample_exports(tmp_path / "data"))
    second = next(workbook for workbook in inventory["workbooks"] if workbook["file"] == "2.xlsx")["sheets"][0]
    assert second["classification"] == "untitled_export"
    assert second["duplicate_characteristics"]["repeated_designations"] == 1

    assert inventory["cross_file"]["total_vs_untitled"] == {"shared": 2, "only_in_total": 1, "only_in_untitled": 1}
    ministry = inventory["cross_file"]["ministry_exports"]
    assert ministry["files"] == 1
    assert ministry["distinct_standards"] == 2
    assert ministry["standards_in_more_than_one_node"] == 0
    assert ministry["not_in_total_or_untitled"] == 1


def test_write_inventory_creates_json_and_markdown(tmp_path):
    inventory = build_inventory(build_sample_exports(tmp_path / "data"))
    json_path = tmp_path / "out" / "data_inventory.json"
    markdown_path = tmp_path / "out" / "DATA_INVENTORY.md"
    write_inventory(inventory, json_path, markdown_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["workbooks"]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| 1.xlsx |" in markdown
    assert "total_export" in markdown
    assert "Ministry of Coal" in markdown
