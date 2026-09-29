"""Unit tests for prompt templates and prompt building."""

from app.llm.prompts import (
    PROMPT_VERSION,
    TurnHistory,
    build_answer_prompt,
    build_repair_prompt,
    build_sql_prompt,
    format_markdown_table,
)


def test_prompt_version() -> None:
    assert PROMPT_VERSION == "v1.0"


def test_turn_history_formatting() -> None:
    turn = TurnHistory(
        question="How many users?",
        sql="SELECT count(*) FROM users;",
        result_summary="1 row, col: count",
    )
    expected = "Q: How many users? / SQL: SELECT count(*) FROM users; / Result: 1 row, col: count"
    assert turn.to_history_str() == expected


def test_format_markdown_table() -> None:
    cols = ["id", "name", "price"]
    rows = [[1, "Laptop", 999.99], [2, "Mouse", 29.99]]
    table_str = format_markdown_table(cols, rows)

    assert "| id | name | price |" in table_str
    assert "| 1 | Laptop | 999.99 |" in table_str
    assert "| 2 | Mouse | 29.99 |" in table_str


def test_format_markdown_table_empty() -> None:
    cols = ["id", "name"]
    table_str = format_markdown_table(cols, [])
    assert "(0 rows returned)" in table_str


def test_build_sql_prompt_without_history() -> None:
    messages = build_sql_prompt(
        question="Top 10 products",
        history=[],
        schema_text="products(id int [PK], name varchar(150))",
        today_date="2026-09-29",
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "MySQL 9.0" in messages[0]["content"]
    assert "products(id int [PK]" in messages[0]["content"]
    assert "### FEW-SHOT EXAMPLES:" in messages[0]["content"]
    assert "CONVERSATION HISTORY" not in messages[0]["content"]
    assert "Top 10 products" in messages[1]["content"]
    assert "Today is 2026-09-29" in messages[1]["content"]


def test_build_sql_prompt_with_history() -> None:
    history = [
        TurnHistory(
            question="Show active users",
            sql="SELECT * FROM users WHERE status = 'active';",
            result_summary="50 rows",
        )
    ]
    messages = build_sql_prompt(
        question="Which of them spent over $100?",
        history=history,
        schema_text="users(id int)",
        today_date="2026-09-29",
    )
    assert "### CONVERSATION HISTORY:" in messages[0]["content"]
    assert "Show active users" in messages[0]["content"]


def test_build_repair_prompt() -> None:
    messages = build_repair_prompt(
        question="Top users",
        bad_sql="SELECT * FROM unknown_table;",
        error_message="Table 'unknown_table' is not in the allowed schema",
        schema_text="users(id int, name varchar)",
    )
    assert len(messages) == 2
    assert "unknown_table" in messages[1]["content"]
    assert "not in the allowed schema" in messages[1]["content"]


def test_build_answer_prompt() -> None:
    cols = ["name", "revenue"]
    rows = [["Alice", 5000], ["Bob", 3000]]
    messages = build_answer_prompt(
        question="Who are the top users?",
        sql="SELECT name, revenue FROM top_users;",
        columns=cols,
        rows=rows,
        row_count=2,
        truncated=False,
    )
    assert len(messages) == 2
    assert "Alice" in messages[1]["content"]
    assert "Bob" in messages[1]["content"]
    assert "All matching rows are shown" in messages[1]["content"]
