"""Service orchestrating documentation Q&A via knowledge-bot."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

from app.errors import (
    KnowledgeBotAuthError,
    KnowledgeBotError,
    KnowledgeBotNotConfiguredError,
    KnowledgeBotQuotaError,
    KnowledgeBotUnreachableError,
    KnowledgeBotUpstreamError,
)
from app.integrations.knowledge_bot import ask_docs
from app.services.chat import format_sse
from app.store.database import (
    create_conversation,
    create_turn,
    get_conversation,
    touch_conversation,
    update_turn,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


async def process_docs_chat(
    message: str,
    conversation_id: str | None,
) -> AsyncIterator[str]:
    """Execute documentation question through knowledge-bot and stream SSE events."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    clean_message = message.strip()
    if not clean_message:
        yield format_sse("error", {"message": "Empty message provided", "code": "EMPTY_MESSAGE"})
        return

    active_conv_id = conversation_id
    if not active_conv_id or not await get_conversation(active_conv_id):
        active_conv_id = str(uuid.uuid4())
        await create_conversation(title=clean_message[:60], conversation_id=active_conv_id)
    else:
        await touch_conversation(active_conv_id)

    turn_id = str(uuid.uuid4())
    await create_turn(
        conversation_id=active_conv_id,
        question=clean_message,
        turn_id=turn_id,
        status="searching_docs",
        kind="docs",
    )

    yield format_sse("status", "searching_docs")

    t_search = time.perf_counter()
    try:
        docs_answer = await ask_docs(clean_message)
    except KnowledgeBotNotConfiguredError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_NOT_CONFIGURED"})
        return
    except KnowledgeBotAuthError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_AUTH_FAILED"})
        return
    except KnowledgeBotQuotaError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_QUOTA_EXCEEDED"})
        return
    except KnowledgeBotUpstreamError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_UPSTREAM_ERROR"})
        return
    except KnowledgeBotUnreachableError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_UNREACHABLE"})
        return
    except KnowledgeBotError as exc:
        err_msg = exc.user_message
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_ERROR"})
        return
    except Exception as exc:
        err_msg = f"Knowledge base error: {exc}"
        logger.error("Unexpected error querying knowledge-bot: %s", exc)
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "DOCS_ERROR"})
        return

    timings["search_ms"] = round((time.perf_counter() - t_search) * 1000, 2)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    sources_data = [s.model_dump() for s in docs_answer.sources]
    sources_json = json.dumps(sources_data)

    await update_turn(
        turn_id,
        answer=docs_answer.answer,
        sources_json=sources_json,
        status="done",
        timings_json=json.dumps(timings),
    )

    yield format_sse(
        "docs_answer",
        {
            "answer": docs_answer.answer,
            "sources": sources_data,
            "refused": docs_answer.refused,
            "model": docs_answer.model,
        },
    )
    yield format_sse(
        "done",
        {
            "conversation_id": active_conv_id,
            "turn_id": turn_id,
            "timings": timings,
        },
    )
