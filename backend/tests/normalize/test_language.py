"""The response language follows the question: Devanagari → Hindi, English → English, Hinglish → selected UI language."""

import pytest

from manakmarg.normalize.language import detect_language


@pytest.mark.parametrize(
    "text",
    [
        "जयपुर में हॉलमार्किंग अनिवार्य है क्या?",
        "कोलकत्ता में IS 2062 के जाँच के लिए लैब बताइए",
        "मुझे copper wire का BIS standard बताइए",
        "स्टील के लिए BIS standard बताइए",
    ],
)
def test_devanagari_questions_are_answered_in_hindi(text):
    assert detect_language(text, "en") == "hi"
    assert detect_language(text, "hi") == "hi"


@pytest.mark.parametrize("text", ["Find laboratories for IS 2062 in Kolkata.", "What is IS 2062?", "capital of France"])
def test_english_questions_are_answered_in_english_even_with_a_hindi_interface(text):
    assert detect_language(text, "hi") == "en"


@pytest.mark.parametrize("text", ["Jaipur mein hallmarking mandatory hai kya?", "mujhe steel ke liye BIS standard batao", "IS 2062", "2062", "", None])
def test_hinglish_and_bare_identifiers_keep_the_selected_language(text):
    assert detect_language(text, "hi") == "hi"
    assert detect_language(text, "en") == "en"


def test_devanagari_digits_alone_are_not_a_language_signal():
    assert detect_language("IS २०६२", "en") == "en"
    assert detect_language("IS 2062", "unknown") == "en"
