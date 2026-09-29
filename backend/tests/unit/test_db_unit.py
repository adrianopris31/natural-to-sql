"""Unit tests for app.core.db module."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.db import check_db_health, close_engine, get_engine


@pytest.mark.asyncio
async def test_check_db_health_failure() -> None:
    with patch("app.core.db.get_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = RuntimeError("DB connection failed")
        mock_get_engine.return_value = mock_engine

        healthy, version = await check_db_health()
        assert healthy is False
        assert version == "unknown"


@pytest.mark.asyncio
async def test_close_engine() -> None:
    _ = get_engine()
    await close_engine()
    await close_engine()
