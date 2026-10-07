# PLAN.md — Natural-to-SQL Chatbot Implementation Plan

Task IDs (`P<phase>.<n>`) are referenced in `PROGRESS.md`. Do the phases in order. Tasks within a phase can run in parallel where noted.

---

## 1. Goals / non-goals
**v1 goals**
- A chat UI where the user asks questions in natural language about their existing MySQL 9.0.1 DB.
- Each answer shows: the **generated SQL** (collapsible, highlighted), the **result table** and a **natural-language answer**.
- **Preview before running** (added 2026-09-29, Phase 8): every generated query is shown with an **EXPLAIN** summary and runs only after the user clicks Run. The user can edit or cancel it. Expensive queries are blocked.
- **Multiple queries** (Phase 8): up to 3 independent SELECTs for questions with separate parts, each with its own table, answered together.
- **Conversation memory**: follow-ups work ("now only for 2025", "and the bottom 5?").
- Fully local: Ollama + `qwen2.5-coder`.
- Safe by construction: it can never modify data, never run away on cost or time, and never leaks outside the allowed tables.

**Non-goals (v1)**: auth or multi-user, charts, writes of any kind, multiple DB engines, cloud LLMs, auto-running SQL without approval, chained queries (one query using another's results).

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

### Request pipeline (`services/chat.py`) — two phases, approval required
**Phase A: plan (`POST /api/chat`, `process_chat`). Never executes SQL.**
0. **Write-request refusal**: if the question clearly asks to change data (`core/intent.py`, e.g. "delete the user X", "can you drop…"), stream `refused` immediately. **No LLM call, no SQL.** The model can also set `write_intent: true` → `refused`. Logged with stage `refused`.
1. **Load context**: the last `HISTORY_TURNS` turns *with status `done`* → `(question, sql, 1-line result summary)`. Cancelled or unapproved turns are excluded.
2. **Schema context**: the cached schema (P1.3). If the schema has more than `SCHEMA_FULL_MAX_TABLES` tables → **table selection** (P6.1).
3. **Generate**: Ollama structured output →
   `{"queries": [{"sql": str, "purpose": str}] (1..MAX_QUERIES, independent SELECTs), "reasoning": str, "needs_clarification": bool, "clarification_question": str|null}`.
   The legacy `{"sql": ...}` shape is accepted as one query. If `needs_clarification`, stream the question and stop.
4. **For each query**: **Validate** (`core/validator.py`) → **EXPLAIN** (`core/explain.py`, `EXPLAIN FORMAT=JSON` in a READ ONLY txn; this does not execute the query). A validation or EXPLAIN error (e.g. an unknown column) goes to the **repair loop** (≤ `MAX_REPAIR_ATTEMPTS`).
5. **Risk flags** (`core/risk.py`) per query: `UNSAFE_DRAFT_BLOCKED` (high: the model first wrote e.g. a DELETE), `DRAFT_REJECTED` (medium), `CARTESIAN_JOIN` (high), `EXPLAIN_BLOCKED` (high), `EXPLAIN_WARNING` (medium), `LARGE_RESULT` (medium: no LIMIT from the model and est. rows > MAX_ROWS), `WRITE_WORDING` (medium: question mentions delete/update…), `USER_EDITED` (info). `level` = max severity. A high level makes the UI require a "Run anyway" confirmation.
6. **Persist** the turn with `status=awaiting_approval` and `queries_json` (sql, purpose, explain, risk), then stream `preview`. **Stop.**

**Phase B: run (`POST /api/chat/{turn_id}/run`, `run_approved_turn`). Only after the user clicks Run.**
6. Only allowed when `status == awaiting_approval` (so it runs once). Optional `queries[i]` = user-edited SQL.
7. **Re-validate + re-EXPLAIN every query** (edited SQL gets no LLM repair). Any rejection or a `blocked` EXPLAIN → error, **nothing runs**, and the turn stays `awaiting_approval`.
8. **Execute** each (`core/executor.py`) → one `result` event per query (a per-query error is reported and the others still run).
9. **Answer**: one streamed LLM call over all results (temp 0.2, ≤ `ANSWER_MAX_ROWS` rows each, grounded only in the rows).
10. **Persist** results + answer (`status=done`). The **audit log** records every SQL (LLM or user-edited), accepted or rejected, with the reason.

`POST /api/chat/{turn_id}/cancel` → `status=cancelled`.

### SSE events
- Plan: `status` (`generating_sql` | `validating` | `explaining` | `repairing`) → `preview {conversation_id, turn_id, queries:[{index, purpose, sql, explain, risk}]}` | `refused {conversation_id, turn_id, message}` | `clarification` (+`done`; the client must keep the clarification status) | `error`
- Run: `status` (`validating` | `explaining` | `executing` | `answering`) → `result {index, sql, columns, rows, row_count, truncated, error}`* → `answer_delta`* → `done` | `error {message, code, index?}`
- Error codes: `VALIDATION_FAILED`, `EXPLAIN_FAILED`, `BLOCKED_BY_EXPLAIN`, `REPAIR_FAILED`, `LLM_ERROR`, `NO_QUERY`, `INVALID_STATE`, `NOT_FOUND`, `EXECUTION_FAILED`, `UNEXPECTED_ERROR`.
- The stream sends an SSE comment `: ping` every 10s while idle (proxy keepalive).

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
| L8 Table allowlist | Every real `exp.Table` must be in the introspected schema. CTE refs are resolved by scope (a non-recursive CTE's own body sees the base table), and CTE names may not shadow real tables. Any db/catalog qualifier other than the target DB is rejected (system schemas always). `DENY_TABLES`/`DENY_COLUMNS`: denied columns can't be named, and `*`/`t.*` is rejected on tables that have denied columns. |
| L9 Row cap | If there is no `LIMIT`, or `LIMIT > MAX_ROWS` (default 500), the outer LIMIT is set to `MAX_ROWS`. The executor also stops fetching at `MAX_ROWS + 1` so it can set `truncated`. |
| L10 Re-render | Execute `ast.sql(dialect="mysql")`, **never the raw LLM string**. This strips comments and stacked-statement tricks. |
| L11 Output limits | Truncate cell values longer than 500 chars. Convert bytes/Decimal/datetime to JSON-safe values. |
| L12 EXPLAIN gate | `EXPLAIN FORMAT=JSON` before preview and again before run. `blocked` if cost > `EXPLAIN_MAX_COST` or estimated rows > `EXPLAIN_MAX_ROWS`. Warnings for full scans/filesorts ≥ `EXPLAIN_WARN_ROWS`. |
| L13 Human approval | No LLM-generated SQL executes until the user approves the preview (`/run`). Edited SQL passes L4–L12 again. |
| L14 Write-request refusal + risk flags | Data-changing requests are refused up front with an explicit "Not performed (read-only)" message (no confirmation questions). Previews carry risk flags; high risk = red banner + confirmation. |
| Audit | Every SQL lifecycle event is logged: `validated`, `rejected`, `explain_failed`, `blocked`, `edited`, `executed` (row_count, elapsed_ms), `execution_failed`, `refused`. Stored in `app.db` `audit_log` and appended as JSONL to `SQL_LOG_PATH`. Shown in the UI "SQL log" panel via `GET /api/audit`. |

The validator is a **pure function** (`validate(sql, schema, settings) -> SafeSQL | ValidationError`), with no I/O, so it can be tested exhaustively.

---

## 4. Prompts (`backend/app/llm/prompts.py`)
- **SQL system prompt**: the role, the MySQL dialect and its version, the rules (only SELECT, only the listed tables and columns, always qualify ambiguous columns, prefer explicit JOINs, use `LIMIT` for "top N", today's date for relative dates, and ask for clarification when truly ambiguous), then the **compact schema**:
  `table(col type [PK] [FK→t.col], …) -- table comment`, plus up to 5 sample distinct values for low-cardinality text columns (`SCHEMA_SAMPLE_VALUES=true`).
- **History block**: the previous turns as `Q: … / SQL: … / Result: <n rows, cols …>`.
- **Few-shot**: 3 generic examples (top-N with a join, group by date, a follow-up rewrite).
- **Repair prompt**: the original question, the bad SQL, the exact error, and "return corrected SQL".
- **Answer prompt**: the question plus one section per query (purpose, SQL, rows as a markdown table, row count and truncation flag, or FAILED + error). One concise answer covering all parts, citing only figures from the rows. Temperature 0.2.
- **SQL prompt v1.1**: `queries` list format, "one query unless the question has separate parts" (≤ MAX_QUERIES, independent), and never `SELECT *`.
- Every prompt is a versioned constant (`PROMPT_VERSION`), which is stored on each turn for eval comparison.

---

## 5. API contract (update this section before changing the API)
| Method | Path | Body / Response |
|---|---|---|
| POST | `/api/chat` | `{conversation_id?: str, message: str}` → SSE plan phase, ending in `preview` (see §2). Never executes. |
| POST | `/api/chat/{turn_id}/run` | `{queries?: (str|null)[]}` (edited SQL per index) → SSE run phase (see §2). Only when `awaiting_approval`. |
| POST | `/api/chat/{turn_id}/cancel` | 204; 409 if the turn is not awaiting approval |
| GET | `/api/audit?limit=200&turn_id=` | newest-first `[{id, created_at, turn_id, conversation_id, question, stage, attempt, accepted, raw_sql, safe_sql, reason, row_count, elapsed_ms}]` |
| GET | `/api/conversations` | `[{id, title, updated_at}]` |
| GET | `/api/conversations/{id}` | `{id, title, turns:[{id, question, sql, columns, rows, row_count, truncated, queries: [{index, purpose, sql, explain, columns, rows, row_count, truncated, error}] | null, answer, status, error, created_at}]}`. Status adds `awaiting_approval`, `cancelled`, `refused`. Each query has `risk: {level, flags:[{code, severity, message}]}`. |
| DELETE | `/api/conversations/{id}` | 204 |
| GET | `/api/databases` | list discovered and configured databases `[{id, name, is_default}]` |
| GET | `/api/schema?database=` | the compact schema (tables, columns) for specified or default database |
| POST | `/api/schema/refresh?database=` | re-introspect specified database → `{tables: n}` |
| GET | `/api/health` | `{db: ok|error, ollama: ok|error, model: str, db_version: str, settings_ui_enabled: bool}` |
| GET | `/api/settings/sources` | list Jira and Slack configured status, non-secret fields, secret_hint, and origin |
| PUT | `/api/settings/sources/{source}` | configure Jira or Slack credentials (secrets write-only, omitted kept) |
| DELETE | `/api/settings/sources/{source}` | remove stored credentials, revert to .env fallback |
| POST | `/api/settings/sources/{source}/test` | test connection with submitted payload or stored credentials |
| POST | `/api/settings/refresh` | trigger background re-index of documents in Knowledge-Bot |

Rows are stored with the turn (capped at MAX_ROWS), so reopening a conversation doesn't re-run the queries. Each conversation/turn records `database: str | null`.

---

## 6. Configuration (`.env.example`)
```
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:CHANGE_ME@127.0.0.1:3306/your_db
TARGET_DATABASES=              # optional JSON mapping of alias -> URL: {"analytics": "..."}
APP_DB_PATH=backend/data/app.db
SQL_LOG_PATH=backend/data/sql_log.jsonl   # JSONL audit of every SQL (git-ignored dir)
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:7b
OLLAMA_NUM_CTX=8192             # 16 GB Mac; raise only if the schema prompt doesn't fit
MAX_ROWS=500
ANSWER_MAX_ROWS=50
QUERY_TIMEOUT_MS=10000
MAX_REPAIR_ATTEMPTS=2
MAX_QUERIES=3                    # independent SELECTs per question
EXPLAIN_MAX_COST=5000000         # blocked above this EXPLAIN cost
EXPLAIN_MAX_ROWS=10000000        # blocked above this estimated row count
EXPLAIN_WARN_ROWS=100000         # warn on full scans/filesorts at or above this
HISTORY_TURNS=4
SCHEMA_FULL_MAX_TABLES=40
SCHEMA_SAMPLE_VALUES=true
ALLOWED_FUNCTIONS=
DENY_TABLES=
DENY_COLUMNS=
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE=/api        # frontend; proxied via next.config rewrites → 127.0.0.1:8000
KNOWLEDGE_BOT_URL=http://127.0.0.1:8100
KNOWLEDGE_BOT_API_KEY=
KNOWLEDGE_BOT_ADMIN_KEY=
KNOWLEDGE_BOT_TIMEOUT_SEC=90.0
KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC=900.0
ENABLE_SETTINGS_UI=false
NEXT_PUBLIC_SETTINGS_API_BASE=http://127.0.0.1:8000/api
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

### Phase 8 — Safety review fixes + preview/approval, EXPLAIN, multi-query (added 2026-09-29, built by Claude)
Status: ✅ = done (committed on branch `feat/sql-preview-safety`), ⏳ = open. Details of what changed: PROGRESS.md → "CHANGES MADE BY CLAUDE".
- ✅ **P8.1** SSE heartbeat (`: ping` every 10s) + Next `proxyTimeout` + frontend stream-cutoff error. Fixes the UI hanging on "generating" on the real DB.
- ✅ **P8.2** Validator holes H1–H5 fixed (star vs DENY_COLUMNS, CTE shadowing, cross-DB refs, forgeable SafeSQL, typed-function names), with attack/safe corpus cases.
- ✅ **P8.3** `core/explain.py`: EXPLAIN FORMAT=JSON summary + gate (L12). Settings `EXPLAIN_MAX_COST`, `EXPLAIN_MAX_ROWS`, `EXPLAIN_WARN_ROWS`.
- ✅ **P8.4** Multi-query generation: `SqlDraft.queries` (≤ `MAX_QUERIES`), prompt v1.1, multi-result answer prompt (temp 0.2).
- ✅ **P8.5** Two-phase pipeline + API: plan → `preview` (no execution); `POST /api/chat/{id}/run` (re-validate + re-EXPLAIN, edits allowed, blocked refused); `/cancel`; `turns.queries_json` + auto-migration; history = done turns only.
- ✅ **P8.6** Frontend: preview card (Edit/Revert/Run/Cancel), EXPLAIN summary, per-query results, new statuses, `runTurn`/`cancelTurn`.
- ✅ **P8.7** Tests: EXPLAIN unit tests, rewritten pipeline integration tests, QueryPreview/use-chat/api/sse tests (backend 257, frontend 50).
- ⏳ **P8.8** Live check with Ollama on `easybiz_data_1`: plan → preview → Run / Edit / Cancel in the UI. Only scripted-model runs have been verified so far.
- ⏳ **P8.9** Re-run evals with prompt v1.1 (`make eval`); accept only if no regression > 2 points vs v1.0 (87.5%).
- ✅ **P8.10** Playwright e2e (`frontend/tests/e2e/chat.spec.ts`): ask → preview → Run → tables → answer; Edit; Cancel; blocked; stream cutoff; docs mode.
- ⏳ **P8.11** Tune EXPLAIN thresholds after observing real query costs (real DB so far: 5–230; defaults are 5M cost / 10M rows).
- ✅ **P8.12** Write-request refusal: `core/intent.py` (keyword check, before the LLM) + `SqlDraft.write_intent` (prompt v1.2 rule 10 + few-shot) → `refused` event/status. Fixes "delete user" showing "Completed" (the model had asked "Are you sure you want to delete…?" and the frontend's `done` hid the clarification).
- ✅ **P8.13** Risk flags: `core/risk.py` → `queries[].risk`; UI red banner, per-query flags, "Run anyway" + confirmation checkbox for high risk.
- ✅ **P8.14** SQL audit log: `audit_log` + `stage/row_count/elapsed_ms` (auto-migrated), JSONL mirror `SQL_LOG_PATH`, `GET /api/audit`, UI "SQL log" panel (header button).
- ✅ **P8.15** Frontend fix: `done` after `clarification`/`refused` no longer overwrites the status.
- ⏳ **P8.16** Re-run evals with prompt v1.2 (includes write-intent rule); check the keyword refusal has no false positives on real questions.

### Phase 9 — Knowledge-Bot Integration (Jira / Slack / Docs Q&A) (added 2026-10-01)
Status: ✅ = done (branch `feat/knowledge-bot-integration`).
- ✅ **P9.1** Integration client: `app/integrations/knowledge_bot.py` (`ask_docs`, `docs_health`), typed errors (`app/errors.py`), settings `KNOWLEDGE_BOT_URL`, `KNOWLEDGE_BOT_API_KEY`, `KNOWLEDGE_BOT_TIMEOUT_SEC`.
- ✅ **P9.2** Data store: SQLite migrations in `app/store/database.py` adding `Turn.kind` (`"sql" | "docs"`) and `Turn.sources_json`.
- ✅ **P9.3** Pipeline: `app/services/docs.py` streaming SSE events (`searching_docs`, `docs_answer`, `done`, `error`); `app/api/chat.py` accepts `mode: "sql" | "docs"` and returns HTTP 409 for `/run` and `/cancel` on docs turns.
- ✅ **P9.4** Frontend contract & state: `lib/types.ts`, `lib/sse.ts`, `lib/api.ts`, `hooks/use-chat.ts` (docs turns stream directly to completion without approval gate).
- ✅ **P9.5** Frontend UI: `components/chat/chat-layout.tsx` (Data / Docs segmented toggle with localStorage persistence, source filter chips for `jira:`, `slack:`, `doc:`), `docs-answer.tsx` (markdown answer, source link chips with security rels, refusal card), `sidebar.tsx` (distinct SQL/Docs icons), `status-stepper.tsx` (Searching → Answering → Completed), and non-blocking `health-banner.tsx`.
- ✅ **P9.6** Tests: unit (`test_knowledge_bot.py`), integration (`test_docs_pipeline.py`), frontend (`docs-answer.test.tsx`, `health-banner.test.tsx`, updated `layout`, `sidebar`, `use-chat`, `api`, `e2e/chat.spec.ts`). All 314 backend + 69 frontend tests passing.

### Phase 10 — External API Service & Headless Querying (added 2026-10-01)
Status: ✅ = done (branch `feat/external-api-service`).
- ✅ **P10.1** API Key authentication & storage: `api_keys` and `api_usage` models in SQLite (`app.db`), SHA-256 key hashing (`nl_live_...`), scopes (`query`, `admin`), in-memory sliding-window rate limiting (60 req/min), and daily quota tracking in `app/core/auth.py`.
- ✅ **P10.2** Headless query service: `app/services/query.py` (`execute_headless_query`, `approve_headless_query`, `cancel_headless_query`) with unified `mode: "sql"` and `mode: "docs"`.
- ✅ **P10.3** Automated safety risk gate: low-risk queries auto-execute in `START TRANSACTION READ ONLY` with statement timeout and row cap; high-risk (Cartesian joins, draft blocked) or EXPLAIN-blocked queries refuse auto-run and return `status="blocked"` for two-phase approval; upfront write-intent checks refuse modifications.
- ✅ **P10.4** External REST endpoints: mounted under `/v1` in `app/api/v1/query.py` and `app/api/v1/keys.py`:
  - `POST /v1/query`: single-shot headless execution (sql or docs)
  - `POST /v1/query/{turn_id}/approve`: two-phase approval for blocked or inspected queries
  - `POST /v1/query/{turn_id}/cancel`: discard turns awaiting approval
  - `GET /v1/health`: public status and DB connectivity check
  - `POST /v1/keys`: issue new API key with scope and quota (admin)
  - `GET /v1/keys`: list keys with prefix and metadata (admin)
  - `DELETE /v1/keys/{prefix}`: revoke API key (admin)
  - `GET /v1/audit`: query SQL lifecycle audit log (admin)
- ✅ **P10.5** CLI management tool: `scripts/manage_keys.py` (`new`, `list`, `revoke`).
- ✅ **P10.6** Test suite: unit (`tests/unit/test_api_auth.py`), integration (`tests/integration/test_v1_api.py`), bringing backend tests to 332 with 100% pass rate.
- ✅ **P10.7** Dynamic multi-database connection: multi-engine pooling, db auto-discovery, schema caching, and UI switcher (completed in Phase 12).

### Phase 11 — Jira/Slack Settings UI (Knowledge-Bot Phase 3) (added 2026-10-05)
Status: ✅ = done (branch `feat/jira-slack-settings-ui`).
- ✅ **P11.1** Backend config & client: `KNOWLEDGE_BOT_ADMIN_KEY` and `ENABLE_SETTINGS_UI` in `app/config.py`; extended `app/integrations/knowledge_bot.py` with admin client functions (`fetch_sources`, `save_jira_source`, `save_slack_source`, `test_source`, `delete_source`, `trigger_refresh`) and typed error mappings in `app/errors.py`.
- ✅ **P11.2** Backend API & security: `app/api/settings.py` guarding `/api/settings/*` behind `ENABLE_SETTINGS_UI` (404 if disabled) and strict localhost client check (403 if non-localhost). 422 validation error handler strips raw inputs to prevent secret leaks.
- ✅ **P11.3** Frontend contract & client: added source types and forms in `frontend/lib/types.ts`; implemented API client functions in `frontend/lib/api.ts`.
- ✅ **P11.4** Frontend UI: `frontend/components/chat/settings-dialog.tsx` with Jira/Slack cards, origin badges (`Stored`, `From .env`, `Not set`), last refresh status, write-only secret toggle, test connection, save, refresh now, and disconnect. Header settings gear conditionally shown when `settings_ui_enabled !== false`.
- ✅ **P11.5** Tests: unit (`tests/unit/test_settings.py`), integration (`tests/integration/test_settings_api.py`), frontend (`tests/settings-dialog.test.tsx`, updated `layout`, `api`, `mocks/handlers.ts`). 358 backend + 79 frontend tests passing.

### Phase 12 — Dynamic Multi-Database Switching (P10.7 Roadmap) (added 2026-10-07)
Status: ✅ = done (branch `feat/dynamic-db-switching`).
- ✅ **P12.1** Engine & Schema Multi-Tenant Manager (`app/core/db.py`, `app/core/schema.py`):
  - Support multi-engine lifecycle management via `get_engine(db_name: str | None = None)` with engine pooling and discovery from MySQL server (`SHOW DATABASES` filtering out system schemas) and optional `TARGET_DATABASES` env mapping.
  - Multi-database schema caching in `SchemaCache` keyed by database name.
- ✅ **P12.2** Storage & Conversation State (`app/store/models.py`, `app/store/database.py`):
  - Add `database` column to `conversations` and `turns` models with SQLite auto-migrations.
- ✅ **P12.3** Backend Endpoints & Query Pipelines:
  - Add `GET /api/databases` in `app/api/databases.py`.
  - Accept `database` query parameter in `/api/schema` and `/api/schema/refresh`.
  - Accept `database` in `POST /api/chat` and `POST /v1/query`, propagating database engine and schema through `process_chat`, `run_approved_turn`, and `execute_headless_query`.
- ✅ **P12.4** Frontend Contract & API Client (`frontend/lib/types.ts`, `frontend/lib/api.ts`):
  - Add `DatabaseItem` type, update `ChatRequest`, `Conversation`, `Turn` with `database?: string`.
  - Add `fetchDatabases()`, update `fetchSchema(database?)` and `refreshSchema(database?)`.
- ✅ **P12.5** Frontend UI & State (`frontend/hooks/use-chat.ts`, `components/chat/`):
  - Add Database Switcher dropdown in UI (header/sidebar) to switch active database.
  - Synchronize Schema Browser and chat requests with selected database.
  - Automatically restore active database when opening historical conversations.
- ✅ **P12.6** Verification & Quality Gates:
  - Unit tests for engine manager, schema multi-cache, and database discovery.
  - Integration tests for multi-database chat pipeline and API query execution.
  - Frontend component tests for Database Switcher and state changes.
  - Full suite verification (`make lint`, `make test`).

---

## 8. Definition of done (v1)
- Against the seed DB, questions like "top 10 users by revenue", "monthly revenue in 2025" and "which products never sold" produce correct SQL, a table and a grounded answer.
- Follow-up questions work within a conversation.
- The attack corpus is 100% rejected, and the RO-user integration test is green.
- Execution accuracy on the eval set is ≥ 80% with the chosen model.
- The app works against the user's real MySQL DB through the RO user.
- No generated SQL executes without the user's approval. Blocked (EXPLAIN) queries can't run unless edited, and edited SQL passes every layer again.

## 9. Risks
| Risk | Mitigation |
|---|---|
| A 7B model is weak on complex joins or large schemas | Table selection (P6.1), FK hints in the schema prompt, the repair loop, and the 14b option |
| Dev/prod version drift | The dev container is pinned to MySQL 9.0 to match prod 9.0.1 |
| Approval step adds a click; EXPLAIN adds latency | EXPLAIN takes milliseconds; the approval is required by the user (always preview) |
| Local LLM generation takes 30s+ and proxies drop idle SSE | `: ping` heartbeat every 10s and Next `proxyTimeout` 300s (P8.1) |
| RAM pressure on the 16 GB Mac (Ollama + Docker + Next dev) | Use the 7b model, `OLLAMA_NUM_CTX=8192` by default, and give Docker ≤ 4 GB |
| Slow queries on a big production DB | The timeout, the LIMIT cap and the RO user; recommend pointing at a replica |
| Hallucinated answers | The answer prompt is grounded in rows only; the UI always shows the SQL and the table |
| Local latency | `keep_alive`, streaming, and the SQL shown as soon as it's ready |
