"""Settings management API router for Jira and Slack sources."""

from __future__ import annotations

import ipaddress
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

# Headers any reverse proxy adds. The Next.js /api rewrite always sends
# X-Forwarded-Host, and it does NOT send X-Forwarded-For, so a proxied request
# reaches us from 127.0.0.1 whoever made it. Settings therefore refuse every
# proxied request; the browser calls the backend directly instead.
PROXY_HEADERS = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-real-ip")

# Sent by the frontend on every settings call. A custom header makes the browser
# preflight cross-origin requests, so another website cannot fire a "simple"
# POST (e.g. /refresh) at the backend: CORS rejects its origin first.
SETTINGS_CLIENT_HEADER = "X-Requested-With"
SETTINGS_CLIENT_VALUE = "natural-to-sql"


def _is_loopback(host: str | None) -> bool:
    """True for 127.0.0.0/8, ::1 and IPv4-mapped loopback (::ffff:127.0.0.1)."""
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def require_settings_enabled() -> None:
    """Ensure Settings UI is enabled in server configuration."""
    settings = get_settings()
    if not settings.ENABLE_SETTINGS_UI:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settings UI is disabled",
        )


def require_localhost(request: Request) -> None:
    """Ensure the request comes straight from this machine.

    Three checks: the peer is a loopback address, no proxy sat in between
    (a proxy hides the real client), and the Host header names this machine
    (a DNS-rebinding page has the attacker's hostname there).
    """
    client_host = request.client.host if request.client else None
    proxied = any(header in request.headers for header in PROXY_HEADERS)
    target = request.url.hostname
    local_target = target == "localhost" or _is_loopback(target)

    if proxied or not _is_loopback(client_host) or not local_target:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: settings can only be accessed from localhost",
        )


def require_settings_client(request: Request) -> None:
    """Ensure the request carries the frontend's custom header (CSRF guard)."""
    if request.headers.get(SETTINGS_CLIENT_HEADER) != SETTINGS_CLIENT_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: missing {SETTINGS_CLIENT_HEADER} header",
        )


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[
        Depends(require_settings_enabled),
        Depends(require_localhost),
        Depends(require_settings_client),
    ],
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
