"""Unit tests for knowledge_bot settings client functions."""

from __future__ import annotations

import logging
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.errors import (
    KnowledgeBotAuthError,
    KnowledgeBotError,
    KnowledgeBotNotConfiguredError,
    KnowledgeBotQuotaError,
    KnowledgeBotUnreachableError,
)
from app.integrations.knowledge_bot import (
    JiraSourceRequest,
    SlackSourceRequest,
    SourceItem,
    delete_source,
    fetch_sources,
    save_jira_source,
    save_slack_source,
    trigger_refresh,
)
from app.integrations.knowledge_bot import (
    test_source as kb_test_source,
)


@pytest.mark.asyncio
async def test_fetch_sources_not_configured() -> None:
    settings = Settings(_env_file=None, KNOWLEDGE_BOT_ADMIN_KEY="")
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotNotConfiguredError) as exc_info:
            await fetch_sources()
        assert "not configured" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sources_success() -> None:
    admin_key = "kb_live_adminkey12345"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY=admin_key,
    )
    route = respx.get("http://127.0.0.1:8100/admin/sources").respond(
        status_code=200,
        json={
            "sources": [
                {
                    "source": "jira",
                    "configured": True,
                    "origin": "stored",
                    "fields": {"base_url": "https://company.atlassian.net"},
                    "secret_hint": None,
                    "last_refresh": "2026-10-01T12:00:00Z",
                    "last_status": "ok",
                },
                {
                    "source": "slack",
                    "configured": False,
                    "origin": "none",
                    "fields": {},
                    "secret_hint": None,
                    "last_refresh": None,
                    "last_status": None,
                },
            ]
        },
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        sources = await fetch_sources()

    assert route.called
    assert route.calls.last.request.headers.get("x-api-key") == admin_key
    assert len(sources) == 2
    assert isinstance(sources[0], SourceItem)
    assert sources[0].source == "jira"
    assert sources[0].configured is True
    assert sources[0].origin == "stored"
    assert sources[1].source == "slack"
    assert sources[1].configured is False


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status_code", [401, 403])
async def test_fetch_sources_auth_error(status_code: int) -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="bad_admin_key",
    )
    respx.get("http://127.0.0.1:8100/admin/sources").respond(
        status_code=status_code,
        json={"detail": "Admin permission required"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotAuthError) as exc_info:
            await fetch_sources()
        assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sources_quota_error() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="key",
    )
    respx.get("http://127.0.0.1:8100/admin/sources").respond(
        status_code=429,
        json={"detail": "Too many requests"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotQuotaError) as exc_info:
            await fetch_sources()
        assert exc_info.value.status_code == 429


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sources_unreachable() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="key",
    )
    respx.get("http://127.0.0.1:8100/admin/sources").mock(
        side_effect=httpx.ConnectError("Failed to connect")
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotUnreachableError) as exc_info:
            await fetch_sources()
        assert exc_info.value.status_code == 503


