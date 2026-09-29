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
    ):
        mock_db.return_value = (True, "9.0.1")
        mock_get_client.return_value = FakeLLMClient(health_status=True)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "db": "ok",
        "ollama": "ok",
        "model": "qwen2.5-coder:7b",
        "db_version": "9.0.1",
    }


@pytest.mark.asyncio
async def test_health_check_ollama_down() -> None:
    transport = ASGITransport(app=app)
    with (
        patch("app.main.check_db_health", new_callable=AsyncMock) as mock_db,
        patch("app.main.get_llm_client") as mock_get_client,
    ):
        mock_db.return_value = (True, "9.0.1")
        mock_get_client.return_value = FakeLLMClient(health_status=False)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "db": "ok",
        "ollama": "error",
        "model": "qwen2.5-coder:7b",
        "db_version": "9.0.1",
    }
