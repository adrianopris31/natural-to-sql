"""API endpoint exposing the SQL audit log (every generated, edited and executed query)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.store.database import list_audit_entries

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntry(BaseModel):
    """One SQL lifecycle event."""

    id: str
    created_at: str
    turn_id: str | None = None
    conversation_id: str | None = None
    question: str | None = None
    stage: str
    attempt: int
    accepted: bool
    raw_sql: str | None = None
    safe_sql: str | None = None
    reason: str | None = None
    row_count: int | None = None
    elapsed_ms: float | None = None


@router.get("", response_model=list[AuditEntry])
async def get_audit_log(
    limit: int = Query(200, ge=1, le=1000),
    turn_id: str | None = None,
) -> list[dict[str, Any]]:
    """Newest-first SQL log, optionally filtered to one turn."""
    return await list_audit_entries(limit=limit, turn_id=turn_id)
