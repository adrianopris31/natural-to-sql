"""Answerer synthesizing streamed natural language responses grounded in SQL query results."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from app.llm.prompts import AnswerResult, build_answer_prompt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.config import Settings
    from app.llm.client import LLMClient

# Low temperature: the answer must restate figures from the rows, not improvise.
ANSWER_TEMPERATURE = 0.2


async def stream_answer(
    question: str,
    results: list[AnswerResult],
    client: LLMClient,
    settings: Settings,
) -> AsyncIterator[str]:
    """Stream one natural language answer covering every executed query."""
    capped = [
        dataclasses.replace(
            res,
            rows=res.rows[: settings.ANSWER_MAX_ROWS],
            truncated=res.truncated or len(res.rows) > settings.ANSWER_MAX_ROWS,
        )
        for res in results
    ]
    messages = build_answer_prompt(question=question, results=capped)

    async for chunk in client.stream_chat(messages=messages, temperature=ANSWER_TEMPERATURE):
        yield chunk
