"""Pytest fixtures for unit and integration tests."""

from collections.abc import AsyncIterator

import pytest

from app.core.db import close_engine
from app.core.schema import get_schema_cache
from app.store.database import close_app_db


@pytest.fixture(autouse=True)
async def cleanup_engine() -> AsyncIterator[None]:
    """Ensure engine is cleanly closed before event loop teardown."""
    yield
    await close_engine()
    await close_app_db()
    cache = get_schema_cache()
    cache._schema = None
    cache._lock = None
