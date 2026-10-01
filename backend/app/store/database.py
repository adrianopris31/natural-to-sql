"""Async SQLite engine, session management, and CRUD repositories for app storage."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.store.models import ApiKey, ApiUsage, AuditLog, Base, Conversation, Turn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_app_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


# Columns added after app.db files already existed: (table, column, SQLite type)
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("turns", "queries_json", "TEXT"),
    ("audit_log", "stage", "VARCHAR(32)"),
    ("audit_log", "row_count", "INTEGER"),
    ("audit_log", "elapsed_ms", "FLOAT"),
    ("turns", "kind", "VARCHAR(16) NOT NULL DEFAULT 'sql'"),
    ("turns", "sources_json", "TEXT"),
]


def resolve_sqlite_url(db_path_str: str | None = None) -> str:
    """Resolve file path to an async SQLite connection URL."""
    if db_path_str is None:
        settings = get_settings()
        db_path_str = settings.APP_DB_PATH

    path = Path(db_path_str)
    if not path.is_absolute() and Path("backend").is_dir() and not Path("app").is_dir():
        path = Path("backend") / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path.resolve()}"


def get_app_engine(db_path_str: str | None = None) -> AsyncEngine:
    """Get or create singleton async SQLite engine."""
    global _app_engine, _session_factory
    if _app_engine is None:
        url = resolve_sqlite_url(db_path_str)
        _app_engine = create_async_engine(url, echo=False)
        _session_factory = async_sessionmaker(_app_engine, expire_on_commit=False)
    return _app_engine


async def close_app_db() -> None:
    """Dispose singleton SQLite engine."""
    global _app_engine, _session_factory
    if _app_engine is not None:
        await _app_engine.dispose()
        _app_engine = None
        _session_factory = None


async def init_app_db(db_path_str: str | None = None) -> None:
    """Initialize application SQLite schema creating all tables."""
    engine = get_app_engine(db_path_str)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations for columns added after a DB file was created
        for table, column, ddl in _MIGRATIONS:
            existing = {row[1] for row in await conn.execute(text(f"PRAGMA table_info({table})"))}
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                logger.info("Migrated app DB: added %s.%s", table, column)
    logger.info("Application SQLite database schema initialized")


@asynccontextmanager
async def get_app_session() -> AsyncIterator[AsyncSession]:
    """Provide a transactional async session scope."""
    global _session_factory
    if _session_factory is None:
        get_app_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# --- CRUD Repositories ---


async def create_conversation(title: str, conversation_id: str | None = None) -> Conversation:
    """Create a new conversation."""
    async with get_app_session() as session:
        conv = Conversation(title=title)
        if conversation_id:
            conv.id = conversation_id
        session.add(conv)
        await session.flush()
        return conv


async def get_conversation(conversation_id: str) -> Conversation | None:
    """Fetch conversation by ID with loaded turns."""
    async with get_app_session() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.turns))
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def list_conversations() -> list[Conversation]:
    """List all conversations ordered by updated_at descending."""
    async with get_app_session() as session:
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.turns))
            .order_by(Conversation.updated_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and all its associated turns."""
    async with get_app_session() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            return False
        await session.delete(conv)
        return True


async def touch_conversation(conversation_id: str) -> None:
    """Update conversation updated_at timestamp to now."""
    async with get_app_session() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.datetime.now(datetime.UTC)
            await session.flush()


async def create_turn(
    conversation_id: str,
    question: str,
    status: str = "generating_sql",
    turn_id: str | None = None,
    prompt_version: str = "v1.0",
    kind: str = "sql",
) -> Turn:
    """Create a new conversation turn."""
    async with get_app_session() as session:
        turn = Turn(
            conversation_id=conversation_id,
            question=question,
            status=status,
            prompt_version=prompt_version,
            kind=kind,
        )
        if turn_id:
            turn.id = turn_id
        session.add(turn)
        await session.flush()
        return turn


async def update_turn(
    turn_id: str,
    **kwargs: Any,
) -> Turn | None:
    """Update fields on an existing turn."""
    async with get_app_session() as session:
        turn = await session.get(Turn, turn_id)
        if turn is None:
            return None
        for key, val in kwargs.items():
            if hasattr(turn, key):
                setattr(turn, key, val)
        await session.flush()
        return turn


async def get_turn(turn_id: str) -> Turn | None:
    """Fetch a single turn by ID."""
    async with get_app_session() as session:
        return await session.get(Turn, turn_id)


