"""Chat orchestration pipeline service implementing SSE streaming,
multi-turn memory, and repair loop.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from app.core.executor import ResultSet
from app.core.executor import run as run_sql
from app.core.table_selector import select_relevant_tables
from app.core.validator import SafeSQL
from app.core.validator import validate as validate_sql
from app.errors import ExecutionError, LLMError, ValidationError
from app.llm.answerer import stream_answer
from app.llm.prompts import PROMPT_VERSION, TurnHistory
from app.llm.sql_generator import generate as generate_sql
from app.llm.sql_generator import repair as repair_sql
from app.store.database import (
    create_conversation,
    create_turn,
    get_conversation,
    get_recent_turns,
    record_audit_log,
    update_turn,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.config import Settings
    from app.core.schema import SchemaCache
    from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


def format_sse(event: str, data: Any) -> str:
    """Format SSE event block: event: <name>\ndata: <json>\n\n."""
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def process_chat(
    message: str,
    conversation_id: str | None,
    client: LLMClient,
    engine: AsyncEngine,
    schema_cache: SchemaCache,
    settings: Settings,
) -> AsyncIterator[str]:
    """Execute end-to-end chat request streaming SSE events to the client."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    clean_message = message.strip()
    if not clean_message:
        yield format_sse("error", {"message": "Empty message provided", "code": "EMPTY_MESSAGE"})
        return

    # 1. Resolve or create conversation
    active_conv_id = conversation_id
    if active_conv_id:
        existing = await get_conversation(active_conv_id)
        if not existing:
            active_conv_id = str(uuid.uuid4())
            await create_conversation(
                title=clean_message[:60],
                conversation_id=active_conv_id,
            )
    else:
        active_conv_id = str(uuid.uuid4())
        await create_conversation(
            title=clean_message[:60],
            conversation_id=active_conv_id,
        )

    # Create initial Turn record
    turn_id = str(uuid.uuid4())
    await create_turn(
        conversation_id=active_conv_id,
        question=clean_message,
        turn_id=turn_id,
        status="generating_sql",
        prompt_version=PROMPT_VERSION,
    )

    # 2. Initial SSE Status
    yield format_sse("status", "generating_sql")

    # 3. Load conversation history
    recent_turns = await get_recent_turns(
        conversation_id=active_conv_id,
        limit=settings.HISTORY_TURNS,
    )
    history: list[TurnHistory] = []
    for t in recent_turns:
        if t.id != turn_id and t.sql:
            summary = f"{t.row_count or 0} rows"
            history.append(
                TurnHistory(
                    question=t.question,
                    sql=t.sql,
                    result_summary=summary,
                )
            )

    # 4. Fetch Schema
    schema = await schema_cache.get_schema()
    schema = select_relevant_tables(schema=schema, question=clean_message, settings=settings)

    # 5. Generate SQL Draft
    t_gen_start = time.perf_counter()
    try:
        draft = await generate_sql(
            question=clean_message,
            history=history,
            schema=schema,
            client=client,
            settings=settings,
        )
    except LLMError as exc:
        err_msg = f"Language model error: {exc}"
        logger.error(err_msg, extra={"error": str(exc)})
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "LLM_ERROR"})
        return

    timings["generation_ms"] = round((time.perf_counter() - t_gen_start) * 1000, 2)

    # 6. Check for Clarification Request
    if draft.needs_clarification:
        clar_question = draft.clarification_question or "Could you please clarify your question?"
        await update_turn(
            turn_id,
            status="clarification",
            error=clar_question,
            timings_json=json.dumps(timings),
        )
        yield format_sse("clarification", {"question": clar_question})
        yield format_sse(
            "done",
            {"conversation_id": active_conv_id, "turn_id": turn_id, "timings": timings},
        )
        return

    # 7. Validation and Execution with Repair Loop
    current_sql = draft.sql or ""
    safe_sql: SafeSQL | None = None
    exec_result: ResultSet | None = None
    repair_attempt = 0

    while repair_attempt <= settings.MAX_REPAIR_ATTEMPTS:
        yield format_sse("status", "validating")

        # Step A: Validate
        try:
            safe_sql = validate_sql(current_sql, schema=schema, settings=settings)
            await record_audit_log(
                turn_id=turn_id,
                attempt=repair_attempt,
                raw_sql=current_sql,
                safe_sql=safe_sql.sql,
                accepted=True,
                reason=None,
            )
        except ValidationError as val_err:
            await record_audit_log(
                turn_id=turn_id,
                attempt=repair_attempt,
                raw_sql=current_sql,
                safe_sql=None,
                accepted=False,
                reason=str(val_err),
            )

            if repair_attempt < settings.MAX_REPAIR_ATTEMPTS:
                yield format_sse("status", "repairing")
                repair_attempt += 1
                try:
                    repaired = await repair_sql(
                        question=clean_message,
                        bad_sql=current_sql,
                        error_msg=str(val_err),
                        schema=schema,
                        client=client,
                        settings=settings,
                    )
                    current_sql = repaired.sql or ""
                    continue
                except LLMError as repair_exc:
                    err_msg = f"Repair failed: {repair_exc}"
                    await update_turn(turn_id, status="error", error=err_msg, sql=current_sql)
                    yield format_sse("error", {"message": err_msg, "code": "REPAIR_FAILED"})
                    return
            else:
                err_msg = f"SQL rejected for safety: {val_err}"
                await update_turn(turn_id, status="error", error=err_msg, sql=current_sql)
                yield format_sse("error", {"message": err_msg, "code": "VALIDATION_FAILED"})
                return

        # Step B: Execute Validated SafeSQL
        assert safe_sql is not None
        yield format_sse("status", "executing")

        try:
            exec_result = await run_sql(safe_sql, engine=engine, settings=settings)
            timings["execution_ms"] = exec_result.elapsed_ms
            break
        except ExecutionError as exec_err:
            await record_audit_log(
                turn_id=turn_id,
                attempt=repair_attempt,
                raw_sql=current_sql,
                safe_sql=safe_sql.sql,
                accepted=False,
                reason=f"Execution error: {exec_err}",
            )

            if repair_attempt < settings.MAX_REPAIR_ATTEMPTS:
                yield format_sse("status", "repairing")
                repair_attempt += 1
                try:
                    repaired = await repair_sql(
                        question=clean_message,
                        bad_sql=current_sql,
                        error_msg=str(exec_err),
                        schema=schema,
                        client=client,
                        settings=settings,
                    )
                    current_sql = repaired.sql or ""
                    continue
                except LLMError as repair_exc:
                    err_msg = f"Repair failed: {repair_exc}"
                    await update_turn(turn_id, status="error", error=err_msg, sql=current_sql)
                    yield format_sse("error", {"message": err_msg, "code": "REPAIR_FAILED"})
                    return
            else:
                err_msg = f"Query execution failed: {exec_err}"
                await update_turn(turn_id, status="error", error=err_msg, sql=current_sql)
                yield format_sse("error", {"message": err_msg, "code": "EXECUTION_FAILED"})
                return

    assert safe_sql is not None and exec_result is not None

    # 8. Yield SQL and Result events
    yield format_sse("sql", safe_sql.sql)
    yield format_sse(
        "result",
        {
            "columns": exec_result.columns,
            "rows": exec_result.rows,
            "row_count": exec_result.row_count,
            "truncated": exec_result.truncated,
        },
    )

    # 9. Synthesize and Stream Natural Language Answer
    yield format_sse("status", "answering")
    t_ans_start = time.perf_counter()
    answer_chunks: list[str] = []

    try:
        async for chunk in stream_answer(
            question=clean_message,
            sql=safe_sql.sql,
            result=exec_result,
            client=client,
            settings=settings,
        ):
            answer_chunks.append(chunk)
            yield format_sse("answer_delta", chunk)
    except Exception as exc:
        logger.warning("Answer streaming encountered error: %s", exc)

    full_answer = "".join(answer_chunks)
    timings["answer_ms"] = round((time.perf_counter() - t_ans_start) * 1000, 2)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # 10. Persist Turn and Emit Done
    await update_turn(
        turn_id,
        sql=safe_sql.sql,
        columns_json=json.dumps(exec_result.columns),
        rows_json=json.dumps(exec_result.rows),
        row_count=exec_result.row_count,
        truncated=exec_result.truncated,
        answer=full_answer,
        status="done",
        timings_json=json.dumps(timings),
    )

    yield format_sse(
        "done",
        {
            "conversation_id": active_conv_id,
            "turn_id": turn_id,
            "timings": timings,
        },
    )
