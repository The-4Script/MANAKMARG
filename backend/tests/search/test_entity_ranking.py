"""Entity-aware ranking: the named product must be matched, a different material is not offered, accessories rank
below the product itself and literal words outrank curated synonyms. Found by benchmarking real queries."""

from datetime import date

import pytest

from manakmarg.reasoning.applicability import assess
from manakmarg.reasoning.assistant import answer
from manakmarg.search.hybrid import entity_flags, find_product_matches
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("entities") / "fixture.sqlite3")
    yield eng
    eng.dispose()


def test_entity_flags():
    assert entity_flags("PVC sandal", product="pipe", material="pvc", synonym_targets=[]) == ["product_mismatch"]
    assert entity_flags("PVC insulated cables for working voltages up to and including 1100V", product="wire", material="copper", synonym_targets=[({"wire"}, {"cable"})]) == ["material_conflict"]
    assert entity_flags("Rubber Gaskets for Pressure Cookers", product="pressure cooker", material=None, synonym_targets=[]) == ["accessory_of_product"]
    assert entity_flags("Domestic Pressure Cooker", product="pressure cooker", material=None, synonym_targets=[]) == []
    assert entity_flags("Copper wires for general engineering purposes", product="wire", material="copper", synonym_targets=[]) == []
    assert entity_flags("Stainless Steel Cookware", product="utensils", material="steel", synonym_targets=[({"utensil"}, {"stainless", "steel", "cookware"})]) == []
    assert entity_flags("Anything at all", product=None, material=None, synonym_targets=[]) == []


@pytest.mark.parametrize(
    "name, product, material, expected",
    [
        ("Chain Pipe Wrenches", "pipe", "pvc", ["product_as_modifier"]),
        ("Steel Pipe Flanges", "pipe", None, ["product_as_modifier"]),
        ("Asbestos Cement Pressure Pipes (Light Duty)", "pipe", "pvc", ["material_conflict"]),
        ("Stainless Steel Welded pipes and tubes for general service", "pipe", "steel", []),
        ("Structural Steel (Ordinary Quality)", "structural steel", "steel", []),
        ("Specification for PVC Insulated (Heavy Duty) Electric Cables Part 1 For Working Voltages up to and Including 1100 V", "cable", "pvc", []),
        ("Low Carbon Galvanized steel wires formed wires and Tapes for armouring of Cables", "cable", None, ["accessory_of_product"]),
        ("Electric Ceiling Type Fans", "ceiling fan", None, []),
    ],
)
def test_product_must_be_the_named_thing_not_a_modifier(name, product, material, expected):
    assert entity_flags(name, product=product, material=material, synonym_targets=[]) == expected


def test_copper_wire_prefers_copper_wire_listings_over_synonym_cables(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "copper wire", material="copper", product="wire")
    top = matches.coverage[0].product_name.lower()
    assert "copper" in top and "wire" in top
    cables = [candidate for candidate in matches.coverage if "pvc insulated" in candidate.product_name.lower()]
    assert all("material_conflict" in candidate.matched_via for candidate in cables)


def test_material_only_matches_are_not_offered_as_listings(engine):
    with engine.connect() as conn:
        assessment = assess(conn, text="pvc pipes", today=TODAY, material="pvc", product="pipe")
    assert all("sandal" not in view.product_name.lower() and "sole" not in view.product_name.lower() for view in assessment.listings)
    assert all("iron" not in view.product_name.lower() for view in assessment.listings)


def test_product_itself_ranks_above_its_accessory(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "pressure cooker", product="pressure cooker")
    names = [candidate.product_name for candidate in matches.coverage]
    assert names.index("Domestic Pressure Cooker") < names.index("Rubber Gaskets for Pressure Cookers")


def test_without_entities_ranking_is_unchanged_in_kind(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "stainless steel cookware")
    assert matches.coverage[0].product_name == "Stainless Steel Cookware"
    assert not any(flag in candidate.matched_via for candidate in matches.coverage for flag in ("product_mismatch", "material_conflict", "accessory_of_product"))


def test_assistant_copper_wire_and_pvc_pipes(engine):
    with engine.connect() as conn:
        copper = answer(conn, "I need BIS standard for copper wire", today=TODAY)
        pvc = answer(conn, "BIS standard for PVC pipes", today=TODAY)
    assert "copper" in copper.headline.lower() and "wire" in copper.headline.lower()
    assert (copper.understanding.material, copper.understanding.product) == ("copper", "wire")
    assert "sandal" not in pvc.headline.lower() and "No compulsory-certification listing" in pvc.headline
