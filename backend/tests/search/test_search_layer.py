"""FTS5 search, LSA vectors and hybrid product matching over a database loaded from real fixture snapshots."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from manakmarg.db import fts, schema
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.ingest.bis_pages import parse_faq_page
from manakmarg.ingest.bis_schemes import parse_scheme_i
from manakmarg.ingest.compliance_loader import load_scheme_records
from manakmarg.ingest.loaders import load_faqs
from manakmarg.ingest.runs import RunRecorder
from manakmarg.search.fts_search import fts_query, search_coverage, search_faq, search_standards, stem
from manakmarg.search.hybrid import expand_synonyms, find_product_matches
from manakmarg.search.vectors import VectorIndex, build_vector_indexes, load_vector_indexes
from tests.standards_seed import add_standard

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bis"
SCHEME_I_URL = sources.REGISTRY["bis_scheme_i_page"].url
FAQ_URL = sources.REGISTRY["bis_faq_hallmarking_general"].url


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    root = tmp_path_factory.mktemp("search")
    eng = get_engine(root / "search.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
        add_standard(conn, "IS 14756:2024", "Stainless Steel Utensils — Specification")
        add_standard(conn, "IS 269:2015", "Ordinary Portland Cement — Specification")
        add_standard(conn, "IS 1417:2016", "Gold and Gold Alloys, Jewellery/Artefacts — Fineness and Marking")
    with RunRecorder(eng, "bis_scheme_i_page") as run:
        load_scheme_records(run, parse_scheme_i((FIXTURES / "scheme_i.html").read_bytes(), SCHEME_I_URL), scheme_id="SCHEME_I", page_url=SCHEME_I_URL)
    with RunRecorder(eng, "bis_faq_hallmarking_general") as run:
        load_faqs(run, parse_faq_page((FIXTURES / "faq_hallmarking_general.html").read_bytes(), "hallmarking_general", FAQ_URL), page_url=FAQ_URL)
    with eng.begin() as conn:
        fts.rebuild_fts(conn)
    yield eng
    eng.dispose()


def _product(conn, coverage_id):
    return conn.execute(
        sa.select(schema.scheme_coverage.c.product_name).where(schema.scheme_coverage.c.coverage_id == coverage_id)
    ).scalar()


@pytest.mark.parametrize(
    "token, expected",
    [("utensils", "utensil"), ("batteries", "battery"), ("glasses", "glass"), ("switches", "switch"), ("gas", "gas"), ("status", "status")],
)
def test_plural_folding(token, expected):
    assert stem(token) == expected


def test_fts_query_quotes_terms_and_never_passes_syntax_through():
    assert fts_query('IS 2062:2011 "steel" -plates NEAR') == '"2062" OR "2011" OR "steel"* OR "plate"* OR "near"*'
    assert fts_query("the of and") == ""
    assert fts_query("cement pipes", mode="all") == '"cement"* AND "pipe"*'


def test_coverage_search_finds_listed_products(engine):
    with engine.connect() as conn:
        hits = search_coverage(conn, "ordinary portland cement")
        assert hits
        assert _product(conn, hits[0].id) == "Ordinary Portland Cement"
        assert search_coverage(conn, "BIS licence") == []
        assert any("14756" in (hit.snippet or "") or "Stainless" in hit.title for hit in search_coverage(conn, "IS 14756"))


def test_standard_and_faq_search(engine):
    with engine.connect() as conn:
        assert search_standards(conn, "gold jewellery fineness")[0].title.startswith("IS 1417:2016")
        faq_hits = search_faq(conn, "What is HUID?")
    assert faq_hits and "HUID" in faq_hits[0].title


def test_vector_index_ranks_related_text_and_survives_a_round_trip(tmp_path):
    texts = [
        "stainless steel utensils and cookware",
        "ordinary portland cement",
        "electric ceiling type fans",
        "protective helmets for two wheeler riders",
        "domestic pressure cookers",
    ]
    index = VectorIndex.build([10, 20, 30, 40, 50], texts)
    assert index.query("ceiling fan", k=2)[0][0] == "30"
    assert index.query("steel cookware", k=1)[0][0] == "10"
    index.save(tmp_path, "tiny")
    assert VectorIndex.load(tmp_path, "tiny").query("helmet for riders", k=3) == index.query("helmet for riders", k=3)


def test_vector_index_uses_svd_for_larger_corpora(tmp_path):
    words = ["steel", "cement", "helmet", "fan", "cooker", "cable", "toy", "tyre", "glass", "pipe"]
    texts = [f"{words[i % 10]} {words[(i * 3) % 10]} product variant {i}" for i in range(260)]
    index = VectorIndex.build(list(range(260)), texts, dimensions=32)
    assert index.svd is not None
    assert index.query(texts[7], k=1)[0][0] == "7"


def test_vector_indexes_are_built_from_the_database(engine, tmp_path):
    with engine.connect() as conn:
        counts = build_vector_indexes(conn, tmp_path, dimensions=64)
    assert counts["coverage"] > 200 and counts["faq"] == 25
    assert set(load_vector_indexes(tmp_path)) == {"coverage", "standards", "faq"}


def test_synonyms_expand_everyday_and_hindi_words():
    assert ("steel ke bartan", "stainless steel utensils") in expand_synonyms("steel ke bartan banane hain")
    assert ("bartan", "stainless steel utensils") in expand_synonyms("bartan")


def test_synonyms_match_plural_forms():
    assert ("solar panel", "photovoltaic modules") in expand_synonyms("BIS for solar panels")
    assert ("led bulb", "self ballasted led lamps") in expand_synonyms("ISI mark for LED bulbs")
    assert any(target == "electric ceiling type fans" for _, target in expand_synonyms("पंखा"))
    assert expand_synonyms("hydraulic press") == []


def test_hybrid_matching_uses_synonyms_and_reports_how(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "steel ke bartan")
    assert ("steel ke bartan", "stainless steel utensils") in matches.synonyms_used or (
        "bartan",
        "stainless steel utensils",
    ) in matches.synonyms_used
    top = matches.coverage[:3]
    assert any("Stainless Steel" in candidate.product_name for candidate in top)
    assert any(via.startswith("synonym:") for candidate in top for via in candidate.matched_via)


def test_hybrid_matching_prefers_listings_linked_to_a_quoted_standard(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "Do I need BIS certification for IS 14756 utensils?")
    assert matches.identifiers[0].family_key == "IS 14756"
    assert "standard_reference" in matches.coverage[0].matched_via
    assert matches.standards[0].std_key == "IS 14756:2024"


def test_exact_product_name_has_full_token_coverage(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "Ordinary Portland Cement")
    assert matches.coverage[0].product_name == "Ordinary Portland Cement"
    assert matches.coverage[0].token_coverage == 1.0


def test_vector_neighbours_sharing_no_query_word_are_not_candidates(engine, tmp_path):
    with engine.connect() as conn:
        build_vector_indexes(conn, tmp_path, dimensions=64)
        matches = find_product_matches(conn, "xylophone quasar", vectors=load_vector_indexes(tmp_path))
        cement = find_product_matches(conn, "portland cement", vectors=load_vector_indexes(tmp_path))
    assert matches.coverage == []
    assert cement.coverage[0].product_name == "Ordinary Portland Cement"


def test_unrelated_text_matches_nothing(engine):
    with engine.connect() as conn:
        matches = find_product_matches(conn, "xylophone quasar")
    assert matches.coverage == [] and matches.identifiers == ()
