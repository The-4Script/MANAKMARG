"""Assistant endpoint language: "auto" answers in the question's language, falling back to the interface language."""

import re

import pytest
from fastapi.testclient import TestClient

from manakmarg.api import deps
from manakmarg.api.app import create_app
from manakmarg.core.config import Settings
from tests.fixture_db import build_fixture_db

DEVANAGARI = re.compile("[ऀ-ॿ]")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("assistant_language")
    engine = build_fixture_db(root / "fixture.sqlite3")
    settings = Settings(_env_file=None)
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=root / "indexes"), frontend_dir=root / "nofe")
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def _ask(client, **body):
    response = client.post("/api/assistant/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_hindi_question_in_an_english_interface_is_answered_in_hindi(client):
    result = _ask(client, query="जयपुर में हॉलमार्किंग अनिवार्य है क्या?", lang="auto", ui_lang="en")
    assert result["lang"] == "hi" and DEVANAGARI.search(result["headline"]) and "Jaipur" in result["headline"]


def test_english_question_in_a_hindi_interface_is_answered_in_english(client):
    result = _ask(client, query="Find laboratories for IS 2062 in Kolkata.", lang="auto", ui_lang="hi")
    assert result["lang"] == "en" and not DEVANAGARI.search(result["headline"]) and "Kolkata" in result["headline"]


def test_hinglish_follows_the_interface_language(client):
    assert _ask(client, query="Jaipur mein hallmarking mandatory hai kya?", lang="auto", ui_lang="hi")["lang"] == "hi"
    assert _ask(client, query="Jaipur mein hallmarking mandatory hai kya?", lang="auto", ui_lang="en")["lang"] == "en"


def test_explicit_language_and_old_clients_are_unchanged(client):
    assert _ask(client, query="Is hallmarking mandatory in Jaipur?", lang="hi")["lang"] == "hi"  # e.g. voice set to Hindi
    assert _ask(client, query="जयपुर में हॉलमार्किंग")["lang"] == "en"  # no lang field: previous default
    assert client.post("/api/assistant/query", json={"query": "IS 2062", "lang": "fr"}).status_code == 422
    assert client.post("/api/assistant/query", json={"query": "IS 2062", "lang": "auto", "ui_lang": "auto"}).status_code == 422
