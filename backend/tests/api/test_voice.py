"""Voice transcription endpoint: configuration, validation, limits and failure mapping. Transcription is faked."""

import pytest
from fastapi.testclient import TestClient

from manakmarg.api import deps
from manakmarg.api.app import create_app
from manakmarg.api.routers import voice
from manakmarg.core.config import Settings
from manakmarg.db.engine import get_engine, init_db
from manakmarg.ingest import sources
from manakmarg.reasoning import groq

AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 4096  # WebM-sized payload; content is never inspected by the fake


def _client(tmp_path, **overrides):
    engine = get_engine(tmp_path / "voice.sqlite3")
    init_db(engine)
    with engine.begin() as conn:
        sources.sync_registry(conn)
    settings = Settings(_env_file=None, db_path=tmp_path / "voice.sqlite3", **overrides)
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=tmp_path / "indexes"), frontend_dir=tmp_path / "nofe")
    return TestClient(app), engine


@pytest.fixture
def keyed(tmp_path, monkeypatch):
    calls = []

    def fake(data, filename, content_type, settings, *, language=None):
        calls.append({"bytes": len(data), "filename": filename, "content_type": content_type, "language": language})
        return "Is hallmarking mandatory in Jaipur?"

    monkeypatch.setattr(groq, "transcribe_audio", fake)
    client, engine = _client(tmp_path, groq_api_key="gsk-test-not-real", voice_max_mb=1, voice_requests_per_minute=5)
    with client:
        yield client, calls
    engine.dispose()


def _post(client, data=AUDIO, filename="question.webm", content_type="audio/webm", language="auto"):
    return client.post("/api/voice/transcribe", files={"file": (filename, data, content_type)}, data={"language": language})


def test_voice_is_unavailable_without_a_key(tmp_path):
    client, engine = _client(tmp_path, groq_api_key=None)
    with client:
        response = _post(client)
        meta = client.get("/api/meta").json()
    engine.dispose()
    assert response.status_code == 503 and "not configured" in response.json()["detail"]
    assert meta["voice_enabled"] is False


def test_successful_transcription_passes_the_language_hint(keyed):
    client, calls = keyed
    auto = _post(client)
    hindi = _post(client, language="hi")
    assert auto.status_code == 200 and auto.json() == {"text": "Is hallmarking mandatory in Jaipur?", "language": "auto"}
    assert hindi.status_code == 200
    assert [call["language"] for call in calls] == [None, "hi"]
    assert calls[0]["filename"] == "voice.webm" and calls[0]["content_type"] == "audio/webm"
    assert client.get("/api/meta").json()["voice_enabled"] is True


@pytest.mark.parametrize(
    "kwargs, status",
    [
        ({"language": "fr"}, 422),
        ({"filename": "notes.txt", "content_type": "text/plain"}, 415),
        ({"data": b""}, 400),
        ({"data": b"\x00" * 200}, 400),
        ({"data": b"\x00" * (1024 * 1024 + 10)}, 413),
    ],
)
def test_invalid_requests_are_rejected_before_transcription(keyed, kwargs, status):
    client, calls = keyed
    assert _post(client, **kwargs).status_code == status
    assert calls == []


def test_content_type_is_enough_when_the_filename_has_no_extension(keyed):
    client, calls = keyed
    assert _post(client, filename="blob", content_type="audio/ogg;codecs=opus").status_code == 200
    assert calls[0]["filename"] == "voice.ogg"


@pytest.mark.parametrize("kind, status", [("timeout", 504), ("rate_limited", 429), ("upstream", 502), ("bad_response", 502)])
def test_transcription_failures_map_to_clear_statuses(tmp_path, monkeypatch, kind, status):
    def failing(*args, **kwargs):
        raise groq.GroqError(kind, "boom")

    monkeypatch.setattr(groq, "transcribe_audio", failing)
    client, engine = _client(tmp_path, groq_api_key="gsk-test-not-real")
    with client:
        response = _post(client)
    engine.dispose()
    assert response.status_code == status
    assert "gsk-" not in response.text and "boom" not in response.text


def test_no_recognised_speech(tmp_path, monkeypatch):
    monkeypatch.setattr(groq, "transcribe_audio", lambda *args, **kwargs: "")
    client, engine = _client(tmp_path, groq_api_key="gsk-test-not-real")
    with client:
        response = _post(client)
    engine.dispose()
    assert response.status_code == 422 and "No speech" in response.json()["detail"]


def test_rate_limit_per_client(keyed):
    client, _ = keyed
    statuses = [_post(client).status_code for _ in range(6)]
    assert statuses[:5] == [200] * 5 and statuses[5] == 429


def test_rate_limiter_window_expires():
    limiter = voice._RateLimiter()
    assert limiter.allow("a", 1, now=0.0)
    assert not limiter.allow("a", 1, now=30.0)
    assert limiter.allow("a", 1, now=61.0)
    assert limiter.allow("b", 1, now=30.0)
