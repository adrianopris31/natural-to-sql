"""LLM client protocol and implementations for Ollama and test fakes."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from app.errors import LLMError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for language model client operations."""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Execute chat completion returning structured JSON matching schema."""
        ...

    def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Execute chat completion streaming text tokens asynchronously."""
        ...

    async def check_health(self) -> tuple[bool, list[str]]:
        """Check LLM service availability and return (is_healthy, available_models)."""
        ...


class OllamaClient:
    """Async Ollama client implementing LLMClient protocol."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
        num_ctx: int = 8192,
        timeout_sec: float = 60.0,
        keep_alive: str = "10m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.timeout_sec = timeout_sec
        self.keep_alive = keep_alive

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Execute structured JSON completion using Ollama's format parameter."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": self.num_ctx,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()

            raw_content = data.get("message", {}).get("content", "")
            if not raw_content:
                raise LLMError("Ollama returned an empty response")

            parsed = json.loads(raw_content)
            if not isinstance(parsed, dict):
                raise LLMError(f"Expected JSON object from Ollama, got {type(parsed).__name__}")
            return parsed

        except httpx.TimeoutException as exc:
            logger.warning("Ollama call timed out after %ss", self.timeout_sec)
            raise LLMError(f"Ollama request timed out after {self.timeout_sec}s") from exc
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("Ollama call failed: %s", exc)
            raise LLMError(f"Ollama request failed: {exc}") from exc

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream response tokens from Ollama /api/chat."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": self.num_ctx,
            },
        }

        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout_sec) as client,
                client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp,
            ):
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
        except (httpx.HTTPError, TimeoutError) as exc:
            logger.warning("Ollama streaming failed: %s", exc)
            raise LLMError(f"Ollama streaming failed: {exc}") from exc

    async def check_health(self) -> tuple[bool, list[str]]:
        """Query /api/tags to check connection and model presence."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    base_target = self.model.split(":")[0]
                    is_available = any(self.model in m or base_target in m for m in models)
                    return is_available, models
                return False, []
        except Exception as exc:
            logger.debug("Ollama health check unreachable: %s", exc)
            return False, []


class FakeLLMClient:
    """Test double for LLMClient protocol."""

    def __init__(
        self,
        json_responses: list[dict[str, Any]] | None = None,
        stream_responses: list[list[str]] | None = None,
        health_status: bool = True,
        available_models: list[str] | None = None,
    ) -> None:
        self.json_responses: list[dict[str, Any]] = list(json_responses or [])
        self.stream_responses: list[list[str]] = list(stream_responses or [])
        self.health_status = health_status
        self.available_models = list(available_models or ["qwen2.5-coder:7b"])
        self.recorded_chat_calls: list[dict[str, Any]] = []
        self.recorded_stream_calls: list[dict[str, Any]] = []

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Return next canned JSON response or empty dict."""
        self.recorded_chat_calls.append(
            {"messages": messages, "schema": schema, "temperature": temperature}
        )
        if self.json_responses:
            return self.json_responses.pop(0)
        return {
            "sql": "SELECT 1",
            "reasoning": "Default fake response",
            "needs_clarification": False,
            "clarification_question": None,
        }

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream next canned token list."""
        self.recorded_stream_calls.append({"messages": messages, "temperature": temperature})
        chunks = (
            self.stream_responses.pop(0)
            if self.stream_responses
            else ["The ", "result ", "is ", "42."]
        )
        for chunk in chunks:
            yield chunk

    async def check_health(self) -> tuple[bool, list[str]]:
        """Return configured fake health status and models."""
        return self.health_status, self.available_models
