"""Integration tests for Settings API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import app


@pytest.mark.asyncio
async def test_settings_api_disabled_returns_404() -> None:
    """When ENABLE_SETTINGS_UI is False, all settings endpoints must return 404."""
    disabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=False,
    )
    transport = ASGITransport(app=app)
    with patch("app.api.settings.get_settings", return_value=disabled_settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.get("/api/settings/sources")
            assert resp1.status_code == 404
            assert resp1.json()["detail"] == "Settings UI is disabled"

            resp2 = await client.put(
                "/api/settings/sources/jira",
                json={"base_url": "https://test.atlassian.net", "auth_mode": "token"},
            )
            assert resp2.status_code == 404
            assert resp2.json()["detail"] == "Settings UI is disabled"

            resp3 = await client.put(
                "/api/settings/sources/slack",
                json={"channels": ["general"]},
            )
            assert resp3.status_code == 404
            assert resp3.json()["detail"] == "Settings UI is disabled"

            resp4 = await client.post("/api/settings/sources/jira/test", json={})
            assert resp4.status_code == 404
            assert resp4.json()["detail"] == "Settings UI is disabled"

            resp5 = await client.delete("/api/settings/sources/jira")
            assert resp5.status_code == 404
            assert resp5.json()["detail"] == "Settings UI is disabled"

            resp6 = await client.post("/api/settings/refresh")
            assert resp6.status_code == 404
            assert resp6.json()["detail"] == "Settings UI is disabled"


@pytest.mark.asyncio
async def test_settings_api_non_localhost_returns_403() -> None:
    """When client is not localhost, endpoints must return 403."""
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
    )
    # Simulate client connecting from remote IP
    transport = ASGITransport(app=app, client=("192.168.1.55", 54321))
    with patch("app.api.settings.get_settings", return_value=enabled_settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/sources")
            assert resp.status_code == 403
            assert "only be accessed from localhost" in resp.json()["detail"]

            resp_put = await client.put(
                "/api/settings/sources/jira",
                json={"base_url": "https://test.atlassian.net", "auth_mode": "token"},
            )
            assert resp_put.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_localhost_get_sources_success() -> None:
    """GET /api/settings/sources returns 200 with list of sources."""
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.get("http://127.0.0.1:8100/admin/sources").respond(
        status_code=200,
        json={
            "sources": [
                {
                    "source": "jira",
                    "configured": True,
                    "origin": "stored",
                    "fields": {"base_url": "https://jira.corp.com"},
                    "secret_hint": None,
                    "last_refresh": None,
                    "last_status": "ok",
                },
                {
                    "source": "slack",
                    "configured": True,
                    "origin": "env",
                    "fields": {"channels": ["#alerts"]},
                    "secret_hint": None,
                    "last_refresh": None,
                    "last_status": "ok",
                },
            ]
        },
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/sources")

    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert len(data["sources"]) == 2
    assert data["sources"][0]["source"] == "jira"
    assert data["sources"][0]["secret_hint"] is None
    assert data["sources"][1]["source"] == "slack"


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_put_jira_source_success_and_never_echoes_secret() -> None:
    """PUT /api/settings/sources/jira sends token upstream but never echoes it back."""
    secret_token = "jira_super_secret_pat_998877"
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.put("http://127.0.0.1:8100/admin/sources/jira").respond(
        status_code=200,
        json={
            "source": "jira",
            "configured": True,
            "origin": "stored",
            "fields": {
                "base_url": "https://test.atlassian.net",
                "auth_mode": "token",
                "email": "dev@test.com",
            },
            "secret_hint": None,
            "last_refresh": None,
            "last_status": None,
        },
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/settings/sources/jira",
                json={
                    "base_url": "https://test.atlassian.net",
                    "auth_mode": "token",
                    "email": "dev@test.com",
                    "api_token": secret_token,
                    "project_key": "ENG",
                },
            )

    assert resp.status_code == 200
    resp_text = resp.text
    # Secret must never be in the response
    assert secret_token not in resp_text
    data = resp.json()
    assert data["source"] == "jira"
    assert data["configured"] is True
    assert data["secret_hint"] is None


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_put_slack_source_success_and_never_echoes_secret() -> None:
    """PUT /api/settings/sources/slack sends token upstream but never echoes it back."""
    slack_token = "xoxb-987654321-abcdefg"
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.put("http://127.0.0.1:8100/admin/sources/slack").respond(
        status_code=200,
        json={
            "source": "slack",
            "configured": True,
            "origin": "stored",
            "fields": {"channels": ["random", "dev"]},
            "secret_hint": None,
            "last_refresh": None,
            "last_status": None,
        },
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/settings/sources/slack",
                json={
                    "bot_token": slack_token,
                    "channels": ["random", "dev"],
                },
            )

    assert resp.status_code == 200
    resp_text = resp.text
    assert slack_token not in resp_text
    data = resp.json()
    assert data["source"] == "slack"
    assert data["configured"] is True


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_test_source_endpoints() -> None:
    """POST /api/settings/sources/{source}/test returns 200 SourceTestResult."""
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.post("http://127.0.0.1:8100/admin/sources/jira/test").respond(
        status_code=200,
        json={"ok": True, "message": "Jira connection successful"},
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/settings/sources/jira/test",
                json={"base_url": "https://jira.com", "api_token": "secret"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["message"] == "Jira connection successful"

    # Test unknown source returns 404
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_unknown = await client.post("/api/settings/sources/notfound/test")
            assert resp_unknown.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_delete_source_success() -> None:
    """DELETE /api/settings/sources/{source} returns 204."""
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.delete("http://127.0.0.1:8100/admin/sources/jira").respond(status_code=204)

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/api/settings/sources/jira")
            assert resp.status_code == 204

            # Unknown source returns 404
            resp_unknown = await client.delete("/api/settings/sources/github")
            assert resp_unknown.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_settings_api_refresh_success() -> None:
    """POST /api/settings/refresh returns 200."""
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )
    respx.post("http://127.0.0.1:8100/admin/refresh").respond(
        status_code=200,
        json={"ok": True, "message": "Sync complete"},
    )

    transport = ASGITransport(app=app)
    with (
        patch("app.api.settings.get_settings", return_value=enabled_settings),
        patch("app.integrations.knowledge_bot.get_settings", return_value=enabled_settings),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/settings/refresh?full=true")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_settings_api_422_never_echoes_secret_input() -> None:
    """When a validation error occurs on /api/settings, secrets are never echoed back in 422."""
    secret_token = "ultra_sensitive_token_do_not_leak_422"
    enabled_settings = Settings(
        _env_file=None,
        ENABLE_SETTINGS_UI=True,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_ADMIN_KEY="admin_key",
    )

    transport = ASGITransport(app=app)
    with patch("app.api.settings.get_settings", return_value=enabled_settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send invalid body: base_url is invalid type (integer), but has api_token
            resp = await client.put(
                "/api/settings/sources/jira",
                json={
                    "base_url": 12345,
                    "auth_mode": "invalid_mode",
                    "api_token": secret_token,
                },
            )

    assert resp.status_code == 422
    resp_text = resp.text
    # Secret MUST NOT appear anywhere in the 422 response body!
    assert secret_token not in resp_text
    data = resp.json()
    assert "detail" in data
    # Confirm "input" field is not included in the error items
    for err in data["detail"]:
        assert "input" not in err
