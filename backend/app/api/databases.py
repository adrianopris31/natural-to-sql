"""API endpoints for database discovery and dynamic database switching."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.db import list_available_databases

router = APIRouter(prefix="/api/databases", tags=["databases"])


class DatabaseItem(BaseModel):
    """Available database item for UI switcher."""

    id: str
    name: str
    is_default: bool


@router.get("", response_model=list[DatabaseItem])
async def get_databases() -> list[DatabaseItem]:
    """List discovered and configured databases for dynamic switching."""
    databases = await list_available_databases()
    return [DatabaseItem.model_validate(db) for db in databases]
