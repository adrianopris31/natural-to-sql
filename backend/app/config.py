"""Application configuration using pydantic-settings.

No os.getenv calls allowed outside this file per .agents/rules/backend.md.
"""

from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings conforming to PLAN.md §6."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    TARGET_DB_URL: str = "mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce"
    APP_DB_PATH: str = "backend/data/app.db"
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"
    OLLAMA_NUM_CTX: int = 8192
    MAX_ROWS: int = 500
    ANSWER_MAX_ROWS: int = 50
    QUERY_TIMEOUT_MS: int = 10000
    MAX_REPAIR_ATTEMPTS: int = 2
    HISTORY_TURNS: int = 4
    SCHEMA_FULL_MAX_TABLES: int = 40
    SCHEMA_SAMPLE_VALUES: bool = True
    ALLOWED_FUNCTIONS: list[str] = []
    DENY_TABLES: list[str] = []
    DENY_COLUMNS: list[str] = []
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    NEXT_PUBLIC_API_BASE: str = "/api"

    @field_validator(
        "CORS_ORIGINS",
        "ALLOWED_FUNCTIONS",
        "DENY_TABLES",
        "DENY_COLUMNS",
        mode="before",
    )
    @classmethod
    def parse_string_or_list(cls, value: Any) -> list[str]:
        """Parse comma-separated string or list into list of clean strings."""
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
