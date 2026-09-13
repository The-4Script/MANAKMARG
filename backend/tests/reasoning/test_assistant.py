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


def _keys(response):
    return [section.key for section in response.sections]


def _texts(response, key):
    return [item.text for section in response.sections if section.key == key for item in section.items]


def test_cable_listing_shows_the_cables_qco_not_the_pressure_cooker_amendment(engine):
    response = _ask(engine, "Is BIS certification mandatory for PVC insulated heavy duty electric cables?")
    orders = _texts(response, "orders")
    assert orders and any("Cables (Quality Control) Order, 2020" in text and "294" in text for text in orders)
    assert not any("Pressure Cooker" in text or "2019(E)" in text for text in orders)
    _assert_evidence_resolves(response)


def test_is_694_listing_has_no_pressure_cooker_order(engine):
    response = _ask(engine, "Is BIS certification mandatory for PVC insulated cables for working voltages up to 1100V?")
    orders = _texts(response, "orders")
    assert orders and all("Pressure Cooker" not in text for text in orders)
    assert any("Cables" in text for text in orders)


@pytest.mark.parametrize("query", ["How do I obtain a BIS licence?", "BIS लाइसेंस कैसे प्राप्त करें?"])
def test_licence_questions_get_official_steps_not_standards(engine, query):
    response = _ask(engine, query, lang="hi" if DEVANAGARI.search(query) else "en")
    assert response.route.category == "certification"
    assert len(_texts(response, "process")) == 10
    assert "standards" not in _keys(response) and "related_standards" not in _keys(response)


def test_scheme_question_answers_from_the_scheme_record(engine):
    response = _ask(engine, "What is Scheme I?")
    assert response.route.category == "scheme_i"
    assert "Scheme – I" in response.headline and "use of mark" in response.headline
    assert "standards" not in _keys(response)
    assert any("compulsory listing" in text for text in _texts(response, "scheme"))
    assert any(link["to"] == "/certification?tab=SCHEME_I" for link in response.links)
    _assert_evidence_resolves(response)


@pytest.mark.parametrize("query, route", [("What is Scheme II?", "scheme_ii"), ("What is Scheme IV?", "scheme_iv"), ("What is Scheme X?", "scheme_x")])
def test_other_schemes_never_fall_back_to_product_matches(engine, query, route):
    response = _ask(engine, query)
    assert response.route.category == route
    assert not {"standards", "related_standards", "other_listings", "orders"} & set(_keys(response))
    scheme = query.removeprefix("What is ").rstrip("?")
    # Answered from the scheme record when it is indexed, otherwise an explicit "not indexed" message.
    assert ("not in the indexed" in response.headline and scheme in response.headline) or response.headline_evidence
    _assert_evidence_resolves(response)


def test_not_covered_question_quotes_the_official_overview(engine):
    response = _ask(engine, "What happens if my product is not covered by mandatory BIS certification?")
    assert response.route.category == "qco_mandatory"
    assert "standards" not in _keys(response) and "other_listings" not in _keys(response)
    documents = _texts(response, "documents")
    assert documents and "voluntary" in documents[0]
    assert response.evidence.get(response.headline_evidence[0]).source_id == "bis_compulsory_overview_page"


@pytest.mark.parametrize("query", ["capital of France", "What is the capital of France?"])
def test_out_of_scope_question_uses_no_records(engine, query):
    response = _ask(engine, query)
    assert response.route.category == "out_of_scope"
    assert not response.sections and not response.evidence.ids()
    assert "outside MANAK MARG" in response.headline


def test_unlisted_product_does_not_show_unrelated_standards(engine):
    response = _ask(engine, "Which BIS standard applies to a quantum flux capacitor?")
    assert "No compulsory-certification listing" in response.headline
    assert "standards" not in _keys(response) and "related_standards" not in _keys(response)


def test_mistyped_is_number_is_unknown_not_confirmed(engine):
    response = _ask(engine, "What is IS 2O62?")
    assert response.status_label == "UNKNOWN" and response.route.category == "invalid_identifier"
    assert "2O62" in response.headline and "IS 2" not in response.headline
    assert "possible_typo" in response.caveats and not response.sections


