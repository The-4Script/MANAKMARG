"""Hindi answers for Hindi questions: official English passages are shown in Hindi only when the translation keeps
every fact; names stay as recorded; English answers and missing keys never call a model. HTTP is faked."""

import json
from datetime import date

import pytest

from manakmarg.core.config import Settings
from manakmarg.reasoning import groq
from manakmarg.reasoning.assistant import answer
from manakmarg.reasoning.localize import _facts, keeps_facts
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)
FEE = "The application is required to be submitted with an application fee of Rs. 1000. An inspection fee of Rs. 7,000 per man day is required."


@pytest.mark.parametrize(
    "translated, ok",
    [
        ("आवेदन Rs. 1000 के आवेदन शुल्क के साथ जमा करना होगा। Rs. 7,000 प्रति मानव-दिवस निरीक्षण शुल्क देना होगा।", True),
        ("आवेदन Rs. १००० के आवेदन शुल्क के साथ जमा करना होगा। Rs. ७,००० प्रति मानव-दिवस निरीक्षण शुल्क देना होगा।", True),  # Devanagari digits
        ("आवेदन शुल्क के साथ जमा करना होगा। Rs. 7,000 प्रति मानव-दिवस निरीक्षण शुल्क देना होगा।", False),  # lost Rs. 1000
        ("आवेदन Rs. 1000 के साथ। Rs. 7,500 प्रति मानव-दिवस।", False),  # changed amount
        (FEE, False),  # not Hindi
        (None, False),
    ],
)
def test_translation_is_used_only_when_every_fact_survives(translated, ok):
    assert keeps_facts(FEE, translated) is ok


def test_urls_and_identifiers_must_survive():
    original = "Apply on www.manakonline.in for IS 2062:2011 under S.O. 4494(E)."
    assert keeps_facts(original, "IS 2062:2011 के लिए www.manakonline.in पर S.O. 4494(E) के अंतर्गत आवेदन करें।")
    assert not keeps_facts(original, "IS 2062:2011 के लिए मानकऑनलाइन पर S.O. 4494(E) के अंतर्गत आवेदन करें।")


class FakeTranslator:
    """Answers every translation request by prefixing each text with Hindi, keeping its facts."""

    def __init__(self, drop_numbers=False):
        self.calls = []
        self.drop_numbers = drop_numbers

    def __call__(self, url, **kwargs):
        self.calls.append(kwargs["json"])
        texts = json.loads(kwargs["json"]["messages"][1]["content"])["texts"]
        # Hindi prose that carries each text's facts (numbers, identifiers, URLs), or drops them when asked to.
        hindi = ["हिंदी अनुवाद: यह आधिकारिक पाठ का अनुवाद है " + ("" if self.drop_numbers else " ".join(_facts(text))) for text in texts]

        class Response:
            status_code = 200

            def json(inner):
                return {"choices": [{"message": {"content": json.dumps({"hi": hindi}, ensure_ascii=False)}}]}

        return Response()


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("localize") / "fixture.sqlite3")
    yield eng
    eng.dispose()


@pytest.fixture
def keyed():
    groq.clear_cache()
    groq.USAGE.reset()
    return Settings(_env_file=None, groq_api_key="gsk-test-not-real")


def _ask(engine, query, settings, lang="auto"):
    with engine.connect() as conn:
        return answer(conn, query, lang=lang, today=TODAY, settings=settings)


def _process_rows(engine):
    import sqlalchemy as sa

    from manakmarg.db import schema

    table = schema.process_step
    with engine.connect() as conn:
        return conn.execute(sa.select(table).where(table.c.is_current.is_(True)).order_by(table.c.ordinal)).mappings().all()


def _texts(response):
    return [item.text for section in response.sections for item in section.items]


def test_hindi_process_answer_shows_steps_in_hindi_once_per_answer(engine, keyed, monkeypatch):
    fake = FakeTranslator()
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "बीआईएस लाइसेंस के लिए आवेदन कैसे करें", keyed)
    steps = next(section for section in response.sections if section.key == "process")
    assert all("हिंदी अनुवाद:" in item.text for item in steps.items)
    assert len(fake.calls) == 1  # one batched request for the whole answer
    assert "machine_translation" in response.caveats
    # the evidence keeps the official English text
    assert all("हिंदी" not in (item.snippet or "") for item in response.evidence.items)
    # a repeated answer is served from the cache
    _ask(engine, "बीआईएस लाइसेंस के लिए आवेदन कैसे करें", keyed)
    assert len(fake.calls) == 1


def test_translation_that_drops_a_number_is_not_shown(engine, keyed, monkeypatch):
    fake = FakeTranslator(drop_numbers=True)
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "बीआईएस लाइसेंस के लिए आवेदन कैसे करें", keyed)
    steps = next(section for section in response.sections if section.key == "process")
    step_texts = [row["text"] for row in _process_rows(engine)]
    for item, original in zip(steps.items, step_texts):
        # a step with a number keeps its official English; a step without one may be shown in Hindi
        assert ("हिंदी अनुवाद:" in item.text) == (not _facts(original))


def test_english_answers_never_call_the_translator(engine, keyed, monkeypatch):
    fake = FakeTranslator()
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "How do I apply for a BIS licence?", keyed)
    assert fake.calls == [] and "machine_translation" not in response.caveats


def test_without_a_key_hindi_answers_keep_the_official_english(engine, monkeypatch):
    fake = FakeTranslator()
    monkeypatch.setattr(groq.requests, "post", fake)
    response = _ask(engine, "बीआईएस लाइसेंस के लिए आवेदन कैसे करें", Settings(_env_file=None, groq_api_key=""))
    assert fake.calls == []
    assert "machine_translation" not in response.caveats
    assert not any("\ue000" in text for text in _texts(response))  # no placeholder ever leaks
