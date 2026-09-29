"""Unit tests for app.core.executor module."""

import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.config import get_settings
from app.core.executor import _sanitize_cell, run
from app.core.validator import SafeSQL
from app.errors import ExecutionError


def test_sanitize_cell_types() -> None:
    # None
    assert _sanitize_cell(None) is None

    # Strings
    assert _sanitize_cell("hello") == "hello"
    assert len(_sanitize_cell("a" * 600)) == 500

    # Datetime, date, time
    now = datetime.datetime(2025, 1, 1, 12, 0, 0)
    assert _sanitize_cell(now) == "2025-01-01T12:00:00"
    today = datetime.date(2025, 1, 1)
    assert _sanitize_cell(today) == "2025-01-01"
    t = datetime.time(12, 0, 0)
    assert _sanitize_cell(t) == "12:00:00"

    # Decimal
    assert _sanitize_cell(Decimal("10.00")) == 10
    assert _sanitize_cell(Decimal("10.50")) == 10.5

    # Bytes
    assert _sanitize_cell(b"hello bytes") == "hello bytes"

    # UUID
    u = uuid4()
    assert _sanitize_cell(u) == str(u)

    # Primitives
    assert _sanitize_cell(42) == 42
    assert _sanitize_cell(3.14) == 3.14
    assert _sanitize_cell(True) is True

    # Fallback object
    class CustomObj:
        def __str__(self) -> str:
            return "custom_str"

    assert _sanitize_cell(CustomObj()) == "custom_str"


@pytest.mark.asyncio
async def test_run_rejects_non_safe_sql() -> None:
    settings = get_settings()
    engine = AsyncMock()
    with pytest.raises(TypeError, match="Executor only accepts SafeSQL instances"):
        await run("SELECT 1", engine, settings)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_run_timeout_error() -> None:
    settings = get_settings()
    engine = MagicMock()
    conn_mock = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__.return_value = conn_mock
    ctx.__aexit__.return_value = None
    engine.connect.return_value = ctx

    with patch("asyncio.wait_for", side_effect=TimeoutError("Execution timed out")):
        safe_sql = SafeSQL(sql="SELECT 1;", original_sql="SELECT 1;")
        with pytest.raises(ExecutionError, match="timed out"):
            await run(safe_sql, engine, settings)
