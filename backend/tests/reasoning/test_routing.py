"""Deterministic routing: every major question type reaches its own flow, in English, Hindi and Hinglish."""

import pytest

from manakmarg.reasoning.intents import Gazetteer, understand
from manakmarg.reasoning.routing import (
    ROUTE_AHC,
    ROUTE_CERTIFICATION,
    ROUTE_GAP,
    ROUTE_GENERAL,
    ROUTE_HALLMARKING,
    ROUTE_INVALID_IDENTIFIER,
    ROUTE_LAB,
    ROUTE_OUT_OF_SCOPE,
    ROUTE_PRODUCT,
    ROUTE_QCO,
    ROUTE_SCHEME_I,
    ROUTE_SCHEME_II,
    ROUTE_SCHEME_IV,
    ROUTE_SCHEME_X,
    ROUTE_UNKNOWN_LOCATION,
    ROUTE_UPCOMING,
    route_query,
)

GAZETTEER = Gazetteer(
    districts={"jaipur": [("Jaipur", "Rajasthan")], "kolkata": [("Kolkata", "West Bengal")], "new delhi": [("New Delhi", "Delhi")]},
    cities={"kolkata": ("Kolkata", "West Bengal")},
    product_words=frozenset({"steel", "structural", "stainless", "utensil", "cookware", "pvc", "cable", "insulated", "thermometer", "clinical", "cement", "wire", "electrical"}),
)


def _route(text):
    understanding = understand(text, gazetteer=GAZETTEER)
    return route_query(understanding, GAZETTEER), understanding


@pytest.mark.parametrize(
    "text, category",
    [
        ("Which standard applies to structural steel?", ROUTE_PRODUCT),
        ("What is IS 2062?", ROUTE_PRODUCT),
        ("I manufacture PVC cables. What standard should I follow?", ROUTE_PRODUCT),
        ("Is BIS certification mandatory for stainless steel utensils?", ROUTE_PRODUCT),
        ("How do I obtain a BIS licence?", ROUTE_CERTIFICATION),
        ("How to apply for a BIS licence?", ROUTE_CERTIFICATION),
        ("What is Scheme I?", ROUTE_SCHEME_I),
        ("What is Scheme II of BIS certification?", ROUTE_SCHEME_II),
        ("What is Scheme IV?", ROUTE_SCHEME_IV),
        ("What is Scheme X?", ROUTE_SCHEME_X),
        ("What happens if my product is not covered by mandatory BIS certification?", ROUTE_QCO),
        ("Find labs for IS 2062 in Kolkata", ROUTE_LAB),
        ("Is hallmarking mandatory in Jaipur?", ROUTE_HALLMARKING),
        ("Is hallmarking mandatory for silver jewellery?", ROUTE_HALLMARKING),
        ("Find AHCs in Jaipur", ROUTE_AHC),
        ("Check my product specification against the applicable requirements.", ROUTE_GAP),
        ("What are upcoming QCOs?", ROUTE_UPCOMING),
        ("capital of France", ROUTE_OUT_OF_SCOPE),
        ("What is the capital of France?", ROUTE_OUT_OF_SCOPE),
        ("What is IS 2O62?", ROUTE_INVALID_IDENTIFIER),
        ("Gotham district", ROUTE_UNKNOWN_LOCATION),
        ("Find IS 2062 labs in Timbuktu", ROUTE_LAB),
        ("Which tests are required?", ROUTE_GENERAL),
    ],
)
def test_english_routes(text, category):
    route, _ = _route(text)
    assert route.category == category, route.reason
    assert route.reason


