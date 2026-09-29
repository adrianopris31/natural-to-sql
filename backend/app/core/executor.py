"""SQL Executor with transaction isolation, execution timeout, and cell sanitization."""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from app.core.validator import SafeSQL
from app.errors import ExecutionError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ResultSet:
    """Execution results returned to callers."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float


def _sanitize_cell(val: Any) -> Any:
    """Sanitize database cell value to JSON-safe primitives (Layer L11)."""
    if val is None:
        return None
    if isinstance(val, str):
        return val[:500]
    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()
    if isinstance(val, Decimal):
        # Return float or int for JSON serialization
        if val % 1 == 0:
            return int(val)
        return float(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")[:500]
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, (int, float, bool)):
        return val
    return str(val)[:500]


async def run(
    safe_sql: SafeSQL,
    engine: AsyncEngine,
    settings: Settings,
) -> ResultSet:
    """Execute SafeSQL inside a read-only transaction with execution timeout."""
    if not isinstance(safe_sql, SafeSQL):
        raise TypeError(f"Executor only accepts SafeSQL instances, got {type(safe_sql).__name__}")

    timeout_sec = (settings.QUERY_TIMEOUT_MS / 1000.0) + 1.0
    start_time = time.perf_counter()

    try:
        async with engine.connect() as conn:
            # 1. Start read-only transaction (Layer L2)
            await conn.execute(text("START TRANSACTION READ ONLY;"))
            try:
                # 2. Set MySQL execution timeout in ms (Layer L3)
                await conn.execute(
                    text(f"SET SESSION max_execution_time = {settings.QUERY_TIMEOUT_MS};")
                )

                # 3. Execute query with client-side timeout guard
                async def _exec() -> tuple[list[str], list[Any]]:
                    result = await conn.execute(text(safe_sql.sql))
                    cols = list(result.keys())
                    raw_rows = list(result.fetchmany(settings.MAX_ROWS + 1))
                    return cols, raw_rows

                exec_coro = _exec()
                try:
                    cols, raw_rows = await asyncio.wait_for(exec_coro, timeout=timeout_sec)
                except Exception:
                    exec_coro.close()
                    raise

            finally:
                # 4. Always ROLLBACK (Layer L2)
                await conn.execute(text("ROLLBACK;"))

    except TimeoutError as exc:
        logger.warning(
            "Query execution timed out",
            extra={"sql": safe_sql.sql, "timeout_ms": settings.QUERY_TIMEOUT_MS},
        )
        raise ExecutionError(
            f"Query timed out after {settings.QUERY_TIMEOUT_MS}ms",
            raw_error=str(exc),
        ) from exc
    except Exception as exc:
        logger.warning(
            "Query execution failed: %s",
            exc,
            extra={"sql": safe_sql.sql, "error": str(exc)},
        )
        raise ExecutionError(
            f"Database query execution failed: {exc}",
            raw_error=str(exc),
        ) from exc

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    truncated = len(raw_rows) > settings.MAX_ROWS
    if truncated:
        raw_rows = raw_rows[: settings.MAX_ROWS]

    # Layer L11: Cell sanitization
    sanitized_rows: list[list[Any]] = []
    for r in raw_rows:
        sanitized_rows.append([_sanitize_cell(cell) for cell in r])

    return ResultSet(
        columns=cols,
        rows=sanitized_rows,
        row_count=len(sanitized_rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )
