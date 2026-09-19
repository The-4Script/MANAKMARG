"""A listing whose cited standard is titled exactly what the user named ranks ahead of a narrower listing name."""

import pytest
import sqlalchemy as sa

from manakmarg.db import schema
from manakmarg.search.hybrid import find_product_matches, title_head
from tests.fixture_db import build_fixture_db
from tests.standards_seed import add_standard


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("ranking") / "fixture.sqlite3")
    with eng.begin() as conn:
        table = schema.standard
        conn.execute(
            table.update()
            .where(table.c.std_key == "IS 2062 (Part 1):2025")
            .values(title="Structural Steel - Part 1 - Hot Rolled Medium and High tensile Steel", title_clean="Structural Steel - Part 1 - Hot Rolled Medium and High tensile Steel")
        )
        add_standard(conn, "IS 15911:2010", "Structural steel (Ordinary Quality) - Specification")
    yield eng
    eng.dispose()


def test_title_head():
    assert title_head("Structural Steel - Part 1 - Hot Rolled Medium and High tensile Steel") == "structural steel"
    assert title_head("Structural steel (Ordinary Quality) - Specification") == "structural steel ordinary quality"
    assert title_head("Stainless Steel Utensils — Specification (Third Revision)") == "stainless steel utensils"


def test_structural_steel_prefers_the_listing_citing_is_2062(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "structural steel")
        links = schema.coverage_standard
        lead_families = {row.family_key for row in conn.execute(sa.select(links.c.family_key).where(links.c.coverage_id == matches.coverage[0].coverage_id))}
    assert matches.coverage[0].product_name == "Hot rolled medium and high tensile structural steel"
    assert "standard_title" in matches.coverage[0].matched_via
    assert "IS 2062" in lead_families
    assert any(candidate.product_name == "Structural Steel (Ordinary Quality)" for candidate in matches.coverage[1:])


def test_title_signal_needs_every_query_word(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "ordinary structural steel")
    assert all("standard_title" not in candidate.matched_via for candidate in matches.coverage)
