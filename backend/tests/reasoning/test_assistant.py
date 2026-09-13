"""Assistant answers: routing, EN/HI wording, identifiers kept verbatim, and evidence behind every item."""

import re
from datetime import date

import pytest

from manakmarg.reasoning.assistant import answer
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)
DEVANAGARI = re.compile("[ऀ-ॿ]")


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("assistant") / "fixture.sqlite3")
    yield eng
    eng.dispose()


def _ask(engine, query, lang="en"):
    with engine.connect() as conn:
        return answer(conn, query, lang=lang, today=TODAY)


def _assert_evidence_resolves(response):
    known = response.evidence.ids()
    for section in response.sections:
        for item in section.items:
            assert set(item.evidence_ids) <= known
    assert set(response.headline_evidence) <= known


def test_manufacturer_question(engine):
    response = _ask(engine, "Which standard applies to stainless steel cookware and is BIS certification mandatory?")
    assert "Stainless Steel Cookware" in response.headline and "compulsory" in response.headline
    assert response.status_label in ("LIKELY_APPLICABLE", "CANDIDATE")
    standards = next(section for section in response.sections if section.key == "standards")
    assert any("14756" in item.text for item in standards.items)
    assert any(link["to"].startswith("/journey") for link in response.links)
    _assert_evidence_resolves(response)


def test_order_numbers_are_not_repeated_when_the_title_already_carries_them(engine):
    response = _ask(engine, "Is ordinary portland cement compulsory?")
    orders = next(section for section in response.sections if section.key == "orders")
    for item in orders.items:
        numbers = [token for token in ("S.O.", "G.S.R.") if token in item.text]
        assert all(item.text.count(token) == 1 for token in numbers), item.text


def test_hindi_answer_keeps_identifiers(engine):
    response = _ask(engine, "Is IS 269 cement compulsory?", lang="hi")
    assert DEVANAGARI.search(response.headline)
    assert any("IS 269" in item.text for section in response.sections for item in section.items)
    _assert_evidence_resolves(response)


def test_hallmarking_district_answer(engine):
    response = _ask(engine, "Is hallmarking mandatory in Jaipur?")
    assert response.status_label == "COVERED"
    assert "Jaipur, Rajasthan" in response.headline and "phase 1" in response.headline
    ahcs = next(section for section in response.sections if section.key == "ahcs")
    assert "operative AHC" in ahcs.items[0].text
    assert any(section.key == "jewellers" for section in response.sections)
    _assert_evidence_resolves(response)


def test_state_level_hallmarking_question_in_hindi(engine):
    response = _ask(engine, "क्या राजस्थान में सोने के गहनों पर हॉलमार्किंग अनिवार्य है?", lang="hi")
    assert response.understanding.state == "Rajasthan"
    assert DEVANAGARI.search(response.headline) and "Rajasthan" in response.headline and "26" in response.headline
    district_notes = next(section for section in response.sections if section.key == "district")
    assert any("Jalore" in item.text for item in district_notes.items)
    ahcs = next(section for section in response.sections if section.key == "ahcs")
    assert ahcs.items[0].text.startswith("Rajasthan में")
    _assert_evidence_resolves(response)


def test_lab_answer(engine):
    response = _ask(engine, "labs for IS 2062")
    assert "IS 2062" in response.headline
    labs = next(section for section in response.sections if section.key == "labs")
    assert labs.items and all(item.evidence_ids for item in labs.items)


def test_upcoming_and_process_answers(engine):
    upcoming = _ask(engine, "upcoming QCOs")
    assert next(section for section in upcoming.sections if section.key == "upcoming").items
    process = _ask(engine, "How do I apply for a BIS licence?")
    assert len(next(section for section in process.sections if section.key == "process").items) == 10


def test_general_question_uses_official_faqs(engine):
    response = _ask(engine, "What is HUID?")
    items = [item for section in response.sections if section.key == "faq" for item in section.items]
    assert items and "HUID" in items[0].text
    assert response.evidence.get(items[0].evidence_ids[0]).kind == "faq"


def test_unknown_product_is_not_declared_unregulated(engine):
    response = _ask(engine, "xylophone quasar compulsory?")
    assert "No compulsory-certification listing" in response.headline
    assert "absence_not_proof" in response.caveats


def test_out_of_scope_question_does_not_search_bis_data(engine):
    response = _ask(engine, "What is the capital of France?")
    assert response.understanding.in_scope is False
    assert "outside MANAK MARG" in response.headline
    assert not response.sections


def test_malformed_standard_identifier_is_not_confirmed(engine):
    response = _ask(engine, "What is IS 2O62?")
    assert response.understanding.standard_refs == ()
    assert "IS 2" not in response.headline
