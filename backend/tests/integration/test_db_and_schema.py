"""Integration tests for target database connectivity, schema introspection, and API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import check_db_health
from app.core.schema import introspect_schema
from app.main import app


@pytest.mark.asyncio
async def test_db_connectivity() -> None:
    """Verify target DB connectivity and MySQL 9.0 version."""
    is_healthy, version = await check_db_health()
    assert is_healthy is True
    assert "9.0" in version


@pytest.mark.asyncio
async def test_schema_introspection() -> None:
    """Verify schema introspection against seeded ecommerce DB."""
    schema = await introspect_schema()
    table_names = schema.table_names

    expected_tables = ["categories", "order_items", "orders", "payments", "products", "users"]
    for expected in expected_tables:
        assert expected in table_names

    # Check users table
    users = schema.get_table("users")
    assert users is not None
    user_cols = {c.name: c for c in users.columns}
    assert "id" in user_cols
    assert user_cols["id"].is_pk is True
    assert "status" in user_cols
    # Verify sample values on status column
    assert "active" in user_cols["status"].sample_values

    # Check products table FK
    products = schema.get_table("products")
    assert products is not None
    prod_cols = {c.name: c for c in products.columns}
    assert prod_cols["category_id"].is_fk is True
    assert prod_cols["category_id"].fk_target == "categories.id"

    # Check prompt output
    prompt = schema.to_prompt()
    assert "users(" in prompt
    assert "[PK]" in prompt
    assert "[FK→categories.id]" in prompt


@pytest.mark.asyncio
async def test_api_schema_endpoint() -> None:
    """Verify GET /api/schema and POST /api/schema/refresh endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /api/schema
        resp = await client.get("/api/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "tables" in data
        assert len(data["tables"]) == 6

        # POST /api/schema/refresh
        refresh_resp = await client.post("/api/schema/refresh")
        assert refresh_resp.status_code == 200
        refresh_data = refresh_resp.json()
        assert refresh_data == {"tables": 6}


@pytest.mark.asyncio
async def test_api_health_real_db() -> None:
    """Verify GET /api/health against real DB returns db=ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["db"] == "ok"
        assert "9.0" in data["db_version"]
        assert data["model"] == "qwen2.5-coder:7b"
