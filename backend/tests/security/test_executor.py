"""Unit and integration tests for executor.py."""

from decimal import Decimal

import pytest

from app.config import Settings
from app.core.db import get_engine
from app.core.executor import _sanitize_cell, run
from app.core.schema import introspect_schema
from app.core.validator import validate
from app.errors import ExecutionError


def test_sanitize_cell() -> None:
    assert _sanitize_cell(None) is None
    assert _sanitize_cell("a" * 600) == "a" * 500
    assert _sanitize_cell(Decimal("123.45")) == 123.45
    assert _sanitize_cell(Decimal("100.00")) == 100
    assert _sanitize_cell(b"hello world") == "hello world"


@pytest.mark.asyncio
async def test_executor_rejects_non_safesql() -> None:
    engine = get_engine()
    settings = Settings()
    with pytest.raises(TypeError, match="Executor only accepts SafeSQL"):
        await run("SELECT 1", engine=engine, settings=settings)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_executor_runs_valid_query() -> None:
    engine = get_engine()
    settings = Settings(MAX_ROWS=50)
    schema = await introspect_schema()

    safe_sql = validate(
        "SELECT id, name, price FROM products ORDER BY id ASC LIMIT 5",
        schema=schema,
        settings=settings,
    )
    result = await run(safe_sql, engine=engine, settings=settings)

    assert result.columns == ["id", "name", "price"]
    assert result.row_count == 5
    assert result.truncated is False
    assert result.elapsed_ms > 0
    assert isinstance(result.rows[0][2], (int, float))


@pytest.mark.asyncio
async def test_executor_truncation() -> None:
    engine = get_engine()
    settings = Settings(MAX_ROWS=5)
    schema = await introspect_schema()

    safe_sql = validate(
        "SELECT id, name FROM users",
        schema=schema,
        settings=settings,
    )
    result = await run(safe_sql, engine=engine, settings=settings)

    assert result.row_count == 5
    assert result.truncated is True


@pytest.mark.asyncio
async def test_executor_maps_errors() -> None:
    engine = get_engine()
    settings = Settings()
    schema = await introspect_schema()

    # Valid syntax according to validator, but non-existent column at execution time
    # We create a safe sql directly via validator on a modified schema or query
    safe_sql = validate(
        "SELECT id FROM users",
        schema=schema,
        settings=settings,
    )
    # Monkeypatch sql text to force DB execution error
    object.__setattr__(safe_sql, "sql", "SELECT non_existent_column_12345 FROM users")

    with pytest.raises(ExecutionError, match="Database query execution failed"):
        await run(safe_sql, engine=engine, settings=settings)
