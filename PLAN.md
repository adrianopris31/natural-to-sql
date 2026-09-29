# PLAN.md — Natural-to-SQL Chatbot Implementation Plan

Task IDs (`P<phase>.<n>`) are referenced in `PROGRESS.md`. Do the phases in order. Tasks within a phase can run in parallel where noted.

---

## 1. Goals / non-goals
**v1 goals**
- A chat UI where the user asks questions in natural language about their existing MySQL 9.0.1 DB.
- Each answer shows: the **generated SQL** (collapsible, highlighted), the **result table** and a **natural-language answer**.
- **Conversation memory**: follow-ups work ("now only for 2025", "and the bottom 5?").
- Fully local: Ollama + `qwen2.5-coder`.
- Safe by construction: it can never modify data, never run away on cost or time, and never leaks outside the allowed tables.

**Non-goals (v1)**: auth or multi-user, charts, writes of any kind, multiple DB engines, cloud LLMs.

---

## 2. Architecture

```
Next.js (3000) ──POST /api/chat (SSE)──▶ FastAPI (127.0.0.1:8000)
                                          │
        ┌─────────────────────────────────┼──────────────────────────────┐
        ▼                                 ▼                              ▼
 store/ (SQLite app.db)        llm/ (Ollama :11434)          core/ (target MySQL, RO user)
 conversations, turns,         generate_sql(), answer()      schema introspection,
 audit log                                                  validator, executor
```

### Request pipeline (`services/chat.py`)
1. **Load context**: the conversation's last `HISTORY_TURNS` (default 4) turns → `(question, sql, 1-line result summary)`.
2. **Schema context**: the cached schema (P1.3). If the schema has more than `SCHEMA_FULL_MAX_TABLES` (default 40) tables → **table selection** (P6.1) picks the top-k relevant tables. Otherwise the full compact schema is used.
3. **Generate SQL**: Ollama structured output →
   `{"sql": str|null, "reasoning": str, "needs_clarification": bool, "clarification_question": str|null}`
   - If `needs_clarification` is true, stream the question back to the user and stop (no SQL runs).
4. **Validate** (`core/validator.py`) → returns the *re-rendered* safe SQL or a `ValidationError(reason)`.
5. **Execute** (`core/executor.py`) → `ResultSet(columns, rows, row_count, truncated, elapsed_ms)`.
6. **Repair loop**: if step 4 or 5 fails, send the error message + the bad SQL back to the LLM. Allow at most `MAX_REPAIR_ATTEMPTS` (2), then return a friendly error that includes the last SQL.
7. **Answer**: a second LLM call (streamed) with the question, the SQL, the columns, the first `ANSWER_MAX_ROWS` (50) rows and the row count / truncation flag. The rules: use only these rows, say so when they're empty, and don't invent numbers.
8. **Persist** the turn (question, SQL, status, row_count, answer, timings) and write an **audit log** row (every SQL the LLM generated, whether it was accepted or rejected, and the reason).

### SSE event stream (`POST /api/chat`)
`status` (`generating_sql` | `validating` | `executing` | `repairing` | `answering`) → `sql` → `result` → `answer_delta`* → `done` | `clarification` | `error`

---

## 3. SQL safety design (the core of the project)

