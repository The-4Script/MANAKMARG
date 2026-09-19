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


def test_speech_to_text_word_splits_are_normalised():
    # Whisper transcribed a spoken Hinglish question as "… हॉल मार्किंग …" (September 2026 live check).
    assert apply_aliases("जयपुर में हॉल मार्किंग अनिवार्य है").text == "Jaipur में hallmarking अनिवार्य है"
    assert apply_aliases("हाल मार्क वाले गहने").text == "hallmark वाले गहने"


def test_aliases_do_not_touch_parts_of_other_words():
    assert apply_aliases("स्टीलवर्क").text == "स्टीलवर्क"
    assert apply_aliases("What is IS 2062?").text == "What is IS 2062?"


def test_hinglish_testing_word():
    assert apply_aliases("IS 2062 ki janch kahan hogi").text == "IS 2062 ki testing kahan hogi"


def test_place_spelling_variants_map_to_the_same_record_name():
    for variant in ("कोलकाता", "कोलकत्ता", "कोलकता", "कलकत्ता"):
        assert apply_aliases(f"{variant} में लैब").text == "Kolkata में लैब"
    for variant in ("मुंबई", "मुम्बई", "बंबई", "बम्बई"):
        assert apply_aliases(f"{variant} में जांच").text == "Mumbai में testing"


def test_speech_to_text_transliterations_and_digits():
    # With the Hindi language hint, Whisper writes English words and digits in Devanagari.
    assert apply_aliases("कॉपर वायर का बीआईएस स्टैंडर्ड बताइए").text == "copper wire का BIS standard बताइए"
    assert apply_aliases("आईएस २०६२ की जाज कोलकत्ता में").text == "IS 2062 की testing Kolkata में"
    assert apply_aliases("तांबे का तार").text == "copper का wire"
    assert apply_aliases("लाइसन्स कैसे लें").text == "licence कैसे लें"


def test_live_whisper_transcript_variants():
    # Transcribed with the Hindi hint during the September 2026 voice check: "लैब" → "लाब", "IS 2062" → "IS-2062".
    assert apply_aliases("कोलकता में IS-2062 की जांच के लिए लाब").text == "Kolkata में IS 2062 की testing के लिए lab"
    assert apply_aliases("आईएस-२०६२ की लैब").text == "IS 2062 की लैब"
    assert apply_aliases("Labs for IS:2062 in Kolkata").text == "Labs for IS 2062 in Kolkata"
    assert apply_aliases("IS 2062:2011 and IS 1786").text == "IS 2062:2011 and IS 1786"  # year suffix untouched
    assert apply_aliases("this is-2 things").text == "this is-2 things"  # lower-case "is" is not the prefix


def test_chandrabindu_nukta_and_invisible_joiner_variants():
    assert apply_aliases("गुडगाँव में").text == "Gurugram में"  # listed as गुड़गांव
    assert apply_aliases("कोलका‍ता में").text == "Kolkata में"
    assert apply_aliases("भारतीय मानक ब्यूरो का मानक").text == "BIS का standard"


def test_unknown_words_are_not_guessed():
    assert apply_aliases("कोलकाटा में लैब").text == "कोलकाटा में लैब"
    assert apply_aliases("टिम्बकटू में").text == "टिम्बकटू में"


def test_alias_targets_are_plain_english():
    for target in list(DOMAIN_ALIASES.values()) + list(PLACE_ALIASES.values()):
        assert target.isascii()


def test_misheard_led_lighting_is_corrected_but_lead_metal_is_not():
    assert apply_aliases("Do I need ISI mark for lead bulbs?").text == "Do I need ISI mark for led bulbs ?"
    assert apply_aliases("standard for lead ingots").text == "standard for lead ingots"
