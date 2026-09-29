"""Prompt templates and builders for SQL generation, repair, and answer synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "v1.2"


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
    max_queries: int = 3,
) -> list[dict[str, str]]:
    """Build system and user messages for SQL generation."""
    system_parts = [
        "You are an expert MySQL database analyst generating SQL queries for MySQL 9.0.",
        "",
        "### STRICT RULES:",
        "1. Every query must be a single, read-only SELECT statement (no semicolon-chained SQL).",
        "2. Use ONLY the tables and column names provided in the DATABASE SCHEMA below.",
        "3. Always qualify ambiguous column names with table names or explicit aliases.",
        "4. Prefer explicit JOIN syntax (INNER JOIN, LEFT JOIN) with explicit ON clauses.",
        "5. For 'top N' or 'most/least' questions, use ORDER BY with an appropriate LIMIT.",
        f"6. Today's date is {today_date}. Use this date for any relative date calculations.",
        "7. If ambiguous, set `needs_clarification: true` and specify `clarification_question`.",
        "8. Never use SELECT *; list the columns you need.",
        "9. Return `queries` as a list. Use ONE query whenever one query can answer the question.",
        f"   Use up to {max_queries} INDEPENDENT queries only when the question asks for",
        "   separate things that do not fit one result table. Each query must stand alone",
        "   (no query may depend on another's results). Give each a short `purpose`.",
        "10. This assistant is READ-ONLY. If the user asks to delete, update, insert, create,",
        "   drop or otherwise change data, set `write_intent: true`, return no queries, and",
        "   do NOT ask for confirmation (the change is impossible, not just risky).",
        "",
        "### DATABASE SCHEMA:",
        schema_text,
        "",
        "### FEW-SHOT EXAMPLES:",
        "- Example 1 (Top N with Join, one query):",
        "  User: 'Top 5 users by total revenue'",
        (
            '  JSON Response: {"queries": [{"sql": "SELECT u.id, u.name, SUM(o.total_amount) '
            "AS total_spent FROM users u JOIN orders o ON u.id = o.user_id WHERE o.status IN "
            "('completed', 'shipped') GROUP BY u.id, u.name ORDER BY total_spent DESC LIMIT 5\", "
            '"purpose": "Top 5 users by revenue"}], '
            '"reasoning": "Join users with completed orders, sum revenue, order desc, limit 5.", '
            '"needs_clarification": false, "clarification_question": null}'
        ),
        "",
        "- Example 2 (Two separate questions, two independent queries):",
        "  User: 'How many orders were placed in 2025, and which product is the most expensive?'",
        (
            '  JSON Response: {"queries": [{"sql": "SELECT COUNT(*) AS orders_2025 FROM orders '
            "WHERE created_at >= '2025-01-01' AND created_at < '2026-01-01'\", "
            '"purpose": "Orders placed in 2025"}, {"sql": "SELECT id, name, price FROM products '
            'ORDER BY price DESC LIMIT 1", "purpose": "Most expensive product"}], '
            '"reasoning": "Two unrelated facts, one query each.", '
            '"needs_clarification": false, "clarification_question": null}'
        ),
        "",
        "- Example 3 (Clarification Request):",
        "  User: 'Show me the report'",
        (
            '  JSON Response: {"queries": [], "reasoning": "The request is too vague.", '
            '"needs_clarification": true, "clarification_question": '
            '"Could you clarify which report you would like to view?"}'
        ),
        "",
        "- Example 4 (Request to change data, refused, no confirmation question):",
        "  User: 'Delete the user John Smith'",
        (
            '  JSON Response: {"queries": [], "reasoning": "Deleting data is not possible; '
            'the assistant is read-only.", "write_intent": true, '
            '"needs_clarification": false, "clarification_question": null}'
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
        "Fix the error and return corrected JSON adhering to the specified schema, with "
        "exactly ONE query in `queries` (never SELECT *)."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


@dataclass
class AnswerResult:
    """One executed query's outcome, as input to the answer prompt."""

    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    purpose: str = ""
    error: str | None = None


def build_answer_prompt(question: str, results: list[AnswerResult]) -> list[dict[str, str]]:
    """Build answer prompt grounded strictly in the result rows of one or more queries."""
    system_content = (
        "You are a concise, helpful data analyst explaining database results to a user.\n\n"
        "### RULES:\n"
        "1. Ground your answer strictly on the provided query results.\n"
        "2. Cite exact figures, names, and metrics directly from the rows.\n"
        "3. Do not invent or assume data that is not in the results.\n"
        "4. If 0 rows were returned, state clearly that no matching records were found.\n"
        "5. If truncated is true, explicitly state that results show the first rows.\n"
        "6. If a query failed, say that part could not be answered.\n"
        "7. When there are several queries, answer every part of the question in one reply.\n"
        "8. Keep your answer brief, clear, and professional."
    )

    sections: list[str] = []
    for i, res in enumerate(results, start=1):
        header = f"### Query {i}" + (f" — {res.purpose}" if res.purpose else "")
        if res.error:
            sections.append(f"{header}\n```sql\n{res.sql}\n```\nFAILED: {res.error}")
            continue
        truncation_note = (
            "Note: Results were truncated to the maximum limit."
            if res.truncated
            else "All matching rows are shown."
        )
        sections.append(
            f"{header}\n```sql\n{res.sql}\n```\n"
            f"Results ({res.row_count} rows, {truncation_note}):\n"
            f"{format_markdown_table(res.columns, res.rows)}"
        )

    user_content = (
        f"User Question: {question}\n\n"
        + "\n\n".join(sections)
        + "\n\nPlease provide a clear, concise answer summarizing these findings."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
