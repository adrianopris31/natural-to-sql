"""Unit tests for sql_generator.py."""

import pytest

from app.config import Settings
from app.core.schema import ColumnModel, SchemaModel, TableModel
from app.errors import LLMError
from app.llm.client import FakeLLMClient
from app.llm.sql_generator import SqlDraft, generate, repair


def _get_mock_schema() -> SchemaModel:
    return SchemaModel(
        tables=[
            TableModel(
                name="users",
                columns=[
                    ColumnModel(name="id", type="int", is_pk=True),
                    ColumnModel(name="name", type="varchar(100)"),
                ],
            )
        ]
    )


@pytest.mark.asyncio
async def test_generate_sql_happy_path() -> None:
    fake_client = FakeLLMClient(
        json_responses=[
            {
                "sql": "SELECT id, name FROM users;",
                "reasoning": "Simple select on users",
                "needs_clarification": False,
                "clarification_question": None,
            }
        ]
    )
    schema = _get_mock_schema()
    settings = Settings()

    draft = await generate(
        question="Show all users",
        history=[],
        schema=schema,
        client=fake_client,
        settings=settings,
    )
    assert isinstance(draft, SqlDraft)
    assert draft.sql == "SELECT id, name FROM users;"
    assert draft.needs_clarification is False


@pytest.mark.asyncio
async def test_generate_sql_clarification() -> None:
    fake_client = FakeLLMClient(
        json_responses=[
            {
                "sql": None,
                "reasoning": "Vague question",
                "needs_clarification": True,
                "clarification_question": "Which specific report do you need?",
            }
        ]
    )
    schema = _get_mock_schema()
    settings = Settings()

    draft = await generate(
        question="Give me report",
        history=[],
        schema=schema,
        client=fake_client,
        settings=settings,
    )
    assert draft.needs_clarification is True
    assert draft.sql is None
    assert "report do you need" in str(draft.clarification_question)


@pytest.mark.asyncio
async def test_generate_sql_retry_success() -> None:
    # First response invalid (wrong types), second response valid
    fake_client = FakeLLMClient(
        json_responses=[
            {"sql": 12345, "needs_clarification": "not_a_bool"},  # type mismatch
            {
                "sql": "SELECT * FROM users;",
                "reasoning": "Fixed JSON",
                "needs_clarification": False,
                "clarification_question": None,
            },
        ]
    )
    schema = _get_mock_schema()
    settings = Settings()

    draft = await generate(
        question="Users",
        history=[],
        schema=schema,
        client=fake_client,
        settings=settings,
    )
    assert draft.sql == "SELECT * FROM users;"
    assert len(fake_client.recorded_chat_calls) == 2


@pytest.mark.asyncio
async def test_generate_sql_retry_exhausted() -> None:
    fake_client = FakeLLMClient(
        json_responses=[
            {"sql": 12345, "needs_clarification": "not_a_bool"},
            {"sql": 67890, "needs_clarification": "not_a_bool"},
        ]
    )
    schema = _get_mock_schema()
    settings = Settings()

    with pytest.raises(LLMError, match="Failed to generate valid SQL structure"):
        await generate(
            question="Users",
            history=[],
            schema=schema,
            client=fake_client,
            settings=settings,
        )


@pytest.mark.asyncio
async def test_repair_sql_happy_path() -> None:
    fake_client = FakeLLMClient(
        json_responses=[
            {
                "sql": "SELECT id, name FROM users;",
                "reasoning": "Corrected column name",
                "needs_clarification": False,
                "clarification_question": None,
            }
        ]
    )
    schema = _get_mock_schema()
    settings = Settings()

    draft = await repair(
        question="Show users",
        bad_sql="SELECT bad_col FROM users;",
        error_msg="Unknown column 'bad_col'",
        schema=schema,
        client=fake_client,
        settings=settings,
    )
    assert draft.sql == "SELECT id, name FROM users;"


def test_sql_draft_accepts_legacy_single_sql_shape() -> None:
    draft = SqlDraft.model_validate({"sql": "SELECT 1", "needs_clarification": False})
    assert [q.sql for q in draft.queries] == ["SELECT 1"]
    assert draft.sql == "SELECT 1"


def test_sql_draft_multi_query_shape() -> None:
    draft = SqlDraft.model_validate(
        {
            "queries": [
                {"sql": "SELECT 1", "purpose": "a"},
                {"sql": "SELECT 2", "purpose": "b"},
            ]
        }
    )
    assert [q.purpose for q in draft.queries] == ["a", "b"]
    assert draft.sql == "SELECT 1"


@pytest.mark.asyncio
async def test_generate_caps_number_of_queries() -> None:
    from app.config import Settings

    client = FakeLLMClient(json_responses=[{"queries": [{"sql": f"SELECT {i}"} for i in range(5)]}])
    draft = await generate(
        question="q",
        history=[],
        schema=_get_mock_schema(),
        client=client,
        settings=Settings(MAX_QUERIES=2),
    )
    assert len(draft.queries) == 2