def test_unknown_city_for_labs_is_reported(engine):
    response = _ask(engine, "Find IS 2062 labs in Timbuktu")
    assert "Timbuktu" in response.headline and "not recognised" in response.headline
    assert "location_not_recognised" in response.caveats
    assert "Timbuktu" in _texts(response, "labs")[0]


def test_unknown_district_is_reported(engine):
    response = _ask(engine, "Gotham district")
    assert response.route.category == "unknown_location" and "Gotham" in response.headline
    hallmarking = _ask(engine, "Is hallmarking mandatory in Gotham district?")
    assert "Gotham was not found" in hallmarking.headline
    assert "ahcs" not in _keys(hallmarking)


def test_silver_hallmarking_question_answers_from_the_district_records(engine):
    response = _ask(engine, "Is hallmarking mandatory for silver jewellery?")
    assert "gold jewellery and gold artefacts only" in response.headline
    assert response.headline_evidence and response.evidence.get(response.headline_evidence[0]).kind == "hallmarking_district"
    assert any("silver" in text.lower() for text in _texts(response, "faq"))
    _assert_evidence_resolves(response)


def test_hindi_devanagari_district_question(engine):
    response = _ask(engine, "जयपुर में हॉलमार्किंग अनिवार्य है क्या?", lang="hi")
    assert response.status_label == "COVERED"
    assert "Jaipur, Rajasthan" in response.headline and DEVANAGARI.search(response.headline)
    variant = _ask(engine, "जयपुर में हालमार्किंग अनिवार्य है क्या?", lang="hi")
    assert variant.status_label == "COVERED"


def test_hindi_ahc_question_lists_centres(engine):
    response = _ask(engine, "जयपुर में Assaying and Hallmarking Centre कहाँ हैं?", lang="hi")
    assert response.route.category == "ahc"
    assert "ahcs" in _keys(response)


def test_hindi_lab_question_with_devanagari_city(engine):
    response = _ask(engine, "कोलकाता में IS 2062 की जाँच", lang="hi")
    assert response.route.category == "lab_testing"
    assert "IS 2062" in response.headline and "Kolkata" in response.headline


def test_hindi_product_question(engine):
    response = _ask(engine, "क्या स्टेनलेस स्टील के बर्तनों के लिए BIS प्रमाणन अनिवार्य है?", lang="hi")
    assert response.understanding.product_text == "stainless steel utensils"
    assert "Stainless Steel Cookware" in response.headline
    _assert_evidence_resolves(response)


def test_hinglish_product_question(engine):
    response = _ask(engine, "mujhe steel ke liye BIS standard batao")
    assert response.route.category == "product_standard"
    assert response.understanding.product_text == "steel"


@pytest.mark.parametrize("query, lang", [("Which standard applies to steel?", "en"), ("स्टील के लिए कौन सा BIS मानक लागू है?", "hi"), ("mujhe steel ke liye BIS standard batao", "en")])
def test_single_broad_word_does_not_single_out_one_listing(engine, query, lang):
    response = _ask(engine, query, lang=lang)
    assert response.status_label == "CANDIDATE"
    assert "steel" in response.headline and not response.headline.startswith(("Possible match", "संभावित मिलान"))
    assert "other_listings" in _keys(response) and "confirm_product" in response.caveats


def test_specific_product_keeps_its_listing_headline(engine):
    response = _ask(engine, "Is BIS certification mandatory for stainless steel cookware?")
    assert "Stainless Steel Cookware" in response.headline


def test_not_covered_answer_has_no_loosely_matched_faqs(engine):
    response = _ask(engine, "What happens if my product is not covered by mandatory BIS certification?")
    assert _keys(response) == ["documents"]


def test_filler_words_do_not_become_product_words(engine):
    response = _ask(engine, "I manufacture PVC cables. What standard should I follow?")
    assert response.understanding.product_text == "pvc cables"
    orders = _texts(response, "orders")
    assert all("Pressure Cooker" not in text for text in orders)


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
