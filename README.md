# Natural-to-SQL Assistant

A production-grade, local-first Natural Language to SQL analytics assistant built on MySQL 9.0, Ollama (`qwen2.5-coder:7b`), FastAPI, and Next.js 15.

---

## Architecture Overview

```
+-------------------------------------------------------------+
|                     Next.js 15 Frontend                     |
|  - Chat UI: status stepper, query PREVIEW with EXPLAIN,     |
|    Edit / Run / Cancel, per-query SQL + result tables       |
|  - Sticky ResultTable with CSV export & truncation          |
|  - Schema browser & conversation history sidebar            |
+------------------------------+------------------------------+
        POST /api/chat (SSE: plan → preview, never executes)
        POST /api/chat/{turn_id}/run (SSE: results → answer)
        POST /api/chat/{turn_id}/cancel
+------------------------------v------------------------------+
|                     FastAPI Async Backend                   |
|  - Conversation & turn memory in SQLite (aiosqlite)         |
|  - Schema cache & FK graph table selector                   |
|  - Structured generation of 1–3 independent SELECTs (Ollama)|
|  - Repair loop (≤2) on validation / EXPLAIN errors          |
|  - EXPLAIN FORMAT=JSON cost gate + human approval           |
|  - SSE heartbeat (": ping" every 10s)                       |
+------------------------------+------------------------------+
                               |
                 13-layer defense-in-depth (below)
                               |
+------------------------------v------------------------------+
|                    MySQL 9.0 Database                       |
|  - Dedicated read-only user (SELECT only)                   |
|  - START TRANSACTION READ ONLY session                      |
|  - Session max_execution_time timeout (10s)                 |
|  - Re-rendered AST execution with LIMIT row capping         |
+-------------------------------------------------------------+
```

---

## Defense-in-Depth Security Model

Every generated (or user-edited) query passes these layers before any data is returned (details: PLAN.md §3):

1. **L1: Dedicated read-only DB user.** `SELECT` only on the target database.
2. **L2: Read-only transaction.** `START TRANSACTION READ ONLY`, with `ROLLBACK` in `finally`.
3. **L3: Server-enforced timeout.** `SET SESSION max_execution_time`.
4. **L4: AST parsing.** `sqlglot` (MySQL dialect); exactly one statement.
5. **L5: SELECT-only roots.** SELECT / UNION / INTERSECT / EXCEPT (CTEs allowed).
6. **L6: Forbidden constructs.** DML/DDL, `SELECT … INTO`, locking reads, variables, `SET`, etc.
7. **L7: Function denylist.** `SLEEP`, `BENCHMARK`, `LOAD_FILE`, locks…; unknown functions need an allowlist entry.
8. **L8: Table/column access control.** Introspected-table allowlist; scope-aware CTEs (no shadowing); no cross-database refs; `DENY_TABLES` / `DENY_COLUMNS`, including rejecting `SELECT *` on tables with denied columns.
9. **L9: Bounded rows.** `LIMIT MAX_ROWS + 1`, truncation flagged.
10. **L10: Re-render.** Only SQL re-rendered from the validated AST is executed, via a `SafeSQL` object only the validator can create.
11. **L11: Output limits.** Cells capped at 500 chars and converted to JSON-safe types.
12. **L12: EXPLAIN gate.** `EXPLAIN FORMAT=JSON` before the preview and again before running; blocked above `EXPLAIN_MAX_COST` / `EXPLAIN_MAX_ROWS`; warnings for large full scans and filesorts.
13. **L13: Human approval.** Nothing executes until the user clicks **Run** on the preview; edits pass L4–L12 again.
14. **L14: Read-only honesty + risk flags.** Requests to change data ("delete the user…") are refused up front with "Not performed (read-only)". Previews flag risky queries (the model's DELETE draft was blocked, cross joins, large scans, huge results) with a red banner and a "Run anyway" confirmation.

**Audit:** every SQL statement (generated, rejected, edited, blocked, executed with row count and time, refused) is logged to `app.db` and to `backend/data/sql_log.jsonl` (`SQL_LOG_PATH`), and is viewable in the UI via the **SQL log** button (`GET /api/audit`).

---

## Quickstart

### Prerequisites
- macOS or Linux with **Docker** installed.
- **Python 3.12** and [**uv**](https://github.com/astral-sh/uv).
- **Node.js 20+** and `pnpm`.
- [**Ollama**](https://ollama.com/) running locally with `qwen2.5-coder:7b`:
  ```bash
  ollama pull qwen2.5-coder:7b
  ```

### 1. Start Infrastructure
Start the deterministic seeded MySQL 9.0 container on port 3307:
```bash
make infra-up
```

### 2. Configure Environment
Copy `.env.example` to `.env` in the project root:
```bash
cp .env.example .env
```
Default configuration:
```env
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce
APP_DB_PATH=backend/data/app.db
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b
MAX_ROWS=500
QUERY_TIMEOUT_MS=10000
MAX_QUERIES=3
EXPLAIN_MAX_COST=5000000
EXPLAIN_MAX_ROWS=10000000
EXPLAIN_WARN_ROWS=100000
```
See `.env.example` / PLAN.md §6 for all keys.

### 3. Start Development Environment
Launch both the FastAPI backend (`:8000`) and Next.js frontend (`:3000`) concurrently:
```bash
make dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser. Ask a question, review the preview (SQL + EXPLAIN), then click **Run** (or Edit / Cancel). See STARTUP_GUIDE.md §5.

---

## Testing & Quality Gates

Run all quality checks and test suites across backend and frontend:

```bash
# Run tests
make test

# Run strict linters, type checks, and formatters
make lint
```

Backend checklist:
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy app`
- `uv run pytest`

Frontend checklist:
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`

---

## Evaluation Benchmark

The evaluation harness tests execution accuracy against 32 diverse queries across aggregations, joins, date functions, subqueries, and top-N ranking:

```bash
make eval
# Or directly:
cd backend && uv run python -m evals.run --model qwen2.5-coder:7b
```

Evaluation results are logged to stdout and saved to:
`backend/evals/results/<YYYY-MM-DD>-<model>-<prompt_version>.json`

---

## Troubleshooting

### MySQL Port Conflict
The dev container runs on port **3307** to avoid conflicts with standard local MySQL installations on 3306. Verify with:
```bash
docker ps --filter "name=natural_to_sql_mysql"
```

### Ollama Connection
If the health check returns `ollama: error`:
1. Verify Ollama is running: `curl http://127.0.0.1:11434/api/tags`
2. Check available models: `ollama list`
3. Ensure model is pulled: `ollama pull qwen2.5-coder:7b`

### MySQL 9.0 Authentication
MySQL 9.0 uses `caching_sha2_password` authentication. The `asyncmy` driver handles this over SSL or with server public key exchange configured in `app/core/db.py`.
