"""Client integration for knowledge-bot service.

This is the ONLY module in natural-to-sql that knows knowledge-bot exists.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, SecretStr

from app.config import get_settings
from app.errors import (
    KnowledgeBotAuthError,
    KnowledgeBotError,
    KnowledgeBotNotConfiguredError,
    KnowledgeBotQuotaError,
    KnowledgeBotUnreachableError,
    KnowledgeBotUpstreamError,
)

logger = logging.getLogger(__name__)


class SourceItem(BaseModel):
    """One source's connection details as reported by knowledge-bot."""

    source: Literal["jira", "slack"]
    configured: bool
    origin: Literal["stored", "env", "none"]
    fields: dict[str, Any] = Field(default_factory=dict)
    secret_hint: str | None = Field(
        None,
        description="Always null: a stored secret is never returned, not even masked.",
    )
    last_refresh: str | None = None
    last_status: str | None = None


class SourceTestResult(BaseModel):
    """Result of a live source connection test."""

    ok: bool
    message: str


class JiraSourceRequest(BaseModel):
    """Configuration for Jira source connection."""

    base_url: str = Field(
        ...,
        max_length=1024,
        description="Jira base URL, e.g. https://acme.atlassian.net",
    )
    browse_url: str | None = Field(
        None,
        max_length=1024,
        description="Where a user opens a ticket in browser. Blank means base_url.",
    )
    auth_mode: Literal["token", "bearer"] = Field(
        "token",
        description="'token' for Jira Cloud (email + api_token); 'bearer' for Data Center PAT.",
    )
    email: str = Field(
        "",
        max_length=320,
        description="Account email for 'token' auth mode.",
    )
    api_token: SecretStr | None = Field(
        None,
        max_length=4096,
        description="API token or PAT. Omit/null to keep stored token.",
    )
    project_key: str | None = Field(None, max_length=255)
    jql: str | None = Field(None, max_length=4000)
    max_issues: int | None = Field(None, ge=1, le=10000)


class SlackSourceRequest(BaseModel):
    """Configuration for Slack source connection."""

    bot_token: SecretStr | None = Field(
        None,
        max_length=4096,
        description="Slack bot token (xoxb-...). Omit/null to keep stored token.",
    )
    channels: list[str] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Channel names or IDs.",
    )
    days_back: int | None = Field(None, ge=0, le=3650)
    max_threads: int | None = Field(None, ge=1, le=10000)


class DocsSource(BaseModel):
    """One document or ticket cited in a knowledge-bot answer."""

    id: str
    source_type: str
    title: str
    url: str
    score: float = 0.0


class DocsAnswer(BaseModel):
    """Structured response from the knowledge-bot ask endpoint."""

    answer: str
    sources: list[DocsSource] = Field(default_factory=list)
    refused: bool = False
    model: str = ""
    filter: str = ""
    documents_searched: int = 0


async def ask_docs(question: str) -> DocsAnswer:
    """Send question to knowledge-bot and return structured DocsAnswer.

    Maps errors to typed user-safe exceptions. Never logs or echoes the API key.
    """
    settings = get_settings()
    api_key = settings.KNOWLEDGE_BOT_API_KEY.strip() if settings.KNOWLEDGE_BOT_API_KEY else ""
    if not api_key:
        raise KnowledgeBotNotConfiguredError(
            "Knowledge base is not configured (missing KNOWLEDGE_BOT_API_KEY)",
            user_message=(
                "Documentation search is not configured. Please set KNOWLEDGE_BOT_API_KEY."
            ),
        )

    clean_question = question.strip()
    if not clean_question:
        raise KnowledgeBotError(
            "Empty question provided",
            user_message="Question cannot be empty.",
        )

    url = f"{settings.KNOWLEDGE_BOT_URL.rstrip('/')}/v1/ask"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "question": clean_question[:2000],
        "model": "",
    }

    logger.info(
        "Querying knowledge-bot at %s (question length: %d)",
        settings.KNOWLEDGE_BOT_URL,
        len(clean_question),
    )

    try:
        async with httpx.AsyncClient(timeout=settings.KNOWLEDGE_BOT_TIMEOUT_SEC) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning(
            "Knowledge-bot request timed out after %.1fs", settings.KNOWLEDGE_BOT_TIMEOUT_SEC
        )
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot timed out: {exc}",
            user_message="Knowledge base service timed out. Please try again.",
        ) from exc
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        logger.warning("Knowledge-bot service unreachable: %s", exc)
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot unreachable: {exc}",
            user_message="Knowledge base service is unreachable. Please verify it is running.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Knowledge-bot HTTP error: %s", exc)
        raise KnowledgeBotError(
            f"Knowledge-bot communication error: {exc}",
            user_message="Failed to communicate with knowledge base service.",
        ) from exc

    if resp.status_code == 200:
        try:
            data = resp.json()
            return DocsAnswer.model_validate(data)
        except Exception as exc:
            logger.error("Failed to parse knowledge-bot response JSON: %s", exc)
            raise KnowledgeBotError(
                f"Invalid JSON response from knowledge-bot: {exc}",
                user_message="Received invalid response from knowledge base service.",
            ) from exc

    if resp.status_code in (401, 403):
        logger.warning("Knowledge-bot authentication error (status %d)", resp.status_code)
        raise KnowledgeBotAuthError(
            f"Authentication failed with status {resp.status_code}",
            user_message="Knowledge base authentication failed. Check your API key.",
        )

    if resp.status_code == 429:
        logger.warning("Knowledge-bot quota/rate limit exceeded (status 429)")
        raise KnowledgeBotQuotaError(
            "Quota or rate limit exceeded",
            user_message="Knowledge base quota or rate limit exceeded. Please try again later.",
        )

    if resp.status_code == 502:
        logger.warning("Knowledge-bot upstream LLM error (status 502)")
        raise KnowledgeBotUpstreamError(
            "Upstream LLM error from knowledge-bot",
            user_message="Knowledge base upstream AI service encountered an error.",
        )

    logger.warning("Knowledge-bot returned HTTP status %d", resp.status_code)
    raise KnowledgeBotError(
        f"Knowledge-bot returned HTTP {resp.status_code}",
        user_message=f"Knowledge base service returned an error (HTTP {resp.status_code}).",
    )


