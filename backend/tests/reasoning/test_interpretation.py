"""Interpreting questions in any language or phrasing before retrieval: the Hindi/Hinglish lexicon, "IS" as a request
for the standard, catalogue-first answers, and the guarded language-model restatement. HTTP is faked; no network."""

import json
from datetime import date

import pytest

from manakmarg.core.config import Settings
from manakmarg.db.engine import get_engine, init_db
from manakmarg.db.fts import rebuild_fts
from manakmarg.ingest import sources
from manakmarg.normalize.aliases import apply_aliases
from manakmarg.reasoning import groq
from manakmarg.reasoning.assistant import answer
from manakmarg.reasoning.intents import INTENT_STANDARD, understand
from manakmarg.search.catalogue import TIER_EXACT, TIER_KIND_OF, TIER_MENTION, TIER_SUBJECT, search_product, short_subject, subject_tier
from tests.standards_seed import add_standard

TODAY = date(2026, 9, 19)
CATALOGUE = {
    "IS 13688:2020": "Packaged Pasteurized Milk — Specification (Second Revision)",
    "IS 7185:2022": "Milk Boiler - Specification",
    "IS 18851:2024": "Milk - Determination of nitrogen content - Block-digestion method",
    "IS 16326:2015": "Ghee - Specification",
    "IS 4743:2018": "Settling Tanks for Ghee — Specification (First Revision)",
    "IS 10484:2021": "Paneer - Specification (First Revision)",
    "IS 544:2014": "Groundnut oil - Specification",
    "IS 11375:2021": "Groundnut oil for cosmetic industry specification",
    "IS 1392:1999": "Glass milk bottles - Specification (Fourth Revision)",
}


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = get_engine(tmp_path_factory.mktemp("interpret") / "catalogue.sqlite3")
    init_db(eng)
    with eng.begin() as conn:
        sources.sync_registry(conn)
        for raw, title in CATALOGUE.items():
            add_standard(conn, raw, title)
        rebuild_fts(conn)
    yield eng
    eng.dispose()


def _ask(engine, query, settings=None):
    with engine.connect() as conn:
        return answer(conn, query, lang="auto", today=TODAY, settings=settings or Settings(_env_file=None, groq_api_key=""))


# --------------------------------------------------------------------------- lexicon


@pytest.mark.parametrize(
    "text, expected",
    [
        ("दूध का IS क्या है", "milk का IS क्या है"),
        ("dudh ka IS kya hai", "milk ka IS kya hai"),
        ("दही का मानक", "dahi का standard"),
        ("पानी की टंकी", "water storage tank"),
        # the genitive agrees with the noun that follows; every form is one phrase
        ("सरसों के तेल का मानक", "mustard oil का standard"),
        ("सरसों का तेल", "mustard oil"),
    ],
)
def test_lexicon_turns_hindi_product_words_into_record_terms(text, expected):
    assert apply_aliases(text).text == expected


@pytest.mark.parametrize("text", ["दूध का IS क्या है", "dudh ka IS kya hai", "What is the IS for milk", "milk ka is kya hai"])
def test_is_without_a_number_asks_for_the_standard(text):
    understanding = understand(text)
    assert INTENT_STANDARD in understanding.intents
    assert understanding.product_text == "milk"


def test_the_english_verb_is_is_not_a_standard_request():
    assert INTENT_STANDARD not in understand("Is hallmarking mandatory in Jaipur?").intents


# --------------------------------------------------------------------------- catalogue ranking


def test_subject_tiers_follow_english_word_order():
    assert subject_tier("ghee", "Ghee - Specification") == TIER_EXACT
    assert subject_tier("milk", "Packaged Pasteurized Milk — Specification") == TIER_KIND_OF
    assert subject_tier("milk", "Milk Boiler - Specification") == TIER_SUBJECT
    # the product named only as a purpose: the standard is about tins
    assert subject_tier("ghee", "Square Tins – 15 Kilograms or litre for Ghee, Vanaspati, Edible Oils") == TIER_MENTION
    assert subject_tier("milk", "Ghee - Specification") is None


