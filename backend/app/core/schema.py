"""Database schema introspection, representation, and prompt formatting."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import get_settings
from app.core.db import get_default_database_name, get_engine
from app.errors import SchemaError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class ColumnModel(BaseModel):
    """Schema representation for a database column."""

    name: str
    type: str
    nullable: bool = False
    is_pk: bool = False
    is_fk: bool = False
    fk_target: str | None = None
    sample_values: list[str] = Field(default_factory=list)
    comment: str | None = None

    def to_prompt_str(self) -> str:
        """Format column for prompt inclusion: col type [PK] [FK→t.col] [samples: ...]."""
        parts = [f"{self.name} {self.type}"]
        if self.is_pk:
            parts.append("[PK]")
        if self.is_fk and self.fk_target:
            parts.append(f"[FK→{self.fk_target}]")
        if self.sample_values:
            quoted_samples = ", ".join(f"'{val}'" for val in self.sample_values[:5])
            parts.append(f"[samples: {quoted_samples}]")
        return " ".join(parts)


class TableModel(BaseModel):
    """Schema representation for a database table."""

    name: str
    comment: str | None = None
    approx_rows: int = 0
    columns: list[ColumnModel] = Field(default_factory=list)
    # True when DENY_COLUMNS removed columns from this table (so SELECT * would leak them)
    has_restricted_columns: bool = False

    def to_prompt_str(self) -> str:
        """Format table for prompt inclusion: table(cols, ...) -- comment."""
        cols_str = ", ".join(c.to_prompt_str() for c in self.columns)
        base = f"{self.name}({cols_str})"
        if self.comment and self.comment.strip():
            base = f"{base} -- {self.comment.strip()}"
        return base


class SchemaModel(BaseModel):
    """Full database schema representation."""

    tables: list[TableModel] = Field(default_factory=list)
    # Target database name; db-qualified table refs must match it
    database: str | None = None

    def get_table(self, table_name: str) -> TableModel | None:
        """Look up a table by case-insensitive name."""
        lowered = table_name.lower()
        for tbl in self.tables:
            if tbl.name.lower() == lowered:
                return tbl
        return None

    @property
    def table_names(self) -> list[str]:
        """Return list of table names."""
        return [t.name for t in self.tables]

    def to_prompt(self, tables: list[str] | None = None) -> str:
        """Format selected or all tables as compact schema strings for prompts."""
        selected = self.tables
        if tables is not None:
            lower_set = {t.lower() for t in tables}
            selected = [t for t in self.tables if t.name.lower() in lower_set]
        return "\n".join(t.to_prompt_str() for t in selected)


async def _fetch_sample_values(
    conn: Any,
    table_name: str,
    column_name: str,
    column_type: str,
) -> list[str]:
    """Fetch up to 5 distinct values for low-cardinality text or enum columns."""
    type_lower = column_type.lower()
    # Check if column is enum or low-cardinality string
    is_candidate = any(t in type_lower for t in ["enum", "char", "varchar", "tinytext"])
    if not is_candidate:
        return []

    try:
        # Fetch up to 6 distinct values; if > 5, it is considered high cardinality
        query = text(
            f"SELECT DISTINCT `{column_name}` FROM `{table_name}` "
            f"WHERE `{column_name}` IS NOT NULL LIMIT 6;"
        )
        res = await conn.execute(query)
        rows = res.fetchall()
        if len(rows) <= 5 and rows:
            return [str(r[0]) for r in rows if r[0] is not None]
    except Exception as exc:
        logger.debug(
            "Could not fetch sample values for %s.%s: %s",
            table_name,
            column_name,
            exc,
        )
    return []


async def introspect_schema(
    engine: AsyncEngine | None = None,
    db_name: str | None = None,
) -> SchemaModel:
    """Introspect target database information_schema and return SchemaModel."""
    settings = get_settings()
    if engine is None:
        engine = get_engine(db_name)
    if db_name is None:
        if hasattr(engine, "url"):
            db_name = getattr(engine.url, "database", None)
        else:
            db_name = get_default_database_name()
    if not db_name:
        raise SchemaError("Database name not configured in TARGET_DB_URL")

    deny_tables = {t.lower() for t in settings.DENY_TABLES}
    deny_columns = {c.lower() for c in settings.DENY_COLUMNS}

    try:
        async with engine.connect() as conn:
            # 1. Introspect tables
            table_query = text(
                """
                SELECT table_name, table_comment, table_rows
                FROM information_schema.tables
                WHERE table_schema = :db_name
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """
            )
            table_rows = (await conn.execute(table_query, {"db_name": db_name})).fetchall()

            # 2. Introspect foreign keys
            fk_query = text(
                """
                SELECT table_name, column_name, referenced_table_name, referenced_column_name
                FROM information_schema.key_column_usage
                WHERE table_schema = :db_name
                  AND referenced_table_name IS NOT NULL
                  AND referenced_column_name IS NOT NULL;
                """
            )
            fk_rows = (await conn.execute(fk_query, {"db_name": db_name})).fetchall()
            fk_map: dict[tuple[str, str], str] = {(r[0], r[1]): f"{r[2]}.{r[3]}" for r in fk_rows}

            # 3. Introspect columns
            col_query = text(
                """
                SELECT table_name, column_name, column_type, is_nullable, column_key, column_comment
                FROM information_schema.columns
                WHERE table_schema = :db_name
                ORDER BY table_name, ordinal_position;
                """
            )
            col_rows = (await conn.execute(col_query, {"db_name": db_name})).fetchall()

            # Organize columns by table
            cols_by_table: dict[str, list[ColumnModel]] = {}
            restricted_tables: set[str] = set()
            for row in col_rows:
                tbl_name, col_name, col_type, is_null, col_key, col_comment = row
                if tbl_name.lower() in deny_tables:
                    continue
                if col_name.lower() in deny_columns:
                    restricted_tables.add(tbl_name)
                    continue

                is_pk = col_key == "PRI"
                fk_target = fk_map.get((tbl_name, col_name))
                is_fk = fk_target is not None

                sample_vals: list[str] = []
                if settings.SCHEMA_SAMPLE_VALUES and not is_pk and not is_fk:
                    sample_vals = await _fetch_sample_values(
                        conn=conn,
                        table_name=tbl_name,
                        column_name=col_name,
                        column_type=col_type,
                    )

                col_model = ColumnModel(
                    name=col_name,
                    type=col_type,
                    nullable=is_null == "YES",
                    is_pk=is_pk,
                    is_fk=is_fk,
                    fk_target=fk_target,
                    sample_values=sample_vals,
                    comment=col_comment if col_comment else None,
                )
                cols_by_table.setdefault(tbl_name, []).append(col_model)

            tables: list[TableModel] = []
            for t_row in table_rows:
                t_name, t_comment, t_approx = t_row
                if t_name.lower() in deny_tables:
                    continue
                tables.append(
                    TableModel(
                        name=t_name,
                        comment=t_comment if t_comment else None,
                        approx_rows=int(t_approx or 0),
                        columns=cols_by_table.get(t_name, []),
                        has_restricted_columns=t_name in restricted_tables,
                    )
                )

            logger.info("Schema introspected successfully: %d tables", len(tables))
            return SchemaModel(tables=tables, database=db_name)

    except Exception as exc:
        logger.error("Failed to introspect schema: %s", exc, extra={"error": str(exc)})
        raise SchemaError(f"Database introspection failed: {exc}") from exc


class SchemaCache:
    """Thread-safe in-memory cache for database schema keyed by database name."""

    def __init__(self) -> None:
        self._schemas: dict[str, SchemaModel] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def _schema(self) -> SchemaModel | None:
        """Backwards compatibility for single-schema access and conftest fixtures."""
        default_db = get_default_database_name()
        return self._schemas.get(default_db)

    @_schema.setter
    def _schema(self, val: SchemaModel | None) -> None:
        if val is None:
            self._schemas.clear()
        else:
            key = val.database or get_default_database_name()
            self._schemas[key] = val

    async def get_schema(
        self,
        db_name: str | None = None,
        force_refresh: bool = False,
    ) -> SchemaModel:
        """Get cached schema or introspect if not cached or force_refresh=True."""
        target_db = db_name or get_default_database_name()
        async with self._get_lock():
            if target_db not in self._schemas or force_refresh:
                self._schemas[target_db] = await introspect_schema(db_name=target_db)
            return self._schemas[target_db]

    def clear(self) -> None:
        """Clear all cached schemas."""
        self._schemas.clear()


_cache = SchemaCache()


def get_schema_cache() -> SchemaCache:
    """Return the global SchemaCache instance."""
    return _cache
