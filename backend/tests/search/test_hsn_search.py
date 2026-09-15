"""Local HSN lookup: exact codes, codes under a heading, text ranking, malformed input, API and assistant use."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from manakmarg.api import deps
from manakmarg.api.app import create_app
from manakmarg.core.config import Settings
from manakmarg.db import fts
from manakmarg.ingest.hsn import ingest_hsn
from manakmarg.reasoning import groq
from manakmarg.reasoning.assistant import answer
from manakmarg.search.hsn import search_hsn
from tests.fixture_db import build_fixture_db
from tests.hsn_workbook import HSN_ROWS, write_hsn_workbook

TODAY = date(2026, 9, 13)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    root = tmp_path_factory.mktemp("hsn_search")
    eng = build_fixture_db(root / "fixture.sqlite3")
    write_hsn_workbook(root / "data")
    ingest_hsn(eng, root / "data")
    with eng.begin() as conn:
        fts.rebuild_fts(conn, "hsn_fts")
    yield eng
    eng.dispose()


def _search(engine, query, **kwargs):
    with engine.connect() as conn:
        return search_hsn(conn, query, **kwargs)


def test_exact_code_then_codes_filed_under_it(engine):
    result = _search(engine, "7305 31")
    assert result.mode == "code"
    assert [match.code for match in result.matches] == ["730531", "73053121", "73053129"]
    assert result.matches[0].match == "exact" and result.matches[1].match == "within_code"
    assert [parent["code"] for parent in result.matches[1].parents] == ["73", "7305", "730531"]
    assert result.matches[1].description == "Non-galvanised, of iron : Clad, plated or coated"


def test_code_with_a_space_and_leading_zero(engine):
    assert [match.code for match in _search(engine, "230700").matches] == ["2307 00"]
    assert [match.code for match in _search(engine, "0101").matches] == ["0101"]


@pytest.mark.parametrize("query, note", [("7", "hsn_code_length"), ("123456789", "hsn_code_length"), ("7305x21", "hsn_code_malformed"), ("99999999", "hsn_code_not_found")])
def test_invalid_or_unknown_codes_return_nothing(engine, query, note):
    result = _search(engine, query)
    assert result.matches == [] and note in result.notes


def test_text_query_prefers_descriptions_with_every_word(engine):
    result = _search(engine, "copper wire")
    assert result.mode == "text"
    assert result.matches[0].code == "7408"  # "COPPER WIRE": the words in the user's order, shortest description
    assert all(match.coverage == 1.0 for match in result.matches)
    assert {match.code for match in result.matches} == {"7408", "74081110", "74081990", "74142010"}
    cloth = next(match for match in result.matches if match.code == "74142010")
    assert [parent["code"] for parent in cloth.parents] == ["74"]  # the "OMITTED" 7414 row is not shown as a heading


def test_partial_word_matches_are_not_offered(engine):
    result = _search(engine, "copper pipes")  # no description contains both words
    assert result.matches == [] and "hsn_no_match" in result.notes


def test_unrelated_text_returns_no_codes(engine):
    result = _search(engine, "quantum flux capacitor")
    assert result.matches == [] and "hsn_no_match" in result.notes


def test_assistant_hsn_question_is_local_and_separate(engine, monkeypatch):
    calls = []
    monkeypatch.setattr(groq.requests, "post", lambda *args, **kwargs: calls.append(1))
    settings = Settings(_env_file=None, groq_api_key="gsk-test-not-real")
    with engine.connect() as conn:
        by_text = answer(conn, "What is the HSN code for copper wire?", today=TODAY, settings=settings)
        by_code = answer(conn, "HSN code 73053121", today=TODAY, settings=settings)
        hindi = answer(conn, "copper wire का एचएसएन कोड क्या है?", lang="hi", today=TODAY, settings=settings)
    assert calls == []  # HSN lookup never calls an external model
    assert by_text.route.category == "hsn_lookup" and [section.key for section in by_text.sections] == ["hsn"]
    assert "not a GST, customs or BIS determination" in by_text.headline and "hsn_not_definitive" in by_text.caveats
    assert any("7408" in item.text for item in by_text.sections[0].items)
    assert by_text.evidence.get(by_text.sections[0].items[0].evidence_ids[0]).source_id == "hsn_master_workbook"
    assert by_code.sections[0].items[0].text.startswith("HSN 73053121 — Non-galvanised, of iron")
    assert hindi.route.category == "hsn_lookup" and hindi.sections


def test_product_answer_adds_related_hsn_without_changing_bis_status(engine):
    with engine.connect() as conn:
        response = answer(conn, "Is BIS certification mandatory for stainless steel cookware?", today=TODAY)
        copper = answer(conn, "I need BIS standard for copper wire", today=TODAY)
    keys = [section.key for section in response.sections]
    assert "Stainless Steel Cookware" in response.headline and "hsn_related" not in keys  # no code has every word
    copper_keys = [section.key for section in copper.sections]
    assert "hsn_related" in copper_keys and copper_keys[0] != "hsn_related"
    assert "hsn_not_definitive" in copper.caveats and "copper" in copper.headline.lower()


def test_hsn_api(engine, tmp_path):
    settings = Settings(_env_file=None)
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=tmp_path / "indexes"), frontend_dir=tmp_path / "nofe")
    with TestClient(app) as client:
        search = client.get("/api/hsn/search", params={"q": "copper wire"})
        code = client.get("/api/hsn/code/7305")
        missing = client.get("/api/hsn/code/99999999")
        invalid = client.get("/api/hsn/code/73x5")
        empty = client.get("/api/hsn/search", params={"q": ""})
        meta = client.get("/api/meta").json()
    assert search.status_code == 200 and search.json()["matches"] and search.json()["source"]["source_id"] == "hsn_master_workbook"
    assert "not a GST" in search.json()["disclaimer"]["en"]
    assert code.status_code == 200 and code.json()["matches"][0]["code"] == "7305"
    assert missing.status_code == 404 and invalid.status_code == 422 and empty.status_code == 422
    assert meta["counts"]["hsn_codes"] == len(HSN_ROWS)
