"""External REST API query endpoints (/v1/query)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.core.auth import require_api_key
from app.core.db import get_engine
from app.core.schema import SchemaCache, get_schema_cache
from app.llm.client import LLMClient, OllamaClient
from app.services.query import (
    approve_headless_query,
    cancel_headless_query,
    execute_headless_query,
)

router = APIRouter(prefix="/v1", tags=["v1-query"])


class QueryRequest(BaseModel):
    """External API query request."""

    question: str = Field(..., min_length=1, description="Natural language question")
    mode: Literal["sql", "docs"] = Field("sql", description="Execution mode: 'sql' or 'docs'")
    auto_approve: bool = Field(
        True,
        description="Automatically run queries that pass safety checks without human review",
    )
    conversation_id: str | None = Field(
        None, description="Optional thread/conversation ID for conversational context"
    )


class ApproveRequest(BaseModel):
    """Approve a blocked or awaiting-approval query turn."""

    queries: list[str | None] | None = Field(
        None, description="Optional edited SQL strings replacing draft queries by index"
    )


def get_v1_llm_client() -> LLMClient:
    """Provide LLM client for V1 API endpoints."""
    settings = get_settings()
    return OllamaClient(
        base_url=settings.OLLAMA_URL,
        model=settings.OLLAMA_MODEL,
        num_ctx=settings.OLLAMA_NUM_CTX,
    )


@router.post("/query", dependencies=[Depends(require_api_key("query"))])
async def post_query(
    request: QueryRequest,
    client: Annotated[LLMClient, Depends(get_v1_llm_client)],
    schema_cache: Annotated[SchemaCache, Depends(get_schema_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Execute a single-shot headless query with natural-to-sql or knowledge-bot docs."""
    try:
        return await execute_headless_query(
            question=request.question,
            mode=request.mode,
            auto_approve=request.auto_approve,
            conversation_id=request.conversation_id,
            client=client,
            engine=get_engine(),
            schema_cache=schema_cache,
            settings=settings,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "message": str(val_err)},
        ) from val_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "server_error", "message": str(exc)},
        ) from exc


@router.post("/query/{turn_id}/approve", dependencies=[Depends(require_api_key("query"))])
async def post_query_approve(
    turn_id: str,
    request: ApproveRequest,
    client: Annotated[LLMClient, Depends(get_v1_llm_client)],
    schema_cache: Annotated[SchemaCache, Depends(get_schema_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Execute an approved headless query after inspection or edits."""
    try:
        return await approve_headless_query(
            turn_id=turn_id,
            sql_overrides=request.queries,
            client=client,
            engine=get_engine(),
            schema_cache=schema_cache,
            settings=settings,
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_request", "message": str(val_err)},
        ) from val_err


@router.post("/query/{turn_id}/cancel", dependencies=[Depends(require_api_key("query"))])
async def post_query_cancel(
    turn_id: str,
) -> dict[str, Any]:
    """Cancel and discard a blocked or previewed turn."""
    cancelled = await cancel_headless_query(turn_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "turn_not_found",
                "message": "Turn not found or not awaiting approval",
            },
        )
    return {"status": "cancelled", "turn_id": turn_id}


@router.get("/health")
async def get_health() -> dict[str, Any]:
    """Public health status check for the API and target database."""
    db_ok = False
    try:
        from sqlalchemy import text

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "target_db": "connected" if db_ok else "unreachable",
        "version": "1.0.0",
    }
