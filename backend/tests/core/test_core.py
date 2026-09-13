from datetime import date, datetime, timedelta, timezone

from manakmarg.core import clock, paths
from manakmarg.core.config import Settings

_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "MANAKMARG_ANTHROPIC_API_KEY",
    "MANAKMARG_LLM_MODEL",
    "GROQ_API_KEY",
    "MANAKMARG_GROQ_API_KEY",
    "MANAKMARG_DB_PATH",
    "MANAKMARG_FETCH_MIN_DELAY_S",
    "MANAKMARG_OFFLINE",
    "MANAKMARG_CORS_ORIGINS",
)


def _clean_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_project_root_contains_backend_package():
    assert (paths.PROJECT_ROOT / "backend" / "manakmarg").is_dir()


def test_data_directories_live_under_data_dir():
    assert paths.DATA_DIR == paths.PROJECT_ROOT / "data"
    for sub in (
        paths.RAW_WEB_DIR,
        paths.RAW_DOCS_DIR,
        paths.STAGING_DIR,
        paths.PROCESSED_DIR,
        paths.INDEX_DIR,
        paths.MANIFEST_DIR,
        paths.UPLOAD_DIR,
    ):
        assert paths.DATA_DIR in sub.parents


def test_ensure_dirs_creates_working_directories():
    paths.ensure_dirs()
    assert paths.RAW_WEB_DIR.is_dir()
    assert paths.MANIFEST_DIR.is_dir()


def test_settings_defaults(monkeypatch):
    _clean_env(monkeypatch)
    s = Settings(_env_file=None)
    assert s.fetch_min_delay_s == 2.5
    assert s.upload_ttl_minutes == 120
    assert s.upload_max_mb == 15
    assert s.offline is False
    assert s.llm_enabled is False
    assert s.db_path == paths.PROCESSED_DIR / "manakmarg.sqlite3"
    assert s.user_agent.startswith("ManakMarg-SIH2026-Prototype/")
    assert s.cors_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_settings_read_environment(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("MANAKMARG_FETCH_MIN_DELAY_S", "4")
    monkeypatch.setenv("MANAKMARG_OFFLINE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MANAKMARG_LLM_MODEL", "test-model")
    monkeypatch.setenv("MANAKMARG_DB_PATH", "data/processed/other.sqlite3")
    s = Settings(_env_file=None)
    assert s.fetch_min_delay_s == 4.0
    assert s.offline is True
    assert s.llm_enabled is True
    assert s.db_path == paths.PROJECT_ROOT / "data" / "processed" / "other.sqlite3"


def test_groq_settings_are_supported(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    s = Settings(_env_file=None)
    assert s.groq_api_key == "gsk-test"
    assert s.llm_enabled is True
    assert s.groq_reasoning_model == "openai/gpt-oss-120b"
    assert s.groq_fast_model == "openai/gpt-oss-20b"


def test_llm_needs_both_key_and_model(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert Settings(_env_file=None).llm_enabled is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("MANAKMARG_LLM_MODEL", "test-model")
    assert Settings(_env_file=None).llm_enabled is False


def test_frozen_clock_controls_today():
    clock.freeze(date(2026, 9, 13))
    assert clock.today() == date(2026, 9, 13)


def test_unfrozen_clock_uses_india_standard_time():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert clock.today() == datetime.now(ist).date()


def test_now_utc_is_timezone_aware():
    assert clock.now_utc().tzinfo is not None
