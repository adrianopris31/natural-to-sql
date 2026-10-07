"""Unit tests for multi-engine database management, discovery, and multi-schema cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.core.db import (
    close_engine,
    get_default_database_name,
    get_engine,
    is_valid_database_identifier,
    list_available_databases,
)
from app.core.schema import ColumnModel, SchemaCache, SchemaModel, TableModel


@pytest.fixture(autouse=True)
async def cleanup_test_engines() -> None:
    """Ensure engines are closed before and after each test."""
    await close_engine()
    yield
    await close_engine()


def test_get_default_database_name() -> None:
    name = get_default_database_name()
    assert name == "ecommerce"


def test_is_valid_database_identifier() -> None:
    assert is_valid_database_identifier("ecommerce") is True
    assert is_valid_database_identifier("analytics_2026") is True
    assert is_valid_database_identifier("data-warehouse") is True
    assert is_valid_database_identifier("my_db_1") is True

    # Invalid cases
    assert is_valid_database_identifier("") is False
    assert is_valid_database_identifier("invalid;drop") is False
    assert is_valid_database_identifier("db with space") is False
    assert is_valid_database_identifier("test`db") is False
    assert is_valid_database_identifier("a" * 65) is False


def test_get_engine_default() -> None:
    eng_none = get_engine(None)
    eng_empty = get_engine("")
    eng_explicit = get_engine("ecommerce")

    assert eng_none is eng_empty
    assert eng_none is eng_explicit
    assert eng_none.url.database == "ecommerce"


def test_get_engine_configured_alias() -> None:
    custom_settings = Settings(
        TARGET_DATABASES='{"analytics": "mysql+asyncmy://nl2sql_ro:secret@127.0.0.1:3307/analytics_prod"}'
    )
    with patch("app.core.db.get_settings", return_value=custom_settings):
        eng = get_engine("analytics")
        assert eng.url.database == "analytics_prod"
        # Engine is cached
        eng2 = get_engine("analytics")
        assert eng is eng2


def test_get_engine_cloned_identifier() -> None:
    eng = get_engine("custom_db")
    assert eng.url.database == "custom_db"
    assert "3307" in str(eng.url)

    # Engine is cached
    eng2 = get_engine("custom_db")
    assert eng is eng2


def test_get_engine_invalid_name_raises() -> None:
    with pytest.raises(ValueError, match="Invalid database identifier"):
        get_engine("invalid; injection")


@pytest.mark.asyncio
async def test_close_engine_disposes_all() -> None:
    import app.core.db as db_module

    mock_disp1 = AsyncMock()
    mock_disp2 = AsyncMock()
    eng1 = MagicMock(dispose=mock_disp1)
    eng2 = MagicMock(dispose=mock_disp2)

    db_module._engines["db1"] = eng1
    db_module._engines["db2"] = eng2
    db_module._engine = eng1

    await close_engine()

    assert mock_disp1.await_count == 1
    assert mock_disp2.await_count == 1
    assert len(db_module._engines) == 0
    assert db_module._engine is None


@pytest.mark.asyncio
async def test_list_available_databases_filtering() -> None:
    mock_engine = MagicMock()
    mock_conn = AsyncMock()

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("information_schema",),
        ("mysql",),
        ("performance_schema",),
        ("sys",),
        ("ecommerce",),
        ("analytics",),
        ("reporting",),
    ]
    mock_conn.execute.return_value = mock_result
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    custom_settings = Settings(
        TARGET_DATABASES='{"warehouse": "mysql+asyncmy://user:pass@127.0.0.1:3307/wh"}'
    )

    with (
        patch("app.core.db.get_engine", return_value=mock_engine),
        patch("app.core.db.get_settings", return_value=custom_settings),
    ):
        dbs = await list_available_databases()

        db_names = [d["name"] for d in dbs]
        assert "information_schema" not in db_names
        assert "mysql" not in db_names
        assert "performance_schema" not in db_names
        assert "sys" not in db_names

        assert "ecommerce" in db_names
        assert "analytics" in db_names
        assert "reporting" in db_names
        assert "warehouse" in db_names

        # Default DB is marked
        default_items = [d for d in dbs if d["is_default"]]
        assert len(default_items) == 1
        assert default_items[0]["name"] == "ecommerce"


@pytest.mark.asyncio
async def test_list_available_databases_fallback_on_error() -> None:
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = RuntimeError("Access denied for SHOW DATABASES")

    with patch("app.core.db.get_engine", return_value=mock_engine):
        dbs = await list_available_databases()
        assert len(dbs) >= 1
        assert dbs[0]["id"] == "ecommerce"
        assert dbs[0]["is_default"] is True


@pytest.mark.asyncio
async def test_schema_cache_multi_database() -> None:
    cache = SchemaCache()

    schema_ecommerce = SchemaModel(
        tables=[TableModel(name="users", columns=[ColumnModel(name="id", type="int")])],
        database="ecommerce",
    )
    schema_analytics = SchemaModel(
        tables=[TableModel(name="events", columns=[ColumnModel(name="event_id", type="int")])],
        database="analytics",
    )

    with patch("app.core.schema.introspect_schema") as mock_introspect:
        mock_introspect.side_effect = lambda db_name=None, **_kwargs: (
            schema_analytics if db_name == "analytics" else schema_ecommerce
        )

        # 1. Fetch ecommerce schema
        res_ecom = await cache.get_schema("ecommerce")
        assert res_ecom.database == "ecommerce"
        assert "users" in res_ecom.table_names

        # 2. Fetch analytics schema
        res_analytics = await cache.get_schema("analytics")
        assert res_analytics.database == "analytics"
        assert "events" in res_analytics.table_names

        # Verify caching (introspect called once per database)
        assert mock_introspect.call_count == 2
        await cache.get_schema("ecommerce")
        await cache.get_schema("analytics")
        assert mock_introspect.call_count == 2

        # 3. Test force refresh
        await cache.get_schema("ecommerce", force_refresh=True)
        assert mock_introspect.call_count == 3

        # 4. Test clear
        cache.clear()
        assert len(cache._schemas) == 0
