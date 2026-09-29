"""Unit tests for answerer.py."""

import pytest

from app.config import Settings
from app.core.executor import ResultSet
from app.llm.answerer import stream_answer
from app.llm.client import FakeLLMClient


@pytest.mark.asyncio
async def test_stream_answer_happy_path() -> None:
    fake_client = FakeLLMClient(
        stream_responses=[["There ", "are ", "500 ", "registered ", "users."]]
    )
    result = ResultSet(
        columns=["count"],
        rows=[[500]],
        row_count=1,
        truncated=False,
        elapsed_ms=5.0,
    )
    settings = Settings()

    chunks = [
        chunk
        async for chunk in stream_answer(
            question="How many users?",
            sql="SELECT count(*) FROM users;",
            result=result,
            client=fake_client,
            settings=settings,
        )
    ]

    assert "".join(chunks) == "There are 500 registered users."
    assert len(fake_client.recorded_stream_calls) == 1
    prompt_content = fake_client.recorded_stream_calls[0]["messages"][1]["content"]
    assert "How many users?" in prompt_content
    assert "| count |" in prompt_content


@pytest.mark.asyncio
async def test_stream_answer_caps_rows() -> None:
    fake_client = FakeLLMClient(stream_responses=[["Summarized ", "top ", "items."]])
    # Generate 100 rows with ANSWER_MAX_ROWS set to 10
    rows = [[i, f"Product {i}"] for i in range(100)]
    result = ResultSet(
        columns=["id", "name"],
        rows=rows,
        row_count=100,
        truncated=False,
        elapsed_ms=10.0,
    )
    settings = Settings(ANSWER_MAX_ROWS=10)

    chunks = [
        chunk
        async for chunk in stream_answer(
            question="List products",
            sql="SELECT id, name FROM products;",
            result=result,
            client=fake_client,
            settings=settings,
        )
    ]
    assert len(chunks) == 3
    prompt_content = fake_client.recorded_stream_calls[0]["messages"][1]["content"]
    assert "Note: Results were truncated" in prompt_content
    # Row 9 should be in markdown table, but row 50 should not
    assert "Product 9" in prompt_content
    assert "Product 50" not in prompt_content
