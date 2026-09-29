"""API router for SSE chat streaming."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.core.db import get_engine
from app.core.schema import get_schema_cache
from app.llm.client import LLMClient, OllamaClient
from app.services.chat import cancel_turn, process_chat, run_approved_turn, with_heartbeat

HEARTBEAT_INTERVAL_SEC = 10.0

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Chat stream request payload."""

    conversation_id: str | None = None
    message: str


class RunRequest(BaseModel):
    """Approve a previewed turn. `queries[i]` optionally replaces query i's SQL."""

    queries: list[str | None] | None = None


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def get_chat_llm_client() -> LLMClient:
    """Provide LLM client for chat endpoint."""
    settings = get_settings()
    return OllamaClient(
        base_url=settings.OLLAMA_URL,
        model=settings.OLLAMA_MODEL,
        num_ctx=settings.OLLAMA_NUM_CTX,
    )


@router.post("")
async def chat_endpoint(
    request: ChatRequest,
    client: Annotated[LLMClient, Depends(get_chat_llm_client)],
) -> StreamingResponse:
    """Stream chat response events via Server-Sent Events (SSE)."""
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    event_generator = process_chat(
        message=request.message,
        conversation_id=request.conversation_id,
        client=client,
        engine=engine,
        schema_cache=schema_cache,
        settings=settings,
    )

    return StreamingResponse(
        with_heartbeat(event_generator, HEARTBEAT_INTERVAL_SEC),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{turn_id}/run")
async def run_turn_endpoint(
    turn_id: str,
    request: RunRequest,
    client: Annotated[LLMClient, Depends(get_chat_llm_client)],
) -> StreamingResponse:
    """Execute a previewed turn after user approval; streams results and the answer (SSE)."""
    event_generator = run_approved_turn(
        turn_id=turn_id,
        sql_overrides=request.queries,
        client=client,
        engine=get_engine(),
        schema_cache=get_schema_cache(),
        settings=get_settings(),
    )
    return StreamingResponse(
        with_heartbeat(event_generator, HEARTBEAT_INTERVAL_SEC),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{turn_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_turn_endpoint(turn_id: str) -> None:
    """Discard a previewed turn without running it."""
    if not await cancel_turn(turn_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Turn not found or not awaiting approval",
        )
