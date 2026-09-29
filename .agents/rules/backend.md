---
trigger: glob
globs: backend/**, infra/**
description: Backend subagent rules (FastAPI, SQL safety, Ollama, MySQL)
---

# Backend Agent Rules

**Scope**: `backend/`, `infra/`. Source of truth: `PLAN.md` §2–§7. Read `PROGRESS.md` before you start and update it when you finish.

## Stack & style
- Python 3.12, **uv** only (`uv add`, `uv run`). Never use pip or a global install.
- FastAPI + Pydantic v2. Type everything. `mypy --strict` must be clean on `app/`. `ruff check` and `ruff format` must be clean.
- Async all the way: SQLAlchemy async (asyncmy for the target DB, aiosqlite for app.db) and `httpx.AsyncClient` for Ollama. Never block the event loop.
- Layering: `api/` (HTTP/SSE only) → `services/` (orchestration) → `core/` (DB, schema, validator, executor) and `llm/` (client, prompts, generator, answerer) and `store/` (app.db). `core/` and `llm/` never import from `api/`.
- Config comes only from `app/config.py` Settings. No `os.getenv` anywhere else. Add every new key to `.env.example` and to PLAN.md §6.
- Custom exceptions live in `app/errors.py` (`ValidationError`, `ExecutionError`, `LLMError`, `SchemaError`), and each is mapped to a friendly message in one place.
- Logging: the stdlib `logging` with structured `extra=`. Log the generated SQL and the validation result. Never log credentials or full result rows.

## SQL safety: hard rules
1. The **only** path to the target DB for LLM-generated SQL is `validator.validate()` → `executor.run(safe_sql)`. `executor.run` accepts only a `SafeSQL` type (a NewType or frozen dataclass that only the validator can construct).
2. Execute the **re-rendered** AST SQL, never the raw LLM string.
3. Never string-format user or LLM input into SQL. Internal queries (introspection, sample values) use bound parameters, and identifiers come from the introspected schema only.
4. Every execution: `START TRANSACTION READ ONLY` → `SET SESSION max_execution_time` (ms; target is MySQL 9.0.1) → the query → fetch at most `MAX_ROWS+1` → `ROLLBACK`, always in `finally`.
5. Whenever you change the validator, add cases to `tests/security/attacks.yaml` or `safe.yaml` **in the same change**.
6. Don't loosen a rule to make an eval pass. Add a narrowly scoped allowlist entry instead, and log it in DECISIONS.

## LLM
- Every Ollama call goes through the `LLMClient` protocol, so tests use `FakeLLMClient`.
- Use `temperature: 0` for SQL generation. Use structured output (`format` = JSON schema) and validate it with Pydantic.
- Prompts live only in `llm/prompts.py`. Bump `PROMPT_VERSION` whenever you change a prompt, and re-run the evals (`uv run python -m evals.run`) when Ollama is available. Record the score in PROGRESS.md.
- The answer prompt gets at most `ANSWER_MAX_ROWS` rows, and it must be told about truncation and empty results.

## API
- The contract is PLAN.md §5. Change PLAN.md first, then the code, and tell the frontend in PROGRESS.md (OPEN/NEXT).
- SSE event names and payloads are exactly as in PLAN.md §2. Each event is `event: <name>\ndata: <json>\n\n`.
- The server binds to 127.0.0.1. CORS is limited to `CORS_ORIGINS`.

## Infra
- The dev DB is `mysql:9.0` (matching prod 9.0.1) on port **3307**, and the seed is deterministic (fixed RNG seed). `create_readonly_user.sql` must also work for the user's real DB (parametrize the DB name and the password placeholder).
- Ollama runs natively. Don't add it to docker-compose.

## Done checklist
`uv run ruff check . && uv run mypy app && uv run pytest` is green → PROGRESS.md is updated.
