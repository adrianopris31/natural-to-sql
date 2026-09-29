"""Unit tests for configuration loading and validation."""

from app.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert "ecommerce" in settings.TARGET_DB_URL
    assert settings.OLLAMA_MODEL == "qwen2.5-coder:7b"
    assert settings.MAX_ROWS == 500
    assert settings.ANSWER_MAX_ROWS == 50
    assert settings.QUERY_TIMEOUT_MS == 10000
    assert settings.MAX_REPAIR_ATTEMPTS == 2
    assert settings.HISTORY_TURNS == 4
    assert settings.SCHEMA_FULL_MAX_TABLES == 40
    assert settings.SCHEMA_SAMPLE_VALUES is True


def test_settings_list_parsing_from_string() -> None:
    settings = Settings(
        CORS_ORIGINS="http://localhost:3000, http://127.0.0.1:3000",
        DENY_TABLES="secret_table, internal_logs",
        ALLOWED_FUNCTIONS="COUNT, SUM, AVG",
    )
    assert settings.CORS_ORIGINS == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.DENY_TABLES == ["secret_table", "internal_logs"]
    assert settings.ALLOWED_FUNCTIONS == ["COUNT", "SUM", "AVG"]


def test_settings_list_parsing_empty_or_none() -> None:
    settings = Settings(
        DENY_TABLES="",
        DENY_COLUMNS="   ",
        ALLOWED_FUNCTIONS=None,
    )
    assert settings.DENY_TABLES == []
    assert settings.DENY_COLUMNS == []
    assert settings.ALLOWED_FUNCTIONS == []


def test_settings_list_parsing_from_list() -> None:
    settings = Settings(
        DENY_TABLES=["orders", "payments "],
    )
    assert settings.DENY_TABLES == ["orders", "payments"]
