from pathlib import Path

import pytest

from manakmarg.ingest.psg import classify_guideline, parse_psg

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
PSG_URL = "https://www.bis.gov.in/product-certification/product-specific-guidelines/?lang=en"


@pytest.fixture(scope="module")
def guidelines():
    return parse_psg((FIXTURES / "psg.html").read_bytes(), PSG_URL)


def _by_ref(records, reference):
    matches = [record for record in records if record.is_ref_raw == reference]
    assert matches, reference
    return matches


def test_every_listed_document_row_is_parsed(guidelines):
    assert len(guidelines) == 54
    assert len({record.locator for record in guidelines}) == len(guidelines)


def test_first_row_fields(guidelines):
    first = guidelines[0]
    assert first.sr_no_raw == "1"
    assert first.is_ref_raw == "IS 3055 (Part 1) : 1994"
    assert first.title == "Clinical Thermometers – Solid stem Type"
    assert first.size_text == "2.3 MB"
    assert first.format_text == "Pdf"
    assert first.url == "https://www.bis.gov.in/wp-content/uploads/2018/12/Product-Manual-30551-V2.pdf"
    assert first.doc_kind == "PRODUCT_MANUAL"


def test_demo_family_manuals_are_present(guidelines):
    utensils = _by_ref(guidelines, "IS 14756: 2024")[0]
    assert utensils.title == "STAINLESS STEEL UTENSILS"
    assert utensils.url == "https://www.bis.gov.in/wp-content/uploads/2025/01/PM-IS-14756.pdf"
    steel = _by_ref(guidelines, "IS 2062:2011")[0]
    assert steel.url == "https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf"


def test_manual_with_scheme_of_inspection_and_testing_is_classified(guidelines):
    acrylate = _by_ref(guidelines, "IS 14708: 1999")[0]
    assert acrylate.doc_kind == "PRODUCT_MANUAL_WITH_SIT"


def test_one_standard_can_have_several_manuals(guidelines):
    manuals = _by_ref(guidelines, "IS 302-1 : 2008")
    assert len(manuals) == 3
    assert len({manual.url for manual in manuals}) == 3


@pytest.mark.parametrize(
    "url, title, expected",
    [
        ("https://www.bis.gov.in/wp-content/uploads/2025/01/PM-IS-14756.pdf", "Stainless steel utensils", "PRODUCT_MANUAL"),
        ("https://www.bis.gov.in/wp-content/uploads/2023/04/Product-Manual-and-SIT-for-Ethyl-AcrylatePDF.pdf", "Ethyl Acrylate", "PRODUCT_MANUAL_WITH_SIT"),
        ("https://www.bis.gov.in/wp-content/uploads/2024/01/Amendment-1-PM-IS-1234.pdf", "Some product", "PRODUCT_MANUAL_AMENDMENT"),
        ("https://www.bis.gov.in/wp-content/uploads/2024/01/Grouping-Guidelines-IS-1234.pdf", "Some product", "GROUPING_GUIDELINE"),
        ("https://www.bis.gov.in/wp-content/uploads/2024/01/PM-IS-9999.pdf", "Composite position sensors", "PRODUCT_MANUAL"),
    ],
)
def test_classify_guideline(url, title, expected):
    assert classify_guideline(url, title) == expected