async def get_recent_turns(conversation_id: str, limit: int = 4) -> list[Turn]:
    """Retrieve the last N turns for a conversation ordered chronologically."""
    async with get_app_session() as session:
        stmt = (
            select(Turn)
            .where(Turn.conversation_id == conversation_id)
            .order_by(Turn.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        turns = list(result.scalars().all())
        turns.reverse()
        return turns


async def record_audit_log(
    attempt: int,
    accepted: bool,
    turn_id: str | None = None,
    raw_sql: str | None = None,
    safe_sql: str | None = None,
    reason: str | None = None,
    stage: str | None = None,
    row_count: int | None = None,
    elapsed_ms: float | None = None,
) -> AuditLog:
    """Record one SQL lifecycle event in app.db and append it to the JSONL SQL log."""
    resolved_stage = stage or ("validated" if accepted else "rejected")
    async with get_app_session() as session:
        log = AuditLog(
            turn_id=turn_id,
            attempt=attempt,
            raw_sql=raw_sql,
            safe_sql=safe_sql,
            accepted=accepted,
            reason=reason,
            stage=resolved_stage,
            row_count=row_count,
            elapsed_ms=elapsed_ms,
        )
        session.add(log)
        await session.flush()
        entry = {
            "ts": log.created_at.isoformat(),
            "turn_id": turn_id,
            "stage": resolved_stage,
            "attempt": attempt,
            "accepted": accepted,
            "raw_sql": raw_sql,
            "safe_sql": safe_sql,
            "reason": reason,
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
        }
    await _append_sql_log(entry)
    return log


async def _append_sql_log(entry: dict[str, Any]) -> None:
    """Append one JSON line to SQL_LOG_PATH (best effort; never breaks the request)."""
    path = Path(get_settings().SQL_LOG_PATH)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    try:
        await asyncio.to_thread(_write)
    except OSError as exc:
        logger.warning("Could not write SQL log file: %s", exc)


async def list_audit_entries(limit: int = 200, turn_id: str | None = None) -> list[dict[str, Any]]:
    """Newest-first SQL log entries joined with their turn's question/conversation."""
    async with get_app_session() as session:
        stmt = (
            select(AuditLog, Turn.question, Turn.conversation_id)
            .outerjoin(Turn, Turn.id == AuditLog.turn_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        if turn_id:
            stmt = stmt.where(AuditLog.turn_id == turn_id)
        rows = (await session.execute(stmt)).all()
        return [
            {
                "id": log.id,
                "created_at": log.created_at.isoformat(),
                "turn_id": log.turn_id,
                "conversation_id": conversation_id,
                "question": question,
                "stage": log.stage or ("validated" if log.accepted else "rejected"),
                "attempt": log.attempt,
                "accepted": log.accepted,
                "raw_sql": log.raw_sql,
                "safe_sql": log.safe_sql,
                "reason": log.reason,
                "row_count": log.row_count,
                "elapsed_ms": log.elapsed_ms,
            }
            for log, question, conversation_id in rows
        ]


# --- API Key & Quota Repositories ---


async def save_api_key(
    key_hash: str,
    label: str,
    scope: str = "query",
    daily_quota: int = 0,
) -> ApiKey:
    """Store a newly generated API key record."""
    async with get_app_session() as session:
        api_key = ApiKey(
            key_hash=key_hash,
            label=label,
            scope=scope,
            daily_quota=daily_quota,
        )
        session.add(api_key)
        await session.flush()
        return api_key


async def find_api_key(key_hash: str, include_revoked: bool = False) -> ApiKey | None:
    """Fetch API key by its SHA-256 hash."""
    async with get_app_session() as session:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        return (await session.execute(stmt)).scalar_one_or_none()


async def revoke_api_key(key_hash_prefix: str) -> bool:
    """Revoke an API key matching hash or prefix. Returns True if revoked, False if not found."""
    async with get_app_session() as session:
        stmt = (
            select(ApiKey)
            .where(ApiKey.key_hash.startswith(key_hash_prefix))
            .where(ApiKey.revoked_at.is_(None))
        )
        key = (await session.execute(stmt)).scalar_one_or_none()
        if not key:
            return False
        key.revoked_at = datetime.datetime.now(datetime.UTC)
        await session.flush()
        return True


async def list_api_keys(include_revoked: bool = False) -> list[dict[str, Any]]:
    """List API keys with metadata (excluding the full key hash)."""
    async with get_app_session() as session:
        stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
        if not include_revoked:
            stmt = stmt.where(ApiKey.revoked_at.is_(None))
        keys = (await session.execute(stmt)).scalars().all()
        return [
            {
                "key_hash_prefix": key.key_hash[:12],
                "label": key.label,
                "scope": key.scope,
                "daily_quota": key.daily_quota,
                "created_at": key.created_at.isoformat(),
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "revoked": key.revoked_at is not None,
                "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
            }
            for key in keys
        ]


async def record_api_usage(key_hash: str) -> None:
    """Record one API request for today's quota tracking and update last_used_at."""
    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    now = datetime.datetime.now(datetime.UTC)
    async with get_app_session() as session:
        key = await session.get(ApiKey, key_hash)
        if key:
            key.last_used_at = now

        stmt = (
            select(ApiUsage)
            .where(ApiUsage.key_hash == key_hash)
            .where(ApiUsage.usage_date == today)
        )
        usage = (await session.execute(stmt)).scalar_one_or_none()
        if usage:
            usage.request_count += 1
        else:
            usage = ApiUsage(key_hash=key_hash, usage_date=today, request_count=1)
            session.add(usage)
        await session.flush()


async def get_api_usage_today(key_hash: str) -> int:
    """Get the number of API requests recorded today for an API key."""
    today = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    async with get_app_session() as session:
        stmt = (
            select(ApiUsage.request_count)
            .where(ApiUsage.key_hash == key_hash)
            .where(ApiUsage.usage_date == today)
        )
        result = (await session.execute(stmt)).scalar_one_or_none()
        return result or 0
