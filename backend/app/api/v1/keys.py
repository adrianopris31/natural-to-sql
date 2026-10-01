"""API key management and audit endpoints (/v1/keys, /v1/audit). Requires admin scope."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import issue_api_key, require_api_key
from app.store.database import list_api_keys, list_audit_entries, revoke_api_key

router = APIRouter(prefix="/v1", tags=["v1-admin"])


class CreateKeyRequest(BaseModel):
    """Payload to create a new API key."""

    label: str = Field(
        ..., min_length=1, max_length=100, description="Descriptive label for this key"
    )
    scope: Literal["query", "admin"] = Field("query", description="API scope permissions")
    daily_quota: int = Field(0, ge=0, description="Max requests per day (0 = unlimited)")


@router.post(
    "/keys",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_key("admin"))],
)
async def create_key(
    request: CreateKeyRequest,
) -> dict[str, Any]:
    """Issue a new API key with the requested scope and daily quota.

    The plaintext secret key is only displayed once upon creation.
    """
    plaintext_key, key_model = await issue_api_key(
        label=request.label,
        scope=request.scope,
        daily_quota=request.daily_quota,
    )
    return {
        "key": plaintext_key,
        "key_hash_prefix": key_model.key_hash[:12],
        "label": key_model.label,
        "scope": key_model.scope,
        "daily_quota": key_model.daily_quota,
        "created_at": key_model.created_at.isoformat(),
    }


@router.get("/keys", dependencies=[Depends(require_api_key("admin"))])
async def get_keys(
    include_revoked: bool = Query(False, description="Include revoked keys in results"),
) -> list[dict[str, Any]]:
    """List API keys with metadata (secrets are never stored or returned)."""
    return await list_api_keys(include_revoked=include_revoked)


@router.delete("/keys/{key_hash_prefix}", dependencies=[Depends(require_api_key("admin"))])
async def delete_key(
    key_hash_prefix: str,
) -> dict[str, Any]:
    """Revoke an active API key by its hash or prefix."""
    if len(key_hash_prefix) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_prefix",
                "message": "Key prefix must be at least 8 characters",
            },
        )
    revoked = await revoke_api_key(key_hash_prefix)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "API key not found or already revoked"},
        )
    return {"status": "revoked", "key_hash_prefix": key_hash_prefix}


@router.get("/audit", dependencies=[Depends(require_api_key("admin"))])
async def get_audit(
    limit: int = Query(200, ge=1, le=1000),
    turn_id: str | None = Query(None, description="Optional turn ID filter"),
) -> list[dict[str, Any]]:
    """Query recent SQL lifecycle audit log entries."""
    return await list_audit_entries(limit=limit, turn_id=turn_id)
