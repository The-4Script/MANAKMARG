"""Hallmarking advisor, laboratory matching and evidence assembly over fixture-loaded official records."""

import json
from datetime import date
from pathlib import Path

import pytest

from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.hallmarking import (
    parse_ahc_events,
    parse_ahc_list,
    parse_gazette_annex,
    parse_phasewise_districts,
    validate_against_gazette,
)
from manakmarg.ingest.lab_lists import parse_group_list
from manakmarg.ingest.lims import parse_lims_directory, parse_lims_scope_search
from manakmarg.ingest.loaders import (
    load_ahc_events,
    load_ahcs,
    load_districts,
    load_gazette_only_districts,
    load_group_list,
    load_lab_scope,
    load_labs,
)
from manakmarg.ingest.runs import RunRecorder
from manakmarg.reasoning.evidence import EvidenceBuilder
from manakmarg.reasoning.hallmarking import (
    AMBIGUOUS,
    COVERED,
    COVERED_NEEDS_VERIFICATION,
    NOT_IN_LIST,
    check_district,
    find_ahcs,
    jeweller_guidance,
)
from manakmarg.reasoning.labs import (
    LAB_BIS,
    LAB_EXPIRED,
    LAB_SUSPENDED,
    LAB_VALID,
    LAB_VALIDITY_UNKNOWN,
    find_labs,
    lab_status,
)
from tests.standards_seed import seed_standards

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
REGISTRY = sources.REGISTRY
TODAY = date(2026, 9, 13)


def _read(name):
    return (FIXTURES / name).read_bytes()


