"""Integration tests for conversations REST API endpoints."""

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.store.database import (
    close_app_db,
    create_conversation,
    create_turn,
    init_app_db,
    update_turn,
)


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path) -> Path:
    """Initialize test SQLite database for each test."""
    await close_app_db()
    db_path = tmp_path / "test_api_conv.db"
    await init_app_db(str(db_path))
    yield db_path
    await close_app_db()


@pytest.mark.asyncio
async def test_list_conversations_empty() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_and_get_conversation_detail() -> None:
    conv = await create_conversation(title="Test Analytics Thread")
    turn = await create_turn(
        conversation_id=conv.id,
        question="How many products are in stock?",
        turn_id="turn-stock-1",
    )
    await update_turn(
        turn_id=turn.id,
        sql="SELECT count(*) as total FROM products",
        columns_json=json.dumps(["total"]),
        rows_json=json.dumps([[150]]),
        row_count=1,
        truncated=False,
        answer="There are 150 products in stock.",
        status="done",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List conversations
        list_resp = await client.get("/api/conversations")
        assert list_resp.status_code == 200
        summaries = list_resp.json()
        assert len(summaries) == 1
        assert summaries[0]["id"] == conv.id
        assert summaries[0]["title"] == "Test Analytics Thread"
        assert "updated_at" in summaries[0]

        # 2. Get conversation detail
        detail_resp = await client.get(f"/api/conversations/{conv.id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == conv.id
        assert detail["title"] == "Test Analytics Thread"
        assert len(detail["turns"]) == 1

        turn_data = detail["turns"][0]
        assert turn_data["id"] == "turn-stock-1"
        assert turn_data["question"] == "How many products are in stock?"
        assert turn_data["sql"] == "SELECT count(*) as total FROM products"
        assert turn_data["columns"] == ["total"]
        assert turn_data["rows"] == [[150]]
        assert turn_data["row_count"] == 1
        assert turn_data["truncated"] is False
        assert turn_data["answer"] == "There are 150 products in stock."
        assert turn_data["status"] == "done"


@pytest.mark.asyncio
async def test_get_conversation_not_found() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversations/non-existent-id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_conversation() -> None:
    conv = await create_conversation(title="Thread to delete")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Delete exists -> 204
        del_resp = await client.delete(f"/api/conversations/{conv.id}")
        assert del_resp.status_code == 204

        # Verify not found now
        get_resp = await client.get(f"/api/conversations/{conv.id}")
        assert get_resp.status_code == 404

        # Delete non-existent -> 404
        del_again = await client.delete(f"/api/conversations/{conv.id}")
        assert del_again.status_code == 404
