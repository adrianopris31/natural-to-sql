"""Async SQLite engine, session management, and CRUD repositories for app storage."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.store.models import AuditLog, Base, Conversation, Turn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_app_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


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
        stmt = select(Conversation).order_by(Conversation.updated_at.desc())
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


async def create_turn(
    conversation_id: str,
    question: str,
    status: str = "generating_sql",
    turn_id: str | None = None,
    prompt_version: str = "v1.0",
) -> Turn:
    """Create a new conversation turn."""
    async with get_app_session() as session:
        turn = Turn(
            conversation_id=conversation_id,
            question=question,
            status=status,
            prompt_version=prompt_version,
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
) -> AuditLog:
    """Insert an audit log entry for SQL validation or execution attempts."""
    async with get_app_session() as session:
        log = AuditLog(
            turn_id=turn_id,
            attempt=attempt,
            raw_sql=raw_sql,
            safe_sql=safe_sql,
            accepted=accepted,
            reason=reason,
        )
        session.add(log)
        await session.flush()
        return log