@pytest.mark.asyncio
@respx.mock
async def test_save_jira_source_success() -> None:
    admin_key = "admin_secret_key"
    token_secret = "jira_api_token_value_xyz"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY=admin_key,
    )
    route = respx.put("http://127.0.0.1:8100/admin/sources/jira").respond(
        status_code=200,
        json={
            "source": "jira",
            "configured": True,
            "origin": "stored",
            "fields": {
                "base_url": "https://test.atlassian.net",
                "auth_mode": "token",
                "email": "dev@test.com",
                "project_key": "ENG",
            },
            "secret_hint": None,
            "last_refresh": None,
            "last_status": None,
        },
    )

    req = JiraSourceRequest(
        base_url="https://test.atlassian.net",
        auth_mode="token",
        email="dev@test.com",
        api_token=SecretStr(token_secret),
        project_key="ENG",
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        item = await save_jira_source(req)

    assert route.called
    assert route.calls.last.request.headers.get("x-api-key") == admin_key
    # Request body sent to KB must contain unwrapped token string
    req_json = route.calls.last.request.read().decode("utf-8")
    assert token_secret in req_json

    assert item.source == "jira"
    assert item.configured is True
    assert item.secret_hint is None


@pytest.mark.asyncio
@respx.mock
async def test_save_slack_source_success() -> None:
    admin_key = "admin_key_slack"
    bot_token = "xoxb-123456789-abcdef"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY=admin_key,
    )
    route = respx.put("http://127.0.0.1:8100/admin/sources/slack").respond(
        status_code=200,
        json={
            "source": "slack",
            "configured": True,
            "origin": "stored",
            "fields": {
                "channels": ["general", "eng"],
                "days_back": 30,
            },
            "secret_hint": None,
            "last_refresh": None,
            "last_status": None,
        },
    )

    req = SlackSourceRequest(
        bot_token=SecretStr(bot_token),
        channels=["general", "eng"],
        days_back=30,
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        item = await save_slack_source(req)

    assert route.called
    assert route.calls.last.request.headers.get("x-api-key") == admin_key
    req_json = route.calls.last.request.read().decode("utf-8")
    assert bot_token in req_json
    assert item.source == "slack"
    assert item.configured is True


@pytest.mark.asyncio
@respx.mock
async def test_test_source_jira_with_body() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    route = respx.post("http://127.0.0.1:8100/admin/sources/jira/test").respond(
        status_code=200,
        json={"ok": True, "message": "Jira connection verified"},
    )

    req = JiraSourceRequest(
        base_url="https://acme.atlassian.net",
        email="user@acme.com",
        api_token=SecretStr("my-token"),
        project_key="ACME",
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        res = await kb_test_source("jira", data=req)

    assert route.called
    assert res.ok is True
    assert res.message == "Jira connection verified"


@pytest.mark.asyncio
@respx.mock
async def test_test_source_slack_without_body() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    route = respx.post("http://127.0.0.1:8100/admin/sources/slack/test").respond(
        status_code=200,
        json={"ok": False, "message": "auth_test_failed: invalid_auth"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        res = await kb_test_source("slack", data=None)

    assert route.called
    assert res.ok is False
    assert "invalid_auth" in res.message


@pytest.mark.asyncio
async def test_test_source_unknown_source_error() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotError) as exc_info:
            await kb_test_source("not_a_source")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_delete_source_success() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    route = respx.delete("http://127.0.0.1:8100/admin/sources/jira").respond(status_code=204)

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        await delete_source("jira")

    assert route.called


@pytest.mark.asyncio
async def test_delete_source_unknown_source_error() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotError) as exc_info:
            await delete_source("invalid")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_trigger_refresh_success() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    route = respx.post("http://127.0.0.1:8100/admin/refresh").respond(
        status_code=200,
        json={"ok": True, "message": "Refresh complete: 15 documents indexed"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        result = await trigger_refresh(full=False)

    assert route.called
    assert result.get("ok") is True
    assert "Refresh complete" in result.get("message", "")


@pytest.mark.asyncio
@respx.mock
async def test_trigger_refresh_409_busy() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.post("http://127.0.0.1:8100/admin/refresh").respond(
        status_code=409,
        json={"detail": "A refresh is already running"},
    )

    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        with pytest.raises(KnowledgeBotError) as exc_info:
            await trigger_refresh()
        assert exc_info.value.status_code == 409
        assert "already running" in exc_info.value.user_message


@pytest.mark.asyncio
@respx.mock
async def test_admin_key_never_leaks_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    secret_admin_key = "kb_live_super_secret_admin_key_should_never_leak"
    secret_token = "jira_secret_token_12345"
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY=secret_admin_key,
    )
    respx.put("http://127.0.0.1:8100/admin/sources/jira").respond(
        status_code=401,
        json={"detail": "Unauthorized"},
    )

    req = JiraSourceRequest(
        base_url="https://test.atlassian.net",
        email="test@test.com",
        api_token=SecretStr(secret_token),
        project_key="TEST",
    )

    with (
        caplog.at_level(logging.DEBUG),
        patch("app.integrations.knowledge_bot.get_settings", return_value=settings),
    ):
        try:
            await save_jira_source(req)
        except Exception as exc:
            assert secret_admin_key not in str(exc)
            assert secret_token not in str(exc)
            if hasattr(exc, "user_message"):
                assert secret_admin_key not in exc.user_message
                assert secret_token not in exc.user_message

    for record in caplog.records:
        assert secret_admin_key not in record.message
        assert secret_token not in record.message
        assert secret_admin_key not in str(record.__dict__)
        assert secret_token not in str(record.__dict__)
