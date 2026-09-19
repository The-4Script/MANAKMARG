"""Rule-based query understanding: intents, identifiers, places and the remaining product words."""

import pytest

from manakmarg.reasoning.intents import (
    INTENT_GENERAL,
    INTENT_HALLMARKING,
    INTENT_LABS,
    INTENT_PROCESS,
    INTENT_PRODUCT,
    INTENT_STANDARD,
    INTENT_STATUS,
    INTENT_UPCOMING,
    Gazetteer,
    understand,
)

GAZETTEER = Gazetteer(
    districts={
        "jaipur": [("Jaipur", "Rajasthan")],
        "gurgaon": [("Gurgaon", "Haryana")],
        "gurugram": [("Gurgaon", "Haryana")],
        "bilaspur": [("Bilaspur", "Himachal Pradesh"), ("Bilaspur", "Chhattisgarh")],
        "kolkata": [("Kolkata", "West Bengal")],
    },
    cities={"kolkata": ("Kolkata", "West Bengal"), "noida": ("Noida", "Uttar Pradesh")},
)


def test_manufacturer_question_keeps_product_words_and_all_intents():
    result = understand("Which standard applies to stainless steel utensils and is BIS certification mandatory?", gazetteer=GAZETTEER)
    assert result.intent == INTENT_STATUS
    assert set(result.intents) >= {INTENT_STATUS, INTENT_STANDARD, INTENT_PRODUCT}
    assert result.product_text == "stainless steel utensils"
    assert result.language == "en"


def test_hallmarking_question_with_a_district():
    result = understand("Is Jaipur covered under mandatory hallmarking?", gazetteer=GAZETTEER)
    assert result.intent == INTENT_HALLMARKING
    assert (result.district, result.state) == ("Jaipur", "Rajasthan")
    assert result.product_text is None


def test_renamed_district_is_recognised_through_aliases():
    result = understand("AHC near Gurugram for gold", gazetteer=GAZETTEER)
    assert (result.intent, result.district, result.state, result.metal) == (INTENT_HALLMARKING, "Gurgaon", "Haryana", "gold")


def test_district_shared_by_two_states_keeps_the_state_open():
    result = understand("hallmarking in Bilaspur", gazetteer=GAZETTEER)
    assert (result.district, result.state) == ("Bilaspur", None)


def test_lab_search_with_standard_and_city():
    result = understand("labs for IS 2062 in Kolkata", gazetteer=GAZETTEER)
    assert result.intent == INTENT_LABS
    assert result.standard_refs == ("IS 2062",)
    assert result.doc_numbers == ("2062",)
    assert (result.city, result.state) == ("Kolkata", "West Bengal")


def test_bare_number_is_read_as_an_indian_standard_only_in_a_lab_or_standard_context():
    assert understand("2062 testing labs West Bengal", gazetteer=GAZETTEER).standard_refs == ("IS 2062",)
    assert understand("2062 testing labs West Bengal").state == "West Bengal"
    assert understand("I make 500 helmets a day").standard_refs == ()


def test_state_abbreviations_need_capitals():
    assert understand("gold jewellery in UP").state == "Uttar Pradesh"
    assert understand("how to set up a cement plant").state is None


def test_hindi_question_is_detected_and_routed():
    result = understand("क्या राजस्थान में सोने के गहनों पर हॉलमार्किंग अनिवार्य है?")
    assert (result.language, result.intent, result.state, result.metal) == ("hi", INTENT_HALLMARKING, "Rajasthan", "gold")
    assert result.product_text is None
    assert INTENT_PRODUCT not in result.intents


@pytest.mark.parametrize(
    "text, material, product",
    [
        ("I need the BIS standard for copper wire", "copper", "wire"),
        ("स्टील के लिए BIS standard बताओ", "steel", None),
        ("mujhe steel ke liye BIS standard batao", "steel", None),
        ("मुझे copper wire का BIS standard चाहिए", "copper", "wire"),
    ],
)
def test_multilingual_product_and_material_entities(text, material, product):
    result = understand(text, gazetteer=GAZETTEER)
    assert result.intent == INTENT_STANDARD
    assert result.material == material
    assert result.product == product
    assert result.in_scope is True


def test_material_only_query_requests_product_clarification():
    result = understand("I need a BIS standard for a copper product")
    assert result.material == "copper"
    assert result.product is None
    assert result.clarification


def test_non_bis_question_is_out_of_scope():
    result = understand("What is the capital of France?")
    assert result.intent == INTENT_GENERAL
    assert result.product_text is None
    assert result.in_scope is False


def test_recognition_number_routes_to_hallmarking():
    result = understand("status of cro/rahc/r-110002 please")
    assert result.recognition_nos == ("CRO/RAHC/R-110002",)
    assert result.intent == INTENT_HALLMARKING


def test_mistyped_is_number_is_never_read_as_a_shorter_standard():
    result = understand("What is IS 2O62?", gazetteer=GAZETTEER)
    assert result.standard_refs == ()
    assert result.invalid_refs == ("IS 2O62",)
    assert understand("What is IS2062?").standard_refs == ("IS 2062",)


def test_explicit_unknown_locations_are_reported():
    assert understand("Find IS 2062 labs in Timbuktu", gazetteer=GAZETTEER).unresolved_place == "Timbuktu"
    assert understand("Gotham district", gazetteer=GAZETTEER).unresolved_place == "Gotham"
    assert understand("labs for IS 2062 in Kolkata", gazetteer=GAZETTEER).unresolved_place is None
    assert understand("Which standard applies in India?", gazetteer=GAZETTEER).unresolved_place is None


def test_devanagari_places_resolve_through_aliases():
    jaipur = understand("जयपुर में हॉलमार्किंग अनिवार्य है क्या?", gazetteer=GAZETTEER)
    assert (jaipur.language, jaipur.intent, jaipur.district, jaipur.state, jaipur.product_text) == ("hi", INTENT_HALLMARKING, "Jaipur", "Rajasthan", None)
    kolkata = understand("कोलकाता में IS 2062 की जाँच", gazetteer=GAZETTEER)
    assert (kolkata.city, kolkata.state, kolkata.standard_refs) == ("Kolkata", "West Bengal", ("IS 2062",))


def test_hindi_and_hinglish_product_words():
    assert understand("स्टील के लिए कौन सा BIS मानक लागू है?").product_text == "steel"
    assert understand("मैं संरचनात्मक इस्पात बनाता हूँ। कौन सा BIS मानक लागू है?").product_text == "structural steel"
    assert understand("mujhe steel ke liye BIS standard batao").product_text == "steel"


@pytest.mark.parametrize(
    "text, intent, product",
    [
        ("How to apply for BIS licence for pressure cookers?", INTENT_PROCESS, "pressure cookers"),
        ("upcoming QCOs", INTENT_UPCOMING, None),
        ("ceiling fans", INTENT_PRODUCT, "ceiling fans"),
        ("hello", INTENT_GENERAL, None),
        ("what is it?", INTENT_GENERAL, None),
    ],
)
def test_primary_intent_and_product_text(text, intent, product):
    result = understand(text)
    assert (result.intent, result.product_text) == (intent, product)
