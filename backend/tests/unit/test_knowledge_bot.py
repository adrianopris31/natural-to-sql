"""Unit tests for knowledge-bot integration client."""

import logging
from unittest.mock import patch

import httpx
import pytest
import respx

from app.config import Settings
from app.errors import (
    KnowledgeBotAuthError,
    KnowledgeBotError,
    KnowledgeBotNotConfiguredError,
    KnowledgeBotQuotaError,
    KnowledgeBotUnreachableError,
    KnowledgeBotUpstreamError,
)
from app.integrations.knowledge_bot import ask_docs, docs_health


@pytest.mark.asyncio
async def test_ask_docs_not_configured() -> None:
    settings = Settings(_env_file=None, KNOWLEDGE_BOT_API_KEY="")
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotNotConfiguredError) as exc_info:
            await ask_docs("What is in the docs?")
        assert "not configured" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_success() -> None:
    test_key = "kb_live_secret12345"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY=test_key,
        KNOWLEDGE_BOT_TIMEOUT_SEC=10.0,
    )
    route = respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": "Here is the summary of Jira ticket PROJ-123.",
            "sources": [
                {
                    "id": "PROJ-123",
                    "source_type": "jira",
                    "title": "Fix login bug",
                    "url": "https://jira.example.com/browse/PROJ-123",
                    "score": 0.95,
                }
            ],
            "refused": False,
            "model": "gpt-4o",
            "filter": "jira",
            "documents_searched": 15,
        },
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        result = await ask_docs("jira: login bug")

    assert route.called
    assert route.calls.last.request.headers.get("x-api-key") == test_key
    assert result.answer == "Here is the summary of Jira ticket PROJ-123."
    assert len(result.sources) == 1
    assert result.sources[0].id == "PROJ-123"
    assert result.sources[0].source_type == "jira"
    assert result.sources[0].title == "Fix login bug"
    assert result.refused is False
    assert result.documents_searched == 15


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_refused_normal_200() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": (
                "The retrieved documents do not contain information about Kubernetes cluster setup."
            ),
            "sources": [],
            "refused": True,
            "model": "gpt-4o",
            "filter": "",
            "documents_searched": 42,
        },
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        result = await ask_docs("How do I set up k8s?")

    assert result.refused is True
    assert result.sources == []
    assert "not contain information" in result.answer


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status_code", [401, 403])
async def test_ask_docs_auth_failure(status_code: int) -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_badkey",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(status_code=status_code)

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotAuthError) as exc_info:
            await ask_docs("Question")
        assert "authentication failed" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_rate_limit_429() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(status_code=429)

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotQuotaError) as exc_info:
            await ask_docs("Question")
        assert "quota" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_upstream_llm_502() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(status_code=502)

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotUpstreamError) as exc_info:
            await ask_docs("Question")
        assert "upstream" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_server_error_500() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(status_code=500)

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotError) as exc_info:
            await ask_docs("Question")
        assert "500" in exc_info.value.user_message


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_timeout() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").mock(
        side_effect=httpx.TimeoutException("Read timed out")
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotUnreachableError) as exc_info:
            await ask_docs("Question")
        assert "timed out" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_ask_docs_unreachable_network() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotUnreachableError) as exc_info:
            await ask_docs("Question")
        assert "unreachable" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_api_key_never_leaks_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    secret_key = "kb_live_super_secret_token_never_leak"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY=secret_key,
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(status_code=401)

    with (
        caplog.at_level(logging.DEBUG),
        patch("app.integrations.knowledge_bot.get_settings", return_value=settings),
    ):
        try:
            await ask_docs("Some question")
        except Exception as exc:
            assert secret_key not in str(exc)
            if hasattr(exc, "user_message"):
                assert secret_key not in exc.user_message

    for record in caplog.records:
        assert secret_key not in record.message
        assert secret_key not in str(record.__dict__)


@pytest.mark.asyncio
async def test_docs_health_not_configured() -> None:
    settings = Settings(_env_file=None, KNOWLEDGE_BOT_API_KEY="")
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        health = await docs_health()
    assert health == {"configured": False, "reachable": False}


@pytest.mark.asyncio
@respx.mock
async def test_docs_health_configured_and_reachable() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    route = respx.get("http://127.0.0.1:8100/v1/health").respond(
        status_code=200,
        json={"ok": True, "label": "test", "scope": "public"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        health = await docs_health()

    assert route.called
    assert health == {"configured": True, "reachable": True}


@pytest.mark.asyncio
@respx.mock
async def test_docs_health_configured_but_unreachable() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_key",
    )
    respx.get("http://127.0.0.1:8100/v1/health").mock(side_effect=httpx.ConnectError("Failed"))

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        health = await docs_health()

    assert health == {"configured": True, "reachable": False}
