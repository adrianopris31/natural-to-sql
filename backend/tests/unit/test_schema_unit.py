"""Unit tests for app.core.schema module edge cases."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.schema import SchemaModel, TableModel, _fetch_sample_values, introspect_schema
from app.errors import SchemaError


def test_schema_model_get_table_miss() -> None:
    schema = SchemaModel(tables=[TableModel(name="users", columns=[])])
    assert schema.get_table("nonexistent") is None
    assert schema.table_names == ["users"]


@pytest.mark.asyncio
async def test_fetch_sample_values_exception() -> None:
    conn = AsyncMock()
    conn.execute.side_effect = RuntimeError("Sampling error")
    vals = await _fetch_sample_values(conn, "users", "status", "varchar(50)")
    assert vals == []


@pytest.mark.asyncio
async def test_introspect_schema_no_database() -> None:
    mock_engine = MagicMock()
    mock_engine.url.database = None

    with (
        patch("app.core.schema.get_engine", return_value=mock_engine),
        patch("app.core.schema.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock()
        with pytest.raises(SchemaError, match="Database name not configured"):
            await introspect_schema()


@pytest.mark.asyncio
async def test_introspect_schema_connection_failure() -> None:
    mock_engine = MagicMock()
    mock_engine.url.database = "ecommerce"
    mock_engine.connect.side_effect = RuntimeError("Connection timeout")

    with (
        patch("app.core.schema.get_engine", return_value=mock_engine),
        patch("app.core.schema.get_settings") as mock_settings,
    ):
        mock_settings.return_value = MagicMock()
        with pytest.raises(SchemaError, match="Database introspection failed"):
            await introspect_schema()
