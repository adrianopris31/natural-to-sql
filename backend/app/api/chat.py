"""API router for SSE chat streaming."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.core.db import get_engine
from app.core.schema import get_schema_cache
from app.llm.client import LLMClient, OllamaClient
from app.services.chat import process_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """Chat stream request payload."""

    conversation_id: str | None = None
    message: str


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
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
