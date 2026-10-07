"""API endpoints for conversation history and turns management."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.store.database import delete_conversation, get_conversation, list_conversations

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    """Summary representation for conversation listings."""

    id: str
    title: str
    updated_at: str
    last_kind: str = "sql"
    database: str | None = None


class QueryResponse(BaseModel):
    """One planned/executed query within a turn (preview + result)."""

    index: int
    purpose: str = ""
    sql: str
    explain: dict[str, Any] | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    row_count: int | None = None
    truncated: bool | None = None
    error: str | None = None


class TurnResponse(BaseModel):
    """Full detail of a conversation turn matching frontend Turn model."""

    id: str
    kind: str = "sql"
    question: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    row_count: int | None = None
    truncated: bool | None = None
    queries: list[QueryResponse] | None = None
    answer: str | None = None
    sources: list[dict[str, Any]] | None = None
    status: str
    error: str | None = None
    created_at: str
    database: str | None = None


class ConversationDetail(BaseModel):
    """Detail view of conversation with all its historical turns."""

    id: str
    title: str
    database: str | None = None
    turns: list[TurnResponse]


@router.get("", response_model=list[ConversationSummary])
async def get_conversations() -> list[ConversationSummary]:
    """List all conversations ordered by recent activity."""
    convs = await list_conversations()
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            updated_at=c.updated_at.isoformat(),
            last_kind=c.turns[-1].kind if c.turns and hasattr(c.turns[-1], "kind") else "sql",
            database=getattr(c, "database", None),
        )
        for c in convs
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation_by_id(conversation_id: str) -> ConversationDetail:
    """Fetch conversation and all turns by ID."""
    conv = await get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found",
        )

    turn_models: list[TurnResponse] = []
    for t in conv.turns:
        cols: list[str] | None = json.loads(t.columns_json) if t.columns_json else None
        rows: list[list[Any]] | None = json.loads(t.rows_json) if t.rows_json else None
        queries = (
            [QueryResponse.model_validate(q) for q in json.loads(t.queries_json)]
            if t.queries_json
            else None
        )
        sources: list[dict[str, Any]] | None = (
            json.loads(t.sources_json) if t.sources_json else None
        )

        turn_models.append(
            TurnResponse(
                id=t.id,
                kind=getattr(t, "kind", "sql") or "sql",
                question=t.question,
                sql=t.sql,
                columns=cols,
                rows=rows,
                row_count=t.row_count,
                truncated=t.truncated,
                queries=queries,
                answer=t.answer,
                sources=sources,
                status=t.status,
                error=t.error,
                created_at=t.created_at.isoformat(),
                database=getattr(t, "database", None),
            )
        )

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        database=getattr(conv, "database", None),
        turns=turn_models,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_conversation(conversation_id: str) -> None:
    """Delete conversation and all related turns."""
    deleted = await delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found",
        )
