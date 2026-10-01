"""Client integration for knowledge-bot service.

This is the ONLY module in natural-to-sql that knows knowledge-bot exists.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import (
    KnowledgeBotAuthError,
    KnowledgeBotError,
    KnowledgeBotNotConfiguredError,
    KnowledgeBotQuotaError,
    KnowledgeBotUnreachableError,
    KnowledgeBotUpstreamError,
)

logger = logging.getLogger(__name__)


class DocsSource(BaseModel):
    """One document or ticket cited in a knowledge-bot answer."""

    id: str
    source_type: str
    title: str
    url: str
    score: float = 0.0


class DocsAnswer(BaseModel):
    """Structured response from the knowledge-bot ask endpoint."""

    answer: str
    sources: list[DocsSource] = Field(default_factory=list)
    refused: bool = False
    model: str = ""
    filter: str = ""
    documents_searched: int = 0


async def ask_docs(question: str) -> DocsAnswer:
    """Send question to knowledge-bot and return structured DocsAnswer.

    Maps errors to typed user-safe exceptions. Never logs or echoes the API key.
    """
    settings = get_settings()
    api_key = settings.KNOWLEDGE_BOT_API_KEY.strip() if settings.KNOWLEDGE_BOT_API_KEY else ""
    if not api_key:
        raise KnowledgeBotNotConfiguredError(
            "Knowledge base is not configured (missing KNOWLEDGE_BOT_API_KEY)",
            user_message=(
                "Documentation search is not configured. Please set KNOWLEDGE_BOT_API_KEY."
            ),
        )

    clean_question = question.strip()
    if not clean_question:
        raise KnowledgeBotError(
            "Empty question provided",
            user_message="Question cannot be empty.",
        )

    url = f"{settings.KNOWLEDGE_BOT_URL.rstrip('/')}/v1/ask"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "question": clean_question[:2000],
        "model": "",
    }

    logger.info(
        "Querying knowledge-bot at %s (question length: %d)",
        settings.KNOWLEDGE_BOT_URL,
        len(clean_question),
    )

    try:
        async with httpx.AsyncClient(timeout=settings.KNOWLEDGE_BOT_TIMEOUT_SEC) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning(
            "Knowledge-bot request timed out after %.1fs", settings.KNOWLEDGE_BOT_TIMEOUT_SEC
        )
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot timed out: {exc}",
            user_message="Knowledge base service timed out. Please try again.",
        ) from exc
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        logger.warning("Knowledge-bot service unreachable: %s", exc)
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot unreachable: {exc}",
            user_message="Knowledge base service is unreachable. Please verify it is running.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Knowledge-bot HTTP error: %s", exc)
        raise KnowledgeBotError(
            f"Knowledge-bot communication error: {exc}",
            user_message="Failed to communicate with knowledge base service.",
        ) from exc

    if resp.status_code == 200:
        try:
            data = resp.json()
            return DocsAnswer.model_validate(data)
        except Exception as exc:
            logger.error("Failed to parse knowledge-bot response JSON: %s", exc)
            raise KnowledgeBotError(
                f"Invalid JSON response from knowledge-bot: {exc}",
                user_message="Received invalid response from knowledge base service.",
            ) from exc

    if resp.status_code in (401, 403):
        logger.warning("Knowledge-bot authentication error (status %d)", resp.status_code)
        raise KnowledgeBotAuthError(
            f"Authentication failed with status {resp.status_code}",
            user_message="Knowledge base authentication failed. Check your API key.",
        )

    if resp.status_code == 429:
        logger.warning("Knowledge-bot quota/rate limit exceeded (status 429)")
        raise KnowledgeBotQuotaError(
            "Quota or rate limit exceeded",
            user_message="Knowledge base quota or rate limit exceeded. Please try again later.",
        )

    if resp.status_code == 502:
        logger.warning("Knowledge-bot upstream LLM error (status 502)")
        raise KnowledgeBotUpstreamError(
            "Upstream LLM error from knowledge-bot",
            user_message="Knowledge base upstream AI service encountered an error.",
        )

    logger.warning("Knowledge-bot returned HTTP status %d", resp.status_code)
    raise KnowledgeBotError(
        f"Knowledge-bot returned HTTP {resp.status_code}",
        user_message=f"Knowledge base service returned an error (HTTP {resp.status_code}).",
    )


async def docs_health() -> dict[str, bool]:
    """Check whether knowledge-bot is configured and reachable."""
    settings = get_settings()
    api_key = settings.KNOWLEDGE_BOT_API_KEY.strip() if settings.KNOWLEDGE_BOT_API_KEY else ""
    if not api_key:
        return {"configured": False, "reachable": False}

    url = f"{settings.KNOWLEDGE_BOT_URL.rstrip('/')}/v1/health"
    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)
            return {"configured": True, "reachable": resp.status_code == 200}
    except Exception as exc:
        logger.debug("Knowledge-bot health check failed: %s", exc)
        return {"configured": True, "reachable": False}
