"""Prompt templates and builders for SQL generation, repair, and answer synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "v1.0"


@dataclass
class TurnHistory:
    """Historical conversation turn used for few-shot context."""

    question: str
    sql: str | None = None
    result_summary: str | None = None

    def to_history_str(self) -> str:
        """Format turn history line: Q: ... / SQL: ... / Result: ..."""
        sql_part = self.sql if self.sql else "N/A"
        res_part = self.result_summary if self.result_summary else "N/A"
        return f"Q: {self.question} / SQL: {sql_part} / Result: {res_part}"


def format_markdown_table(columns: list[str], rows: list[list[Any]]) -> str:
    """Render columns and rows into a compact GitHub-flavored markdown table."""
    if not columns:
        return "(No columns)"
    if not rows:
        sep = " | ".join(["---"] * len(columns))
        return f"| {' | '.join(columns)} |\n| {sep} |\n(0 rows returned)"

    header = f"| {' | '.join(columns)} |"
    separator = f"| {' | '.join(['---'] * len(columns))} |"
    data_lines = [
        f"| {' | '.join(str(cell) if cell is not None else 'NULL' for cell in row)} |"
        for row in rows
    ]
    return "\n".join([header, separator, *data_lines])


def build_sql_prompt(
    question: str,
    history: list[TurnHistory],
    schema_text: str,
    today_date: str,
) -> list[dict[str, str]]:
    """Build system and user messages for SQL generation."""
    system_parts = [
        "You are an expert MySQL database analyst generating SQL queries for MySQL 9.0.",
        "",
        "### STRICT RULES:",
        "1. Generate strictly a single, read-only SELECT statement.",
        "2. Use ONLY the tables and column names provided in the DATABASE SCHEMA below.",
        "3. Always qualify ambiguous column names with table names or explicit aliases.",
        "4. Prefer explicit JOIN syntax (INNER JOIN, LEFT JOIN) with explicit ON clauses.",
        "5. For 'top N' or 'most/least' questions, use ORDER BY with an appropriate LIMIT.",
        f"6. Today's date is {today_date}. Use this date for any relative date calculations.",
        "7. If ambiguous, set `needs_clarification: true` and specify `clarification_question`.",
        "",
        "### DATABASE SCHEMA:",
        schema_text,
        "",
        "### FEW-SHOT EXAMPLES:",
        "- Example 1 (Top N with Join):",
        "  User: 'Top 5 users by total revenue'",
        (
            '  JSON Response: {"sql": "SELECT u.id, u.name, SUM(o.total_amount) AS total_spent '
            "FROM users u JOIN orders o ON u.id = o.user_id WHERE o.status IN ('completed', "
            "'shipped') GROUP BY u.id, u.name ORDER BY total_spent DESC LIMIT 5;\", "
            '"reasoning": "Join users with completed orders, sum revenue, order desc, limit 5.", '
            '"needs_clarification": false, "clarification_question": null}'
        ),
        "",
        "- Example 2 (Date Aggregation):",
        "  User: 'Monthly revenue in 2025'",
        (
            '  JSON Response: {"sql": "SELECT DATE_FORMAT(created_at, \'%Y-%m\') AS month, '
            "SUM(total_amount) AS revenue FROM orders WHERE created_at >= '2025-01-01' AND "
            "created_at < '2026-01-01' AND status IN ('completed', 'shipped') "
            'GROUP BY month ORDER BY month;", "reasoning": "Filter 2025 orders, group by month.", '
            '"needs_clarification": false, "clarification_question": null}'
        ),
        "",
        "- Example 3 (Clarification Request):",
        "  User: 'Show me the report'",
        (
            '  JSON Response: {"sql": null, "reasoning": "The request is too vague.", '
            '"needs_clarification": true, "clarification_question": '
            '"Could you clarify which report you would like to view?"}'
        ),
    ]

    if history:
        system_parts.append("")
        system_parts.append("### CONVERSATION HISTORY:")
        for turn in history:
            system_parts.append(turn.to_history_str())

    user_content = f"Today is {today_date}.\nQuestion: {question}"

    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": user_content},
    ]


def build_repair_prompt(
    question: str,
    bad_sql: str,
    error_message: str,
    schema_text: str,
) -> list[dict[str, str]]:
    """Build repair prompt providing the bad SQL and exact validation or DB error."""
    system_content = (
        "You are an expert MySQL database analyst repairing a failed SQL query for MySQL 9.0.\n"
        "Analyze the error, verify against DATABASE SCHEMA, and generate corrected SQL.\n\n"
        "### DATABASE SCHEMA:\n"
        f"{schema_text}"
    )

    user_content = (
        f"Original User Question: {question}\n\n"
        f"Previously Generated SQL:\n```sql\n{bad_sql}\n```\n\n"
        f"Error Encountered:\n{error_message}\n\n"
        "Please fix the error and return corrected JSON adhering to the specified schema."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def build_answer_prompt(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    row_count: int,
    truncated: bool,
) -> list[dict[str, str]]:
    """Build answer prompt grounded strictly in result rows."""
    system_content = (
        "You are a concise, helpful data analyst explaining database results to a user.\n\n"
        "### RULES:\n"
        "1. Ground your answer strictly on the provided query results.\n"
        "2. Cite exact figures, names, and metrics directly from the rows.\n"
        "3. Do not invent or assume data that is not in the results.\n"
        "4. If 0 rows were returned, state clearly that no matching records were found.\n"
        "5. If truncated is true, explicitly state that results show the first rows.\n"
        "6. Keep your answer brief, clear, and professional."
    )

    table_md = format_markdown_table(columns, rows)
    truncation_note = (
        "Note: Results were truncated to the maximum limit."
        if truncated
        else "All matching rows are shown."
    )

    user_content = (
        f"User Question: {question}\n\n"
        f"Executed SQL:\n```sql\n{sql}\n```\n\n"
        f"Query Results ({row_count} rows, {truncation_note}):\n"
        f"{table_md}\n\n"
        "Please provide a clear, concise answer summarizing these findings."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
