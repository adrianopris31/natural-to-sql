"""Async database engine management, lifecycle, and connectivity checks."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings

logger = logging.getLogger(__name__)

_engines: dict[str, AsyncEngine] = {}
_engine: AsyncEngine | None = None

_DB_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SYSTEM_SCHEMAS = frozenset({"information_schema", "mysql", "performance_schema", "sys"})


def is_valid_database_identifier(name: str) -> bool:
    """Check if string is a safe MySQL database identifier."""
    return bool(_DB_NAME_REGEX.match(name))


def get_default_database_name() -> str:
    """Extract default database name from TARGET_DB_URL."""
    settings = get_settings()
    try:
        url = make_url(settings.TARGET_DB_URL)
        return url.database or "default"
    except Exception:
        return "default"


def get_engine(db_name: str | None = None) -> AsyncEngine:
    """Get or create singleton async engine for the specified target DB (or default DB)."""
    global _engine, _engines
    settings = get_settings()
    default_db = get_default_database_name()

    cleaned_db = db_name.strip() if db_name else None

    # Default engine resolution
    if cleaned_db is None or cleaned_db == default_db:
        if default_db not in _engines:
            engine = create_async_engine(
                settings.TARGET_DB_URL,
                pool_size=5,
                pool_pre_ping=True,
            )
            _engines[default_db] = engine
        _engine = _engines[default_db]
        return _engines[default_db]

    # Explicit alias resolution from TARGET_DATABASES
    custom_dbs = settings.target_databases_dict
    if cleaned_db in custom_dbs:
        if cleaned_db not in _engines:
            target_url = custom_dbs[cleaned_db]
            engine = create_async_engine(
                target_url,
                pool_size=5,
                pool_pre_ping=True,
            )
            _engines[cleaned_db] = engine
        return _engines[cleaned_db]

    # Valid identifier resolution by cloning default TARGET_DB_URL with new database name
    if is_valid_database_identifier(cleaned_db):
        if cleaned_db not in _engines:
            try:
                base_url = make_url(settings.TARGET_DB_URL)
                cloned_url = base_url.set(database=cleaned_db)
                engine = create_async_engine(
                    cloned_url,
                    pool_size=5,
                    pool_pre_ping=True,
                )
                _engines[cleaned_db] = engine
            except Exception as exc:
                raise ValueError(
                    f"Could not construct engine for database '{cleaned_db}': {exc}"
                ) from exc
        return _engines[cleaned_db]

    raise ValueError(f"Invalid database identifier: '{cleaned_db}'")


async def close_engine() -> None:
    """Dispose of all target DB engine connection pools."""
    global _engine, _engines
    for engine in list(_engines.values()):
        await engine.dispose()
    _engines.clear()
    _engine = None


async def check_db_health(db_name: str | None = None) -> tuple[bool, str]:
    """Check connectivity to the target DB and return (is_healthy, version)."""
    try:
        engine = get_engine(db_name)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT @@version;"))
            version = str(result.scalar() or "unknown")
            return True, version
    except Exception as exc:
        logger.warning(
            "Target database health check failed for '%s'",
            db_name or "default",
            extra={"error": str(exc)},
        )
        return False, "unknown"


async def list_available_databases() -> list[dict[str, Any]]:
    """Discover available databases on MySQL server and merge with configured aliases."""
    settings = get_settings()
    default_db = get_default_database_name()
    databases: dict[str, dict[str, Any]] = {}

    # 1. Default database
    if default_db:
        databases[default_db] = {
            "id": default_db,
            "name": default_db,
            "is_default": True,
        }

    # 2. Configured aliases in TARGET_DATABASES
    for alias in settings.target_databases_dict:
        if alias not in databases:
            databases[alias] = {
                "id": alias,
                "name": alias,
                "is_default": (alias == default_db),
            }

    # 3. Discovery via SHOW DATABASES; on default engine
    try:
        engine = get_engine(default_db)
        async with engine.connect() as conn:
            result = await conn.execute(text("SHOW DATABASES;"))
            rows = result.fetchall()
            for row in rows:
                name = str(row[0])
                if name.lower() not in SYSTEM_SCHEMAS and name not in databases:
                    databases[name] = {
                        "id": name,
                        "name": name,
                        "is_default": (name == default_db),
                    }
    except Exception as exc:
        logger.warning(
            "SHOW DATABASES failed; returning configured databases: %s",
            exc,
        )

    # Sort with is_default=True first, then alphabetically
    return sorted(
        databases.values(),
        key=lambda d: (not d["is_default"], d["name"].lower()),
    )