@pytest.mark.parametrize(
    "text, category",
    [
        ("IS 2062 क्या है?", ROUTE_PRODUCT),
        ("स्टील के लिए कौन सा BIS मानक लागू है?", ROUTE_PRODUCT),
        ("क्या स्टेनलेस स्टील के बर्तनों के लिए BIS प्रमाणन अनिवार्य है?", ROUTE_PRODUCT),
        ("BIS लाइसेंस कैसे प्राप्त करें?", ROUTE_CERTIFICATION),
        ("जयपुर में हॉलमार्किंग अनिवार्य है क्या?", ROUTE_HALLMARKING),
        ("जयपुर में हालमार्किंग अनिवार्य है क्या?", ROUTE_HALLMARKING),
        ("जयपुर में Assaying and Hallmarking Centre कहाँ हैं?", ROUTE_AHC),
        ("कोलकाता में IS 2062 की जाँच", ROUTE_LAB),
        ("राजस्थान में गहनों पर हॉलमार्किंग अनिवार्य है क्या?", ROUTE_HALLMARKING),
        ("mujhe steel ke liye BIS standard batao", ROUTE_PRODUCT),
        ("PVC cable के लिए BIS certification ज़रूरी है क्या?", ROUTE_PRODUCT),
    ],
)
def test_hindi_and_hinglish_routes(text, category):
    route, _ = _route(text)
    assert route.category == category, route.reason


def test_scheme_route_carries_the_scheme_id():
    route, _ = _route("What is Scheme IV?")
    assert route.scheme_id == "SCHEME_IV"


def test_multi_part_product_question_stays_a_product_question():
    route, understanding = _route(
        "I manufacture structural steel products. What BIS standard applies, is certification mandatory, what testing is required, and where can I get it tested?"
    )
    assert route.category == ROUTE_PRODUCT
    assert understanding.product_text == "structural steel"


def test_without_vocabulary_any_product_words_still_route_to_product_search():
    understanding = understand("ceiling fans")
    assert route_query(understanding, Gazetteer()).category == ROUTE_PRODUCT


# Product words from the listings (as the database vocabulary would supply them) for the scope checks below.
LISTING_GAZETTEER = Gazetteer(
    product_words=frozenset({"electric", "iron", "helmet", "packaged", "pasteurized", "milk", "led", "lamp", "bulb", "pressure", "cooker", "weather", "car", "weight", "steel", "gold", "cement", "copper", "colour", "hair", "dye", "match"}),
)


@pytest.mark.parametrize("text", ["electric iron", "helmet", "Packaged Pasteurized Milk", "LED bulbs"])
def test_product_named_only_by_listed_words_is_in_scope(text):
    understanding = understand(text, gazetteer=LISTING_GAZETTEER)
    assert understanding.in_scope
    assert route_query(understanding, LISTING_GAZETTEER).category == ROUTE_PRODUCT


@pytest.mark.parametrize(
    "text",
    ["weather today", "car insurance", "how to lose weight", "who won the cricket match", "steel share price", "gold rate today", "cement company jobs", "copper colour hair dye ideas"],
)
def test_other_topics_stay_out_of_scope_even_with_a_product_word(text):
    understanding = understand(text, gazetteer=LISTING_GAZETTEER)
    assert route_query(understanding, LISTING_GAZETTEER).category == ROUTE_OUT_OF_SCOPE


def test_isi_mark_question_asks_about_compulsory_status_of_the_product():
    understanding = understand("Do I need ISI mark for LED bulbs", gazetteer=LISTING_GAZETTEER)
    assert route_query(understanding, LISTING_GAZETTEER).category == ROUTE_PRODUCT
    assert understanding.product_text == "led bulbs"


def test_hinglish_filler_words_are_not_product_words():
    understanding = understand("mera product ke liye BIS chahiye kya, main pressure cooker banata hoon", gazetteer=LISTING_GAZETTEER)
    assert understanding.product_text == "pressure cooker"


@pytest.mark.parametrize(
    "text",
    ["how much is the fee for BIS certification", "how long does it take to get BIS license", "BIS licence kitne din me milta hai", "how to renew BIS licence"],
)
def test_fee_timeline_and_renewal_questions_are_process_questions(text):
    route, _ = _route(text)
    assert route.category == ROUTE_CERTIFICATION, route.reason
