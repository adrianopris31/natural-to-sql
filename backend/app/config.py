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
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    TARGET_DB_URL: str = "mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce"
    TARGET_DATABASES: str = "{}"
    APP_DB_PATH: str = "backend/data/app.db"
    # JSONL mirror of the audit log: every generated/edited/executed SQL (git-ignored dir)
    SQL_LOG_PATH: str = "backend/data/sql_log.jsonl"
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"
    OLLAMA_NUM_CTX: int = 8192
    MAX_ROWS: int = 500
    ANSWER_MAX_ROWS: int = 50
    QUERY_TIMEOUT_MS: int = 10000
    MAX_REPAIR_ATTEMPTS: int = 2
    MAX_QUERIES: int = 3
    # EXPLAIN gate: queries above these estimates are blocked (cannot be approved)
    EXPLAIN_MAX_COST: float = 5_000_000.0
    EXPLAIN_MAX_ROWS: int = 10_000_000
    # EXPLAIN warnings: full scans / filesorts over this many estimated rows are flagged
    EXPLAIN_WARN_ROWS: int = 100_000
    HISTORY_TURNS: int = 4
    SCHEMA_FULL_MAX_TABLES: int = 40
    SCHEMA_SAMPLE_VALUES: bool = True
    ALLOWED_FUNCTIONS: list[str] | str = []
    DENY_TABLES: list[str] | str = []
    DENY_COLUMNS: list[str] | str = []
    CORS_ORIGINS: list[str] | str = ["http://localhost:3000"]
    NEXT_PUBLIC_API_BASE: str = "/api"
    KNOWLEDGE_BOT_URL: str = "http://127.0.0.1:8100"
    KNOWLEDGE_BOT_API_KEY: str = ""
    KNOWLEDGE_BOT_ADMIN_KEY: str = ""
    KNOWLEDGE_BOT_TIMEOUT_SEC: float = 90.0
    KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC: float = 900.0
    ENABLE_SETTINGS_UI: bool = False

    @field_validator("TARGET_DB_URL", mode="before")
    @classmethod
    def sanitize_target_db_url(cls, value: Any) -> str:
        """Sanitize database URL by URL-encoding special characters in the password."""
        import re
        import urllib.parse

        if isinstance(value, str):
            value = value.strip()
            # Match scheme://user:password@rest where password might contain @
            match = re.match(r"^(.*?://)(.*?):(.*)@([^@]+)$", value)
            if match:
                prefix, user, password, rest = match.groups()
                if "@" in password and "%40" not in password:
                    encoded_password = urllib.parse.quote(password)
                    return f"{prefix}{user}:{encoded_password}@{rest}"
        return str(value)

    @field_validator("TARGET_DATABASES", mode="before")
    @classmethod
    def serialize_target_databases(cls, value: Any) -> str:
        """Ensure TARGET_DATABASES is stored as a JSON string."""
        import json

        if isinstance(value, dict):
            return json.dumps(value)
        if isinstance(value, str):
            return value.strip() or "{}"
        return "{}"

    @property
    def target_databases_dict(self) -> dict[str, str]:
        """Parse TARGET_DATABASES JSON string into a dict of alias -> URL."""
        import json

        if not self.TARGET_DATABASES or not self.TARGET_DATABASES.strip():
            return {}
        try:
            parsed = json.loads(self.TARGET_DATABASES)
            if isinstance(parsed, dict):
                return {
                    str(k).strip(): self.sanitize_target_db_url(str(v).strip())
                    for k, v in parsed.items()
                    if str(k).strip() and str(v).strip()
                }
        except Exception:
            pass
        return {}

    @field_validator("APP_DB_PATH", "SQL_LOG_PATH", mode="after")
    @classmethod
    def resolve_app_db_path(cls, value: str) -> str:
        """Resolve APP_DB_PATH relative to project root or backend directory."""
        from pathlib import Path

        p = Path(value)
        if not p.is_absolute():
            backend_dir = Path(__file__).resolve().parent.parent
            if value.startswith("backend/") or value.startswith("backend\\"):
                return (backend_dir.parent / value).resolve().as_posix()
            return (backend_dir / value).resolve().as_posix()
        return p.resolve().as_posix()

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
