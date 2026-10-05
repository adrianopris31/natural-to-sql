"""Settings management API router for Jira and Slack sources."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.errors import KnowledgeBotError
from app.integrations.knowledge_bot import (
    JiraSourceRequest,
    SlackSourceRequest,
    SourceItem,
    SourceTestResult,
    delete_source,
    fetch_sources,
    save_jira_source,
    save_slack_source,
    test_source,
    trigger_refresh,
)

logger = logging.getLogger(__name__)

ALLOWED_LOCALHOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def require_settings_enabled() -> None:
    """Ensure Settings UI is enabled in server configuration."""
    settings = get_settings()
    if not settings.ENABLE_SETTINGS_UI:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settings UI is disabled",
        )


def require_localhost(request: Request) -> None:
    """Ensure request originates from localhost only."""
    client_host = request.client.host if request.client else None
    if not client_host or client_host not in ALLOWED_LOCALHOSTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: settings can only be accessed from localhost",
        )


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_settings_enabled), Depends(require_localhost)],
)


class SourcesResponse(BaseModel):
    """List of configured sources."""

    sources: list[SourceItem]


@router.get("/sources", response_model=SourcesResponse)
async def get_sources() -> SourcesResponse:
    """List all configured remote sources (Jira, Slack)."""
    try:
        items = await fetch_sources()
        return SourcesResponse(sources=items)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc


@router.put("/sources/jira", response_model=SourceItem)
async def update_jira_source(body: JiraSourceRequest) -> SourceItem:
    """Save Jira connection configuration."""
    try:
        return await save_jira_source(body)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc


@router.put("/sources/slack", response_model=SourceItem)
async def update_slack_source(body: SlackSourceRequest) -> SourceItem:
    """Save Slack connection configuration."""
    try:
        return await save_slack_source(body)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc


@router.post("/sources/{source}/test", response_model=SourceTestResult)
async def test_source_connection(
    source: str,
    body: dict[str, Any] | None = None,
) -> SourceTestResult:
    """Test connection to Jira or Slack."""
    clean_source = source.strip().lower()
    if clean_source not in ("jira", "slack"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No source called {source!r}",
        )
    try:
        return await test_source(clean_source, data=body)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc


@router.delete("/sources/{source}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_source(source: str) -> Response:
    """Forget a configured source connection."""
    clean_source = source.strip().lower()
    if clean_source not in ("jira", "slack"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No source called {source!r}",
        )
    try:
        await delete_source(clean_source)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc


@router.post("/refresh")
async def trigger_refresh_endpoint(full: bool = False) -> dict[str, Any]:
    """Trigger a remote sync refresh."""
    try:
        return await trigger_refresh(full=full)
    except KnowledgeBotError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc
