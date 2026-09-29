"""Async database engine management and connectivity checks for the target DB."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Get or create singleton async engine for the target DB."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.TARGET_DB_URL,
            pool_size=5,
            pool_pre_ping=True,
        )
    return _engine


async def close_engine() -> None:
    """Dispose of the target DB engine connection pool."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def check_db_health() -> tuple[bool, str]:
    """Check connectivity to the target DB and return (is_healthy, version)."""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT @@version;"))
            version = str(result.scalar() or "unknown")
            return True, version
    except Exception as exc:
        logger.warning(
            "Target database health check failed",
            extra={"error": str(exc)},
        )
        return False, "unknown"
