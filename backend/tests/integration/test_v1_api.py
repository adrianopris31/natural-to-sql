"""Integration tests for /v1 external REST API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.query import get_v1_llm_client
from app.core.auth import issue_api_key, reset_rate_limits
from app.integrations.knowledge_bot import DocsAnswer, DocsSource
from app.llm.client import FakeLLMClient
from app.main import app
from app.store.database import close_app_db, init_app_db

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture(autouse=True)
async def setup_test_env(tmp_path: Path) -> AsyncIterator[None]:
    """Ensure clean isolated database and rate limit state for each test."""
    await close_app_db()
    db_file = tmp_path / "test_v1.db"
    await init_app_db(str(db_file))
    reset_rate_limits()
    app.dependency_overrides.clear()
    yield
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
async def admin_key() -> str:
    key, _ = await issue_api_key(label="Admin Key", scope="admin")
    return key


@pytest.fixture
async def query_key() -> str:
    key, _ = await issue_api_key(label="Query Key", scope="query")
    return key


def _canned_draft(*sqls: str) -> dict[str, Any]:
    return {
        "queries": [{"sql": s, "purpose": f"q{i}"} for i, s in enumerate(sqls)],
        "reasoning": "v1 test reasoning",
        "needs_clarification": False,
        "clarification_question": None,
    }


async def test_health_endpoint(api_client: AsyncClient) -> None:
    resp = await api_client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "target_db" in data
    assert data["version"] == "1.0.0"


async def test_key_management_flow(api_client: AsyncClient, admin_key: str, query_key: str) -> None:
    # 1. Query key cannot create keys (403)
    resp = await api_client.post(
        "/v1/keys",
        headers={"X-API-Key": query_key},
        json={"label": "New Key", "scope": "query"},
    )
    assert resp.status_code == 403

    # 2. Admin key creates new query key (201)
    resp = await api_client.post(
        "/v1/keys",
        headers={"X-API-Key": admin_key},
        json={"label": "Production Worker", "scope": "query", "daily_quota": 500},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["key"].startswith("nl_live_")
    assert created["label"] == "Production Worker"
    prefix = created["key_hash_prefix"]

    # 3. Admin lists keys
    resp = await api_client.get(
        "/v1/keys",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    keys = resp.json()
    assert any(k["key_hash_prefix"] == prefix for k in keys)

    # 4. Admin revokes key
    resp = await api_client.delete(
        f"/v1/keys/{prefix}",
        headers={"X-API-Key": admin_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"

    # 5. Revoking again returns 404
    resp = await api_client.delete(
        f"/v1/keys/{prefix}",
        headers={"X-API-Key": admin_key},
    )
    assert resp.status_code == 404


async def test_admin_audit_endpoint(
    api_client: AsyncClient, admin_key: str, query_key: str
) -> None:
    # Query key forbidden from /v1/audit
    resp = await api_client.get("/v1/audit", headers={"X-API-Key": query_key})
    assert resp.status_code == 403

    # Admin key allowed
    resp = await api_client.get("/v1/audit", headers={"X-API-Key": admin_key})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_query_auth_failures(api_client: AsyncClient) -> None:
    # Missing key -> 401
    resp = await api_client.post("/v1/query", json={"question": "Show users"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "missing_api_key"

    # Invalid key -> 401
    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": "nl_live_bogus_key"},
        json={"question": "Show users"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"] == "invalid_api_key"


async def test_query_sql_write_intent_refusal(api_client: AsyncClient, query_key: str) -> None:
    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={"question": "DROP TABLE users;"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "refused"
    assert data["blocked"] is True
    assert "Not performed" in data["answer"]
    assert "read-only" in data["answer"]
    assert data["queries"] == []


async def test_query_sql_safe_auto_approve(api_client: AsyncClient, query_key: str) -> None:
    fake_client = FakeLLMClient(
        json_responses=[_canned_draft("SELECT 1 AS count")],
        stream_responses=[["Count ", "is ", "1."]],
    )
    app.dependency_overrides[get_v1_llm_client] = lambda: fake_client

    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={"question": "What is the count?", "auto_approve": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["mode"] == "sql"
    assert len(data["queries"]) == 1
    assert "SELECT 1 AS count" in data["queries"][0]["sql"]
    assert data["answer"] == "Count is 1."


async def test_query_sql_cartesian_join_blocked(api_client: AsyncClient, query_key: str) -> None:
    fake_client = FakeLLMClient(
        json_responses=[_canned_draft("SELECT * FROM users, orders")],
    )
    app.dependency_overrides[get_v1_llm_client] = lambda: fake_client

    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={"question": "Show all users and orders", "auto_approve": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["blocked"] is True
    assert data["code"] == "HIGH_RISK_QUERY"
    assert "high risk" in data["block_reason"]
    assert len(data["queries"]) == 1


async def test_query_sql_two_phase_approval(api_client: AsyncClient, query_key: str) -> None:
    fake_client = FakeLLMClient(
        json_responses=[_canned_draft("SELECT 2 AS val")],
        stream_responses=[["Value ", "is ", "2."]],
    )
    app.dependency_overrides[get_v1_llm_client] = lambda: fake_client

    # 1. auto_approve=False returns awaiting_approval
    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={"question": "Calculate value", "auto_approve": False},
    )
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["status"] == "awaiting_approval"
    turn_id = preview["turn_id"]

    # 2. Approve turn
    resp = await api_client.post(
        f"/v1/query/{turn_id}/approve",
        headers={"X-API-Key": query_key},
        json={"queries": None},
    )
    assert resp.status_code == 200
    approved = resp.json()
    assert approved["status"] == "done"
    assert approved["answer"] == "Value is 2."


async def test_query_sql_cancellation(api_client: AsyncClient, query_key: str) -> None:
    fake_client = FakeLLMClient(
        json_responses=[_canned_draft("SELECT 3 AS val")],
    )
    app.dependency_overrides[get_v1_llm_client] = lambda: fake_client

    resp = await api_client.post(
        "/v1/query",
        headers={"X-API-Key": query_key},
        json={"question": "Calculate value", "auto_approve": False},
    )
    turn_id = resp.json()["turn_id"]

    # Cancel turn
    resp = await api_client.post(
        f"/v1/query/{turn_id}/cancel",
        headers={"X-API-Key": query_key},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Cancelling again returns 404
    resp = await api_client.post(
        f"/v1/query/{turn_id}/cancel",
        headers={"X-API-Key": query_key},
    )
    assert resp.status_code == 404


async def test_query_docs_mode(api_client: AsyncClient, query_key: str) -> None:
    mock_docs_answer = DocsAnswer(
        answer="Jira ticket PROJ-123 is currently in progress.",
        sources=[
            DocsSource(
                id="doc_1",
                title="PROJ-123",
                url="https://jira.example.com/browse/PROJ-123",
                source_type="jira",
                score=0.95,
            )
        ],
        refused=False,
        model="gpt-4o-mini",
    )

    with patch("app.services.query.ask_docs", new_callable=AsyncMock) as mock_ask:
        mock_ask.return_value = mock_docs_answer

        resp = await api_client.post(
            "/v1/query",
            headers={"X-API-Key": query_key},
            json={"question": "What is status of PROJ-123?", "mode": "docs"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "docs"
        assert data["status"] == "done"
        assert "PROJ-123 is currently in progress" in data["answer"]
        assert len(data["sources"]) == 1
        assert data["sources"][0]["title"] == "PROJ-123"
