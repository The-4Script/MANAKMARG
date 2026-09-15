"""Runtime settings from environment variables (prefix MANAKMARG_) and an optional project .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from manakmarg.core import paths

USER_AGENT = "ManakMarg-SIH2026-Prototype/0.1 (educational research; polite crawler)"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANAKMARG_",
        env_file=(paths.PROJECT_ROOT / ".env.local", paths.PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    db_path: Path = paths.PROCESSED_DIR / "manakmarg.sqlite3"
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "MANAKMARG_ANTHROPIC_API_KEY"),
    )
    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY", "MANAKMARG_GROQ_API_KEY"))
    llm_model: str | None = None
    groq_fast_model: str = "openai/gpt-oss-20b"
    groq_reasoning_model: str = "openai/gpt-oss-120b"
    groq_transcription_model: str = "whisper-large-v3-turbo"
    groq_transcription_fallback_model: str = "whisper-large-v3"
    groq_timeout_s: float = 8.0
    groq_transcription_timeout_s: float = 30.0
    voice_max_mb: int = 10
    voice_requests_per_minute: int = 12
    fetch_min_delay_s: float = 2.5
    user_agent: str = USER_AGENT
    offline: bool = False
    upload_ttl_minutes: int = 120
    upload_max_mb: int = 15
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("HOST", "MANAKMARG_HOST"))
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT", "MANAKMARG_PORT"))
    data_url: str | None = Field(default=None, validation_alias=AliasChoices("MANAKMARG_DATA_URL"))
    data_bundle: Path = paths.PROJECT_ROOT / "deploy" / "data" / "manakmarg-data.tar.gz"
    # Weekly BIS standards refresh (docs/DATA_REFRESH.md). "auto": scheduled by `start` (deployment), not by `serve`.
    refresh_schedule: str = Field(default="auto", pattern="^(auto|on|off)$")
    refresh_weekday: int = Field(default=5, ge=0, le=6)  # Monday = 0 … Saturday = 5
    refresh_time_ist: str = "02:30"
    refresh_catch_up: bool = True
    refresh_dir: Path = paths.DATA_DIR / "refresh"
    refresh_keep_versions: int = 6
    refresh_max_shrink: float = 0.05
    refresh_min_row_ratio: float = 0.9
    refresh_export_timeout_s: float = 900.0
    refresh_run_pytest: bool = False

    @field_validator("db_path", "data_bundle", "refresh_dir")
    @classmethod
    def _anchor_relative_db_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else paths.PROJECT_ROOT / value

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key) or (bool(self.anthropic_api_key) and bool(self.llm_model))

    @property
    def voice_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
