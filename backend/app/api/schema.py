"""API endpoints for database schema metadata and refresh."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.schema import TableModel, get_schema_cache

router = APIRouter(prefix="/api/schema", tags=["schema"])


class SchemaResponse(BaseModel):
    """Schema response matching frontend expectations."""

    tables: list[TableModel]


class SchemaRefreshResponse(BaseModel):
    """Response returned upon refreshing schema."""

    tables: int


@router.get("", response_model=SchemaResponse)
async def get_schema() -> SchemaResponse:
    """Return introspected schema metadata for the UI sidebar."""
    cache = get_schema_cache()
    schema = await cache.get_schema()
    return SchemaResponse(tables=schema.tables)


@router.post("/refresh", response_model=SchemaRefreshResponse)
async def refresh_schema() -> SchemaRefreshResponse:
    """Trigger re-introspection and return refreshed table count."""
    cache = get_schema_cache()
    schema = await cache.get_schema(force_refresh=True)
    return SchemaRefreshResponse(tables=len(schema.tables))