async def docs_health() -> dict[str, bool]:
    """Check whether knowledge-bot is configured and reachable."""
    settings = get_settings()
    api_key = settings.KNOWLEDGE_BOT_API_KEY.strip() if settings.KNOWLEDGE_BOT_API_KEY else ""
    if not api_key:
        return {"configured": False, "reachable": False}

    url = f"{settings.KNOWLEDGE_BOT_URL.rstrip('/')}/v1/health"
    headers = {"X-API-Key": api_key}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)
            return {"configured": True, "reachable": resp.status_code == 200}
    except Exception as exc:
        logger.debug("Knowledge-bot health check failed: %s", exc)
        return {"configured": True, "reachable": False}


def _dump_source_request(body: BaseModel | dict[str, Any] | None) -> dict[str, Any] | None:
    """Serialize request model or dict, unwrapping SecretStr without logging or persisting."""
    if body is None:
        return None
    data = body if isinstance(body, dict) else body.model_dump()
    result: dict[str, Any] = {}
    for k, v in data.items():
        if hasattr(v, "get_secret_value"):
            result[k] = v.get_secret_value()
        else:
            result[k] = v
    return result


def _get_admin_key() -> str:
    """Retrieve the admin key from settings or raise KnowledgeBotNotConfiguredError."""
    settings = get_settings()
    key = settings.KNOWLEDGE_BOT_ADMIN_KEY.strip() if settings.KNOWLEDGE_BOT_ADMIN_KEY else ""
    if not key:
        raise KnowledgeBotNotConfiguredError(
            "Knowledge base admin key is not configured (missing KNOWLEDGE_BOT_ADMIN_KEY)",
            user_message=(
                "Knowledge base admin operations are not configured. "
                "Please set KNOWLEDGE_BOT_ADMIN_KEY."
            ),
        )
    return key


def _extract_detail(resp: httpx.Response) -> str | None:
    """Extract detail message safely from response without echoing sensitive data."""
    try:
        data = resp.json()
        if isinstance(data, dict) and "detail" in data:
            detail = data["detail"]
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list):
                msgs = [item.get("msg", str(item)) for item in detail if isinstance(item, dict)]
                return "; ".join(msgs) if msgs else str(detail)
            return str(detail)
    except Exception:
        pass
    return None


