"""EXPLAIN-based cost gate: run `EXPLAIN FORMAT=JSON` on SafeSQL and summarize the plan."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from app.core.validator import SafeSQL
from app.errors import ExecutionError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class TableAccess:
    """One table access from the plan."""

    table: str
    access_type: str
    key: str | None
    rows_examined: int
    rows_produced: int


@dataclass
class ExplainSummary:
    """Human-readable plan summary plus the gate decision."""

    cost: float | None
    estimated_rows: int
    tables: list[TableAccess] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_int(val: Any) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def _walk(node: Any, tables: list[dict[str, Any]], flags: set[str], costs: list[float]) -> None:
    if isinstance(node, dict):
        cost_info = node.get("cost_info")
        if isinstance(cost_info, dict) and "query_cost" in cost_info:
            with contextlib.suppress(TypeError, ValueError):
                costs.append(float(cost_info["query_cost"]))
        for flag in ("using_filesort", "using_temporary_table"):
            if node.get(flag) is True:
                flags.add(flag)
        tbl = node.get("table")
        if isinstance(tbl, dict) and "table_name" in tbl:
            tables.append(tbl)
        for value in node.values():
            _walk(value, tables, flags, costs)
    elif isinstance(node, list):
        for item in node:
            _walk(item, tables, flags, costs)


def summarize_explain(plan: dict[str, Any], settings: Settings) -> ExplainSummary:
    """Summarize a MySQL `EXPLAIN FORMAT=JSON` document and apply the gate thresholds."""
    raw_tables: list[dict[str, Any]] = []
    flags: set[str] = set()
    costs: list[float] = []
    _walk(plan, raw_tables, flags, costs)

    tables = [
        TableAccess(
            table=str(t.get("table_name")),
            access_type=str(t.get("access_type", "unknown")),
            key=t.get("key"),
            rows_examined=_to_int(t.get("rows_examined_per_scan")),
            rows_produced=_to_int(t.get("rows_produced_per_join")),
        )
        for t in raw_tables
    ]
    # Top-level query_cost comes first in document order; UNIONs contribute several.
    cost = max(costs) if costs else None
    estimated_rows = max((t.rows_produced for t in tables), default=0)

    warnings: list[str] = []
    for t in tables:
        if t.access_type == "ALL" and t.rows_examined >= settings.EXPLAIN_WARN_ROWS:
            warnings.append(f"Full table scan on '{t.table}' (~{t.rows_examined:,} rows)")
    if flags and estimated_rows >= settings.EXPLAIN_WARN_ROWS:
        if "using_filesort" in flags:
            warnings.append(f"Sorts ~{estimated_rows:,} rows without an index (filesort)")
        if "using_temporary_table" in flags:
            warnings.append("Uses a temporary table over a large intermediate result")

    blocked = False
    reason: str | None = None
    if cost is not None and cost > settings.EXPLAIN_MAX_COST:
        blocked = True
        reason = f"Estimated cost {cost:,.0f} exceeds the limit of {settings.EXPLAIN_MAX_COST:,.0f}"
    elif estimated_rows > settings.EXPLAIN_MAX_ROWS:
        blocked = True
        reason = (
            f"Estimated {estimated_rows:,} intermediate rows exceeds the limit of "
            f"{settings.EXPLAIN_MAX_ROWS:,}"
        )

    return ExplainSummary(
        cost=cost,
        estimated_rows=estimated_rows,
        tables=tables,
        warnings=warnings,
        blocked=blocked,
        block_reason=reason,
    )


async def explain(safe_sql: SafeSQL, engine: AsyncEngine, settings: Settings) -> ExplainSummary:
    """Run EXPLAIN FORMAT=JSON for validated SQL inside a read-only transaction.

    EXPLAIN does not execute the SELECT; errors (unknown column, etc.) surface here
    so they can be repaired before the user is asked to approve anything.
    """
    if not isinstance(safe_sql, SafeSQL):
        raise TypeError(f"explain only accepts SafeSQL instances, got {type(safe_sql).__name__}")

    timeout_sec = (settings.QUERY_TIMEOUT_MS / 1000.0) + 1.0
    try:
        async with engine.connect() as conn:
            await conn.execute(text("START TRANSACTION READ ONLY;"))
            try:
                await conn.execute(
                    text(f"SET SESSION max_execution_time = {int(settings.QUERY_TIMEOUT_MS)};")
                )
                result = await asyncio.wait_for(
                    conn.execute(text(f"EXPLAIN FORMAT=JSON {safe_sql.sql}")),
                    timeout=timeout_sec,
                )
                raw = result.scalar()
            finally:
                await conn.execute(text("ROLLBACK;"))
    except TimeoutError as exc:
        raise ExecutionError("EXPLAIN timed out", raw_error=str(exc)) from exc
    except Exception as exc:
        logger.warning("EXPLAIN failed: %s", exc, extra={"sql": safe_sql.sql})
        raise ExecutionError(f"Query check (EXPLAIN) failed: {exc}", raw_error=str(exc)) from exc

    try:
        plan = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ExecutionError("Could not parse EXPLAIN output", raw_error=str(raw)) from exc
    return summarize_explain(plan, settings)
