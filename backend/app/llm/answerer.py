"""Answerer synthesizing streamed natural language responses grounded in SQL query results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm.prompts import build_answer_prompt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from app.config import Settings
    from app.core.executor import ResultSet
    from app.llm.client import LLMClient


async def stream_answer(
    question: str,
    sql: str,
    result: ResultSet,
    client: LLMClient,
    settings: Settings,
) -> AsyncIterator[str]:
    """Stream natural language explanation of SQL query results."""
    # Cap rows to ANSWER_MAX_ROWS for answer synthesis
    rows_for_prompt = result.rows[: settings.ANSWER_MAX_ROWS]

    messages = build_answer_prompt(
        question=question,
        sql=sql,
        columns=result.columns,
        rows=rows_for_prompt,
        row_count=result.row_count,
        truncated=result.truncated or (len(result.rows) > len(rows_for_prompt)),
    )

    async for chunk in client.stream_chat(messages=messages, temperature=0.7):
        yield chunk