def test_product_specification_ranks_above_equipment_and_test_methods(engine):
    with engine.connect() as conn:
        matches, phrase = search_product(conn, "milk")
    assert phrase == "milk"
    assert matches[0].std_key == "IS 13688:2020"
    assert [match.std_key for match in matches].index("IS 18851:2024") > [match.std_key for match in matches].index("IS 7185:2022")


def test_general_standard_ranks_above_a_narrower_use(engine):
    with engine.connect() as conn:
        matches, _ = search_product(conn, "groundnut oil")
    assert [match.std_key for match in matches][:2] == ["IS 544:2014", "IS 11375:2021"]


def test_long_product_phrases_are_relaxed_to_their_head_noun_but_never_to_one_generic_word(engine):
    with engine.connect() as conn:
        matches, phrase = search_product(conn, "children milk bottles")
        assert phrase == "milk bottles" and matches[0].std_key == "IS 1392:1999"
        assert search_product(conn, "solar panel") == ([], None)


def test_short_subject_names_the_part_about_the_product():
    assert short_subject("Pulverized fuel ash - Lime bricks - Specification", "bricks") == "Lime bricks"
    assert short_subject("Specification for acid resistant bricks", "bricks") == "acid resistant bricks"


# --------------------------------------------------------------------------- answers without a model


@pytest.mark.parametrize("query", ["दूध का IS क्या है", "दूध का आईएस क्या है", "dudh ka IS kya hai", "What is the IS for milk"])
def test_milk_standard_is_found_in_any_script_without_a_model(engine, query):
    response = _ask(engine, query)
    assert response.route.category == "product_standard"
    assert "IS 13688:2020" in response.headline
    assert response.sections[0].key == "catalogue_standards"


def test_hindi_question_is_answered_in_hindi(engine):
    assert _ask(engine, "घी का IS क्या है").lang == "hi"
    assert "IS 16326:2015" in _ask(engine, "घी का IS क्या है").headline


def test_status_question_without_a_listing_says_certification_is_voluntary(engine):
    response = _ask(engine, "is BIS mandatory for ghee")
    assert "voluntary" in response.headline and "IS 16326:2015" in response.headline
    assert "absence_not_proof" in response.caveats


# --------------------------------------------------------------------------- guarded model restatement


class FakeGroq:
    def __init__(self, rewrite):
        self.calls = []
        self.rewrite = rewrite

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})

        class Response:
            status_code = 200

            def json(inner):
                return {"choices": [{"message": {"content": json.dumps(self.rewrite)}}]}

        return Response()


@pytest.fixture
def keyed():
    groq.clear_cache()
    groq.USAGE.reset()
    return Settings(_env_file=None, groq_api_key="gsk-test-not-real")


def test_unknown_language_is_restated_in_english_and_shown(engine, keyed, monkeypatch):
    fake = FakeGroq({"english": "What is the IS for paneer made from cow's milk?", "product": "paneer", "intent": "applicable_standard"})
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "गाईच्या दुधापासून बनवलेल्या पनीरचा IS काय आहे", keyed)
    assert len(fake.calls) == 1
    assert fake.calls[0]["json"]["messages"][1]["content"] == "गाईच्या दुधापासून बनवलेल्या पनीरचा IS काय आहे"
    assert response.understanding.interpreted_as == "What is the IS for paneer made from cow's milk?"
    assert response.understanding.interpretation_source == "model"
    assert response.understanding.product_text == "paneer"
    assert "IS 10484:2021" in response.headline
    assert response.lang == "hi"  # answered in the language of the question