| Layer | Implementation |
|---|---|
| L1 DB privileges | A dedicated user with `SELECT` only on the target schema (`infra/mysql/create_readonly_user.sql`). |
| L2 Transaction | Every query runs inside `START TRANSACTION READ ONLY` … `ROLLBACK`. |
| L3 Timeout | `SET SESSION max_execution_time = <ms>` (MySQL 9.0.1; this only applies to SELECT, which is all we allow). Log `SELECT VERSION()` at startup, and warn if the server isn't MySQL ≥ 8. There is also an `asyncio.wait_for` guard in the client. |
| L4 Parse | `sqlglot.parse(sql, read="mysql")` must return **exactly 1** statement. A parse error means reject. |
| L5 Statement type | The root must be `exp.Select`, or `exp.Union`/`Intersect`/`Except` of selects (CTEs `WITH` are allowed). |
| L6 AST walk (deny) | Reject any node of type Insert/Update/Delete/Merge/Create/Drop/Alter/TruncateTable/Command/Set/Use/Transaction/Commit/Rollback/LoadData/Grant; `SELECT … INTO` (OUTFILE/DUMPFILE/@var); locking reads (`FOR UPDATE`, `LOCK IN SHARE MODE`); variable assignment `@x :=`. |
| L7 Function denylist | `SLEEP, BENCHMARK, LOAD_FILE, GET_LOCK, RELEASE_LOCK, IS_FREE_LOCK, RELEASE_ALL_LOCKS, MASTER_POS_WAIT, SOURCE_POS_WAIT, SYS_EXEC, SYS_EVAL`, and any function name that is not recognized (`exp.Anonymous`) unless it is on a configurable allowlist. |
| L8 Table allowlist | Every `exp.Table` must resolve to a table in the introspected schema (CTE names are allowed). Schemas `mysql`, `information_schema`, `performance_schema` and `sys` are always rejected. Optional `DENY_TABLES` / `DENY_COLUMNS` env (empty by default, since the user said there's no PII concern; the hook exists anyway). |
| L9 Row cap | If there is no `LIMIT`, or `LIMIT > MAX_ROWS` (default 500), the outer LIMIT is set to `MAX_ROWS`. The executor also stops fetching at `MAX_ROWS + 1` so it can set `truncated`. |
| L10 Re-render | Execute `ast.sql(dialect="mysql")`, **never the raw LLM string**. This strips comments and stacked-statement tricks. |
| L11 Output limits | Truncate cell values longer than 500 chars. Convert bytes/Decimal/datetime to JSON-safe values. |

The validator is a **pure function** (`validate(sql, schema, settings) -> SafeSQL | ValidationError`), with no I/O, so it can be tested exhaustively.

---

## 4. Prompts (`backend/app/llm/prompts.py`)
- **SQL system prompt**: the role, the MySQL dialect and its version, the rules (only SELECT, only the listed tables and columns, always qualify ambiguous columns, prefer explicit JOINs, use `LIMIT` for "top N", today's date for relative dates, and ask for clarification when truly ambiguous), then the **compact schema**:
  `table(col type [PK] [FK→t.col], …) -- table comment`, plus up to 5 sample distinct values for low-cardinality text columns (`SCHEMA_SAMPLE_VALUES=true`).
- **History block**: the previous turns as `Q: … / SQL: … / Result: <n rows, cols …>`.
- **Few-shot**: 3 generic examples (top-N with a join, group by date, a follow-up rewrite).
- **Repair prompt**: the original question, the bad SQL, the exact error, and "return corrected SQL".
- **Answer prompt**: the question, the SQL, the rows as a compact markdown table, the row count and truncation flag. The answer must be concise, cite figures from the rows only, and mention truncation.
- Every prompt is a versioned constant (`PROMPT_VERSION`), which is stored on each turn for eval comparison.

---

## 5. API contract (update this section before changing the API)
| Method | Path | Body / Response |
|---|---|---|
| POST | `/api/chat` | `{conversation_id?: str, message: str}` → SSE (see §2). The first event includes `conversation_id`. |
| GET | `/api/conversations` | `[{id, title, updated_at}]` |
| GET | `/api/conversations/{id}` | `{id, title, turns:[{id, question, sql, columns, rows, row_count, truncated, answer, status, error, created_at}]}` |
| DELETE | `/api/conversations/{id}` | 204 |
| GET | `/api/schema` | the compact schema (tables, columns) for the UI sidebar |
| POST | `/api/schema/refresh` | re-introspect → `{tables: n}` |
| GET | `/api/health` | `{db: ok|error, ollama: ok|error, model: str, db_version: str}` |

Rows are stored with the turn (capped at MAX_ROWS), so reopening a conversation doesn't re-run the queries.

---

## 6. Configuration (`.env.example`)
```
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:CHANGE_ME@127.0.0.1:3306/your_db
APP_DB_PATH=backend/data/app.db
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b
OLLAMA_NUM_CTX=8192             # 16 GB Mac; raise only if the schema prompt doesn't fit
MAX_ROWS=500
ANSWER_MAX_ROWS=50
QUERY_TIMEOUT_MS=10000
MAX_REPAIR_ATTEMPTS=2
HISTORY_TURNS=4
SCHEMA_FULL_MAX_TABLES=40
SCHEMA_SAMPLE_VALUES=true
ALLOWED_FUNCTIONS=
DENY_TABLES=
DENY_COLUMNS=
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE=/api        # frontend; proxied via next.config rewrites → 127.0.0.1:8000
```

---

## 7. Phases & tasks

### Phase 0 — Scaffold (tasks can run in parallel)
- **P0.1** Repo skeleton per GEMINI.md, root `.gitignore` (`.env`, `backend/data/`, `node_modules`, `.venv`), `.env.example`, `git init`.
- **P0.2** `backend/`: `uv init`, deps (`fastapi[standard] sqlalchemy[asyncio] asyncmy sqlglot httpx pydantic-settings aiosqlite`), dev deps (`pytest pytest-asyncio testcontainers[mysql] respx ruff mypy`), ruff and mypy config, `app/main.py` with `/api/health` returning a stub.
- **P0.3** `frontend/`: `create-next-app` (TS, Tailwind, App Router, ESLint), shadcn/ui init, Vitest + RTL + Playwright setup, `next.config` rewrite `/api/*` → `http://127.0.0.1:8000/api/*`.
- **P0.4** `infra/docker-compose.yml`: `mysql:9.0` (it matches prod 9.0.1) on port **3307** (to avoid clashing with the user's DB), `seed.sql` (e-commerce: `users, products, orders, order_items, payments, categories`, about 1k users and 10k orders with deterministic data), and `create_readonly_user.sql` applied at init.
- **Done when**: `uv run pytest` and `pnpm test` run (they may be empty), compose comes up, and `/api/health` answers.

### Phase 1 — Target DB access & schema
- **P1.1** `config.py`: Settings (pydantic-settings) with every key in §6.
- **P1.2** `core/db.py`: an async engine for the target DB (pool size 5, `pool_pre_ping`), and a startup version log. MySQL 9 defaults to `caching_sha2_password`, so make sure asyncmy connects (it needs TLS or `get_server_public_key`) and document the fix.
- **P1.3** `core/schema.py`: introspect `information_schema` (tables, columns, types, PK, FK, comments; approximate row counts) for the configured DB → a `SchemaModel` dataclass. The result is cached in memory, and a refresh can be triggered. Also provides `to_prompt(tables=None) -> str` (the compact format from §4) and optional sample values (`SELECT DISTINCT col … LIMIT 6` for text columns with fewer than ~20 distinct values, run through the executor).
- **P1.4** `/api/schema`, `/api/schema/refresh`, and a real `/api/health` DB check.
- **Tests**: introspection against the testcontainer seed; snapshot test of `to_prompt()`.

### Phase 2 — SQL safety (security-critical; do this before the LLM phase)
- **P2.1** `core/validator.py`, implementing §3 layers L4–L10 as a pure function.
- **P2.2** `core/executor.py`: L2, L3, L9 (fetch cap) and L11; returns `ResultSet`. A MySQL error becomes `ExecutionError(user_message, raw)`.
- **P2.3** An **adversarial corpus** `tests/security/attacks.yaml` (at least 60 cases): DML/DDL, stacked queries (`; DROP`), comment tricks (`/*!50000 DROP*/`, `-- `, `#`), `INTO OUTFILE`, `LOAD_FILE`, `SLEEP`/`BENCHMARK`, system schemas, `FOR UPDATE`, `@var:=`, `SET`, `CALL`, `HANDLER`, `DO`, unicode/case obfuscation, CTE that wraps DML, UNION into `mysql.user`, and huge cross joins (these are capped by LIMIT and the timeout). Include a **safe corpus** (at least 40 valid SELECTs that must pass unchanged in meaning).
- **P2.4** An integration test: even if the validator is monkeypatched to allow everything, the RO user + READ ONLY transaction still block writes (this proves L1/L2 on their own).
- **Done when**: 100% of the attack corpus is rejected, 100% of the safe corpus passes, and the P2.4 test is green.

### Phase 3 — LLM integration
- **P3.1** `llm/client.py`: an `LLMClient` protocol plus `OllamaClient` (chat, structured JSON via `format`, streaming, timeouts, and `keep_alive` so the model stays loaded). Includes a `FakeLLMClient` for tests.
- **P3.2** `llm/prompts.py`, as described in §4.
- **P3.3** `llm/sql_generator.py`: `generate(question, history, schema) -> SqlDraft` and `repair(...)`. Parses and validates the JSON output, with one retry if the JSON is invalid.
- **P3.4** `llm/answerer.py`: `stream_answer(question, sql, result) -> AsyncIterator[str]`.
- **P3.5** `/api/health`: Ollama check (`/api/tags` contains the model).
- **Tests**: prompt snapshots; generator tested with `FakeLLMClient` and with `respx`-mocked Ollama HTTP responses.

### Phase 4 — Chat pipeline, memory & API
- **P4.1** `store/`: SQLite (SQLAlchemy async + aiosqlite) with tables `conversations(id, title, created_at, updated_at)`, `turns(id, conversation_id, question, sql, columns_json, rows_json, row_count, truncated, answer, status, error, prompt_version, timings_json, created_at)`, and `audit_log(id, turn_id, attempt, raw_sql, safe_sql, accepted, reason, created_at)`.
- **P4.2** `services/chat.py`: the pipeline from §2, including the repair loop and history handling. The conversation title is the first question, truncated to 60 chars.
- **P4.3** `api/chat.py`: the SSE endpoint (`sse-starlette` or a `StreamingResponse` with `text/event-stream`), plus the conversations CRUD.
- **P4.4** Error UX: errors map to friendly messages (the model is unavailable, the DB is unreachable, the query was rejected for safety, the query timed out, no answer after the repair attempts).
- **Tests**: the pipeline with FakeLLM + the testcontainer DB, covering the happy path, a clarification, repair success, repair exhaustion and a follow-up that uses history; also an SSE event-order test.

### Phase 5 — Frontend (can start after P0.3, against a mocked API; it's wired up after Phase 4)
- **P5.1** `lib/api.ts`: a typed client and an SSE parser for `POST /api/chat`. Types mirror §5 (hand-written in `lib/types.ts`).
- **P5.2** Layout: a left sidebar (conversation list, "New chat", and a schema browser that can be collapsed) and a main chat pane.
- **P5.3** Message components: a user bubble, and an assistant turn made of a status stepper (generating → validating → executing → answering), a **SQL block** (collapsible, highlighted with `shiki` or `prism`, a copy button), a **ResultTable** (TanStack Table: sticky header, a "showing N of M / truncated" note, CSV export), and the streamed markdown answer.
- **P5.4** Clarification and error states. There's also a retry button, which re-sends the question.
- **P5.5** Health banner (Ollama or the DB is down), empty state with example questions, dark mode, keyboard handling (Enter sends, Shift+Enter adds a newline) and a stop-generation button (aborts the fetch).
- **Tests**: component tests (SQL block, table, SSE parser) and Playwright e2e against the mocked backend (MSW or a fixture SSE server).

### Phase 6 — Accuracy & scale hardening
- **P6.1** Table selection for large schemas: embed table descriptions with Ollama `nomic-embed-text`, keep the vectors in memory, and pick the top-k (8) tables by similarity to the question plus history, expanded with the FK neighbors. Only used when the table count is above `SCHEMA_FULL_MAX_TABLES`.
- **P6.2** An eval harness `backend/evals/`: `questions.yaml` (at least 30 questions over the seed DB, each with a reference SQL). The metric is **execution accuracy**: the result set equals the reference result set, compared order-insensitively unless an ORDER BY is required. Record the pass rate, the average latency and the repair rate in `evals/results/<date>-<model>-<prompt_version>.json`.
- **P6.3** Tune the prompts and few-shots against the evals. Optionally try `qwen2.5-coder:14b`: on a 16 GB Mac it needs about 9 GB plus context, so it's tight. Only switch if accuracy gains ≥ 5 points and latency stays acceptable. Record the decision in PROGRESS.md.
- **P6.4** User-DB eval: add 10–20 questions specific to the user's real schema (with the user's help).

### Phase 7 — Polish & docs
- **P7.1** A `README.md` covering setup (Ollama, the RO user, .env, running) and troubleshooting.
- **P7.2** `make dev` / a `justfile` that starts the backend and the frontend together.
- **P7.3** Final security review against §3 and a check of the audit log.

---

## 8. Definition of done (v1)
- Against the seed DB, questions like "top 10 users by revenue", "monthly revenue in 2025" and "which products never sold" produce correct SQL, a table and a grounded answer.
- Follow-up questions work within a conversation.
- The attack corpus is 100% rejected, and the RO-user integration test is green.
- Execution accuracy on the eval set is ≥ 80% with the chosen model.
- The app works against the user's real MySQL DB through the RO user.

## 9. Risks
| Risk | Mitigation |
|---|---|
| A 7B model is weak on complex joins or large schemas | Table selection (P6.1), FK hints in the schema prompt, the repair loop, and the 14b option |
| Dev/prod version drift | The dev container is pinned to MySQL 9.0 to match prod 9.0.1 |
| RAM pressure on the 16 GB Mac (Ollama + Docker + Next dev) | Use the 7b model, `OLLAMA_NUM_CTX=8192` by default, and give Docker ≤ 4 GB |
| Slow queries on a big production DB | The timeout, the LIMIT cap and the RO user; recommend pointing at a replica |
| Hallucinated answers | The answer prompt is grounded in rows only; the UI always shows the SQL and the table |
| Local latency | `keep_alive`, streaming, and the SQL shown as soon as it's ready |
