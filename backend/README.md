# 🛠️ Natural-to-SQL Backend

FastAPI asynchronous backend powering the Natural-to-SQL system.

## Features
- **FastAPI + Pydantic v2**: High performance, strictly typed endpoints.
- **SQL Safety Layer (`app/core/validator.py`)**: Multi-stage AST analysis using `sqlglot`.
- **MySQL EXPLAIN Gate (`app/core/explain.py`)**: Cost and scan row estimation prior to execution.
- **Ollama Integration (`app/llm/`)**: Structured JSON SQL generation and streaming grounded answers using `qwen2.5-coder:7b`.
- **Dual Audit Logging**: Full audit trail stored in SQLite (`app.db`) and mirrored to JSONL (`sql_log.jsonl`).

## Quickstart (Development)

```bash
# Sync virtualenv and dependencies
uv sync

# Run development server
uv run uvicorn app.main:app --reload --port 8000
```

- Interactive OpenAPI Swagger Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

## Testing & Quality Gates

```bash
# Run all unit, security, and integration tests
uv run pytest

# Check security attack corpus
uv run pytest tests/security -v

# Run code style, format, and type checks
uv run ruff check .
uv run ruff format --check .
uv run mypy app
```
