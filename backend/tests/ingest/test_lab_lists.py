"""BIS Group-1 (recognised) and Group-2 (empanelled) laboratory list parsing from PDF table extracts."""

import json
from datetime import date
from pathlib import Path

import pytest

from manakmarg.ingest.lab_lists import derive_lab_status, parse_group_list

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"


def _pages(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pages"]


@pytest.fixture(scope="module")
def group1():
    return parse_group_list(_pages("lab_group1_tables.json"), group=1)


def test_group1_rows_and_as_of_date(group1):
    assert group1.as_of == date(2026, 8, 24)
    assert len(group1.records) == 18
    assert [record.sl_no for record in group1.records] == [str(number) for number in range(1, 19)]
    assert [record.name for record in group1.records[:3]] == [
        "AES Laboratories (P) Ltd, Noida",
        "Alpha Test House Private Limited, New Delhi",
        "Anacon Laboratories Pvt Ltd, Nagpur",
    ]
    aes = group1.records[0]
    assert (aes.sl_no, aes.state, aes.ownership, aes.osl_code, aes.valid_upto) == (
        "1",
        "Uttar Pradesh",
        "Private",
        "8117716",
        date(2027, 2, 14),
    )
    assert aes.derived_status == "LISTED"
    assert aes.group_no == 1


def test_remarks_continue_across_page_breaks(group1):
    anacon = group1.records[2]
    assert "Deferrment of Renewal of recognition" in anacon.remarks_raw
    atharva = next(record for record in group1.records if record.osl_code == "8134206")
    assert "SUSPENDED W.E.F. 01-08-2023" in atharva.remarks_raw
    assert atharva.derived_status == "LISTED"
    assert "09-03-2026" in atharva.status_basis


def test_source_typos_are_normalised_but_kept(group1):
    mohali = next(record for record in group1.records if record.osl_code == "9138706")
    assert (mohali.state, mohali.state_raw) == ("Punjab", "Pubjab")
    assert mohali.valid_upto == date(2026, 12, 31)
    accurate = next(record for record in group1.records if record.osl_code == "8141226")
    assert (accurate.ownership, accurate.ownership_raw) == ("Private", "Priavate")


def test_group2_list():
    result = parse_group_list(_pages("lab_group2_tables.json"), group=2)
    assert result.as_of == date(2026, 8, 7)
    assert len(result.records) == 37
    first = result.records[0]
    assert (first.name, first.state, first.ownership, first.osl_code) == (
        "Bhabha Atomic Research Centre (BARC), Bullandshar",
        "Uttar Pradesh",
        "Govt",
        "8117101",
    )
    assert first.valid_upto is None
    trombay = next(record for record in result.records if record.osl_code == "7112901")
    assert trombay.ownership == "Govt"


@pytest.mark.parametrize(
    "remarks, expected",
    [
        ("", "LISTED"),
        ("Suspended w.e.f. 05-04-2024.", "SUSPENDED"),
        ("Suspension revoked w.e.f. 23-08-2024 (Present status operative) Suspended w.e.f. 05-04-2024.", "LISTED"),
        ("SUSPENDED W.E.F. 31-01-2020 Suspension revoked w.e.f. 05-11-2019..", "SUSPENDED"),
        ("Suspended for three months w.e.f. 25-09-2019.", "SUSPENDED"),
        ("Recognition withdrawn w.e.f. 01-02-2025", "WITHDRAWN"),
        ("Deferrment of Renewal of recognition w.e.f. 16-12-2017", "LISTED"),
    ],
)
def test_derive_lab_status(remarks, expected):
    status, basis = derive_lab_status(remarks)
    assert status == expected
    assert basis
