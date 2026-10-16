"""FastAPI main application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.audit import router as audit_router
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.databases import router as databases_router
from app.api.schema import router as schema_router
from app.api.settings import router as settings_router
from app.api.v1.keys import router as v1_keys_router
from app.api.v1.query import router as v1_query_router
from app.config import get_settings
from app.core.db import check_db_health, close_engine
from app.core.schema import get_schema_cache
from app.integrations.knowledge_bot import docs_health
from app.llm.client import LLMClient, OllamaClient
from app.store.database import close_app_db, init_app_db

logger = logging.getLogger(__name__)


def get_llm_client() -> LLMClient:
    """Get Ollama client initialized with current settings."""
    current_settings = get_settings()
    return OllamaClient(
        base_url=current_settings.OLLAMA_URL,
        model=current_settings.OLLAMA_MODEL,
        num_ctx=current_settings.OLLAMA_NUM_CTX,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager: manages DB pool, SQLite memory, and logging."""
    logger.info("Starting Natural-to-SQL backend service")
    try:
        await init_app_db()
    except Exception as exc:
        logger.error("Failed to initialize SQLite application database: %s", exc)

    db_ok, db_version = await check_db_health()
    if db_ok:
        logger.info(
            "Connected to target database successfully",
            extra={"db_version": db_version},
        )
        try:
            cache = get_schema_cache()
            schema = await cache.get_schema()
            logger.info(
                "Pre-warmed schema cache with %d tables",
                len(schema.tables),
                extra={"tables_count": len(schema.tables)},
            )
        except Exception as exc:
            logger.warning(
                "Could not pre-warm schema cache",
                extra={"error": str(exc)},
            )
    else:
        logger.warning(
            "Target database connection failed at startup",
            extra={"db_version": db_version},
        )

    yield

    logger.info("Shutting down Natural-to-SQL backend service")
    await close_app_db()
    await close_engine()


settings = get_settings()

app = FastAPI(
    title="Natural-to-SQL API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(schema_router)
app.include_router(databases_router)
app.include_router(audit_router)
app.include_router(v1_query_router)
app.include_router(v1_keys_router)
app.include_router(settings_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors without echoing secrets from settings requests."""
    if request.url.path.startswith("/api/settings"):
        errors = [
            {k: v for k, v in error.items() if k not in ("input", "ctx", "url")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
    return await request_validation_exception_handler(request, exc)


class KnowledgeBotHealth(BaseModel):
    configured: bool
    reachable: bool


class HealthResponse(BaseModel):
    """Health check response schema."""

    db: Literal["ok", "error"]
    ollama: Literal["ok", "error"]
    model: str
    db_version: str
    knowledge_bot: KnowledgeBotHealth
    settings_ui_enabled: bool


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return health status of database, LLM service, and knowledge base."""
    current_settings = get_settings()
    db_ok, db_version = await check_db_health()
    client = get_llm_client()
    ollama_ok, _ = await client.check_health()
    kb_health = await docs_health()

    return HealthResponse(
        db="ok" if db_ok else "error",
        ollama="ok" if ollama_ok else "error",
        model=current_settings.OLLAMA_MODEL,
        db_version=db_version,
        knowledge_bot=KnowledgeBotHealth(
            configured=kb_health["configured"],
            reachable=kb_health["reachable"],
        ),
        settings_ui_enabled=current_settings.ENABLE_SETTINGS_UI,
    )
