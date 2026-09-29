"""Unit tests for OllamaClient and FakeLLMClient."""

import json

import httpx
import pytest
import respx

from app.errors import LLMError
from app.llm.client import FakeLLMClient, OllamaClient


@pytest.mark.asyncio
async def test_fake_llm_client_chat_and_stream() -> None:
    fake = FakeLLMClient(
        json_responses=[{"sql": "SELECT * FROM users;", "reasoning": "Simple select"}],
        stream_responses=[["Hello", " ", "World"]],
    )

    # chat_json
    data = await fake.chat_json(
        messages=[{"role": "user", "content": "Hi"}],
        schema={},
    )
    assert data["sql"] == "SELECT * FROM users;"
    assert len(fake.recorded_chat_calls) == 1

    # stream_chat
    chunks = [c async for c in fake.stream_chat(messages=[{"role": "user", "content": "Hi"}])]
    assert chunks == ["Hello", " ", "World"]
    assert len(fake.recorded_stream_calls) == 1

    # check_health
    is_healthy, models = await fake.check_health()
    assert is_healthy is True
    assert "qwen2.5-coder:7b" in models


@pytest.mark.asyncio
@respx.mock
async def test_ollama_client_chat_json_success() -> None:
    client = OllamaClient(base_url="http://mock-ollama:11434", model="qwen2.5-coder:7b")

    mock_res = {
        "message": {
            "role": "assistant",
            "content": json.dumps({"sql": "SELECT 1;", "reasoning": "Static"}),
        }
    }
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json=mock_res)
    )

    result = await client.chat_json(
        messages=[{"role": "user", "content": "Query"}],
        schema={"type": "object"},
    )
    assert result == {"sql": "SELECT 1;", "reasoning": "Static"}


@pytest.mark.asyncio
@respx.mock
async def test_ollama_client_chat_json_timeout() -> None:
    client = OllamaClient(
        base_url="http://mock-ollama:11434",
        model="qwen2.5-coder:7b",
        timeout_sec=0.01,
    )

    respx.post("http://mock-ollama:11434/api/chat").mock(
        side_effect=httpx.TimeoutException("Timeout")
    )

    with pytest.raises(LLMError, match="timed out"):
        await client.chat_json(messages=[], schema={})


@pytest.mark.asyncio
@respx.mock
async def test_ollama_client_stream_chat() -> None:
    client = OllamaClient(base_url="http://mock-ollama:11434", model="qwen2.5-coder:7b")

    stream_content = "\n".join(
        [
            json.dumps({"message": {"content": "First "}, "done": False}),
            json.dumps({"message": {"content": "second."}, "done": True}),
        ]
    )
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, text=stream_content)
    )

    chunks = [c async for c in client.stream_chat(messages=[])]
    assert chunks == ["First ", "second."]


@pytest.mark.asyncio
@respx.mock
async def test_ollama_client_check_health() -> None:
    client = OllamaClient(base_url="http://mock-ollama:11434", model="qwen2.5-coder:7b")

    # Target model present
    respx.get("http://mock-ollama:11434/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5-coder:7b"}, {"name": "llama3:latest"}]},
        )
    )
    is_healthy, models = await client.check_health()
    assert is_healthy is True
    assert "qwen2.5-coder:7b" in models

    # Target model absent
    respx.get("http://mock-ollama:11434/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={"models": [{"name": "mistral:latest"}]},
        )
    )
    is_healthy_absent, _ = await client.check_health()
    assert is_healthy_absent is False
