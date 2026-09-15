"""Local-first AI policy: deterministic questions never call the model, ambiguous ones call it at most once, payloads
stay small, and every failure falls back to the deterministic answer. HTTP is faked; no network is used."""

import json
from datetime import date

import pytest
import requests

from manakmarg.core.config import Settings
from manakmarg.reasoning import groq
from manakmarg.reasoning.assistant import answer
from tests.fixture_db import build_fixture_db

TODAY = date(2026, 9, 13)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeGroq:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        hints = {"intent": "applicable_standard", "material": "copper", "product": "wire", "application": None, "confidence": 0.8}
        return FakeResponse(200, {"choices": [{"message": {"content": json.dumps(hints)}}]})


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    eng = build_fixture_db(tmp_path_factory.mktemp("groq") / "fixture.sqlite3")
    yield eng
    eng.dispose()


@pytest.fixture
def keyed():
    return Settings(_env_file=None, groq_api_key="gsk-test-not-real")


@pytest.fixture
def fake(monkeypatch):
    fake = FakeGroq()
    monkeypatch.setattr(groq.requests, "post", fake)
    return fake


def _ask(engine, query, settings, lang="en"):
    with engine.connect() as conn:
        return answer(conn, query, lang=lang, today=TODAY, settings=settings)


@pytest.mark.parametrize(
    "query",
    [
        "What is IS 2062?",
        "Is hallmarking mandatory in Jaipur?",
        "Labs for IS 2062 in Kolkata",
        "What is Scheme I?",
        "How do I obtain a BIS licence?",
        "Is BIS certification mandatory for stainless steel cookware?",
        "What are upcoming QCOs?",
        "What is IS 2O62?",
        "capital of France",
        "जयपुर में हॉलमार्किंग अनिवार्य है क्या?",
    ],
)
def test_deterministic_and_out_of_scope_questions_never_call_the_model(engine, keyed, fake, query):
    response = _ask(engine, query, keyed)
    assert fake.calls == []
    assert response.headline


def test_unroutable_in_scope_question_calls_once_then_uses_the_cache(engine, keyed, fake):
    query = "Which tests are required?"
    first = _ask(engine, query, keyed)
    second = _ask(engine, query, keyed)
    assert len(fake.calls) == 1
    usage = groq.usage_snapshot()
    assert usage["understanding_calls"] == 1 and usage["understanding_cache_hits"] == 1
    payload = fake.calls[0]["json"]
    assert payload["messages"][1]["content"] == query
    assert len(json.dumps(payload)) < 2000  # only the query and a fixed instruction, never records
    assert fake.calls[0]["timeout"] == keyed.groq_timeout_s
    assert first.headline and second.headline


def test_no_key_means_no_call(engine, fake):
    response = _ask(engine, "Which tests are required?", Settings(_env_file=None, groq_api_key=None))
    assert fake.calls == [] and response.headline


def test_model_failures_fall_back_to_the_local_answer(engine, keyed, monkeypatch):
    failing = FakeGroq([FakeResponse(500), requests.Timeout()])
    monkeypatch.setattr(groq.requests, "post", failing)
    response = _ask(engine, "Which tests are required?", keyed)
    assert len(failing.calls) == 2  # larger model, then the faster fallback
    assert groq.usage_snapshot()["understanding_failures"] == 2
    assert response.route.category in ("general", "out_of_scope") and response.headline


def test_hints_are_allow_listed_and_cannot_invent_identifiers(engine, keyed, monkeypatch):
    invented = {"intent": "made_up", "material": "unobtainium", "product": "IS 99999", "confidence": 5}
    monkeypatch.setattr(groq.requests, "post", FakeGroq([FakeResponse(200, {"choices": [{"message": {"content": json.dumps(invented)}}]})]))
    response = _ask(engine, "Which tests are required?", keyed)
    assert response.understanding.standard_refs == ()
    assert response.understanding.material is None and response.understanding.product is None


def test_transcription_success_timeout_and_rate_limit(keyed, monkeypatch):
    ok = FakeGroq([FakeResponse(200, {"text": "  IS 2062 क्या है?  "})])
    monkeypatch.setattr(groq.requests, "post", ok)
    assert groq.transcribe_audio(b"x" * 2048, "voice.webm", "audio/webm", keyed, language="hi") == "IS 2062 क्या है?"
    assert ok.calls[0]["data"]["language"] == "hi" and ok.calls[0]["timeout"] == keyed.groq_transcription_timeout_s

    monkeypatch.setattr(groq.requests, "post", FakeGroq([requests.Timeout(), requests.Timeout()]))
    with pytest.raises(groq.GroqError) as timeout:
        groq.transcribe_audio(b"x" * 2048, "voice.webm", "audio/webm", keyed)
    assert timeout.value.kind == "timeout"

    monkeypatch.setattr(groq.requests, "post", FakeGroq([FakeResponse(429), FakeResponse(429)]))
    with pytest.raises(groq.GroqError) as limited:
        groq.transcribe_audio(b"x" * 2048, "voice.webm", "audio/webm", keyed)
    assert limited.value.kind == "rate_limited"


def test_transcription_without_key_is_unavailable():
    with pytest.raises(groq.GroqUnavailable):
        groq.transcribe_audio(b"x" * 2048, "voice.webm", "audio/webm", Settings(_env_file=None, groq_api_key=None))


def test_errors_never_carry_the_key(keyed, monkeypatch):
    monkeypatch.setattr(groq.requests, "post", FakeGroq([FakeResponse(401), FakeResponse(401)]))
    with pytest.raises(groq.GroqError) as failure:
        groq.transcribe_audio(b"x" * 2048, "voice.webm", "audio/webm", keyed)
    assert keyed.groq_api_key not in str(failure.value)
