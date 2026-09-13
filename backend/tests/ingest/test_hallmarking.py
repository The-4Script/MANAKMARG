"""Hallmarking sources: AHC list, cancelled/suspended AHCs, effective status, district coverage and Gazette check."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from manakmarg.ingest.hallmarking import (
    AhcEventRecord,
    effective_ahc_status,
    parse_ahc_events,
    parse_ahc_list,
    parse_gazette_annex,
    parse_phasewise_districts,
    validate_against_gazette,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
AHC_URL = "https://www.manakonline.in/MANAK/AHCListForWebsite"
EVENTS_URL = "https://huid.manakonline.in/MANAK/AHCSuspendCancelledAppsForWebsite"
TODAY = date(2026, 9, 13)


def _read(name):
    return (FIXTURES / name).read_bytes()


def _page_texts(name):
    return [page["text"] for page in json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pages"]]


# --------------------------------------------------------------------------- AHC list


@pytest.fixture(scope="module")
def ahcs():
    return parse_ahc_list(_read("ahc_list.html"), AHC_URL)


def test_ahc_list_record_fields(ahcs):
    assert len(ahcs) == 31
    first = ahcs[0]
    assert first.recognition_no == "CRO/RAHC/R-110002"
    assert first.region_code == "CRO"
    assert first.validity_date == date(2028, 7, 31)
    assert first.name == "M/s Jalan Hallmarking Centre"
    assert (first.address.district, first.address.state, first.address.pincode) == ("South Delhi", "Delhi", "110025")
    assert first.scope_text == "Recognized for Yellow Gold,Silver Hallmarking"
    assert (first.gold, first.silver) == (True, True)
    assert first.list_status_raw == "Operative"
    assert (first.org_phone, first.org_email) == ("9810009929", "jalan@jalanco.com")
    assert not hasattr(first, "contact_person")


def test_ahc_scope_variants(ahcs):
    both = next(record for record in ahcs if record.recognition_no == "CRO/RAHC/R-110006")
    assert both.scope_text == "Recognized for Gold & Silver Both Hallmarking"
    assert (both.gold, both.silver) == (True, True)
    assert both.address.state == "Rajasthan"


def test_ahc_list_statuses_are_kept_raw(ahcs):
    statuses = Counter(record.list_status_raw for record in ahcs)
    assert statuses["Under Suspension"] == 3
    assert statuses["Under Suspension(Gold Only)"] == 3
    assert statuses["Deferred"] == 3
    assert statuses["Deferment Letter Generated"] == 3


def test_ahc_events():
    events = parse_ahc_events(_read("ahc_cancelled_suspended.html"), EVENTS_URL)
    assert len(events) >= 15
    first = events[0]
    assert (first.recognition_no, first.status, first.event_date, first.region, first.center_type) == (
        "CRO/RAHC/R-110034",
        "CANCELLED",
        date(2026, 4, 30),
        "CRO",
        "AHC",
    )
    assert first.name_address_raw.startswith("SHREERAM HALLMARKING CENTRE")
    suspended = {event.recognition_no: event for event in events if event.status == "UNDER SUSPENSION"}
    assert suspended["CRO/RAHC/R-110046"].event_date == date(2026, 7, 31)


# --------------------------------------------------------------------------- effective status


def _event(status, day):
    return AhcEventRecord(
        recognition_no="CRO/RAHC/R-1",
        status=status,
        event_date=day,
        event_date_raw=day.strftime("%d/%m/%Y") if day else None,
        region="CRO",
        center_type="AHC",
        name_address_raw="X",
        locator="row1",
    )


def test_operative_valid_without_events_is_operative():
    status, reasons = effective_ahc_status("Operative", date(2028, 7, 31), [], today=TODAY)
    assert status == "OPERATIVE"
    assert reasons


def test_expired_validity_is_not_operative():
    status, reasons = effective_ahc_status("Operative", date(2026, 1, 1), [], today=TODAY)
    assert status == "EXPIRED_VALIDITY"
    assert "2026-01-01" in " ".join(reasons)


def test_missing_validity_is_not_presented_as_operative():
    assert effective_ahc_status("Operative", None, [], today=TODAY)[0] == "VALIDITY_UNKNOWN"


def test_cancellation_event_overrides_list_status():
    status, reasons = effective_ahc_status("Operative", date(2028, 1, 1), [_event("CANCELLED", date(2026, 4, 30))], today=TODAY)
    assert status == "CANCELLED"
    assert "2026-04-30" in " ".join(reasons)


@pytest.mark.parametrize(
    "list_status, expected",
    [
        ("Under Suspension", "SUSPENDED"),
        ("Under Suspension(Gold Only)", "SUSPENDED_GOLD_ONLY"),
        ("Deferred", "NOT_OPERATIVE"),
        ("Deferment Letter Generated", "NOT_OPERATIVE"),
        ("Something new", "UNKNOWN"),
    ],
)
def test_list_statuses(list_status, expected):
    assert effective_ahc_status(list_status, date(2028, 1, 1), [], today=TODAY)[0] == expected


def test_suspension_event_marks_suspended():
    assert effective_ahc_status("Operative", date(2028, 1, 1), [_event("UNDER SUSPENSION", date(2026, 7, 31))], today=TODAY)[0] == "SUSPENDED"


# --------------------------------------------------------------------------- districts


@pytest.fixture(scope="module")
def districts():
    return parse_phasewise_districts(_page_texts("hm_districts_phasewise_2026_09.json"))


def test_phasewise_district_counts(districts):
    assert len(districts) == 392
    assert Counter(record.phase_no for record in districts) == {1: 256, 2: 32, 3: 55, 4: 18, 5: 12, 6: 7, 7: 5, 8: 7}
    assert [record.sr_no for record in districts] == list(range(1, 393))


def test_phasewise_district_fields(districts):
    first = districts[0]
    assert (first.sr_no, first.state, first.district, first.phase_no, first.phase_order_date) == (
        1,
        "Haryana",
        "Ambala",
        1,
        date(2021, 6, 23),
    )
    assert next(record for record in districts if record.phase_no == 2).phase_order_date == date(2022, 4, 4)
    last = districts[-1]
    assert (last.sr_no, last.state, last.district, last.phase_no, last.phase_order_date) == (
        392,
        "Madhya Pradesh",
        "Vidisha",
        8,
        date(2026, 8, 3),
    )


def test_phasewise_state_names_are_normalised(districts):
    jaunpur = next(record for record in districts if record.district_raw == "Jaunpur District")
    assert (jaunpur.state, jaunpur.state_raw, jaunpur.district_norm) == ("Uttar Pradesh", "U.P.", "jaunpur")
    assert all(record.state for record in districts)
    assert {"Tamil Nadu", "Puducherry", "Chhattisgarh"} <= {record.state for record in districts}


def test_gazette_annex():
    annex = parse_gazette_annex(_page_texts("hm_gazette_so4345_2026_08_03_english.json"))
    assert len(annex) == 392
    assert annex[0] == ("Andhra Pradesh", "Anantapur")
    assert annex[-1] == ("West Bengal", "Uttar Dinajpur")
    assert len({state for state, _ in annex}) == 26


def test_phasewise_list_is_cross_checked_against_the_gazette(districts):
    annex = parse_gazette_annex(_page_texts("hm_gazette_so4345_2026_08_03_english.json"))
    validation = validate_against_gazette(districts, annex)
    assert validation.matched + len(validation.missing_in_gazette) == 392
    assert validation.matched + len(validation.extra_in_gazette) == 392
    assert ("Haryana", "Ambala") in validation.matched_pairs
