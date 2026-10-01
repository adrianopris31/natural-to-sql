"""Integration tests for the two-phase chat pipeline (preview → approval → run) over SSE."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.chat import get_chat_llm_client
from app.config import Settings, get_settings
from app.core.db import get_engine
from app.core.schema import get_schema_cache
from app.llm.client import FakeLLMClient
from app.main import app
from app.services.chat import cancel_turn, process_chat, run_approved_turn
from app.store.database import (
    close_app_db,
    get_conversation,
    get_recent_turns,
    get_turn,
    init_app_db,
    list_audit_entries,
)


@pytest.fixture(autouse=True)
async def setup_test_store(tmp_path: Path) -> AsyncIterator[Path]:
    """Ensure clean isolated SQLite database for each pipeline test."""
    await close_app_db()
    db_file = tmp_path / "test_chat.db"
    await init_app_db(str(db_file))
    yield db_file
    await close_app_db()


def parse_sse_events(raw_sse: str) -> list[tuple[str, Any]]:
    """Parse raw SSE text into list of (event_type, payload). Comment lines are skipped."""
    events: list[tuple[str, Any]] = []
    for block in raw_sse.strip().split("\n\n"):
        event_name = None
        data = None
        for line in block.strip().split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_str = line[len("data: ") :].strip()
                try:
                    data = json.loads(data_str)
                except Exception:
                    data = data_str
        if event_name:
            events.append((event_name, data))
    return events


def _draft(*sqls: str) -> dict[str, Any]:
    return {
        "queries": [{"sql": s, "purpose": f"q{i}"} for i, s in enumerate(sqls)],
        "reasoning": "test",
        "needs_clarification": False,
        "clarification_question": None,
    }


async def _plan(
    message: str,
    client: FakeLLMClient,
    conversation_id: str | None = None,
    settings: Settings | None = None,
) -> list[tuple[str, Any]]:
    raw = [
        e
        async for e in process_chat(
            message=message,
            conversation_id=conversation_id,
            client=client,
            engine=get_engine(),
            schema_cache=get_schema_cache(),
            settings=settings or get_settings(),
        )
    ]
    return parse_sse_events("".join(raw))


async def _run(
    turn_id: str,
    client: FakeLLMClient,
    overrides: list[str | None] | None = None,
    settings: Settings | None = None,
) -> list[tuple[str, Any]]:
    raw = [
        e
        async for e in run_approved_turn(
            turn_id=turn_id,
            sql_overrides=overrides,
            client=client,
            engine=get_engine(),
            schema_cache=get_schema_cache(),
            settings=settings or get_settings(),
        )
    ]
    return parse_sse_events("".join(raw))


def _payloads(events: list[tuple[str, Any]], name: str) -> list[Any]:
    return [data for ev, data in events if ev == name]


@pytest.mark.asyncio
async def test_chat_pipeline_empty_message() -> None:
    parsed = await _plan("   ", FakeLLMClient())
    assert len(parsed) == 1
    assert parsed[0][0] == "error"
    assert parsed[0][1]["code"] == "EMPTY_MESSAGE"


@pytest.mark.asyncio
async def test_preview_never_executes_then_run_after_approval() -> None:
    client = FakeLLMClient(
        json_responses=[_draft("SELECT id, name FROM users ORDER BY id ASC LIMIT 2")],
        stream_responses=[["Here ", "are ", "the users."]],
    )

    planned = await _plan("List 2 users", client)
    names = [e[0] for e in planned]
    assert _payloads(planned, "status") == ["generating_sql", "validating", "explaining"]
    assert "result" not in names and "answer_delta" not in names and "done" not in names
    assert names[-1] == "preview"

    preview = _payloads(planned, "preview")[0]
    assert len(preview["queries"]) == 1
    q = preview["queries"][0]
    assert q["sql"].startswith("SELECT") and "LIMIT 2" in q["sql"]
    assert q["explain"]["tables"] and q["explain"]["blocked"] is False
    assert q["rows"] is None

    turn = await get_turn(preview["turn_id"])
    assert turn is not None and turn.status == "awaiting_approval"
    assert client.recorded_stream_calls == []  # no answer before approval

    ran = await _run(preview["turn_id"], client)
    assert _payloads(ran, "status") == ["executing", "answering"]
    results = _payloads(ran, "result")
    assert len(results) == 1 and results[0]["row_count"] == 2 and results[0]["index"] == 0
    assert "".join(_payloads(ran, "answer_delta")) == "Here are the users."
    done = _payloads(ran, "done")[0]
    assert done["turn_id"] == preview["turn_id"]

    conv = await get_conversation(done["conversation_id"])
    assert conv is not None
    stored = conv.turns[0]
    assert stored.status == "done" and stored.row_count == 2
    assert stored.answer == "Here are the users."
    stored_queries = json.loads(stored.queries_json or "[]")
    assert stored_queries[0]["rows"] and stored_queries[0]["error"] is None


@pytest.mark.asyncio
async def test_multiple_queries_previewed_and_answered_together() -> None:
    client = FakeLLMClient(
        json_responses=[
            _draft(
                "SELECT COUNT(*) AS n FROM orders",
                "SELECT id, name, price FROM products ORDER BY price DESC LIMIT 1",
            )
        ],
        stream_responses=[["combined"]],
    )
    planned = await _plan("How many orders, and most expensive product?", client)
    preview = _payloads(planned, "preview")[0]
    assert [q["index"] for q in preview["queries"]] == [0, 1]
    assert [q["purpose"] for q in preview["queries"]] == ["q0", "q1"]

    ran = await _run(preview["turn_id"], client)
    results = _payloads(ran, "result")
    assert [r["index"] for r in results] == [0, 1]
    assert results[0]["columns"] == ["n"]
    assert results[1]["row_count"] == 1
    answer_prompt = client.recorded_stream_calls[0]["messages"][1]["content"]
    assert "### Query 1" in answer_prompt and "### Query 2" in answer_prompt


@pytest.mark.asyncio
async def test_user_edited_sql_is_revalidated_and_executed() -> None:
    client = FakeLLMClient(json_responses=[_draft("SELECT id FROM users LIMIT 1")])
    preview = _payloads(await _plan("A user", client), "preview")[0]

    ran = await _run(preview["turn_id"], client, overrides=["SELECT id, name FROM users LIMIT 3"])
    result = _payloads(ran, "result")[0]
    assert result["columns"] == ["id", "name"] and result["row_count"] == 3
    assert "name" in result["sql"]


@pytest.mark.asyncio
async def test_dangerous_edit_is_rejected_and_nothing_runs() -> None:
    client = FakeLLMClient(json_responses=[_draft("SELECT id FROM users LIMIT 1")])
    preview = _payloads(await _plan("A user", client), "preview")[0]

    ran = await _run(preview["turn_id"], client, overrides=["DROP TABLE users"])
    names = [e[0] for e in ran]
    assert "result" not in names and "executing" not in _payloads(ran, "status")
    err = _payloads(ran, "error")[0]
    assert err["code"] == "VALIDATION_FAILED" and err["index"] == 0
    turn = await get_turn(preview["turn_id"])
    assert turn is not None and turn.status == "awaiting_approval"  # user can fix and retry


@pytest.mark.asyncio
async def test_explain_gate_blocks_expensive_query() -> None:
    strict = get_settings().model_copy(update={"EXPLAIN_MAX_COST": 0.0})
    client = FakeLLMClient(json_responses=[_draft("SELECT id FROM users")])
    preview = _payloads(await _plan("All users", client, settings=strict), "preview")[0]
    assert preview["queries"][0]["explain"]["blocked"] is True

    ran = await _run(preview["turn_id"], client, settings=strict)
    err = _payloads(ran, "error")[0]
    assert err["code"] == "BLOCKED_BY_EXPLAIN"
    assert "result" not in [e[0] for e in ran]


@pytest.mark.asyncio
async def test_clarification() -> None:
    client = FakeLLMClient(
        json_responses=[
            {
                "queries": [],
                "reasoning": "Unclear time period",
                "needs_clarification": True,
                "clarification_question": "Which year would you like sales figures for?",
            }
        ]
    )
    parsed = await _plan("Show sales", client)
    assert [e[0] for e in parsed] == ["status", "clarification", "done"]
    conv = await get_conversation(parsed[2][1]["conversation_id"])
    assert conv is not None and conv.turns[0].status == "clarification"


@pytest.mark.asyncio
async def test_repair_after_validation_error() -> None:
    client = FakeLLMClient(
        json_responses=[
            _draft("SELECT * FROM secret_admin_vault"),
            _draft("SELECT id, name FROM users LIMIT 1"),
        ]
    )
    planned = await _plan("Show admin user", client)
    assert "repairing" in _payloads(planned, "status")
    preview = _payloads(planned, "preview")[0]
    assert "users" in preview["queries"][0]["sql"]


@pytest.mark.asyncio
async def test_repair_after_explain_error_unknown_column() -> None:
    client = FakeLLMClient(
        json_responses=[
            _draft("SELECT id, no_such_column FROM users LIMIT 1"),
            _draft("SELECT id, name FROM users LIMIT 1"),
        ]
    )
    planned = await _plan("Users", client)
    statuses = _payloads(planned, "status")
    assert statuses.count("explaining") == 2 and "repairing" in statuses
    repair_prompt = client.recorded_chat_calls[1]["messages"][1]["content"]
    assert "no_such_column" in repair_prompt
    assert _payloads(planned, "preview")


@pytest.mark.asyncio
async def test_repair_exhausted() -> None:
    bad = _draft("DROP TABLE users")
    client = FakeLLMClient(json_responses=[bad, bad, bad])
    planned = await _plan("Show the users table", client)
    err = _payloads(planned, "error")[0]
    assert err["code"] == "VALIDATION_FAILED"
    assert "safety" in err["message"]
    assert not _payloads(planned, "preview")


@pytest.mark.asyncio
async def test_run_only_once_and_cancel() -> None:
    client = FakeLLMClient(
        json_responses=[_draft("SELECT id FROM users LIMIT 1"), _draft("SELECT id FROM users")]
    )
    first = _payloads(await _plan("A", client), "preview")[0]
    assert _payloads(await _run(first["turn_id"], client), "done")
    again = await _run(first["turn_id"], client)
    assert _payloads(again, "error")[0]["code"] == "INVALID_STATE"

    second = _payloads(await _plan("B", client), "preview")[0]
    assert await cancel_turn(second["turn_id"]) is True
    assert await cancel_turn(second["turn_id"]) is False
    after_cancel = await _run(second["turn_id"], client)
    assert _payloads(after_cancel, "error")[0]["code"] == "INVALID_STATE"


@pytest.mark.asyncio
async def test_history_only_includes_executed_turns() -> None:
    client = FakeLLMClient(
        json_responses=[
            _draft("SELECT id, name FROM users LIMIT 1"),
            _draft("SELECT id FROM orders LIMIT 1"),
            _draft("SELECT id, name, email FROM users LIMIT 1"),
        ],
        stream_responses=[["User 1"]],
    )
    p1 = _payloads(await _plan("Show a user", client), "preview")[0]
    await _run(p1["turn_id"], client)
    conv_id = p1["conversation_id"]

    p2 = _payloads(await _plan("Show an order", client, conversation_id=conv_id), "preview")[0]
    await cancel_turn(p2["turn_id"])

    await _plan("Now also include their email", client, conversation_id=conv_id)
    assert len(await get_recent_turns(conv_id, limit=5)) == 3

    system_prompt = client.recorded_chat_calls[2]["messages"][0]["content"]
    assert "### CONVERSATION HISTORY:" in system_prompt
    assert "Show a user" in system_prompt
    assert "Show an order" not in system_prompt


@pytest.mark.asyncio
async def test_http_endpoints_preview_run_cancel() -> None:
    fake_client = FakeLLMClient(
        json_responses=[
            _draft("SELECT id, name FROM categories LIMIT 2"),
            _draft("SELECT id FROM categories LIMIT 1"),
        ],
        stream_responses=[["Categories: ", "Electronics"]],
    )
    app.dependency_overrides[get_chat_llm_client] = lambda: fake_client
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            resp = await http.post("/api/chat", json={"message": "Show categories"})
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            preview = _payloads(parse_sse_events(resp.text), "preview")[0]

            run = await http.post(f"/api/chat/{preview['turn_id']}/run", json={})
            ran = parse_sse_events(run.text)
            assert _payloads(ran, "result") and _payloads(ran, "done")

            conv = await http.get(f"/api/conversations/{preview['conversation_id']}")
            turn = conv.json()["turns"][0]
            assert turn["status"] == "done"
            assert turn["queries"][0]["explain"]["tables"]

            resp2 = await http.post(
                "/api/chat",
                json={"message": "One", "conversation_id": preview["conversation_id"]},
            )
            p2 = _payloads(parse_sse_events(resp2.text), "preview")[0]
            assert (await http.post(f"/api/chat/{p2['turn_id']}/cancel")).status_code == 204
            assert (await http.post(f"/api/chat/{p2['turn_id']}/cancel")).status_code == 409
    finally:
        app.dependency_overrides.pop(get_chat_llm_client, None)


@pytest.mark.asyncio
async def test_delete_request_refused_without_llm_or_sql() -> None:
    client = FakeLLMClient()
    planned = await _plan("Delete the user Adrian Opris", client)
    assert [e[0] for e in planned] == ["refused"]
    refused = planned[0][1]
    assert refused["message"].startswith("Not performed")
    assert client.recorded_chat_calls == []  # never reached the model

    turn = await get_turn(refused["turn_id"])
    assert turn is not None and turn.status == "refused"
    entries = await list_audit_entries(turn_id=refused["turn_id"])
    assert [e["stage"] for e in entries] == ["refused"]


@pytest.mark.asyncio
async def test_model_write_intent_refused() -> None:
    client = FakeLLMClient(
        json_responses=[{"queries": [], "write_intent": True, "reasoning": "delete"}]
    )
    planned = await _plan("Get rid of inactive clients from the system", client)
    assert [e[0] for e in planned] == ["status", "refused"]


@pytest.mark.asyncio
async def test_preview_flags_blocked_unsafe_draft_and_audit_stages() -> None:
    client = FakeLLMClient(
        json_responses=[
            _draft("DELETE FROM users WHERE id = 1"),
            _draft("SELECT id, name FROM users WHERE id = 1"),
        ],
        stream_responses=[["ok"]],
    )
    planned = await _plan("Show me user number one", client)
    preview = _payloads(planned, "preview")[0]
    risk = preview["queries"][0]["risk"]
    assert risk["level"] == "high"
    assert risk["flags"][0]["code"] == "UNSAFE_DRAFT_BLOCKED"

    await _run(preview["turn_id"], client, overrides=["SELECT id FROM users WHERE id = 1"])
    stages = [e["stage"] for e in reversed(await list_audit_entries(turn_id=preview["turn_id"]))]
    assert stages == ["rejected", "validated", "edited", "validated", "executed"]
    executed = (await list_audit_entries(turn_id=preview["turn_id"]))[0]
    assert executed["row_count"] == 1 and executed["elapsed_ms"] is not None

    log_lines = Path(get_settings().SQL_LOG_PATH).read_text().strip().splitlines()
    logged = [json.loads(line) for line in log_lines]
    assert any(e["stage"] == "executed" and e["turn_id"] == preview["turn_id"] for e in logged)


@pytest.mark.asyncio
async def test_audit_endpoint() -> None:
    fake_client = FakeLLMClient()
    app.dependency_overrides[get_chat_llm_client] = lambda: fake_client
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            await http.post("/api/chat", json={"message": "delete user"})
            resp = await http.get("/api/audit", params={"limit": 5})
            assert resp.status_code == 200
            first = resp.json()[0]
            assert first["stage"] == "refused"
            assert first["question"] == "delete user"
    finally:
        app.dependency_overrides.pop(get_chat_llm_client, None)
