"""Headless query execution service for external API callers (/v1/query).

Supports both mode='sql' (MySQL natural-to-sql pipeline with safety gating)
and mode='docs' (Knowledge-Bot Jira/Slack/docs Q&A).
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from app.core.db import get_default_database_name, get_engine
from app.core.intent import detect_write_request, read_only_refusal
from app.core.table_selector import select_relevant_tables
from app.errors import KnowledgeBotError, LLMError
from app.integrations.knowledge_bot import ask_docs
from app.llm.prompts import PROMPT_VERSION, TurnHistory
from app.llm.sql_generator import generate as generate_sql
from app.services.chat import (
    AWAITING_APPROVAL,
    PreparedQuery,
    PrepareFailedError,
    cancel_turn,
    prepare_query,
    run_approved_turn,
)
from app.store.database import (
    create_conversation,
    create_turn,
    get_conversation,
    get_recent_turns,
    get_turn,
    record_audit_log,
    touch_conversation,
    update_turn,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.config import Settings
    from app.core.schema import SchemaCache
    from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


async def execute_headless_query(
    question: str,
    mode: str = "sql",
    auto_approve: bool = True,
    conversation_id: str | None = None,
    database: str | None = None,
    *,
    client: LLMClient,
    engine: AsyncEngine,
    schema_cache: SchemaCache,
    settings: Settings,
) -> dict[str, Any]:
    """Execute a single-shot headless query across either SQL or Docs modes.

    In SQL mode with auto_approve=True:
    - Safe queries (no EXPLAIN block, low/medium risk) execute immediately and return answer.
    - High-risk queries or EXPLAIN-blocked queries are halted and returned as status='blocked',
      awaiting explicit approval via approve_headless_query.
    """
    t0 = time.perf_counter()
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("Question cannot be empty")

    if mode not in ("sql", "docs"):
        raise ValueError(f"Unsupported mode '{mode}'. Supported modes are 'sql' and 'docs'.")

    # Resolve or create conversation
    active_conv_id = conversation_id
    target_db = database
    if active_conv_id:
        existing_conv = await get_conversation(active_conv_id)
        if existing_conv:
            if not target_db and getattr(existing_conv, "database", None):
                target_db = existing_conv.database
            await touch_conversation(active_conv_id)
        else:
            active_conv_id = str(uuid.uuid4())
            await create_conversation(
                title=clean_question[:60],
                conversation_id=active_conv_id,
                database=target_db,
            )
    else:
        active_conv_id = str(uuid.uuid4())
        await create_conversation(
            title=clean_question[:60],
            conversation_id=active_conv_id,
            database=target_db,
        )

    resolved_db = target_db or get_default_database_name()

    # 1. DOCS MODE
    if mode == "docs":
        turn_id = str(uuid.uuid4())
        await create_turn(
            conversation_id=active_conv_id,
            question=clean_question,
            turn_id=turn_id,
            status="searching_docs",
            kind="docs",
        )
        try:
            docs_answer = await ask_docs(clean_question)
        except KnowledgeBotError as exc:
            await update_turn(turn_id, status="error", error=exc.user_message)
            return {
                "turn_id": turn_id,
                "conversation_id": active_conv_id,
                "mode": "docs",
                "status": "error",
                "error": exc.user_message,
                "code": exc.__class__.__name__,
            }
        except Exception as exc:
            msg = f"Knowledge base error: {exc}"
            await update_turn(turn_id, status="error", error=msg)
            return {
                "turn_id": turn_id,
                "conversation_id": active_conv_id,
                "mode": "docs",
                "status": "error",
                "error": msg,
                "code": "DOCS_ERROR",
            }

        total_ms = round((time.perf_counter() - t0) * 1000, 2)
        sources_data = [s.model_dump() for s in docs_answer.sources]
        await update_turn(
            turn_id,
            answer=docs_answer.answer,
            sources_json=json.dumps(sources_data),
            status="done",
            timings_json=json.dumps({"total_ms": total_ms}),
        )
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "docs",
            "status": "done",
            "answer": docs_answer.answer,
            "sources": sources_data,
            "queries": [],
            "timings": {"total_ms": total_ms},
        }

    # 2. SQL MODE
    turn_id = str(uuid.uuid4())
    await create_turn(
        conversation_id=active_conv_id,
        question=clean_question,
        turn_id=turn_id,
        status="planning",
        kind="sql",
        prompt_version=PROMPT_VERSION,
        database=resolved_db,
    )

    # 2a. Upfront read-only write-intent refusal
    matched_write = detect_write_request(clean_question)
    if matched_write:
        refusal_msg = read_only_refusal(matched_write)
        await record_audit_log(
            turn_id=turn_id,
            attempt=0,
            raw_sql=None,
            safe_sql=None,
            accepted=False,
            reason=f"Write request refused upfront (matched: {matched_write})",
            stage="refused",
        )
        await update_turn(
            turn_id,
            status="refused",
            answer=refusal_msg,
        )
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "sql",
            "status": "refused",
            "answer": refusal_msg,
            "blocked": True,
            "refusal_reason": "Database modifications are not permitted (read-only)",
            "queries": [],
        }

    # 2b. Schema introspection & Table selection
    if engine is None or (
        hasattr(engine, "url")
        and getattr(engine.url, "database", None) != resolved_db
        and target_db is not None
    ):
        engine = get_engine(resolved_db)

    schema = await schema_cache.get_schema(db_name=resolved_db)
    relevant_schema = select_relevant_tables(
        schema=schema, question=clean_question, settings=settings
    )

    # Conversation history
    recent_turns = await get_recent_turns(
        conversation_id=active_conv_id, limit=settings.HISTORY_TURNS
    )
    history = [
        TurnHistory(
            question=t.question,
            sql=t.sql,
            result_summary=f"{t.row_count or 0} rows",
        )
        for t in recent_turns
        if t.id != turn_id and t.sql and t.status == "done"
    ]

    # 2c. SQL Generation
    try:
        draft = await generate_sql(
            question=clean_question,
            schema=relevant_schema,
            client=client,
            settings=settings,
            history=history,
        )
    except LLMError as exc:
        err_msg = f"Failed to generate SQL: {exc}"
        await update_turn(turn_id, status="error", error=err_msg)
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "sql",
            "status": "error",
            "error": err_msg,
            "code": "GENERATION_FAILED",
            "queries": [],
        }

    # 2d. Prepare queries (validate + explain + risk + repair)
    prepared: list[PreparedQuery] = []
    for idx, q in enumerate(draft.queries):
        try:
            async for item in prepare_query(
                index=idx,
                purpose=q.purpose,
                raw_sql=q.sql,
                question=clean_question,
                schema=schema,
                client=client,
                engine=engine,
                settings=settings,
                turn_id=turn_id,
                max_repairs=settings.MAX_REPAIR_ATTEMPTS,
                history=history,
            ):
                if isinstance(item, PreparedQuery):
                    prepared.append(item)
        except PrepareFailedError as fail:
            await update_turn(turn_id, status="error", error=fail.message)
            return {
                "turn_id": turn_id,
                "conversation_id": active_conv_id,
                "mode": "sql",
                "status": "error",
                "error": fail.message,
                "code": fail.code,
                "queries": [p.to_state() for p in prepared],
            }

    states = [p.to_state() for p in prepared]
    joined_sql = "\n\n".join(p.safe_sql.sql for p in prepared)
    await update_turn(
        turn_id,
        status=AWAITING_APPROVAL,
        sql=joined_sql,
        queries_json=json.dumps(states),
    )

    # 2e. Check safety blocks: explain block or high-risk flags
    blocked_by_explain = [p for p in prepared if p.explain.blocked]
    high_risk = [p for p in prepared if p.risk.level == "high"]

    if blocked_by_explain:
        p_b = blocked_by_explain[0]
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "sql",
            "status": "blocked",
            "blocked": True,
            "code": "EXPLAIN_BLOCKED",
            "block_reason": f"Query {p_b.index + 1} blocked by EXPLAIN: {p_b.explain.block_reason}",
            "queries": states,
        }

    if high_risk:
        p_hr = high_risk[0]
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "sql",
            "status": "blocked",
            "blocked": True,
            "code": "HIGH_RISK_QUERY",
            "block_reason": (
                f"Query {p_hr.index + 1} flagged as high risk: "
                f"{', '.join(f.message for f in p_hr.risk.flags)}"
            ),
            "queries": states,
        }

    # 2f. If auto_approve is False, wait for approval
    if not auto_approve:
        return {
            "turn_id": turn_id,
            "conversation_id": active_conv_id,
            "mode": "sql",
            "status": "awaiting_approval",
            "blocked": False,
            "queries": states,
        }

    # 2g. If auto_approve is True and query is safe -> execute!
    return await approve_headless_query(
        turn_id=turn_id,
        sql_overrides=None,
        client=client,
        engine=engine,
        schema_cache=schema_cache,
        settings=settings,
    )


async def approve_headless_query(
    turn_id: str,
    sql_overrides: list[str | None] | None,
    client: LLMClient,
    engine: AsyncEngine,
    schema_cache: SchemaCache,
    settings: Settings,
) -> dict[str, Any]:
    """Execute an approved headless query and return the execution summary as a dict."""
    turn = await get_turn(turn_id)
    if turn is None:
        raise ValueError(f"Turn '{turn_id}' not found")
    if turn.status != AWAITING_APPROVAL:
        raise ValueError(f"Turn '{turn_id}' is not awaiting approval (status: {turn.status})")

    turn_db = getattr(turn, "database", None) or get_default_database_name()
    if engine is None or (
        hasattr(engine, "url")
        and getattr(engine.url, "database", None) != turn_db
        and getattr(turn, "database", None) is not None
    ):
        engine = get_engine(turn_db)

    error_payload: dict[str, Any] | None = None
    async for raw_sse in run_approved_turn(
        turn_id=turn_id,
        sql_overrides=sql_overrides,
        client=client,
        engine=engine,
        schema_cache=schema_cache,
        settings=settings,
    ):
        if raw_sse.startswith("event: error\n"):
            lines = raw_sse.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    with contextlib.suppress(Exception):
                        error_payload = json.loads(line[6:])

    updated_turn = await get_turn(turn_id)
    if updated_turn is None:
        raise ValueError(f"Turn '{turn_id}' missing after execution")

    queries_data = json.loads(updated_turn.queries_json) if updated_turn.queries_json else []
    timings_data = json.loads(updated_turn.timings_json) if updated_turn.timings_json else {}

    if error_payload:
        code = error_payload.get("code", "EXECUTION_ERROR")
        return {
            "turn_id": turn_id,
            "conversation_id": updated_turn.conversation_id,
            "mode": "sql",
            "status": "blocked" if code == "BLOCKED_BY_EXPLAIN" else "error",
            "blocked": code == "BLOCKED_BY_EXPLAIN",
            "code": code,
            "error": error_payload.get("message"),
            "queries": queries_data,
        }

    return {
        "turn_id": turn_id,
        "conversation_id": updated_turn.conversation_id,
        "mode": "sql",
        "status": updated_turn.status,
        "answer": updated_turn.answer,
        "queries": queries_data,
        "timings": timings_data,
    }


async def cancel_headless_query(turn_id: str) -> bool:
    """Discard a previewed/blocked turn without running it."""
    return await cancel_turn(turn_id)
