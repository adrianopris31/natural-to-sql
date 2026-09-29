"""SQL generator calling LLM with structured output and repair capabilities."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.errors import LLMError
from app.llm.prompts import TurnHistory, build_repair_prompt, build_sql_prompt

if TYPE_CHECKING:
    from app.config import Settings
    from app.core.schema import SchemaModel
    from app.llm.client import LLMClient

logger = logging.getLogger(__name__)


class QueryDraft(BaseModel):
    """One independent SELECT with a short description of what it answers."""

    sql: str
    purpose: str = ""


class SqlDraft(BaseModel):
    """Structured LLM response: 1..MAX_QUERIES independent queries, or a clarification."""

    queries: list[QueryDraft] = Field(default_factory=list)
    reasoning: str = ""
    # True when the user asks to change data (delete/update/insert/...): the app refuses.
    write_intent: bool = False
    needs_clarification: bool = False
    clarification_question: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_single_sql(cls, data: Any) -> Any:
        """Accept the legacy/single shape {"sql": "..."} as one query."""
        if isinstance(data, dict) and "queries" not in data:
            data = dict(data)
            legacy_sql = data.pop("sql", None)
            data["queries"] = [{"sql": legacy_sql, "purpose": ""}] if legacy_sql else []
        return data

    @property
    def sql(self) -> str | None:
        """First query's SQL (single-query callers such as evals)."""
        return self.queries[0].sql if self.queries else None


async def generate(
    question: str,
    history: list[TurnHistory],
    schema: SchemaModel,
    client: LLMClient,
    settings: Settings,
    today_date: str | None = None,
) -> SqlDraft:
    """Generate SQL from natural language question with structured JSON validation and 1 retry."""
    date_str = today_date or datetime.date.today().isoformat()
    schema_text = schema.to_prompt()
    messages = build_sql_prompt(
        question=question,
        history=history,
        schema_text=schema_text,
        today_date=date_str,
        max_queries=settings.MAX_QUERIES,
    )
    json_schema = SqlDraft.model_json_schema()

    for attempt in range(2):
        try:
            raw_json = await client.chat_json(
                messages=messages,
                schema=json_schema,
                temperature=0.0,
            )
            draft = SqlDraft.model_validate(raw_json)
            if len(draft.queries) > settings.MAX_QUERIES:
                logger.warning(
                    "LLM returned %d queries; keeping first %d",
                    len(draft.queries),
                    settings.MAX_QUERIES,
                )
                draft.queries = draft.queries[: settings.MAX_QUERIES]
            return draft
        except (PydanticValidationError, LLMError) as exc:
            if attempt == 0:
                logger.warning(
                    "Initial SQL generation JSON validation failed, retrying once",
                    extra={"error": str(exc)},
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid JSON conforming to the schema. "
                            "Please return strictly valid JSON."
                        ),
                    }
                )
                continue
            raise LLMError(f"Failed to generate valid SQL structure: {exc}") from exc

    raise LLMError("Exhausted retries generating valid SQL draft")


async def repair(
    question: str,
    bad_sql: str,
    error_msg: str,
    schema: SchemaModel,
    client: LLMClient,
    settings: Settings,
) -> SqlDraft:
    """Request corrected SQL from the LLM based on specific error feedback."""
    _ = settings
    schema_text = schema.to_prompt()
    messages = build_repair_prompt(
        question=question,
        bad_sql=bad_sql,
        error_message=error_msg,
        schema_text=schema_text,
    )
    json_schema = SqlDraft.model_json_schema()

    for attempt in range(2):
        try:
            raw_json = await client.chat_json(
                messages=messages,
                schema=json_schema,
                temperature=0.0,
            )
            return SqlDraft.model_validate(raw_json)
        except (PydanticValidationError, LLMError) as exc:
            if attempt == 0:
                logger.warning(
                    "Repair JSON validation failed, retrying once",
                    extra={"error": str(exc)},
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was not valid JSON conforming to the schema. "
                            "Please return strictly valid JSON."
                        ),
                    }
                )
                continue
            raise LLMError(f"Failed to repair SQL structure: {exc}") from exc

    raise LLMError("Exhausted retries repairing SQL draft")
