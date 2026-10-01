"""Chat orchestration: SSE streaming, multi-turn memory, repair loop, and approval gate.

Two phases per turn:
1. `process_chat`: generate 1..MAX_QUERIES queries, validate + EXPLAIN each (repairing
   failures), persist them and stream a `preview`. Nothing is executed.
2. `run_approved_turn`: after the user approves (optionally with edited SQL), re-validate
   and re-EXPLAIN every query, refuse blocked ones, execute, and stream one answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlglot

from app.core.executor import run as run_sql
from app.core.explain import ExplainSummary
from app.core.explain import explain as explain_sql
from app.core.intent import detect_write_request, mentions_write_words, read_only_refusal
from app.core.risk import RiskReport, assess_risk
from app.core.table_selector import select_relevant_tables
from app.core.validator import SafeSQL
from app.core.validator import validate as validate_sql
from app.errors import ExecutionError, LLMError, ValidationError
from app.llm.answerer import stream_answer
from app.llm.prompts import PROMPT_VERSION, AnswerResult, TurnHistory
from app.llm.sql_generator import generate as generate_sql
from app.llm.sql_generator import repair as repair_sql
from app.store.database import (
    create_conversation,
    create_turn,
    get_conversation,
    get_recent_turns,
    get_turn,
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


SSE_HEARTBEAT = ": ping\n\n"


async def with_heartbeat(events: AsyncIterator[str], interval_sec: float) -> AsyncIterator[str]:
    """Interleave SSE comment pings while `events` is idle.

    Local LLM calls can take 30s+ without emitting anything; proxies (e.g. the
    Next.js dev rewrite, 30s idle timeout) drop silent connections.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in events:
                await queue.put(item)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval_sec)
            except TimeoutError:
                yield SSE_HEARTBEAT
                continue
            if item is None:
                break
            yield item
        await task  # surface exceptions from the wrapped generator
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


AWAITING_APPROVAL = "awaiting_approval"


@dataclass
class PreparedQuery:
    """A query that passed validation and EXPLAIN (but has not been executed)."""

    index: int
    purpose: str
    safe_sql: SafeSQL
    explain: ExplainSummary
    risk: RiskReport

    def to_state(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "purpose": self.purpose,
            "sql": self.safe_sql.sql,
            "explain": self.explain.to_dict(),
            "risk": self.risk.to_dict(),
            "columns": None,
            "rows": None,
            "row_count": None,
            "truncated": None,
            "error": None,
        }


