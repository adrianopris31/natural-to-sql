"""Integration tests for documentation Q&A pipeline via knowledge-bot."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aiosqlite
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import app
from app.store.database import (
    close_app_db,
    get_conversation,
    get_turn,
    init_app_db,
)


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path: Path) -> Path:
    """Initialize a fresh SQLite test database for each test."""
    await close_app_db()
    db_path = tmp_path / "test_docs_pipeline.db"
    await init_app_db(str(db_path))
    yield db_path
    await close_app_db()


def _parse_sse(text: str) -> list[tuple[str, Any]]:
    """Parse raw SSE text into a list of (event_name, data)."""
    events: list[tuple[str, Any]] = []
    blocks = [b for b in text.split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.split("\n")
        event_name = "message"
        data_lines = []
        for line in lines:
            if line.startswith(":"):
                continue
            if line.startswith("event: "):
                event_name = line[len("event: ") :].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        if data_lines:
            raw = "\n".join(data_lines)
            try:
                events.append((event_name, json.loads(raw)))
            except Exception:
                events.append((event_name, raw))
    return events


@pytest.mark.asyncio
@respx.mock
async def test_docs_chat_stream_success() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_testkey",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": "Here is the information from Slack thread #general.",
            "sources": [
                {
                    "id": "slack-123",
                    "source_type": "slack",
                    "title": "Release schedule announcement",
                    "url": "https://slack.com/archives/C123/p456",
                    "score": 0.88,
                }
            ],
            "refused": False,
            "model": "gpt-4o",
            "filter": "slack",
            "documents_searched": 5,
        },
    )

    transport = ASGITransport(app=app)
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "slack: What is the release schedule?", "mode": "docs"},
            )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e[0] for e in events]

    assert "status" in event_names
    assert "docs_answer" in event_names
    assert "done" in event_names
    assert "preview" not in event_names

    # Check status payload
    status_events = [e[1] for e in events if e[0] == "status"]
    assert status_events == ["searching_docs"]

    # Check docs_answer payload
    docs_payload = next(e[1] for e in events if e[0] == "docs_answer")
    assert docs_payload["answer"] == "Here is the information from Slack thread #general."
    assert len(docs_payload["sources"]) == 1
    assert docs_payload["sources"][0]["id"] == "slack-123"
    assert docs_payload["refused"] is False

    # Check done payload
    done_payload = next(e[1] for e in events if e[0] == "done")
    turn_id = done_payload["turn_id"]
    conv_id = done_payload["conversation_id"]
    assert turn_id and conv_id

    # Verify persisted turn in app.db
    turn = await get_turn(turn_id)
    assert turn is not None
    assert turn.kind == "docs"
    assert turn.status == "done"
    assert turn.sql is None
    assert turn.answer == "Here is the information from Slack thread #general."
    assert turn.sources_json is not None
    stored_sources = json.loads(turn.sources_json)
    assert stored_sources[0]["id"] == "slack-123"


@pytest.mark.asyncio
@respx.mock
async def test_docs_turn_persists_and_reloads_via_conversations_api() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_testkey",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": "Documented in onboarding guide.",
            "sources": [
                {
                    "id": "doc-456",
                    "source_type": "doc",
                    "title": "Onboarding Guide",
                    "url": "https://wiki.example.com/onboarding",
                    "score": 0.92,
                }
            ],
            "refused": False,
            "model": "gpt-4o",
            "filter": "",
            "documents_searched": 12,
        },
    )

    transport = ASGITransport(app=app)
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "Where is the onboarding guide?", "mode": "docs"},
            )
            assert resp.status_code == 200
            events = _parse_sse(resp.text)
            done_payload = next(e[1] for e in events if e[0] == "done")
            conv_id = done_payload["conversation_id"]

            # Reload via GET /api/conversations/{id}
            get_resp = await client.get(f"/api/conversations/{conv_id}")
            assert get_resp.status_code == 200
            detail = get_resp.json()
            assert detail["id"] == conv_id
            assert len(detail["turns"]) == 1

            turn = detail["turns"][0]
            assert turn["kind"] == "docs"
            assert turn["question"] == "Where is the onboarding guide?"
            assert turn["answer"] == "Documented in onboarding guide."
            assert turn["sources"] == [
                {
                    "id": "doc-456",
                    "source_type": "doc",
                    "title": "Onboarding Guide",
                    "url": "https://wiki.example.com/onboarding",
                    "score": 0.92,
                }
            ]
            assert turn["sql"] is None


@pytest.mark.asyncio
@respx.mock
async def test_mixed_conversation_reloads_correctly() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_testkey",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": "Sprint starts every Monday.",
            "sources": [],
            "refused": False,
            "model": "gpt-4o",
            "filter": "",
            "documents_searched": 8,
        },
    )

    from app.store.database import create_conversation, create_turn, update_turn

    conv = await create_conversation(title="Mixed conversation")

    # Turn 1: SQL turn
    sql_turn = await create_turn(
        conversation_id=conv.id,
        question="Count all users",
        kind="sql",
        status="done",
    )
    await update_turn(
        turn_id=sql_turn.id,
        sql="SELECT count(*) FROM users",
        columns_json=json.dumps(["count"]),
        rows_json=json.dumps([[100]]),
        row_count=1,
        truncated=False,
        answer="There are 100 users.",
    )

    # Turn 2: Docs turn in the same conversation
    transport = ASGITransport(app=app)
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={
                    "conversation_id": conv.id,
                    "message": "When does sprint start?",
                    "mode": "docs",
                },
            )
            assert resp.status_code == 200

            # Reload conversation
            conv_resp = await client.get(f"/api/conversations/{conv.id}")
            assert conv_resp.status_code == 200
            data = conv_resp.json()
            assert len(data["turns"]) == 2

            t1, t2 = data["turns"][0], data["turns"][1]
            assert t1["kind"] == "sql"
            assert t1["sql"] == "SELECT count(*) FROM users"
            assert t1["answer"] == "There are 100 users."

            assert t2["kind"] == "docs"
            assert t2["question"] == "When does sprint start?"
            assert t2["answer"] == "Sprint starts every Monday."
            assert t2["sql"] is None


@pytest.mark.asyncio
@respx.mock
async def test_docs_turn_run_and_cancel_return_409() -> None:
    settings = Settings(
        _env_file=None,
        KNOWLEDGE_BOT_URL="http://127.0.0.1:8100",
        KNOWLEDGE_BOT_API_KEY="kb_live_testkey",
    )
    respx.post("http://127.0.0.1:8100/v1/ask").respond(
        status_code=200,
        json={
            "answer": "Docs answer",
            "sources": [],
            "refused": False,
            "model": "gpt-4o",
            "filter": "",
            "documents_searched": 1,
        },
    )

    transport = ASGITransport(app=app)
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "Sample docs question", "mode": "docs"},
            )
            assert resp.status_code == 200
            events = _parse_sse(resp.text)
            done = next(e[1] for e in events if e[0] == "done")
            turn_id = done["turn_id"]

            # /run on docs turn -> 409
            run_resp = await client.post(f"/api/chat/{turn_id}/run", json={})
            assert run_resp.status_code == 409

            # /cancel on docs turn -> 409
            cancel_resp = await client.post(f"/api/chat/{turn_id}/cancel")
            assert cancel_resp.status_code == 409


@pytest.mark.asyncio
async def test_docs_chat_error_when_not_configured() -> None:
    settings = Settings(_env_file=None, KNOWLEDGE_BOT_API_KEY="")

    transport = ASGITransport(app=app)
    with patch("app.integrations.knowledge_bot.get_settings", return_value=settings):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "Any question", "mode": "docs"},
            )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_names = [e[0] for e in events]
    assert "error" in event_names

    err_payload = next(e[1] for e in events if e[0] == "error")
    assert err_payload["code"] == "DOCS_NOT_CONFIGURED"
    assert "not configured" in err_payload["message"].lower()


@pytest.mark.asyncio
async def test_migration_adds_columns_to_existing_db(tmp_path: Path) -> None:
    old_db_file = tmp_path / "legacy_app.db"

    # Create older schema directly with sqlite3
    async with aiosqlite.connect(old_db_file) as conn:
        await conn.execute(
            """
            CREATE TABLE conversations (
                id VARCHAR(36) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE turns (
                id VARCHAR(36) PRIMARY KEY,
                conversation_id VARCHAR(36) NOT NULL,
                question TEXT NOT NULL,
                sql TEXT,
                columns_json TEXT,
                rows_json TEXT,
                queries_json TEXT,
                row_count INTEGER,
                truncated BOOLEAN,
                answer TEXT,
                status VARCHAR(50) NOT NULL,
                error TEXT,
                prompt_version VARCHAR(50) NOT NULL DEFAULT 'v1.0',
                timings_json TEXT,
                created_at DATETIME NOT NULL
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE audit_log (
                id VARCHAR(36) PRIMARY KEY,
                turn_id VARCHAR(36),
                attempt INTEGER NOT NULL,
                raw_sql TEXT,
                safe_sql TEXT,
                accepted BOOLEAN NOT NULL,
                reason TEXT,
                created_at DATETIME NOT NULL
            );
            """
        )
        await conn.execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES ('old-conv-1', 'Legacy Thread', datetime('now'), datetime('now'));
            """
        )
        await conn.execute(
            """
            INSERT INTO turns (id, conversation_id, question, status, created_at)
            VALUES ('old-turn-1', 'old-conv-1', 'Legacy question', 'done', datetime('now'));
            """
        )
        await conn.commit()

    # Now run init_app_db against the existing legacy database
    await close_app_db()
    await init_app_db(str(old_db_file))

    # Verify columns were added and old rows read as kind='sql'
    async with aiosqlite.connect(old_db_file) as conn:
        async with conn.execute("PRAGMA table_info(turns)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
            assert "kind" in columns
            assert "sources_json" in columns

        query = "SELECT kind, sources_json FROM turns WHERE id = 'old-turn-1'"
        async with conn.execute(query) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "sql"
            assert row[1] is None

    # Verify through ORM get_conversation
    conv = await get_conversation("old-conv-1")
    assert conv is not None
    assert len(conv.turns) == 1
    assert conv.turns[0].kind == "sql"
    assert conv.turns[0].sources_json is None

    await close_app_db()
