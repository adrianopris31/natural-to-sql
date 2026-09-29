"""Unit tests for answerer.py."""

import pytest

from app.config import Settings
from app.llm.answerer import stream_answer
from app.llm.client import FakeLLMClient
from app.llm.prompts import AnswerResult


@pytest.mark.asyncio
async def test_stream_answer_happy_path() -> None:
    fake_client = FakeLLMClient(
        stream_responses=[["There ", "are ", "500 ", "registered ", "users."]]
    )
    result = AnswerResult(
        sql="SELECT count(*) FROM users;",
        columns=["count"],
        rows=[[500]],
        row_count=1,
        truncated=False,
    )
    settings = Settings()

    chunks = [
        chunk
        async for chunk in stream_answer(
            question="How many users?",
            results=[result],
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
    result = AnswerResult(
        sql="SELECT id, name FROM products;",
        columns=["id", "name"],
        rows=rows,
        row_count=100,
        truncated=False,
    )
    settings = Settings(ANSWER_MAX_ROWS=10)

    chunks = [
        chunk
        async for chunk in stream_answer(
            question="List products",
            results=[result],
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


@pytest.mark.asyncio
async def test_stream_answer_multiple_results_and_failures() -> None:
    fake_client = FakeLLMClient(stream_responses=[["ok"]])
    results = [
        AnswerResult(
            sql="SELECT COUNT(*) AS n FROM orders",
            columns=["n"],
            rows=[[42]],
            row_count=1,
            truncated=False,
            purpose="Order count",
        ),
        AnswerResult(
            sql="SELECT name FROM products",
            columns=[],
            rows=[],
            row_count=0,
            truncated=False,
            purpose="Products",
            error="timed out",
        ),
    ]
    _ = [c async for c in stream_answer("Q", results, fake_client, Settings())]
    call = fake_client.recorded_stream_calls[0]
    content = call["messages"][1]["content"]
    assert "### Query 1 — Order count" in content
    assert "### Query 2 — Products" in content
    assert "FAILED: timed out" in content
    assert call["temperature"] <= 0.3
