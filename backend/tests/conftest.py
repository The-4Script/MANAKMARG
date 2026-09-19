import pytest

from manakmarg.core import clock
from manakmarg.core.config import get_settings


@pytest.fixture(autouse=True)
def _unfrozen_clock():
    """Every test starts and ends with the real clock."""
    clock.freeze(None)
    yield
    clock.freeze(None)


@pytest.fixture(autouse=True)
def _no_external_ai(monkeypatch):
    """Tests never reach Groq: an explicitly empty key overrides any developer .env / .env.local, and caches, usage
    counters and the voice rate limiter start empty. Tests that need a key pass their own Settings and fake HTTP."""
    from manakmarg.api.routers import voice
    from manakmarg.reasoning import groq

    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.delenv("MANAKMARG_GROQ_API_KEY", raising=False)
    get_settings.cache_clear()
    groq.clear_cache()
    groq.USAGE.reset()
    voice.LIMITER.reset()
    yield
    get_settings.cache_clear()
