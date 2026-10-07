"""Integration tests for multi-database dynamic switching API endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.query import get_v1_llm_client
from app.core.auth import issue_api_key, reset_rate_limits
from app.llm.client import FakeLLMClient
from app.main import app
from app.services.chat import process_chat
from app.store.database import close_app_db, get_conversation, init_app_db

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path) -> AsyncIterator[Path]:
    """Initialize test SQLite database for each test."""
    await close_app_db()
    db_path = tmp_path / "test_api_databases.db"
    await init_app_db(str(db_path))
    reset_rate_limits()
    app.dependency_overrides.clear()
    yield db_path
    app.dependency_overrides.clear()
    await close_app_db()
    reset_rate_limits()


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    """Provide async HTTP client for the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def query_key() -> str:
    key, _ = await issue_api_key(label="Query Key", scope="query")
    return key


@pytest.mark.asyncio
async def test_get_databases_endpoint(api_client: AsyncClient) -> None:
    """Verify GET /api/databases returns database items with default database."""
    resp = await api_client.get("/api/databases")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    default_item = next((d for d in data if d["is_default"] is True), None)
    assert default_item is not None
    assert default_item["id"] == "ecommerce"
    assert default_item["name"] == "ecommerce"


@pytest.mark.asyncio
async def test_get_schema_with_database_param(api_client: AsyncClient) -> None:
    """Verify GET /api/schema with and without database query parameter."""
    # 1. Without database param (default database)
    resp = await api_client.get("/api/schema")
    assert resp.status_code == 200
    data = resp.json()
    assert "tables" in data
    assert len(data["tables"]) == 6
    assert data["database"] == "ecommerce"

    # 2. With valid database param
    resp2 = await api_client.get("/api/schema?database=ecommerce")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["database"] == "ecommerce"
    assert len(data2["tables"]) == 6

    # 3. With invalid database identifier -> 400
    resp_invalid = await api_client.get("/api/schema?database=invalid;drop")
    assert resp_invalid.status_code == 400
    assert resp_invalid.json()["detail"]["error"] == "invalid_database"


@pytest.mark.asyncio
async def test_refresh_schema_with_database_param(api_client: AsyncClient) -> None:
    """Verify POST /api/schema/refresh with database parameter."""
    resp = await api_client.post("/api/schema/refresh?database=ecommerce")
    assert resp.status_code == 200
    assert resp.json() == {"tables": 6}

    # Invalid database identifier -> 400
    resp_invalid = await api_client.post("/api/schema/refresh?database=bad`db")
    assert resp_invalid.status_code == 400
    assert resp_invalid.json()["detail"]["error"] == "invalid_database"


@pytest.mark.asyncio
async def test_chat_pipeline_records_database() -> None:
    """Verify process_chat persists the specified database on conversation and turn."""
    fake_client = FakeLLMClient(
        json_responses=[
            {
                "queries": [{"sql": "SELECT count(*) FROM users", "purpose": "count users"}],
                "reasoning": "test",
                "needs_clarification": False,
                "clarification_question": None,
            }
        ]
    )

    events: list[str] = []
    async for e in process_chat(
        message="How many users are there?",
        conversation_id=None,
        database="ecommerce",
        client=fake_client,
    ):
        events.append(e)

    # Preview event should be emitted
    assert any("event: preview\n" in e for e in events)

    # Find conversation_id from preview event
    conv_id = None
    for e in events:
        if "event: preview\n" in e:
            for line in e.strip().split("\n"):
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    conv_id = payload.get("conversation_id")

    assert conv_id is not None
    conv = await get_conversation(conv_id)
    assert conv is not None
    assert conv.database == "ecommerce"
    assert len(conv.turns) == 1
    assert conv.turns[0].database == "ecommerce"


@pytest.mark.asyncio
async def test_v1_query_with_database_param(api_client: AsyncClient, query_key: str) -> None:
    """Verify POST /v1/query propagates database parameter."""
    fake_client = FakeLLMClient(
        json_responses=[
            {
                "queries": [{"sql": "SELECT 1 AS ok", "purpose": "health check"}],
                "reasoning": "test",
                "needs_clarification": False,
                "clarification_question": None,
            }
        ],
        stream_responses=[["Everything ", "is ", "fine."]],
    )

    app.dependency_overrides[get_v1_llm_client] = lambda: fake_client
    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={
            "question": "Is the system ok?",
            "auto_approve": True,
            "database": "ecommerce",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"

    conv = await get_conversation(data["conversation_id"])
    assert conv is not None
    assert conv.database == "ecommerce"
    assert conv.turns[0].database == "ecommerce"