def _json_pages(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["pages"]


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = get_engine(tmp_path_factory.mktemp("reasoning") / "reasoning.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
        seed_standards(conn, ["IS 2062 (Part 1):2025", "IS 269:2015"])

    ahc_url = REGISTRY["manak_ahc_list"].url
    with RunRecorder(eng, "manak_ahc_list") as run:
        load_ahcs(run, parse_ahc_list(_read("ahc_list.html"), ahc_url), page_url=ahc_url)
    events_url = REGISTRY["manak_ahc_cancelled_suspended"].url
    with RunRecorder(eng, "manak_ahc_cancelled_suspended") as run:
        load_ahc_events(run, parse_ahc_events(_read("ahc_cancelled_suspended.html"), events_url), page_url=events_url)

    records = parse_phasewise_districts([page["text"] for page in _json_pages("hm_districts_phasewise_2026_09.json")])
    annex = parse_gazette_annex([page["text"] for page in _json_pages("hm_gazette_so4345_2026_08_03_english.json")])
    validation = validate_against_gazette(records, annex)
    with RunRecorder(eng, "bis_hm_districts_phasewise") as run:
        load_districts(run, records, validation, document_url=REGISTRY["bis_hm_districts_phasewise"].url)
    with RunRecorder(eng, "bis_hm_gazette_2026_08_03") as run:
        load_gazette_only_districts(
            run,
            list(validation.extra_in_gazette),
            document_url=REGISTRY["bis_hm_gazette_2026_08_03"].url,
            note="Listed in the Gazette annex but not in the BIS phase-wise coverage list; verify with BIS.",
        )

    directories = (
        ("lims_recognised_labs", "lims_recognised_labs_page1.html", "BIS_RECOGNISED"),
        ("lims_bis_labs", "lims_bis_labs.html", "BIS_LAB"),
        ("lims_empanelled_labs", "lims_empanelled_labs_page1.html", "GOVT_EMPANELLED"),
    )
    for source_id, fixture, category in directories:
        url = REGISTRY[source_id].url
        with RunRecorder(eng, source_id) as run:
            load_labs(run, parse_lims_directory(_read(fixture), category, url).labs, directory_url=url)
    with RunRecorder(eng, "bis_lab_group1_list") as run:
        load_group_list(
            run, parse_group_list(_json_pages("lab_group1_tables.json"), group=1), document_url=REGISTRY["bis_lab_group1_list"].url
        )
    for doc_no, fixture in (("2062", "lims_scope_search_2062_page1.html"), ("269", "lims_scope_search_269_page1.html")):
        url = f"https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no={doc_no}"
        with RunRecorder(eng, "lims_is_scope_search", notes=f"is_number__doc_no={doc_no}") as run:
            load_lab_scope(run, parse_lims_scope_search(_read(fixture), url).rows, query_doc_no=doc_no, search_url=url)
    yield eng
    eng.dispose()


# --------------------------------------------------------------------------- districts


def test_renamed_district_is_found_through_the_curated_rename(engine):
    with engine.connect() as conn:
        check = check_district(conn, "Gurugram")
    assert check.status == COVERED
    match = check.matches[0]
    assert (match.district, match.state, match.phase_no, match.match_basis) == ("Gurgaon", "Haryana", 1, "curated_rename")
    evidence = {check.evidence.get(evidence_id).kind: check.evidence.get(evidence_id) for evidence_id in match.evidence_ids}
    assert evidence["hallmarking_district"].url == REGISTRY["bis_hm_districts_phasewise"].url
    assert evidence["gazette_cross_check"].authority == "derived"


def test_district_missing_from_the_gazette_annex_needs_verification(engine):
    with engine.connect() as conn:
        assert check_district(conn, "Kakinada", "Andhra Pradesh").status == COVERED_NEEDS_VERIFICATION


def test_district_listed_only_in_the_gazette_is_flagged_not_dropped(engine):
    with engine.connect() as conn:
        check = check_district(conn, "Jalore")
    assert check.status == COVERED_NEEDS_VERIFICATION
    assert "gazette_only" in check.notes
    assert check.evidence.get(check.matches[0].evidence_ids[0]).source_id == "bis_hm_gazette_2026_08_03"


def test_same_district_name_in_two_states_is_ambiguous_until_a_state_is_given(engine):
    with engine.connect() as conn:
        assert check_district(conn, "Bilaspur").status == AMBIGUOUS
        chhattisgarh = check_district(conn, "Bilaspur", "Chhattisgarh")
    assert chhattisgarh.status == COVERED
    assert [match.state for match in chhattisgarh.matches] == ["Chhattisgarh"]


def test_unlisted_district_is_not_confirmed_and_typos_get_suggestions(engine):
    with engine.connect() as conn:
        assert check_district(conn, "Leh").status == NOT_IN_LIST
        typo = check_district(conn, "Ambalaa")
    assert typo.status == NOT_IN_LIST and typo.matches == []
    assert {"district": "Ambala", "state": "Haryana"} in typo.suggestions


# --------------------------------------------------------------------------- assaying & hallmarking centres


def test_only_operative_centres_are_returned_by_default(engine):
    with engine.connect() as conn:
        result = find_ahcs(conn, today=TODAY)
    assert result.operative and all(view.effective_status == "OPERATIVE" for view in result.operative)
    assert result.inactive == []
    assert result.counts["OPERATIVE"] == len(result.operative)
    assert sum(result.counts.values()) == 31
    jalan = next(view for view in result.operative if view.recognition_no == "CRO/RAHC/R-110002")
    assert result.evidence.get(jalan.evidence_ids[0]).url == REGISTRY["manak_ahc_list"].url


def test_inactive_centres_carry_the_reasons_for_their_status(engine):
    with engine.connect() as conn:
        result = find_ahcs(conn, include_inactive=True, today=TODAY)
    views = {view.recognition_no: view for view in result.inactive}
    assert views["CRO/RAHC/R-110046"].effective_status == "SUSPENDED"
    assert any("2026-07-31" in reason for reason in views["CRO/RAHC/R-110046"].reasons)
    assert views["CRO/RAHC/R-110085"].effective_status == "SUSPENDED"
    assert views["ERO/RAHC/R-700060"].effective_status == "NOT_OPERATIVE"
    assert views["CRO/RAHC/R-110077"].effective_status == "SUSPENDED_GOLD_ONLY"


def test_operability_is_computed_against_the_given_date(engine):
    with engine.connect() as conn:
        later = find_ahcs(conn, include_inactive=True, today=date(2026, 10, 1))
    assert {view.recognition_no: view.effective_status for view in later.inactive}["CRO/RAHC/R-110059"] == "EXPIRED_VALIDITY"


def test_centres_are_filtered_by_state_and_district(engine):
    with engine.connect() as conn:
        south_delhi = find_ahcs(conn, state="Delhi", district="South Delhi", today=TODAY)
    assert "CRO/RAHC/R-110002" in {view.recognition_no for view in south_delhi.operative}
    assert all(view.state == "Delhi" for view in south_delhi.operative)


def test_jeweller_lookup_points_to_the_official_report():
    guidance = jeweller_guidance()
    assert guidance["access_status"] == "captcha_blocked"
    assert guidance["url"].startswith("https://huid.manakonline.in/")


# --------------------------------------------------------------------------- laboratories


def test_labs_for_a_standard_rank_valid_published_versions_first(engine):
    with engine.connect() as conn:
        result = find_labs(conn, "IS 2062", today=TODAY)
    assert result.indexed_doc_numbers == ["2062"]
    assert len(result.matches) == 6
    first = result.matches[0]
    assert first.status in {LAB_VALID, LAB_BIS} and first.version_in_published_list
    erl = next(match for match in result.matches if "Eastern Regional Laboratory" in match.lab_name)
    assert (erl.status, erl.version_in_published_list, erl.lab_category) == (LAB_BIS, False, "BIS_LAB")
    assert next(match for match in result.matches if match.osl_code == "9164606").status == LAB_VALIDITY_UNKNOWN
    unique = next(match for match in result.matches if match.osl_code == "9134536")
    assert (unique.status, unique.charges_total, unique.test_count) == (LAB_VALID, 14000.0, 98)
    assert unique.tests[0] == "Cl-6 — MANUFACTURE"
    assert result.evidence.get(unique.evidence_ids[0]).kind == "lab_scope"


def test_part_filter_and_unindexed_standards(engine):
    with engine.connect() as conn:
        part_two = find_labs(conn, "IS 2062 (Part 2)", today=TODAY)
        water = find_labs(conn, "IS 14543", today=TODAY)
    assert {match.is_ref_raw for match in part_two.matches} == {"IS 2062 (Part 2) (2026)"}
    assert len(part_two.matches) == 2
    assert water.matches == [] and water.notes == ["scope_not_indexed"]
    assert water.lims_search_urls == ["https://lims.bis.gov.in/home/search_is_number/?is_number__doc_no=14543"]


def test_location_filter_and_labelled_fallback(engine):
    with engine.connect() as conn:
        erl_state = next(
            match.state for match in find_labs(conn, "IS 2062", today=TODAY).matches if "Eastern Regional" in match.lab_name
        )
        in_state = find_labs(conn, "IS 2062", state=erl_state, today=TODAY)
        nowhere = find_labs(conn, "IS 2062", state="Nagaland", today=TODAY)
    assert erl_state
    assert not in_state.location_fallback
    assert in_state.matches and all(match.location_match == "state" for match in in_state.matches)
    assert nowhere.location_fallback
    assert all(match.location_match == "outside_location" for match in nowhere.matches)


SUSPENDED_ENTRY = {
    "group_no": 1,
    "list_as_of": "2026-08-24",
    "status_basis": 'Latest dated remark: "Suspended w.e.f. 05-04-2026"',
    "derived_status": "SUSPENDED",
    "valid_upto": date(2027, 1, 1),
}


@pytest.mark.parametrize(
    "row, entry, expected",
    [
        ({"validity_date": date(2027, 1, 1), "lims_validity_date": None, "lab_category": "BIS_RECOGNISED"}, None, LAB_VALID),
        ({"validity_date": date(2026, 1, 1), "lims_validity_date": None, "lab_category": "BIS_RECOGNISED"}, None, LAB_EXPIRED),
        ({"validity_date": None, "lims_validity_date": None, "lab_category": "BIS_LAB"}, None, LAB_BIS),
        ({"validity_date": None, "lims_validity_date": None, "lab_category": "BIS_RECOGNISED"}, None, LAB_VALIDITY_UNKNOWN),
        ({"validity_date": date(2027, 1, 1), "lims_validity_date": None, "lab_category": "BIS_RECOGNISED"}, SUSPENDED_ENTRY, LAB_SUSPENDED),
    ],
)
def test_lab_status_rules(row, entry, expected):
    status, reasons = lab_status(row, entry, TODAY)
    assert status == expected
    assert reasons


# --------------------------------------------------------------------------- evidence


def test_evidence_is_deduplicated_and_rolled_up_by_source(engine):
    with engine.connect() as conn:
        builder = EvidenceBuilder(conn)
    first = builder.add(kind="faq", record_id=1, title="Q", source_id="bis_faq_laboratory", snippet="x" * 400)
    again = builder.add(kind="faq", record_id=1, title="Q", source_id="bis_faq_laboratory")
    other = builder.add(kind="faq", record_id=2, title="Q2", source_id="bis_faq_laboratory", locator="https://www.bis.gov.in/faq/#faq-2")
    assert (first, again, other) == ("E1", "E1", "E2")
    assert len(builder.get("E1").snippet) <= 300
    assert builder.get("E2").url == "https://www.bis.gov.in/faq/"
    rollup = builder.sources()
    assert rollup[0]["evidence_ids"] == ["E1", "E2"]
    assert rollup[0]["authority"] == "official_primary"
