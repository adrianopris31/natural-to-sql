"""API endpoints for database schema metadata and refresh."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.schema import TableModel, get_schema_cache

router = APIRouter(prefix="/api/schema", tags=["schema"])


class SchemaResponse(BaseModel):
    """Schema response matching frontend expectations."""

    tables: list[TableModel]
    database: str | None = None


class SchemaRefreshResponse(BaseModel):
    """Response returned upon refreshing schema."""

    tables: int


@router.get("", response_model=SchemaResponse)
async def get_schema(database: str | None = None) -> SchemaResponse:
    """Return introspected schema metadata for the UI sidebar."""
    cache = get_schema_cache()
    try:
        schema = await cache.get_schema(db_name=database)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_database", "message": str(val_err)},
        ) from val_err
    return SchemaResponse(tables=schema.tables, database=schema.database)


@router.post("/refresh", response_model=SchemaRefreshResponse)
async def refresh_schema(database: str | None = None) -> SchemaRefreshResponse:
    """Trigger re-introspection and return refreshed table count."""
    cache = get_schema_cache()
    try:
        schema = await cache.get_schema(db_name=database, force_refresh=True)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_database", "message": str(val_err)},
        ) from val_err
    return SchemaRefreshResponse(tables=len(schema.tables))
