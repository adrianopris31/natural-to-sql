"""Unit tests for SQLite conversation memory, turns, and audit logging."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.store.database import (
    close_app_db,
    create_conversation,
    create_turn,
    delete_conversation,
    get_conversation,
    get_recent_turns,
    init_app_db,
    list_conversations,
    record_audit_log,
    resolve_sqlite_url,
    update_turn,
)


@pytest.fixture(autouse=True)
async def setup_sqlite_db(tmp_path: Path) -> AsyncIterator[Path]:
    """Initialize an isolated SQLite database file for testing."""
    await close_app_db()
    db_file = tmp_path / "test_store.db"
    await init_app_db(str(db_file))
    yield db_file
    await close_app_db()


@pytest.mark.asyncio
async def test_resolve_sqlite_url() -> None:
    url = resolve_sqlite_url("/tmp/custom.db")
    assert url.startswith("sqlite+aiosqlite:////") or url.startswith("sqlite+aiosqlite:///")
    assert "custom.db" in url


@pytest.mark.asyncio
async def test_create_and_get_conversation() -> None:
    conv = await create_conversation(title="Test Thread 1")
    assert conv.id is not None
    assert conv.title == "Test Thread 1"

    fetched = await get_conversation(conv.id)
    assert fetched is not None
    assert fetched.id == conv.id
    assert fetched.title == "Test Thread 1"
    assert len(fetched.turns) == 0


@pytest.mark.asyncio
async def test_create_conversation_explicit_id() -> None:
    custom_id = "custom-uuid-1234"
    conv = await create_conversation(title="Explicit ID Thread", conversation_id=custom_id)
    assert conv.id == custom_id

    fetched = await get_conversation(custom_id)
    assert fetched is not None
    assert fetched.id == custom_id


@pytest.mark.asyncio
async def test_get_nonexistent_conversation() -> None:
    fetched = await get_conversation("non-existent-id")
    assert fetched is None


@pytest.mark.asyncio
async def test_list_conversations() -> None:
    conv1 = await create_conversation(title="Conv 1")
    conv2 = await create_conversation(title="Conv 2")

    convs = await list_conversations()
    assert len(convs) >= 2
    conv_ids = [c.id for c in convs]
    assert conv1.id in conv_ids
    assert conv2.id in conv_ids


@pytest.mark.asyncio
async def test_create_and_update_turn() -> None:
    conv = await create_conversation(title="Turn Thread")
    turn = await create_turn(
        conversation_id=conv.id,
        question="How many users signed up?",
        turn_id="turn-101",
    )
    assert turn.id == "turn-101"
    assert turn.conversation_id == conv.id
    assert turn.question == "How many users signed up?"
    assert turn.status == "generating_sql"

    updated = await update_turn(
        turn_id="turn-101",
        sql="SELECT COUNT(*) FROM users",
        columns_json=json.dumps(["COUNT(*)"]),
        rows_json=json.dumps([[42]]),
        row_count=1,
        truncated=False,
        answer="There are 42 users.",
        status="done",
    )
    assert updated is not None
    assert updated.sql == "SELECT COUNT(*) FROM users"
    assert updated.row_count == 1
    assert updated.answer == "There are 42 users."
    assert updated.status == "done"

    # Verify conversation.turns has this turn
    fetched_conv = await get_conversation(conv.id)
    assert fetched_conv is not None
    assert len(fetched_conv.turns) == 1
    assert fetched_conv.turns[0].id == "turn-101"


@pytest.mark.asyncio
async def test_update_nonexistent_turn() -> None:
    updated = await update_turn("does-not-exist", status="done")
    assert updated is None


@pytest.mark.asyncio
async def test_get_recent_turns() -> None:
    conv = await create_conversation(title="Multi-turn Thread")

    await create_turn(conv.id, "Question 1", turn_id="t1")
    await update_turn("t1", sql="SELECT 1", status="done")

    await create_turn(conv.id, "Question 2", turn_id="t2")
    await update_turn("t2", sql="SELECT 2", status="done")

    await create_turn(conv.id, "Question 3", turn_id="t3")
    await update_turn("t3", sql="SELECT 3", status="done")

    recent = await get_recent_turns(conv.id, limit=2)
    assert len(recent) == 2
    # Should be the 2 most recent, ordered chronologically (t2, then t3)
    assert recent[0].id == "t2"
    assert recent[1].id == "t3"


@pytest.mark.asyncio
async def test_delete_conversation_cascades() -> None:
    conv = await create_conversation(title="To Delete")
    await create_turn(conv.id, "Turn to delete", turn_id="del-turn-1")

    # Delete existing
    deleted = await delete_conversation(conv.id)
    assert deleted is True

    # Check conversation is gone
    assert await get_conversation(conv.id) is None

    # Check turns are gone
    turns = await get_recent_turns(conv.id, limit=10)
    assert len(turns) == 0

    # Delete non-existent
    deleted_again = await delete_conversation("already-deleted")
    assert deleted_again is False


@pytest.mark.asyncio
async def test_record_audit_log() -> None:
    log1 = await record_audit_log(
        turn_id="audit-turn-1",
        attempt=0,
        raw_sql="SELECT * FROM orders",
        safe_sql="SELECT * FROM orders LIMIT 501",
        accepted=True,
    )
    assert log1.id is not None
    assert log1.accepted is True
    assert log1.attempt == 0

    log2 = await record_audit_log(
        turn_id="audit-turn-1",
        attempt=1,
        raw_sql="DROP TABLE orders",
        safe_sql=None,
        accepted=False,
        reason="Disallowed statement type: Drop",
    )
    assert log2.id is not None
    assert log2.accepted is False
    assert log2.reason is not None
    assert "Drop" in log2.reason
