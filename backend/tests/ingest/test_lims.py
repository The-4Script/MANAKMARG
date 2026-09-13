"""LIMS directory and Indian Standard-wise scope search parsers on trimmed real snapshots."""

from datetime import date
from pathlib import Path

from manakmarg.ingest.lims import ScopeItem, exclusions_from_remark, parse_lims_directory, parse_lims_scope_search

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_recognised_labs_directory_page():
    page = parse_lims_directory(_read("lims_recognised_labs_page1.html"), "BIS_RECOGNISED", "https://lims.bis.gov.in/home/labs/")
    assert len(page.labs) == 20
    assert page.total_pages == 22
    assert len(page.page_urls) == 21
    assert page.page_urls[0] == "https://lims.bis.gov.in/home/labs/?page=2"
    assert page.page_urls[-1] == "https://lims.bis.gov.in/home/labs/?page=22"

    lab = page.labs[0]
    assert (lab.osl_code, lab.name) == ("8102006", "SIIR, Delhi Shriram Institute For Industrial Research")
    assert (lab.address.city, lab.address.district, lab.address.state, lab.address.pincode) == ("Delhi", "North", "Delhi", "110007")
    assert lab.org_phone == "+91 011 35200445"
    assert lab.org_email.endswith("@shriraminstitute.org")
    assert lab.validity_date == date(2026, 12, 31)
    assert lab.lims_lab_id == 15
    assert lab.scope_url == "https://lims.bis.gov.in/home_lab_scope/15/"
    assert lab.category == "BIS_RECOGNISED"
    assert not hasattr(lab, "contact_person")
    assert page.labs[1].validity_date == date(2029, 12, 31)


def test_bis_labs_directory_has_no_codes_or_validity():
    page = parse_lims_directory(_read("lims_bis_labs.html"), "BIS_LAB", "https://lims.bis.gov.in/home/bis_labs/")
    assert len(page.labs) == 10
    assert page.total_pages == 1
    assert page.page_urls == []
    first = page.labs[0]
    assert first.osl_code is None
    assert first.name == "BIS, Bengaluru Branch Laboratory (BNBL)"
    assert first.validity_date is None
    assert first.address.state == "Karnataka"


def test_empanelled_labs_directory():
    page = parse_lims_directory(_read("lims_empanelled_labs_page1.html"), "GOVT_EMPANELLED", "https://lims.bis.gov.in/home/empaneled_labs/")
    assert len(page.labs) == 20
    assert page.total_pages == 7
    assert page.labs[0].osl_code == "6133034"


SEARCH_2062 = "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062"


def test_scope_search_page_rows():
    page = parse_lims_scope_search(_read("lims_scope_search_2062_page1.html"), SEARCH_2062)
    assert page.total_results == 63
    assert len(page.rows) == 6
    assert page.page_urls == [
        "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062&page=2",
        "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=2062&page=3",
    ]

    erl, unique = page.rows[0], page.rows[1]
    assert erl.lab_name_raw == "BIS, Eastern Regional Laboratory (ERL)"
    assert erl.osl_code_raw is None
    assert erl.is_ref_raw == "IS 2062 (Part 2) (2026)"
    assert erl.product.startswith("Structural Steel - Part 2")
    assert erl.grade_type == "For all grades"
    assert erl.charges_total is None
    assert erl.validity_date is None
    assert erl.remark_raw == "Mech: Complete"

    assert unique.osl_code_raw == "9134536"
    assert unique.is_ref_raw == "IS 2062 (Part 1) (2025)"
    assert unique.charges_total == 14000.0
    assert unique.validity_date == date(2028, 9, 7)
    assert unique.remark_raw == "Included w.e.f 31.08.2026"


def test_scope_search_breakup_items():
    page = parse_lims_scope_search(_read("lims_scope_search_2062_page1.html"), SEARCH_2062)
    erl, unique = page.rows[0], page.rows[1]
    assert unique.items[0] == ScopeItem(
        clause="Cl-6",
        parameter="MANUFACTURE",
        exclusion=None,
        charge=100.0,
        charge_raw="100",
        effective_date_raw=None,
        remark=None,
    )
    assert erl.items[0].clause == "Cl-8.1 & 8.4, Table 7"
    assert erl.items[0].parameter.startswith("Minimum Yield Strength ReH")
    assert erl.items[0].charge is None


def test_scope_search_other_standard():
    page = parse_lims_scope_search(_read("lims_scope_search_269_page1.html"), "https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=269")
    assert page.total_results == 50
    guwahati = page.rows[3]
    assert guwahati.lab_name_raw == "National Test House (NER) - NTH, Guwahati"
    assert guwahati.grade_type == "OPC 33/43/ 53 Grade,OPC 43S & 53S Grade"
    assert guwahati.charges_total == 12000.0
    assert guwahati.validity_date == date(2027, 12, 13)


def test_exclusions_are_read_from_remarks():
    assert exclusions_from_remark("Exclusion: Table 3 ii) b) Soundness by Autoclave Test Method") == (
        "Table 3 ii) b) Soundness by Autoclave Test Method"
    )
    assert exclusions_from_remark("Included w.e.f 03.03.2025 Exclusion : Cl 6.3 Mineral Matter") == "Cl 6.3 Mineral Matter"
    assert exclusions_from_remark("Included w.e.f 10.02.2025") is None
    assert exclusions_from_remark(None) is None