def test_model_cannot_add_an_is_number(engine, keyed, monkeypatch):
    fake = FakeGroq({"english": "What is IS 9999 for ghee?", "product": "ghee", "intent": "applicable_standard"})
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "गाईच्या तुपाचा IS काय आहे", keyed)
    assert "9999" not in (response.understanding.interpreted_as or "")
    assert response.understanding.standard_refs == ()


def test_model_product_unknown_to_the_records_is_rejected(engine, keyed, monkeypatch):
    fake = FakeGroq({"english": "What is the standard for unobtainium?", "product": "unobtainium", "intent": "applicable_standard"})
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "अनोब्टेनियम का IS क्या है", keyed)
    assert len(fake.calls) == 1
    assert response.understanding.interpreted_as is None


@pytest.mark.parametrize("query", ["दूध का IS क्या है", "What is the IS for milk", "capital of France"])
def test_questions_the_records_already_understand_never_call_the_model(engine, keyed, monkeypatch, query):
    fake = FakeGroq({"english": "unused", "product": None, "intent": None})
    monkeypatch.setattr(groq.requests, "post", fake)
    _ask(engine, query, keyed)
    assert fake.calls == []


def test_without_a_key_unknown_words_get_the_local_answer(engine, monkeypatch):
    fake = FakeGroq({"english": "unused", "product": None, "intent": None})
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "गाईच्या दुधापासून बनवलेल्या पनीरचा IS काय आहे")
    assert fake.calls == [] and response.headline


# --------------------------------------------------------------------------- evaluation set


def test_evaluation_cases_are_well_formed():
    from manakmarg.eval import load_cases
    from manakmarg.reasoning import routing

    routes = {value for name, value in vars(routing).items() if name.startswith("ROUTE_")} | set(routing.SCHEME_ROUTES)
    cases = load_cases()
    assert len({case["query"] for case in cases}) == len(cases)
    for case in cases:
        assert case["route"] in routes, case
        assert all(number.isdigit() for number in case.get("any_is", [])), case


def test_evaluation_scores_route_and_named_standard(engine):
    from manakmarg.eval import run_eval, summary

    cases = [
        {"query": "दूध का IS क्या है", "route": "product_standard", "any_is": ["13688"]},
        {"query": "घी का IS क्या है", "route": "product_standard", "any_is": ["9999"]},
        {"query": "capital of France", "route": "product_standard"},
        {"query": "पनीरचा IS काय आहे", "route": "product_standard", "needs_model": True},
    ]
    with engine.connect() as conn:
        report = summary(run_eval(conn, Settings(_env_file=None, groq_api_key=""), with_model=False, today=TODAY, cases=cases))
    assert (report["passed"], report["scored"], report["skipped"]) == (1, 3, 1)
    problems = [failure["problem"] for failure in report["failures"]]
    assert "none of IS 9999 in the answer" in problems
    assert any(problem.startswith("route 'out_of_scope'") for problem in problems)


# --------------------------------------------------------------------------- misheard speech (sound-alike recovery)


@pytest.mark.parametrize(
    "heard, meant",
    [("geeka", "ghee"), ("गीका", "ghee"), ("डूद्स", "milk"), ("doodhka", "milk"), ("sabunka", "soap"), ("gee", "ghee")],
)
def test_sound_alike_recovers_typical_speech_to_text_slips(heard, meant):
    from manakmarg.normalize.phonetic import sound_alike

    assert sound_alike(heard) == meant


@pytest.mark.parametrize("word", ["hai", "kya", "standard", "price", "hello"])
def test_sound_alike_leaves_other_words_alone(word):
    from manakmarg.normalize.phonetic import sound_alike

    assert sound_alike(word) is None


@pytest.mark.parametrize("heard", ["GEEKA STANDARD क्या है?", "गीका स्टेंडर्ड क्या है?"])
def test_misheard_product_is_recovered_without_a_model(engine, heard):
    response = _ask(engine, heard)
    assert response.understanding.interpretation_source == "sound-alike"
    assert "IS 16326:2015" in response.headline
