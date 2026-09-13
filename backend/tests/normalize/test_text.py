import pytest

from manakmarg.normalize.text import clean_ws, norm_match, snippet, split_title


def test_clean_ws_collapses_whitespace_and_handles_none():
    assert clean_ws("  Textile floor coverings -  Aircraft Woven Carpet \n") == "Textile floor coverings - Aircraft Woven Carpet"
    assert clean_ws(None) == ""


def test_norm_match_lowercases_and_strips_punctuation():
    assert (
        norm_match("Stainless Steel Utensils — Specification ( Third Revision )")
        == "stainless steel utensils specification third revision"
    )
    assert norm_match("Plugs and socket-outlets of Rated Voltage") == "plugs and socket outlets of rated voltage"
    assert norm_match("snake_case") == "snake case"


def test_norm_match_keeps_devanagari_words_whole():
    assert norm_match("क्या राजस्थान में सोने के गहनों पर हॉलमार्किंग?") == "क्या राजस्थान में सोने के गहनों पर हॉलमार्किंग"


@pytest.mark.parametrize(
    "title, clean, revision, amendment",
    [
        (
            "Stainless Steel Utensils — Specification ( Third Revision )",
            "Stainless Steel Utensils — Specification (Third Revision)",
            "Third Revision",
            None,
        ),
        (
            "Household Refrigerating Appliances - Characteristics and Methods Of Test   Part 3 Energy Consumption "
            "and Volume  (First Revision) Amendment - 1",
            "Household Refrigerating Appliances - Characteristics and Methods Of Test Part 3 Energy Consumption "
            "and Volume (First Revision) Amendment - 1",
            "First Revision",
            "Amendment 1",
        ),
        ("Soil Reclamation - Terminology (first revision)", "Soil Reclamation - Terminology (first revision)", "First Revision", None),
        ("PILE DRIVING HAMMER  SPECIFICATION  First Revision of IS 6426", "PILE DRIVING HAMMER SPECIFICATION First Revision of IS 6426", "First Revision", None),
        ("Sulphur Dusting Powders - Specification second revision", "Sulphur Dusting Powders - Specification second revision", "Second Revision", None),
        ("Precast Concrete Paving Flags - Specification Amendment - 1", "Precast Concrete Paving Flags - Specification Amendment - 1", None, "Amendment 1"),
        ("Tea bags - Specification", "Tea bags - Specification", None, None),
    ],
)
def test_split_title(title, clean, revision, amendment):
    parts = split_title(title)
    assert parts.title_clean == clean
    assert parts.revision_label == revision
    assert parts.amendment_label == amendment


def test_snippet_respects_limit_and_word_boundaries():
    text = "word " * 200
    result = snippet(text, limit=50)
    assert len(result) <= 50
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")
    assert snippet("short text", limit=50) == "short text"
