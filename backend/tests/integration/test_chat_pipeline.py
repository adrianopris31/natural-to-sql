"""Integration tests for end-to-end chat pipeline and SSE streaming."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.chat import get_chat_llm_client
from app.config import get_settings
from app.core.db import get_engine
from app.core.schema import get_schema_cache
from app.llm.client import FakeLLMClient
from app.main import app
from app.services.chat import process_chat
from app.store.database import (
    close_app_db,
    get_conversation,
    get_recent_turns,
    init_app_db,
)


@pytest.fixture(autouse=True)
async def setup_test_store(tmp_path: Path) -> Path:
    """Ensure clean isolated SQLite database for each pipeline test."""
    await close_app_db()
    db_file = tmp_path / "test_chat.db"
    await init_app_db(str(db_file))
    yield db_file
    await close_app_db()


def parse_sse_events(raw_sse: str) -> list[tuple[str, Any]]:
    """Parse raw SSE text into list of (event_type, payload_dict)."""
    events: list[tuple[str, Any]] = []
    blocks = raw_sse.strip().split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
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


@pytest.mark.asyncio
async def test_chat_pipeline_empty_message() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()
    client = FakeLLMClient()

    events_raw = [
        event
        async for event in process_chat(
            message="   ",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]

    parsed = parse_sse_events("".join(events_raw))
    assert len(parsed) == 1
    assert parsed[0][0] == "error"
    assert parsed[0][1]["code"] == "EMPTY_MESSAGE"


@pytest.mark.asyncio
async def test_chat_pipeline_happy_path() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    sql_response = {
        "sql": "SELECT id, name FROM users ORDER BY id ASC LIMIT 2",
        "reasoning": "Fetch the first two users ordered by id",
        "assumptions": ["Sorted ascending"],
        "needs_clarification": False,
        "clarification_question": None,
    }
    client = FakeLLMClient(
        json_responses=[sql_response],
        stream_responses=[["Here ", "are ", "the users."]],
    )

    events_raw = [
        event
        async for event in process_chat(
            message="List 2 users",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]

    parsed = parse_sse_events("".join(events_raw))
    event_names = [e[0] for e in parsed]

    # Verify event sequencing
    assert "status" in event_names
    assert "sql" in event_names
    assert "result" in event_names
    assert "answer_delta" in event_names
    assert "done" in event_names

    # Verify status sequence
    statuses = [e[1] for e in parsed if e[0] == "status"]
    assert statuses == ["generating_sql", "validating", "executing", "answering"]

    # Verify SQL payload
    sql_events = [e[1] for e in parsed if e[0] == "sql"]
    assert len(sql_events) == 1
    assert "SELECT" in sql_events[0]
    assert "users" in sql_events[0]

    # Verify Result payload
    result_events = [e[1] for e in parsed if e[0] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["row_count"] == 2
    assert "id" in result_events[0]["columns"]
    assert "name" in result_events[0]["columns"]

    # Verify Answer tokens
    answer_deltas = [e[1] for e in parsed if e[0] == "answer_delta"]
    assert "".join(answer_deltas) == "Here are the users."

    # Verify Done event
    done_events = [e[1] for e in parsed if e[0] == "done"]
    assert len(done_events) == 1
    conv_id = done_events[0]["conversation_id"]
    turn_id = done_events[0]["turn_id"]
    assert "timings" in done_events[0]

    # Verify persistence in SQLite
    conv = await get_conversation(conv_id)
    assert conv is not None
    assert conv.title == "List 2 users"
    assert len(conv.turns) == 1

    turn = conv.turns[0]
    assert turn.id == turn_id
    assert turn.status == "done"
    assert turn.sql is not None
    assert turn.answer == "Here are the users."
    assert turn.row_count == 2


@pytest.mark.asyncio
async def test_chat_pipeline_clarification() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    clarification_response = {
        "sql": None,
        "reasoning": "Unclear time period",
        "assumptions": [],
        "needs_clarification": True,
        "clarification_question": "Which year would you like sales figures for?",
    }
    client = FakeLLMClient(json_responses=[clarification_response])

    events_raw = [
        event
        async for event in process_chat(
            message="Show sales",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]

    parsed = parse_sse_events("".join(events_raw))
    event_names = [e[0] for e in parsed]

    assert event_names == ["status", "clarification", "done"]
    assert parsed[1][1]["question"] == "Which year would you like sales figures for?"

    conv_id = parsed[2][1]["conversation_id"]
    conv = await get_conversation(conv_id)
    assert conv is not None
    assert conv.turns[0].status == "clarification"
    assert conv.turns[0].error == "Which year would you like sales figures for?"


@pytest.mark.asyncio
async def test_chat_pipeline_repair_success() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    # Attempt 0: Invalid SQL (table does not exist in schema)
    bad_draft = {
        "sql": "SELECT * FROM secret_admin_vault",
        "reasoning": "Attempting invalid table",
        "assumptions": [],
        "needs_clarification": False,
        "clarification_question": None,
    }
    # Attempt 1 (repair): Valid SQL
    good_repair = {
        "sql": "SELECT id, name FROM users LIMIT 1",
        "reasoning": "Fixed table to users",
        "assumptions": [],
        "needs_clarification": False,
        "clarification_question": None,
    }

    client = FakeLLMClient(
        json_responses=[bad_draft, good_repair],
        stream_responses=[["Found ", "user."]],
    )

    events_raw = [
        event
        async for event in process_chat(
            message="Show admin user",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]

    parsed = parse_sse_events("".join(events_raw))
    event_names = [e[0] for e in parsed]

    # Verify repairing status event was emitted
    statuses = [e[1] for e in parsed if e[0] == "status"]
    assert "repairing" in statuses
    assert "done" in event_names

    # Check conversation turn succeeded
    done_payload = next(e[1] for e in parsed if e[0] == "done")
    conv = await get_conversation(done_payload["conversation_id"])
    assert conv is not None
    assert conv.turns[0].status == "done"
    assert "users" in (conv.turns[0].sql or "")


@pytest.mark.asyncio
async def test_chat_pipeline_repair_exhausted() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    # Rejection repeatedly (DROP statement rejected by validator)
    bad_draft = {
        "sql": "DROP TABLE users",
        "reasoning": "Destructive query",
        "assumptions": [],
        "needs_clarification": False,
        "clarification_question": None,
    }

    client = FakeLLMClient(
        json_responses=[bad_draft, bad_draft, bad_draft],
    )

    events_raw = [
        event
        async for event in process_chat(
            message="Delete users",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]

    parsed = parse_sse_events("".join(events_raw))
    event_names = [e[0] for e in parsed]

    assert "error" in event_names
    error_event = next(e[1] for e in parsed if e[0] == "error")
    assert error_event["code"] == "VALIDATION_FAILED"
    assert "safety" in error_event["message"]


@pytest.mark.asyncio
async def test_chat_pipeline_multi_turn_history() -> None:
    settings = get_settings()
    engine = get_engine()
    schema_cache = get_schema_cache()

    client = FakeLLMClient(
        json_responses=[
            {
                "sql": "SELECT id, name FROM users LIMIT 1",
                "reasoning": "Turn 1",
                "assumptions": [],
                "needs_clarification": False,
                "clarification_question": None,
            },
            {
                "sql": "SELECT id, name, email FROM users LIMIT 1",
                "reasoning": "Turn 2 follow up",
                "assumptions": [],
                "needs_clarification": False,
                "clarification_question": None,
            },
        ],
        stream_responses=[["User 1"], ["User 1 with email"]],
    )

    # Turn 1
    events1 = [
        event
        async for event in process_chat(
            message="Show a user",
            conversation_id=None,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]
    parsed1 = parse_sse_events("".join(events1))
    conv_id = next(e[1] for e in parsed1 if e[0] == "done")["conversation_id"]

    # Turn 2 with same conversation_id
    events2 = [
        event
        async for event in process_chat(
            message="Now also include their email",
            conversation_id=conv_id,
            client=client,
            engine=engine,
            schema_cache=schema_cache,
            settings=settings,
        )
    ]
    parsed2 = parse_sse_events("".join(events2))
    assert any(e[0] == "done" for e in parsed2)

    # Verify conversation in SQLite has 2 turns
    recent_turns = await get_recent_turns(conv_id, limit=5)
    assert len(recent_turns) == 2
    assert recent_turns[0].question == "Show a user"
    assert recent_turns[1].question == "Now also include their email"

    # Verify the second LLM prompt included the history in system instructions
    assert len(client.recorded_chat_calls) == 2
    turn2_messages = client.recorded_chat_calls[1]["messages"]
    system_prompt = turn2_messages[0]["content"]
    assert "### CONVERSATION HISTORY:" in system_prompt
    assert "Show a user" in system_prompt


@pytest.mark.asyncio
async def test_chat_endpoint_http_sse() -> None:
    sql_response = {
        "sql": "SELECT id, name FROM categories LIMIT 2",
        "reasoning": "Fetch categories",
        "assumptions": [],
        "needs_clarification": False,
        "clarification_question": None,
    }
    fake_client = FakeLLMClient(
        json_responses=[sql_response],
        stream_responses=[["Categories: ", "Electronics"]],
    )

    app.dependency_overrides[get_chat_llm_client] = lambda: fake_client
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "Show categories"},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = parse_sse_events(resp.text)
            event_types = [e[0] for e in events]
            assert "status" in event_types
            assert "sql" in event_types
            assert "result" in event_types
            assert "answer_delta" in event_types
            assert "done" in event_types
    finally:
        app.dependency_overrides.pop(get_chat_llm_client, None)