async def _admin_request(
    method: str,
    path: str,
    *,
    json_data: Any | None = None,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Perform an authenticated admin request to knowledge-bot.

    Never logs payloads or secrets. Maps transport and HTTP errors to typed exceptions.
    `timeout` overrides KNOWLEDGE_BOT_TIMEOUT_SEC for calls that are slow by design.
    """
    settings = get_settings()
    admin_key = _get_admin_key()
    url = f"{settings.KNOWLEDGE_BOT_URL.rstrip('/')}{path}"
    headers = {
        "X-API-Key": admin_key,
        "Content-Type": "application/json",
    }
    if timeout is None:
        timeout = settings.KNOWLEDGE_BOT_TIMEOUT_SEC

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
            )
    except httpx.TimeoutException as exc:
        logger.warning(
            "Knowledge-bot admin request %s %s timed out after %.1fs",
            method,
            path,
            timeout,
        )
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot timed out: {exc}",
            user_message="Knowledge base service timed out. Please try again.",
        ) from exc
    except (httpx.ConnectError, httpx.NetworkError) as exc:
        logger.warning(
            "Knowledge-bot service unreachable for %s %s: %s",
            method,
            path,
            exc,
        )
        raise KnowledgeBotUnreachableError(
            f"Knowledge-bot unreachable: {exc}",
            user_message="Knowledge base service is unreachable. Please verify it is running.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Knowledge-bot HTTP error for %s %s: %s", method, path, exc)
        raise KnowledgeBotError(
            f"Knowledge-bot communication error: {exc}",
            user_message="Failed to communicate with knowledge base service.",
        ) from exc

    if resp.status_code in (401, 403):
        detail = (
            _extract_detail(resp)
            or "Knowledge base authentication failed. Check your admin API key."
        )
        logger.warning("Knowledge-bot admin auth error (status %d)", resp.status_code)
        raise KnowledgeBotAuthError(
            f"Authentication failed with status {resp.status_code}: {detail}",
            user_message=detail,
            status_code=resp.status_code,
        )

    if resp.status_code == 429:
        detail = (
            _extract_detail(resp)
            or "Knowledge base quota or rate limit exceeded. Please try again later."
        )
        logger.warning("Knowledge-bot quota/rate limit exceeded (status 429)")
        raise KnowledgeBotQuotaError(
            f"Quota or rate limit exceeded: {detail}",
            user_message=detail,
        )

    if resp.status_code == 502:
        detail = _extract_detail(resp) or "Knowledge base upstream service encountered an error."
        logger.warning("Knowledge-bot upstream error (status 502)")
        raise KnowledgeBotUpstreamError(
            f"Upstream error from knowledge-bot: {detail}",
            user_message=detail,
        )

    if resp.status_code >= 400:
        detail = (
            _extract_detail(resp)
            or f"Knowledge base service returned an error (HTTP {resp.status_code})."
        )
        logger.warning(
            "Knowledge-bot admin returned HTTP %d: %s",
            resp.status_code,
            detail,
        )
        raise KnowledgeBotError(
            f"Knowledge-bot returned HTTP {resp.status_code}: {detail}",
            user_message=detail,
            status_code=resp.status_code,
        )

    return resp


async def fetch_sources() -> list[SourceItem]:
    """Fetch all configured remote sources from knowledge-bot."""
    resp = await _admin_request("GET", "/admin/sources")
    try:
        data = resp.json()
        sources_raw = data.get("sources", [])
        return [SourceItem.model_validate(item) for item in sources_raw]
    except Exception as exc:
        raise KnowledgeBotError(
            f"Invalid JSON response from knowledge-bot: {exc}",
            user_message="Received invalid response from knowledge base service.",
        ) from exc


async def save_jira_source(data: JiraSourceRequest) -> SourceItem:
    """Save Jira source configuration in knowledge-bot."""
    payload = _dump_source_request(data)
    resp = await _admin_request("PUT", "/admin/sources/jira", json_data=payload)
    try:
        return SourceItem.model_validate(resp.json())
    except Exception as exc:
        raise KnowledgeBotError(
            f"Invalid JSON response from knowledge-bot: {exc}",
            user_message="Received invalid response from knowledge base service.",
        ) from exc


async def save_slack_source(data: SlackSourceRequest) -> SourceItem:
    """Save Slack source configuration in knowledge-bot."""
    payload = _dump_source_request(data)
    resp = await _admin_request("PUT", "/admin/sources/slack", json_data=payload)
    try:
        return SourceItem.model_validate(resp.json())
    except Exception as exc:
        raise KnowledgeBotError(
            f"Invalid JSON response from knowledge-bot: {exc}",
            user_message="Received invalid response from knowledge base service.",
        ) from exc


async def test_source(
    source: str,
    data: JiraSourceRequest | SlackSourceRequest | dict[str, Any] | None = None,
) -> SourceTestResult:
    """Run a live test of source connectivity without saving credentials."""
    clean_source = source.strip().lower()
    if clean_source not in ("jira", "slack"):
        raise KnowledgeBotError(
            f"Unknown source type: {source}",
            user_message=f"Unknown source type: {source}",
            status_code=404,
        )
    payload = _dump_source_request(data) if data is not None else None
    resp = await _admin_request("POST", f"/admin/sources/{clean_source}/test", json_data=payload)
    try:
        return SourceTestResult.model_validate(resp.json())
    except Exception as exc:
        raise KnowledgeBotError(
            f"Invalid JSON response from knowledge-bot: {exc}",
            user_message="Received invalid response from knowledge base service.",
        ) from exc


test_source.__test__ = False  # type: ignore[attr-defined]


async def delete_source(source: str) -> None:
    """Delete a configured source connection from knowledge-bot."""
    clean_source = source.strip().lower()
    if clean_source not in ("jira", "slack"):
        raise KnowledgeBotError(
            f"Unknown source type: {source}",
            user_message=f"Unknown source type: {source}",
            status_code=404,
        )
    await _admin_request("DELETE", f"/admin/sources/{clean_source}")


async def trigger_refresh(full: bool = False) -> dict[str, Any]:
    """Run a remote sync refresh on knowledge-bot and return its result.

    knowledge-bot answers only once the whole fetch has finished (and 409 while
    another one is running), so this call gets its own, much longer timeout.
    """
    params = {"full": "true"} if full else {}
    resp = await _admin_request(
        "POST",
        "/admin/refresh",
        params=params,
        timeout=get_settings().KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC,
    )
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"ok": True, "result": data}
    except Exception as exc:
        raise KnowledgeBotError(
            f"Invalid JSON response from knowledge-bot: {exc}",
            user_message="Received invalid response from knowledge base service.",
        ) from exc
