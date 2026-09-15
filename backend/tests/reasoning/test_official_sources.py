"""Official-source actions: offered only for stored official BIS/Gazette URLs, never for supplied or derived data."""

from datetime import date

import pytest

from manakmarg.reasoning.assistant import answer
from manakmarg.reasoning.evidence import official_action
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)


@pytest.mark.parametrize(
    "kind, url, authority, expected",
    [
        ("regulatory_order", "https://www.bis.gov.in/wp-content/uploads/2020/01/Cables_28012020.pdf", "official_primary", "view_notification"),
        ("lab_scope", "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062", "official_primary", "view_lims"),
        ("ahc", "https://www.manakonline.in/MANAK/AHCListForWebsite", "official_primary", "view_hallmarking_source"),
        ("standard", "https://standards.bis.gov.in/website/published-standards/published-standard-deptwise", "official_primary", "view_standard_portal"),
        ("coverage_listing", "https://bis.gov.in/product-certification/", "official_primary", "verify_on_bis"),
        ("something_new", "https://www.bis.gov.in/x", "official_primary", "view_official_source"),
        ("regulatory_order", "https://bis.gov.in.example.com/fake.pdf", "official_primary", None),
        ("regulatory_order", "https://example.com/bis.gov.in.pdf", "official_primary", None),
        ("regulatory_order", "javascript:alert(1)", "official_primary", None),
        ("gazette_cross_check", "https://www.bis.gov.in/doc.pdf", "derived", None),
        ("hsn_code", None, "supplied_dataset", None),
    ],
)
def test_official_action(kind, url, authority, expected):
    assert official_action(kind, url, authority) == expected


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("sources") / "fixture.sqlite3")
    yield eng
    eng.dispose()


def test_answers_carry_real_official_links(engine):
    with engine.connect() as conn:
        product = answer(conn, "Is BIS certification mandatory for PVC insulated heavy duty electric cables?", today=TODAY)
        hallmarking = answer(conn, "Is hallmarking mandatory in Jaipur?", today=TODAY)
    orders = [product.evidence.get(item.evidence_ids[0]) for section in product.sections if section.key == "orders" for item in section.items]
    assert orders and all(order.action == "view_notification" and order.url.startswith("https://www.bis.gov.in/") for order in orders)
    actions = {item.action for item in hallmarking.evidence.items}
    assert "view_hallmarking_source" in actions
    for item in product.evidence.items + hallmarking.evidence.items:
        if item.action:
            assert item.url and item.authority == "official_primary"
