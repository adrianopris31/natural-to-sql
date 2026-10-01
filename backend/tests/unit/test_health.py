"""Unit tests for the health check endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.client import FakeLLMClient
from app.main import app


@pytest.mark.asyncio
async def test_health_check_all_ok() -> None:
    transport = ASGITransport(app=app)
    with (
        patch("app.main.check_db_health", new_callable=AsyncMock) as mock_db,
        patch("app.main.get_llm_client") as mock_get_client,
        patch("app.main.docs_health", new_callable=AsyncMock) as mock_docs_health,
    ):
        mock_db.return_value = (True, "9.0.1")
        mock_get_client.return_value = FakeLLMClient(health_status=True)
        mock_docs_health.return_value = {"configured": True, "reachable": True}

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "db": "ok",
        "ollama": "ok",
        "model": "qwen2.5-coder:7b",
        "db_version": "9.0.1",
        "knowledge_bot": {"configured": True, "reachable": True},
    }


@pytest.mark.asyncio
async def test_health_check_ollama_down() -> None:
    transport = ASGITransport(app=app)
    with (
        patch("app.main.check_db_health", new_callable=AsyncMock) as mock_db,
        patch("app.main.get_llm_client") as mock_get_client,
        patch("app.main.docs_health", new_callable=AsyncMock) as mock_docs_health,
    ):
        mock_db.return_value = (True, "9.0.1")
        mock_get_client.return_value = FakeLLMClient(health_status=False)
        mock_docs_health.return_value = {"configured": False, "reachable": False}

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "db": "ok",
        "ollama": "error",
        "model": "qwen2.5-coder:7b",
        "db_version": "9.0.1",
        "knowledge_bot": {"configured": False, "reachable": False},
    }


@pytest.mark.asyncio
async def test_health_check_knowledge_bot_unreachable_does_not_fail() -> None:
    transport = ASGITransport(app=app)
    with (
        patch("app.main.check_db_health", new_callable=AsyncMock) as mock_db,
        patch("app.main.get_llm_client") as mock_get_client,
        patch("app.main.docs_health", new_callable=AsyncMock) as mock_docs_health,
    ):
        mock_db.return_value = (True, "9.0.1")
        mock_get_client.return_value = FakeLLMClient(health_status=True)
        mock_docs_health.return_value = {"configured": True, "reachable": False}

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "db": "ok",
        "ollama": "ok",
        "model": "qwen2.5-coder:7b",
        "db_version": "9.0.1",
        "knowledge_bot": {"configured": True, "reachable": False},
    }

