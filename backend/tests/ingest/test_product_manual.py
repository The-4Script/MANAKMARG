"""Product Manual parsing, tested on the page text and PyMuPDF tables of the BIS manual for IS 14756."""

import json
from pathlib import Path

import pytest

from manakmarg.ingest.product_manual import ManualPage, parse_product_manual

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "bis" / "pm_is_14756_pages.json"


@pytest.fixture(scope="module")
def manual():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pages = [ManualPage(number=page["page"], text=page["text"], tables=page.get("tables", [])) for page in data["pages"]]
    return parse_product_manual(pages)


def _section(manual, key):
    return next(section for section in manual.sections if section.section_key == key)


def test_header_fields(manual):
    assert manual.document_no == "PM/IS 14756/7/January 2025"
    assert manual.product_standard == "IS 14756: 2024"
    assert manual.product_title == "Stainless Steel Utensils"
    assert manual.amendments == "Nil"


def test_summary_items(manual):
    assert manual.summary["sample_size"].startswith("2 Pcs")
    assert manual.summary["tests_per_day"] == "All test except Staining Test."
    assert "IS 5522" in manual.summary["raw_material"]
    assert manual.summary["grouping_guidelines"].startswith("Please refer ANNEX")
    assert "BUREAU OF INDIAN" not in manual.summary["other_guidelines"]


def test_annex_sections_are_split_and_keyed(manual):
    starts = {section.section_key: section.page_start for section in manual.sections}
    assert (starts["grouping"], starts["test_equipment"], starts["sit"], starts["scope_of_licence"], starts["other_guidelines"]) == (
        3,
        5,
        7,
        11,
        12,
    )
    grouping = _section(manual, "grouping")
    assert grouping.heading == "Grouping Guidelines"
    assert grouping.page_end == 4
    assert "Type of Utensils" in grouping.text
    assert "PM/ IS 14756" not in grouping.text
    assert _section(manual, "test_equipment").page_end == 6


def test_summary_section_is_kept(manual):
    summary = _section(manual, "summary")
    assert summary.page_start == 2
    assert summary.structured["tests_per_day"] == "All test except Staining Test."


def test_test_equipment_rows(manual):
    tests = _section(manual, "test_equipment").structured["tests"]
    assert len(tests) == 19
    assert tests[0] == {
        "sl": "1",
        "test": "Shape and Dimension",
        "clauses": ["4.1"],
        "equipment": ["Measuring Scale", "Vernier Caliper"],
        "standards": [],
        "annexes": [],
    }
    assert tests[1]["test"] == "Thickness of Utensils and material"
    assert tests[1]["clauses"] == ["4.2", "4.3"]
    assert next(test for test in tests if test["test"] == "Staining Test")["clauses"] == ["6.1"]
    fragmentation = next(test for test in tests if test["test"] == "Fragmentation test")
    assert fragmentation["clauses"] == ["3.5", "8.15.1"]
    assert fragmentation["standards"] == ["IS 2347"]
    leaching = next(test for test in tests if test["test"].startswith("Test for leaching"))
    assert leaching["annexes"] == ["C"]
    mechanical = next(test for test in tests if test["test"] == "Mechanical Shock Test")
    assert mechanical["equipment"] == [
        "Arrangement for Mechanical Shock test equipped with Steel Ball of half a kilogram and dropping arrangement "
        "from a Height of 500mm"
    ]


def test_scheme_of_inspection_and_testing_rows(manual):
    rows = _section(manual, "sit").structured["rows"]
    staining = next(row for row in rows if row["requirement"] == "Staining Test")
    assert (staining["clause"], staining["equipment_requirement"], staining["samples"], staining["frequency"]) == (
        "6.1",
        "R",
        "One",
        "Once in a year",
    )
    assert staining["group"] == "TESTS"

    mechanical = next(row for row in rows if row["requirement"] == "Mechanical Shock")
    assert mechanical["frequency"] == "Once in a month or one in 50000 utensils, whichever is earlier"
    assert mechanical["remarks"] == "For cladded utensils only"
    assert mechanical["merged_from_previous"] is False

    thermal = next(row for row in rows if row["requirement"] == "Thermal Shock")
    assert thermal["merged_from_previous"] is True
    assert thermal["frequency"] == mechanical["frequency"]

    shapes = [row for row in rows if row["requirement"] == "Shapes and Dimensions"]
    assert [row["test_method_clause"] for row in shapes] == ["4.1", "4.2, 4.3 Table 1"]
    assert [row["clause"] for row in shapes] == ["4", "4"]

    adhesion = next(row for row in rows if row["requirement"] == "Adhesion test")
    assert adhesion["frequency"] == ""
    assert adhesion["merged_from_previous"] is False

    leaching = next(row for row in rows if row["requirement"] == "Test for leaching")
    assert leaching["frequency"] == "Once in 3 months"
    assert leaching["group"].startswith("Additional tests for Stainless Steel")

    assert not any(row["requirement"] in {"Requirement", "Test Details"} for row in rows)


def test_scope_of_licence_fields(manual):
    scope = _section(manual, "scope_of_licence").structured
    assert scope["fields"][:3] == ["Name of the product", "Type of Utensil", "Body material"]
    assert scope["values"] == {"Name of the product": "Stainless Steel Utensils"}