class PrepareFailedError(Exception):
    """A query could not be made valid/explainable (after repairs, if any)."""

    def __init__(self, code: str, message: str, sql: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.sql = sql


async def _prepare_query(
    *,
    index: int,
    purpose: str,
    raw_sql: str,
    question: str,
    schema: Any,
    client: LLMClient | None,
    engine: AsyncEngine,
    settings: Settings,
    turn_id: str,
    max_repairs: int,
    user_edited: bool = False,
    history: list[TurnHistory] | None = None,
) -> AsyncIterator[str | PreparedQuery]:
    """Validate + EXPLAIN one query, repairing via the LLM up to `max_repairs` times.

    Yields SSE status strings, then exactly one PreparedQuery. Raises PrepareFailedError.
    """
    current_sql = raw_sql
    attempt = 0
    rejected_attempts: list[tuple[str, str]] = []
    write_words = mentions_write_words(question)
    while True:
        yield format_sse("status", "validating")
        code: str
        err_msg: str
        try:
            safe_sql = validate_sql(current_sql, schema=schema, settings=settings)
        except ValidationError as val_err:
            await record_audit_log(
                turn_id=turn_id,
                attempt=attempt,
                raw_sql=current_sql,
                safe_sql=None,
                accepted=False,
                reason=str(val_err),
                stage="rejected",
            )
            rejected_attempts.append((current_sql, str(val_err)))
            code, err_msg = "VALIDATION_FAILED", f"SQL rejected for safety: {val_err}"
        else:
            await record_audit_log(
                turn_id=turn_id,
                attempt=attempt,
                raw_sql=current_sql,
                safe_sql=safe_sql.sql,
                accepted=True,
                reason="user-edited SQL" if user_edited else None,
                stage="validated",
            )
            yield format_sse("status", "explaining")
            try:
                summary = await explain_sql(safe_sql, engine=engine, settings=settings)
                risk = assess_risk(
                    safe_sql=safe_sql.sql,
                    explain=summary,
                    settings=settings,
                    rejected_attempts=rejected_attempts,
                    question_write_words=write_words,
                    user_edited=user_edited,
                    model_set_limit=_has_outer_limit(current_sql),
                )
                yield PreparedQuery(
                    index=index, purpose=purpose, safe_sql=safe_sql, explain=summary, risk=risk
                )
                return
            except ExecutionError as exp_err:
                await record_audit_log(
                    turn_id=turn_id,
                    attempt=attempt,
                    raw_sql=current_sql,
                    safe_sql=safe_sql.sql,
                    accepted=False,
                    reason=f"EXPLAIN error: {exp_err}",
                    stage="explain_failed",
                )
                code, err_msg = "EXPLAIN_FAILED", f"Query check failed: {exp_err}"

        if client is None or attempt >= max_repairs:
            raise PrepareFailedError(code, err_msg, current_sql)

        yield format_sse("status", "repairing")
        attempt += 1
        try:
            repaired = await repair_sql(
                question=question,
                bad_sql=current_sql,
                error_msg=err_msg,
                schema=schema,
                client=client,
                settings=settings,
                history=history,
            )
        except LLMError as repair_exc:
            raise PrepareFailedError(
                "REPAIR_FAILED", f"Repair failed: {repair_exc}", current_sql
            ) from repair_exc
        current_sql = repaired.sql or ""


prepare_query = _prepare_query


def _has_outer_limit(sql: str) -> bool:
    try:
        return sqlglot.parse_one(sql, read="mysql").args.get("limit") is not None
    except Exception:
        return False


async def _refuse_write(
    turn_id: str, conversation_id: str, question: str, matched: str | None, source: str
) -> str:
    """Persist + log a refused write request; returns the SSE `refused` event."""
    message = read_only_refusal(matched)
    await update_turn(turn_id, status="refused", error=message)
    await record_audit_log(
        turn_id=turn_id,
        attempt=0,
        raw_sql=None,
        safe_sql=None,
        accepted=False,
        reason=f"Write request refused ({source}): {question}",
        stage="refused",
    )
    return format_sse(
        "refused",
        {"conversation_id": conversation_id, "turn_id": turn_id, "message": message},
    )


async def process_chat(
    message: str,
    conversation_id: str | None,
    client: LLMClient,
    engine: AsyncEngine,
    schema_cache: SchemaCache,
    settings: Settings,
) -> AsyncIterator[str]:
    """Phase 1: plan queries and stream a preview for approval. Never executes SQL."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    clean_message = message.strip()
    if not clean_message:
        yield format_sse("error", {"message": "Empty message provided", "code": "EMPTY_MESSAGE"})
        return

    active_conv_id = conversation_id
    if not active_conv_id or not await get_conversation(active_conv_id):
        active_conv_id = str(uuid.uuid4())
        await create_conversation(title=clean_message[:60], conversation_id=active_conv_id)

    turn_id = str(uuid.uuid4())
    await create_turn(
        conversation_id=active_conv_id,
        question=clean_message,
        turn_id=turn_id,
        status="generating_sql",
        prompt_version=PROMPT_VERSION,
    )

    try:
        # The app is read-only: refuse obvious data-changing requests before calling the LLM.
        matched = detect_write_request(clean_message)
        if matched:
            yield await _refuse_write(turn_id, active_conv_id, clean_message, matched, "keyword")
            return

        yield format_sse("status", "generating_sql")

        recent_turns = await get_recent_turns(
            conversation_id=active_conv_id,
            limit=settings.HISTORY_TURNS,
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

        schema = await schema_cache.get_schema()
        schema = select_relevant_tables(schema=schema, question=clean_message, settings=settings)

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

        if draft.write_intent:
            yield await _refuse_write(turn_id, active_conv_id, clean_message, None, "model")
            return

        if draft.needs_clarification:
            clar_question = (
                draft.clarification_question or "Could you please clarify your question?"
            )
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

        if not draft.queries:
            err_msg = "The model did not produce a query for this question"
            await update_turn(turn_id, status="error", error=err_msg)
            yield format_sse("error", {"message": err_msg, "code": "NO_QUERY"})
            return

        t_prep_start = time.perf_counter()
        prepared: list[PreparedQuery] = []
        for index, query in enumerate(draft.queries):
            try:
                async for item in _prepare_query(
                    index=index,
                    purpose=query.purpose,
                    raw_sql=query.sql,
                    question=clean_message,
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
                    else:
                        yield item
            except PrepareFailedError as fail:
                prefix = f"Query {index + 1}: " if len(draft.queries) > 1 else ""
                await update_turn(
                    turn_id, status="error", error=prefix + fail.message, sql=fail.sql
                )
                yield format_sse("error", {"message": prefix + fail.message, "code": fail.code})
                return
        timings["prepare_ms"] = round((time.perf_counter() - t_prep_start) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        states = [p.to_state() for p in prepared]
        await update_turn(
            turn_id,
            status=AWAITING_APPROVAL,
            sql="\n\n".join(p.safe_sql.sql for p in prepared),
            queries_json=json.dumps(states),
            timings_json=json.dumps(timings),
        )
        yield format_sse(
            "preview",
            {"conversation_id": active_conv_id, "turn_id": turn_id, "queries": states},
        )
    except asyncio.CancelledError:
        # Client disconnected mid-request; don't leave the turn stuck in a running state.
        with contextlib.suppress(Exception):
            await asyncio.shield(
                update_turn(turn_id, status="error", error="Client disconnected before completion")
            )
        raise
    except Exception as exc:
        err_msg = f"Unexpected error during chat processing: {exc}"
        logger.error(err_msg, exc_info=True)
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "UNEXPECTED_ERROR"})


async def run_approved_turn(
    turn_id: str,
    sql_overrides: list[str | None] | None,
    client: LLMClient,
    engine: AsyncEngine,
    schema_cache: SchemaCache,
    settings: Settings,
) -> AsyncIterator[str]:
    """Phase 2: execute the previewed (or user-edited) queries after explicit approval."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    turn = await get_turn(turn_id)
    if turn is None:
        yield format_sse("error", {"message": "Turn not found", "code": "NOT_FOUND"})
        return
    if turn.status != AWAITING_APPROVAL or not turn.queries_json:
        yield format_sse(
            "error",
            {
                "message": f"Turn is not awaiting approval (status: {turn.status})",
                "code": "INVALID_STATE",
            },
        )
        return

    states: list[dict[str, Any]] = json.loads(turn.queries_json)
    overrides = list(sql_overrides or [])
    if len(overrides) > len(states):
        yield format_sse(
            "error", {"message": "More SQL overrides than queries", "code": "BAD_REQUEST"}
        )
        return

    try:
        # Re-check everything right before execution: validation (which also produces the
        # SafeSQL the executor requires) and the EXPLAIN gate. Edited SQL gets no LLM repair.
        schema = await schema_cache.get_schema()
        approved: list[PreparedQuery] = []
        for state in states:
            index = int(state["index"])
            override = overrides[index] if index < len(overrides) else None
            edited = bool(override and override.strip() and override.strip() != state["sql"])
            if edited and override:
                await record_audit_log(
                    turn_id=turn_id,
                    attempt=0,
                    raw_sql=override.strip(),
                    safe_sql=None,
                    accepted=True,
                    reason=f"User edited query {index + 1} before running",
                    stage="edited",
                )
            try:
                async for item in _prepare_query(
                    index=index,
                    purpose=str(state.get("purpose") or ""),
                    raw_sql=override.strip() if edited and override else str(state["sql"]),
                    question=turn.question,
                    schema=schema,
                    client=None,
                    engine=engine,
                    settings=settings,
                    turn_id=turn_id,
                    max_repairs=0,
                    user_edited=edited,
                ):
                    if isinstance(item, PreparedQuery):
                        approved.append(item)
            except PrepareFailedError as fail:
                yield format_sse(
                    "error",
                    {
                        "message": f"Query {index + 1}: {fail.message}",
                        "code": fail.code,
                        "index": index,
                    },
                )
                return

        blocked = [p for p in approved if p.explain.blocked]
        for p in blocked:
            await record_audit_log(
                turn_id=turn_id,
                attempt=0,
                raw_sql=p.safe_sql.original_sql,
                safe_sql=p.safe_sql.sql,
                accepted=False,
                reason=p.explain.block_reason,
                stage="blocked",
            )
        if blocked:
            first = blocked[0]
            yield format_sse(
                "error",
                {
                    "message": f"Query {first.index + 1} blocked: {first.explain.block_reason}",
                    "code": "BLOCKED_BY_EXPLAIN",
                    "index": first.index,
                },
            )
            return

        await update_turn(turn_id, status="executing")
        yield format_sse("status", "executing")

        t_exec = time.perf_counter()
        new_states: list[dict[str, Any]] = []
        answer_inputs: list[AnswerResult] = []
        for p in approved:
            state = p.to_state()
            try:
                result = await run_sql(p.safe_sql, engine=engine, settings=settings)
                await record_audit_log(
                    turn_id=turn_id,
                    attempt=0,
                    raw_sql=p.safe_sql.original_sql,
                    safe_sql=p.safe_sql.sql,
                    accepted=True,
                    reason=None,
                    stage="executed",
                    row_count=result.row_count,
                    elapsed_ms=result.elapsed_ms,
                )
                state.update(
                    columns=result.columns,
                    rows=result.rows,
                    row_count=result.row_count,
                    truncated=result.truncated,
                )
                answer_inputs.append(
                    AnswerResult(
                        sql=p.safe_sql.sql,
                        columns=result.columns,
                        rows=result.rows,
                        row_count=result.row_count,
                        truncated=result.truncated,
                        purpose=p.purpose,
                    )
                )
            except ExecutionError as exec_err:
                await record_audit_log(
                    turn_id=turn_id,
                    attempt=0,
                    raw_sql=p.safe_sql.original_sql,
                    safe_sql=p.safe_sql.sql,
                    accepted=False,
                    reason=f"Execution error: {exec_err}",
                    stage="execution_failed",
                )
                state["error"] = str(exec_err)
                answer_inputs.append(
                    AnswerResult(
                        sql=p.safe_sql.sql,
                        columns=[],
                        rows=[],
                        row_count=0,
                        truncated=False,
                        purpose=p.purpose,
                        error=str(exec_err),
                    )
                )
            new_states.append(state)
            yield format_sse(
                "result",
                {
                    "index": p.index,
                    "sql": p.safe_sql.sql,
                    "columns": state["columns"] or [],
                    "rows": state["rows"] or [],
                    "row_count": state["row_count"] or 0,
                    "truncated": bool(state["truncated"]),
                    "error": state["error"],
                },
            )
        timings["execution_ms"] = round((time.perf_counter() - t_exec) * 1000, 2)

        joined_sql = "\n\n".join(p.safe_sql.sql for p in approved)
        succeeded = [s for s in new_states if s["error"] is None]
        if not succeeded:
            err_msg = "Query execution failed: " + "; ".join(str(s["error"]) for s in new_states)
            await update_turn(
                turn_id,
                status="error",
                error=err_msg,
                sql=joined_sql,
                queries_json=json.dumps(new_states),
            )
            yield format_sse("error", {"message": err_msg, "code": "EXECUTION_FAILED"})
            return

        yield format_sse("status", "answering")
        t_ans = time.perf_counter()
        answer_chunks: list[str] = []
        try:
            async for chunk in stream_answer(
                question=turn.question,
                results=answer_inputs,
                client=client,
                settings=settings,
            ):
                answer_chunks.append(chunk)
                yield format_sse("answer_delta", chunk)
        except Exception as exc:
            logger.warning("Answer streaming encountered error: %s", exc)
        timings["answer_ms"] = round((time.perf_counter() - t_ans) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        first_ok = succeeded[0]
        await update_turn(
            turn_id,
            sql=joined_sql,
            queries_json=json.dumps(new_states),
            columns_json=json.dumps(first_ok["columns"]),
            rows_json=json.dumps(first_ok["rows"]),
            row_count=sum(int(s["row_count"] or 0) for s in succeeded),
            truncated=any(bool(s["truncated"]) for s in succeeded),
            answer="".join(answer_chunks),
            status="done",
            timings_json=json.dumps(timings),
        )
        yield format_sse(
            "done",
            {"conversation_id": turn.conversation_id, "turn_id": turn_id, "timings": timings},
        )
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.shield(
                update_turn(turn_id, status="error", error="Client disconnected before completion")
            )
        raise
    except Exception as exc:
        err_msg = f"Unexpected error while running approved queries: {exc}"
        logger.error(err_msg, exc_info=True)
        await update_turn(turn_id, status="error", error=err_msg)
        yield format_sse("error", {"message": err_msg, "code": "UNEXPECTED_ERROR"})


async def cancel_turn(turn_id: str) -> bool:
    """Mark a previewed turn as cancelled. Returns False if it is not awaiting approval."""
    turn = await get_turn(turn_id)
    if turn is None or turn.status != AWAITING_APPROVAL:
        return False
    await update_turn(turn_id, status="cancelled")
    return True
