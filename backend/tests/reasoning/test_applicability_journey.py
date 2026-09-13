"""Applicability labels, compulsory status and the compliance journey over fixture-loaded official records."""

from datetime import date

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.reasoning.applicability import (
    CANDIDATE,
    COMPULSORY,
    CONFIRMED,
    DENOTIFIED,
    ENFORCEMENT_DATE_REACHED,
    LIKELY_APPLICABLE,
    NEEDS_VERIFICATION,
    NO_LISTING_FOUND,
    UNKNOWN,
    UPCOMING,
    assess,
)
from manakmarg.reasoning.journey import build_journey
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("applicability") / "fixture.sqlite3")
    yield eng
    eng.dispose()


def test_product_words_matching_a_listing(engine):
    with engine.connect() as conn:
        result = assess(conn, text="Ordinary Portland Cement", today=TODAY)
    assert result.basis == "product_text"
    assert result.label in (LIKELY_APPLICABLE, CANDIDATE)
    assert result.compulsory == COMPULSORY
    assert result.listings[0].product_name == "Ordinary Portland Cement"
    assert "confirm_product" in result.caveats
    assert result.evidence.get(result.listings[0].evidence_id).kind == "coverage_listing"


def test_quoted_standard_confirms_the_listing(engine):
    with engine.connect() as conn:
        result = assess(conn, std_key="IS 269", today=TODAY)
    assert (result.label, result.compulsory, result.basis) == (CONFIRMED, COMPULSORY, "standard_reference")
    assert "Ordinary Portland Cement" in {listing.product_name for listing in result.listings}


def test_standard_published_only_in_parts_still_finds_listings_citing_the_whole_standard(engine):
    with engine.connect() as conn:
        result = assess(conn, std_key="IS 14756", today=TODAY)
    assert result.identifiers[0].kind == "family_ambiguous"
    assert (result.label, result.compulsory) == (CONFIRMED, COMPULSORY)
    assert any("14756" in link.ref_raw for listing in result.listings for link in listing.standards)


def test_denotified_listing_needs_verification(engine):
    with engine.connect() as conn:
        result = assess(conn, text="packaged drinking water", today=TODAY)
    assert (result.label, result.compulsory) == (NEEDS_VERIFICATION, DENOTIFIED)
    assert "status_needs_verification" in result.caveats


def test_no_listing_is_never_presented_as_proof(engine):
    with engine.connect() as conn:
        result = assess(conn, text="xylophone quasar", today=TODAY)
    assert (result.label, result.compulsory) == (UNKNOWN, NO_LISTING_FOUND)
    assert "absence_not_proof" in result.caveats


def test_product_on_scheme_page_and_upcoming_page_leads_with_the_enforcement_date(engine):
    # The fixture lists "Pipe Wrenches – General Purpose" on the Scheme I page and on the upcoming-QCO page.
    with engine.connect() as conn:
        before = assess(conn, text="Pipe Wrenches General Purpose", today=TODAY)
        after = assess(conn, text="Pipe Wrenches General Purpose", today=date(2026, 10, 2))
    assert (before.listings[0].page_kind, before.listings[0].effect, before.listings[0].days_to_enforcement) == ("upcoming_qco", UPCOMING, 18)
    assert before.compulsory == UPCOMING
    assert {listing.page_kind for listing in before.listings[:2]} == {"upcoming_qco", "scheme_i"}
    assert "listed_and_upcoming" in before.caveats
    upcoming_after = next(listing for listing in after.listings if listing.page_kind == "upcoming_qco")
    assert upcoming_after.effect == ENFORCEMENT_DATE_REACHED
    assert "listed_and_upcoming" not in after.caveats


def test_upcoming_caveat_only_describes_the_lead_listing(engine):
    with engine.connect() as conn:
        heavy = conn.execute(
            sa.select(schema.scheme_coverage.c.coverage_id).where(schema.scheme_coverage.c.product_name == "Ordinary Portland Cement")
        ).scalar()
        wrench_twins = [
            row.coverage_id
            for row in conn.execute(
                sa.select(schema.scheme_coverage.c.coverage_id).where(schema.scheme_coverage.c.product_name.like("Pipe Wrenches%General Purpose"))
            )
        ]
        from manakmarg.reasoning.applicability import _lead_with_future_enforcement, load_listings
        from manakmarg.reasoning.evidence import EvidenceBuilder

        listings = load_listings(conn, [heavy, *wrench_twins], EvidenceBuilder(conn), TODAY)
    ordered, flagged = _lead_with_future_enforcement(listings)
    assert ordered[0].product_name == "Ordinary Portland Cement"
    assert flagged is False
    ordered, flagged = _lead_with_future_enforcement(listings[1:])
    assert ordered[0].page_kind == "upcoming_qco" and flagged is True


def test_selected_listing_is_confirmed(engine):
    with engine.connect() as conn:
        coverage_id = conn.execute(
            sa.select(schema.scheme_coverage.c.coverage_id).where(schema.scheme_coverage.c.product_name == "Ordinary Portland Cement")
        ).scalar()
        result = assess(conn, coverage_id=coverage_id, today=TODAY)
    assert (result.label, result.basis, result.listings[0].coverage_id) == (CONFIRMED, "selected_listing", coverage_id)


def test_journey_for_utensils_uses_the_parsed_manual_and_official_steps(engine):
    with engine.connect() as conn:
        journey = build_journey(conn, std_key="IS 14756", city="Delhi", today=TODAY)
    steps = {step.key: step for step in journey.steps}
    assert list(steps) == ["product", "standards", "compulsory_status", "scheme", "product_manual", "tests", "labs", "application"]
    assert steps["compulsory_status"].state == "ok"
    assert steps["scheme"].data["scheme_id"] == "SCHEME_I" and len(steps["scheme"].data["documents"]) == 11
    assert steps["product_manual"].data["manuals"][0]["title"] == "STAINLESS STEEL UTENSILS"
    assert steps["tests"].data["source"] == "product_manual"
    assert any(row["requirement"] == "Staining Test" for row in steps["tests"].data["sit_rows"])
    assert steps["labs"].state == "attention" and steps["labs"].data["lims_search_urls"]
    assert len(steps["application"].data["steps"]) == 10
    codes = [action["code"] for action in journey.next_actions]
    assert "read_product_manual" in codes and "search_lims" in codes and "apply_online" in codes
    known = journey.evidence.ids()
    assert all(evidence_id in known for step in journey.steps for evidence_id in step.evidence_ids)


def test_journey_without_any_record_marks_steps_missing(engine):
    with engine.connect() as conn:
        journey = build_journey(conn, text="xylophone quasar", today=TODAY)
    steps = {step.key: step for step in journey.steps}
    assert steps["compulsory_status"].state == "missing"
    assert "absence_not_proof" in steps["compulsory_status"].notes
    assert steps["standards"].state == "missing"
    assert "check_official_listing" in [action["code"] for action in journey.next_actions]
