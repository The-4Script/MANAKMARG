import pytest

from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.search.resolvers import StandardResolver
from tests.standards_seed import add_standard, seed_standards

SEEDED = [
    "IS 269:2015",
    "IS 1489 (Part 1):2015",
    "IS 1489 (Part 2):2015",
    "IS 14756:2024",
    "IS/ISO 80000-9:2019",
    "IS/IEC 60947 (Part 2):2016",
    "IS 10325:2000",
    "IS 10325:2026",
    "IS/ISO 13450:2008",
    "ISO 24342:2024",
]


@pytest.fixture
def seeded(tmp_path):
    engine = get_engine(tmp_path / "resolver.sqlite3")
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
        ids = seed_standards(conn, SEEDED)
        ids["retired"] = add_standard(conn, "IS 999:2001", current=False)
    with engine.connect() as conn:
        yield StandardResolver(conn), ids
    engine.dispose()


def _only(resolutions):
    assert len(resolutions) == 1, resolutions
    return resolutions[0]


def test_exact_version(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS 269:2015"))
    assert resolution.kind == "exact_version"
    assert resolution.standard_ids == (ids["IS 269:2015"],)
    assert resolution.family_key == "IS 269"


def test_spacing_variant_is_still_exact(seeded):
    resolver, ids = seeded
    assert _only(resolver.resolve_text("IS 269 : 2015")).kind == "exact_version"


def test_colon_part_notation_is_exact(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS/IEC 60947: Part 2:2016"))
    assert resolution.kind == "exact_version"
    assert resolution.standard_ids == (ids["IS/IEC 60947 (Part 2):2016"],)


def test_part_notation_variant_matches_hyphen_form(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS/ISO 80000 (Part 9):2019"))
    assert resolution.kind == "match_key_version"
    assert resolution.standard_ids == (ids["IS/ISO 80000-9:2019"],)


def test_reference_without_year_resolves_to_latest_version_first(seeded):
    resolver, ids = seeded
    single = _only(resolver.resolve_text("IS 269"))
    assert single.kind == "family_latest"
    assert single.standard_ids == (ids["IS 269:2015"],)
    versions = _only(resolver.resolve_text("IS 10325"))
    assert versions.kind == "family_latest"
    assert versions.standard_ids == (ids["IS 10325:2026"], ids["IS 10325:2000"])


def test_year_not_in_published_list(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS 14756 : 2022"))
    assert resolution.kind == "version_not_in_master"
    assert resolution.standard_ids == (ids["IS 14756:2024"],)
    assert "IS 14756:2024" in resolution.note


def test_reference_without_part_is_ambiguous_across_parts(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS 1489"))
    assert resolution.kind == "family_ambiguous"
    assert set(resolution.standard_ids) == {ids["IS 1489 (Part 1):2015"], ids["IS 1489 (Part 2):2015"]}


def test_international_reference_is_not_forced_onto_an_indian_standard(seeded):
    resolver, _ = seeded
    resolution = _only(resolver.resolve_text("ISO 10282:2023"))
    assert resolution.kind == "international_reference"
    assert resolution.standard_ids == ()


def test_international_prefix_listed_by_bis_resolves_exactly(seeded):
    resolver, ids = seeded
    assert _only(resolver.resolve_text("ISO 24342:2024")).standard_ids == (ids["ISO 24342:2024"],)


def test_prefix_mismatch_is_only_a_flagged_candidate(seeded):
    resolver, ids = seeded
    resolution = _only(resolver.resolve_text("IS 13450:2008"))
    assert resolution.kind == "prefix_mismatch_candidate"
    assert resolution.standard_ids == (ids["IS/ISO 13450:2008"],)


def test_multiple_references_in_one_cell(seeded):
    resolver, _ = seeded
    resolutions = resolver.resolve_text("IS 14286 IS/IEC 61730 -1 IS/IEC 61730 -2")
    assert [resolution.designation.std_key for resolution in resolutions] == ["IS 14286", "IS/IEC 61730-1", "IS/IEC 61730-2"]
    assert {resolution.kind for resolution in resolutions} == {"unresolved"}


def test_prefix_is_assumed_only_on_request(seeded):
    resolver, _ = seeded
    assert resolver.resolve_text("4003 (Part 1):1978") == []
    resolution = _only(resolver.resolve_text("4003 (Part 1):1978", assume_is_prefix=True))
    assert resolution.designation.std_key == "IS 4003 (Part 1):1978"
    assert resolution.kind == "unresolved"


def test_references_inside_requirement_text(seeded):
    resolver, _ = seeded
    assert [r.designation.std_key for r in resolver.resolve_text("Clause 4.2.2 of IS 10613: 2023")] == ["IS 10613:2023"]


def test_retired_standards_are_not_candidates(seeded):
    resolver, _ = seeded
    assert _only(resolver.resolve_text("IS 999:2001")).kind == "unresolved"
