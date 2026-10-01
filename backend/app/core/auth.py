"""API key authentication, rate limiting, and daily quota enforcement for /v1 endpoints."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.store.database import (
    find_api_key,
    get_api_usage_today,
    record_api_usage,
    save_api_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.store.models import ApiKey

KEY_PREFIX = "nl_live_"
VALID_SCOPES = {"query", "admin"}
DEFAULT_RATE_LIMIT_PER_MINUTE = 60

# In-memory sliding window for rate limiting: key_hash -> list of timestamps (seconds)
_rate_limit_records: dict[str, list[float]] = defaultdict(list)

_bearer_scheme = HTTPBearer(auto_error=False)


def generate_api_key() -> str:
    """Generate a high-entropy secret API key with nl_live_ prefix."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(24)}"


def hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256 for secure storage and lookup."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def issue_api_key(
    label: str,
    scope: str = "query",
    daily_quota: int = 0,
) -> tuple[str, ApiKey]:
    """Issue a new API key, store its hash in SQLite, and return (plaintext_key, api_key_model)."""
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Must be one of: {sorted(VALID_SCOPES)}")
    plaintext_key = generate_api_key()
    key_hash = hash_api_key(plaintext_key)
    model = await save_api_key(
        key_hash=key_hash,
        label=label,
        scope=scope,
        daily_quota=daily_quota,
    )
    return plaintext_key, model


def check_rate_limit(key_hash: str, limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE) -> bool:
    """Check and record request timestamp in sliding 60-second window. Returns True if in limit."""
    now = time.monotonic()
    window_start = now - 60.0
    timestamps = _rate_limit_records[key_hash]

    # Filter out timestamps older than 60 seconds
    valid_timestamps = [t for t in timestamps if t > window_start]
    if len(valid_timestamps) >= limit_per_minute:
        _rate_limit_records[key_hash] = valid_timestamps
        return False

    valid_timestamps.append(now)
    _rate_limit_records[key_hash] = valid_timestamps
    return True


def reset_rate_limits() -> None:
    """Clear in-memory rate limiting state (useful in test teardown)."""
    _rate_limit_records.clear()


def require_api_key(required_scope: str = "query") -> Callable[..., Any]:
    """FastAPI dependency factory enforcing API key auth, scope, rate limits, and quota."""

    async def _dependency(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
        bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    ) -> ApiKey:
        token: str | None = None
        if x_api_key:
            token = x_api_key.strip()
        elif bearer and bearer.credentials:
            token = bearer.credentials.strip()

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "missing_api_key",
                    "message": "API key required in X-API-Key or Authorization header",
                },
            )

        key_hash = hash_api_key(token)
        api_key = await find_api_key(key_hash)

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": "invalid_api_key", "message": "Invalid or revoked API key"},
            )

        # Scope check
        if required_scope == "admin" and api_key.scope != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_scope",
                    "message": "Admin scope required for this endpoint",
                },
            )

        # Rate limit check (60 req/min)
        if not check_rate_limit(key_hash, DEFAULT_RATE_LIMIT_PER_MINUTE):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded ({DEFAULT_RATE_LIMIT_PER_MINUTE} req/min)",
                },
            )

        # Quota check
        if api_key.daily_quota > 0:
            usage_today = await get_api_usage_today(key_hash)
            if usage_today >= api_key.daily_quota:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "quota_exceeded",
                        "message": (
                            f"Daily quota of {api_key.daily_quota} requests exceeded for today"
                        ),
                    },
                )

        # Record usage
        await record_api_usage(key_hash)
        return api_key

    return _dependency
