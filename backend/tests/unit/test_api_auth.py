"""Unit tests for API key generation, hashing, database storage, rate limiting, and auth."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException

from app.core.auth import (
    KEY_PREFIX,
    check_rate_limit,
    generate_api_key,
    hash_api_key,
    issue_api_key,
    require_api_key,
    reset_rate_limits,
)
from app.store.database import (
    close_app_db,
    find_api_key,
    get_api_usage_today,
    init_app_db,
    list_api_keys,
    record_api_usage,
    revoke_api_key,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path) -> AsyncIterator[None]:
    """Ensure clean isolated SQLite database for each auth test."""
    await close_app_db()
    db_file = tmp_path / "test_auth.db"
    await init_app_db(str(db_file))
    reset_rate_limits()
    yield
    await close_app_db()
    reset_rate_limits()


def test_generate_and_hash_api_key() -> None:
    key1 = generate_api_key()
    key2 = generate_api_key()

    assert key1.startswith(KEY_PREFIX)
    assert key2.startswith(KEY_PREFIX)
    assert len(key1) >= 32
    assert key1 != key2

    hash1 = hash_api_key(key1)
    hash2 = hash_api_key(key2)
    assert len(hash1) == 64
    assert hash1 != hash2
    assert hash1 == hash_api_key(key1)


async def test_issue_and_find_api_key() -> None:
    plaintext, model = await issue_api_key(
        label="Test Integration",
        scope="query",
        daily_quota=100,
    )
    assert plaintext.startswith(KEY_PREFIX)
    assert model.label == "Test Integration"
    assert model.scope == "query"
    assert model.daily_quota == 100

    found = await find_api_key(model.key_hash)
    assert found is not None
    assert found.label == "Test Integration"

    with pytest.raises(ValueError, match="Invalid scope 'superadmin'"):
        await issue_api_key(label="Bad", scope="superadmin")


async def test_revoke_and_list_api_keys() -> None:
    _plaintext, model = await issue_api_key(label="To Revoke", scope="admin")
    prefix = model.key_hash[:12]

    # Listed before revocation
    keys = await list_api_keys(include_revoked=False)
    assert any(k["key_hash_prefix"] == prefix for k in keys)

    # Revoke
    revoked = await revoke_api_key(prefix)
    assert revoked is True

    # Not found without include_revoked
    assert await find_api_key(model.key_hash, include_revoked=False) is None
    found_revoked = await find_api_key(model.key_hash, include_revoked=True)
    assert found_revoked is not None
    assert found_revoked.revoked_at is not None

    # Revoking nonexistent prefix returns False
    assert await revoke_api_key("nonexistent_prefix") is False

    # Listed with include_revoked=True
    all_keys = await list_api_keys(include_revoked=True)
    revoked_entry = next(k for k in all_keys if k["key_hash_prefix"] == prefix)
    assert revoked_entry["revoked"] is True


def test_rate_limiting_sliding_window() -> None:
    test_hash = "mock_hash_12345"
    limit = 5

    for _ in range(limit):
        assert check_rate_limit(test_hash, limit_per_minute=limit) is True

    # Limit exceeded
    assert check_rate_limit(test_hash, limit_per_minute=limit) is False

    # Another hash is independent
    assert check_rate_limit("other_hash_67890", limit_per_minute=limit) is True

    # Reset clears tracking
    reset_rate_limits()
    assert check_rate_limit(test_hash, limit_per_minute=limit) is True


async def test_api_usage_and_quota_tracking() -> None:
    _, model = await issue_api_key(label="Quota Key", scope="query", daily_quota=10)
    key_hash = model.key_hash

    assert await get_api_usage_today(key_hash) == 0

    await record_api_usage(key_hash)
    await record_api_usage(key_hash)
    assert await get_api_usage_today(key_hash) == 2

    found = await find_api_key(key_hash)
    assert found is not None
    assert found.last_used_at is not None


async def test_require_api_key_dependency_success() -> None:
    plaintext, model = await issue_api_key(label="Query Key", scope="query")
    dep = require_api_key("query")

    # Pass via header
    auth_key = await dep(x_api_key=plaintext, bearer=None)
    assert auth_key.key_hash == model.key_hash

    # Pass via Bearer
    from fastapi.security import HTTPAuthorizationCredentials

    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=plaintext)
    auth_key_bearer = await dep(x_api_key=None, bearer=bearer)
    assert auth_key_bearer.key_hash == model.key_hash


async def test_require_api_key_dependency_errors() -> None:
    query_key, _ = await issue_api_key(label="Query Key", scope="query")
    dep_query = require_api_key("query")
    dep_admin = require_api_key("admin")

    # 1. Missing key -> 401
    with pytest.raises(HTTPException) as exc_info:
        await dep_query(x_api_key=None, bearer=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "missing_api_key"

    # 2. Invalid key -> 401
    with pytest.raises(HTTPException) as exc_info:
        await dep_query(x_api_key="nl_live_invalid_secret_key_12345", bearer=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "invalid_api_key"

    # 3. Insufficient scope -> 403
    with pytest.raises(HTTPException) as exc_info:
        await dep_admin(x_api_key=query_key, bearer=None)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "insufficient_scope"


async def test_require_api_key_quota_exceeded() -> None:
    plaintext, _model = await issue_api_key(label="Limited Key", scope="query", daily_quota=2)
    dep = require_api_key("query")

    # 1st request -> ok
    await dep(x_api_key=plaintext, bearer=None)
    # 2nd request -> ok
    await dep(x_api_key=plaintext, bearer=None)

    # 3rd request -> 429 quota_exceeded
    with pytest.raises(HTTPException) as exc_info:
        await dep(x_api_key=plaintext, bearer=None)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "quota_exceeded"
