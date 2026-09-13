"""Hindi/Hinglish aliases replace only known entities and domain words; the rest of the question is untouched."""

from manakmarg.normalize.aliases import DOMAIN_ALIASES, PLACE_ALIASES, apply_aliases


def test_product_words_are_normalised_longest_first():
    result = apply_aliases("क्या स्टेनलेस स्टील के बर्तनों के लिए BIS प्रमाणन अनिवार्य है?")
    assert "stainless steel" in result.text and "utensils" in result.text and "certification" in result.text
    assert "स्टील" not in result.text
    assert ("स्टेनलेस स्टील", "stainless steel") in result.replacements
    assert "क्या" in result.text and "अनिवार्य" in result.text  # not a translation


def test_both_hallmarking_spellings_and_places():
    assert apply_aliases("जयपुर में हॉलमार्किंग").text == "Jaipur में hallmarking"
    assert apply_aliases("जयपुर में हालमार्किंग").text == "Jaipur में hallmarking"
    assert apply_aliases("कोलकाता में IS 2062 की जाँच").text == "Kolkata में IS 2062 की testing"


def test_aliases_do_not_touch_parts_of_other_words():
    assert apply_aliases("स्टीलवर्क").text == "स्टीलवर्क"
    assert apply_aliases("What is IS 2062?").text == "What is IS 2062?"


def test_hinglish_testing_word():
    assert apply_aliases("IS 2062 ki janch kahan hogi").text == "IS 2062 ki testing kahan hogi"


def test_alias_targets_are_plain_english():
    for target in list(DOMAIN_ALIASES.values()) + list(PLACE_ALIASES.values()):
        assert target.isascii()
