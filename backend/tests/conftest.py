import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import get_settings
from app.core.db import close_engine
from app.core.schema import get_schema_cache
from app.store.database import close_app_db

# Ensure integration tests run against dev container test DB unless explicitly set
if "TEST_TARGET_DB_URL" in os.environ:
    os.environ["TARGET_DB_URL"] = os.environ["TEST_TARGET_DB_URL"]
elif not os.environ.get("USE_ENV_TARGET_DB"):
    os.environ["TARGET_DB_URL"] = (
        "mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce"
    )

# Never append test runs to the real SQL log file
os.environ["SQL_LOG_PATH"] = str(Path(tempfile.mkdtemp(prefix="nl2sql-test-")) / "sql_log.jsonl")

get_settings.cache_clear()


@pytest.fixture(autouse=True)
async def cleanup_engine() -> AsyncIterator[None]:
    """Ensure engine is cleanly closed before event loop teardown."""
    yield
    await close_engine()
    await close_app_db()
    cache = get_schema_cache()
    cache._schema = None
    cache._lock = None
