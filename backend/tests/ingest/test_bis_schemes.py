"""Compulsory-certification page parsers, tested on trimmed real snapshots (tests/fixtures/README.md)."""

from datetime import date
from pathlib import Path

import pytest

from manakmarg.ingest.bis_schemes import (
    parse_scheme_i,
    parse_scheme_ii,
    parse_scheme_iv,
    parse_scheme_x,
    parse_upcoming_qcos,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
BASE = "https://www.bis.gov.in/product-certification/products-under-compulsory-certification/"
SCHEME_I_URL = BASE + "scheme-i-mark-scheme/?lang=en"
SCHEME_II_URL = BASE + "scheme-ii-registration-scheme/?lang=en"
SCHEME_IV_URL = BASE + "scheme-4/?lang=en"
SCHEME_X_URL = "https://www.bis.gov.in/products-under-compulsory-certification-scheme-x/?lang=en"
UPCOMING_URL = "https://www.bis.gov.in/upcoming-qcos-notified-and-due-for-implementation/?lang=en"


def _read(name):
    return (FIXTURES / name).read_bytes()


def _find(records, **criteria):
    matches = [record for record in records if all(getattr(record, key) == value for key, value in criteria.items())]
    assert matches, criteria
    return matches


def _so_numbers(record):
    return [order.so_number for order in record.orders]


# --------------------------------------------------------------------------- Scheme I


@pytest.fixture(scope="module")
def scheme_i():
    return parse_scheme_i(_read("scheme_i.html"), SCHEME_I_URL)


def test_scheme_i_first_listing(scheme_i):
    first = scheme_i[0]
    assert (first.page_kind, first.scheme_id) == ("scheme_i", "SCHEME_I")
    assert first.category == "Cement (any variety of cement manufactured or sold in India) such as"
    assert (first.sr_no_raw, first.standard_ref_raw, first.product_name) == (
        "1.",
        "IS 12330",
        "Sulphate Resisting Portland Cement",
    )
    assert first.item_kind == "listing"
    assert first.listing_status == "LISTED_COMPULSORY"
    assert first.orders[0].so_number == "S.O. 191(E)"
    assert first.orders[0].url.startswith("https://www.bis.gov.in/")
    assert first.locator.startswith("desktop_table!row")


def test_scheme_i_rowspan_notification_is_inherited(scheme_i):
    opc = _find(scheme_i, standard_ref_raw="IS 269")[0]
    assert opc.product_name == "Ordinary Portland Cement"
    assert "S.O. 191(E)" in _so_numbers(opc)


def test_scheme_i_denotified_entries(scheme_i):
    water = _find(scheme_i, standard_ref_raw="IS 14543")[0]
    assert water.listing_status == "DENOTIFIED"
    assert "De-notified" in water.category
    assert "De-notified" in water.status_basis


def test_scheme_i_cookware_listing(scheme_i):
    cookware = _find(scheme_i, standard_ref_raw="IS 14756 : 2022")[0]
    assert cookware.product_name == "Stainless Steel Cookware"
    assert cookware.category == "Cookware, Utensils and Cans for food and beverages"
    assert "S.O. 3583(E)" in _so_numbers(cookware)


def test_scheme_i_category_row_with_empty_notification_cell(scheme_i):
    bottles = _find(scheme_i, standard_ref_raw="IS 14625")[0]
    assert bottles.category == "Feeding Bottles"
    assert bottles.product_name == "Plastic Feeding Bottles"


def test_scheme_i_illustrative_appliance_items(scheme_i):
    items = [record for record in scheme_i if record.item_kind == "illustrative_item"]
    assert len(items) == 89
    assert {record.standard_ref_raw for record in items} == {"IS 302 (Part 1) : 2024 IEC 60335-1:2020"}
    assert "Spin Extractors" in {record.product_name for record in items}
    parent = next(record for record in scheme_i if record.locator == items[0].parent_locator)
    assert parent.item_kind == "listing"
    assert parent.product_name.startswith("All Electrical Appliances")
    assert items[0].orders == parent.orders


def test_scheme_i_rowspan_ends_before_next_category(scheme_i):
    wrenches = _find(scheme_i, standard_ref_raw="IS 4123:1982")[0]
    assert wrenches.item_kind == "listing"
    assert wrenches.category == "Hand Tools"


def test_scheme_i_keeps_multiple_standards_of_one_cell(scheme_i):
    collector = _find(scheme_i, product_name="Solar Flat Plate Collector for Solar Water Heating Systems")[0]
    assert collector.standard_ref_raw == "IS 12933 (Part 1): 2003 IS 12933 (Part 2): 2003"


def test_scheme_i_empty_serial_number_becomes_none(scheme_i):
    assert _find(scheme_i, standard_ref_raw="IS 8637 : 2020")[0].sr_no_raw is None


def test_scheme_i_ignores_mobile_copy(scheme_i):
    assert len(_find(scheme_i, product_name="Sulphate Resisting Portland Cement")) == 1


def test_scheme_i_records_are_complete_and_uniquely_located(scheme_i):
    assert all(record.product_name for record in scheme_i)
    assert all(record.status_basis for record in scheme_i)
    assert len({record.locator for record in scheme_i}) == len(scheme_i)


def test_scheme_i_order_names_come_from_the_line_before_each_link(scheme_i):
    cement = scheme_i[0].orders[0]
    assert cement.kind == "qco"
    assert cement.title.startswith("Cement (Quality Control)Order, 2003")
    assert cement.so_number == "S.O. 191(E)"

    electrical = _find(scheme_i, standard_ref_raw="IS 12640 (Part 1)")[0]
    kinds = [order.kind for order in electrical.orders]
    assert kinds[0] == "qco"
    assert "amendment" in kinds
    assert electrical.orders[0].so_number == "S.O. 189(E)"

    cookware = _find(scheme_i, standard_ref_raw="IS 14756 : 2022")[0].orders[0]
    assert cookware.title.startswith("Cookware and Utensils (Quality Control) Order, 2023")
    assert cookware.order_date == date(2023, 8, 9)


# --------------------------------------------------------------------------- Scheme II


@pytest.fixture(scope="module")
def scheme_ii():
    return parse_scheme_ii(_read("scheme_ii.html"), SCHEME_II_URL)


def test_scheme_ii_rows_by_section(scheme_ii):
    assert len(scheme_ii) == 74
    labels = [record.section_label for record in scheme_ii]
    assert sum("Electronics and IT Goods" in label for label in labels) == 65
    assert sum("Solar Photovoltaics" in label for label in labels) == 5
    assert sum("chemicals" in label.lower() for label in labels) == 3
    assert sum("Textile" in label for label in labels) == 1


def test_scheme_ii_laptop_listing(scheme_ii):
    laptop = _find(scheme_ii, product_name="Laptop/Notebook/Tablets")[0]
    assert laptop.scheme_id == "SCHEME_II"
    assert laptop.standard_ref_raw == "IS/IEC 62368: Part 1: 2023"
    assert laptop.standard_title_raw.startswith("Audio/Video, Information and Communication Technology Equipment")
    assert "superseding_order" in {order.kind for order in laptop.orders}
    assert laptop.listing_status == "LISTED_COMPULSORY"


def test_scheme_ii_solar_module_row_keeps_all_standard_references(scheme_ii):
    record = _find(scheme_ii, standard_ref_raw="IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2")[0]
    assert "Solar Photovoltaics" in record.section_label
    assert record.product_name.startswith("Crystalline Silicon Terrestrial Photovoltaic")


def test_scheme_ii_textile_listing(scheme_ii):
    bales = _find(scheme_ii, product_name="Cotton Bales")[0]
    assert bales.standard_ref_raw == "IS 12171:2019"
    assert "Cotton Bales (Quality Control) Order, 2023" in bales.notification_text


# --------------------------------------------------------------------------- Scheme IV


def test_scheme_iv_uses_desktop_copy_and_essential_requirements():
    records = parse_scheme_iv(_read("scheme_iv.html"), SCHEME_IV_URL)
    assert len(records) == 2
    stampings, reflectors = records
    assert stampings.scheme_id == "SCHEME_IV"
    assert stampings.product_name == "Stampings/laminations/cores of transformers (with or without winding)"
    assert "IS 3024:2015" in stampings.essential_requirement
    assert stampings.standard_ref_raw is None
    assert stampings.standard_refs == [(stampings.essential_requirement, "referenced_in_requirement")]
    assert reflectors.essential_requirement == "Clause 4.2.2 of IS 10613: 2023"
    assert "S.O. 2290(E)" in reflectors.notification_text


# --------------------------------------------------------------------------- Scheme X


@pytest.fixture(scope="module")
def scheme_x():
    return parse_scheme_x(_read("scheme_x.html"), SCHEME_X_URL)


def test_scheme_x_switchgear_rows(scheme_x):
    switchgear = [record for record in scheme_x if "switchgear and controlgear" in (record.section_label or "").lower()]
    assert len(switchgear) == 32
    first = switchgear[0]
    assert first.scheme_id == "SCHEME_X"
    assert first.sr_no_raw == "1.1 (a)"
    assert first.standard_ref_raw == "IS/IEC 60947: Part 2:2016"
    assert first.standard_title_raw.startswith("Low")
    assert first.product_name.startswith("AC Circuit")
    assert first.specific_requirement.startswith("All test as per IS/IEC 60947")


def test_scheme_x_deferred_phase_needs_verification(scheme_x):
    deferred = _find(scheme_x, sr_no_raw="1.1(b)")[0]
    assert deferred.listing_status == "NEEDS_VERIFICATION"
    assert "Deferment" in deferred.status_basis


def test_scheme_x_machinery_rows_are_rescinded(scheme_x):
    machinery = [record for record in scheme_x if "Omnibus Technical Regulation" in (record.section_label or "")]
    assert len(machinery) == 20
    assert {record.listing_status for record in machinery} == {"RESCINDED"}
    assert "S.O. 239(E)" in machinery[0].status_basis
    assert machinery[0].product_name.startswith("All types of Pumps")
    assert ("IS 16189:2018", "type_a") in [
        (reference, role) for reference, role in machinery[0].standard_refs if reference.startswith("IS 16189")
    ]


# --------------------------------------------------------------------------- Upcoming QCOs


@pytest.fixture(scope="module")
def upcoming():
    return parse_upcoming_qcos(_read("upcoming_qcos.html"), UPCOMING_URL)


def test_upcoming_listing_rows(upcoming):
    listings = [record for record in upcoming if record.item_kind == "listing"]
    assert len(listings) == 28
    first = listings[0]
    assert (first.page_kind, first.scheme_id) == ("upcoming_qco", None)
    assert (first.sr_no_raw, first.ministry_department, first.product_name, first.standard_ref_raw) == (
        "1",
        "Department of Chemicals and Petrochemicals",
        "Linear Alkyl Benzene",
        "IS 12795:2020",
    )
    assert first.enforcement_date == date(2026, 9, 30)
    assert first.enforcement_date_raw == "30 September 2026"
    assert first.listing_status == "UPCOMING"
    assert first.refs_assume_is_prefix is True


def test_upcoming_prefixless_standard_is_kept_raw(upcoming):
    wrench = _find(upcoming, product_name="Pipe Wrenches-General Purpose")[0]
    assert wrench.standard_ref_raw == "4003 (Part 1):1978"
    assert wrench.enforcement_date == date(2026, 10, 1)


def test_upcoming_colspan_product_cell(upcoming):
    cans = _find(upcoming, product_name="Aluminium cans for beverages")[0]
    assert cans.standard_ref_raw == "IS 14407:2023"


def test_upcoming_illustrative_appliances_inherit_standard_and_date(upcoming):
    items = [record for record in upcoming if record.item_kind == "illustrative_item"]
    assert len(items) == 90
    assert {record.enforcement_date for record in items} == {date(2026, 10, 1)}
    assert {record.standard_ref_raw for record in items} == {"IS 302 (Part 1) : 2024 IEC 60335-1:2020"}
    assert items[0].product_name == "Vacuum Cleaners and Water Suction Cleaning Appliances"
    assert items[-1].product_name == "DC supplied/ battery-operated air purifier"


def test_upcoming_last_row(upcoming):
    last = [record for record in upcoming if record.item_kind == "listing"][-1]
    assert last.sr_no_raw == "28"
    assert last.standard_ref_raw == "IS 5175:2022"
    assert last.enforcement_date == date(2027, 6, 5)
