# GEMINI.md — Natural-to-SQL Chatbot

> Read this first, then read `PROGRESS.md` (current state, next steps, and **CHANGES MADE BY CLAUDE**), then `PLAN.md` (the full plan).
> Domain rules are in `.agents/rules/` (backend, frontend, testing).
> ⚠️ Code was changed outside Antigravity on 2026-09-29 (Claude session): validator fixes, SSE heartbeat, and the **preview/approval + EXPLAIN + multi-query** feature (PLAN.md Phase 8). If the code differs from what you remember, trust the code + PROGRESS.md + PLAN.md, not your earlier context.

## What this project is
A local chatbot. The user asks a question about their data in plain language (for example, *"give me the top users by revenue"*). The app:
0. refuses requests to change data up front ("Not performed (read-only)"), since the app can never write,
1. turns the question into **1–3 independent read-only MySQL `SELECT`s** (usually one), using a **local LLM** (Ollama),
2. **validates** each with an AST-based safety layer and checks it with **`EXPLAIN`** (cost / rows / full scans; too expensive = blocked),
3. shows a **preview** (SQL + EXPLAIN summary + **risk flags**, with a red banner for dangerous-looking queries) and **waits for the user to click Run**. The user can also edit the SQL or cancel. Nothing touches the data before that,
4. on approval, re-validates + re-EXPLAINs and **runs** the queries through a **read-only DB user** with a timeout and a row cap,
5. answers in natural language **based only on the returned rows** (one combined answer), shows the SQL + table per query, and supports follow-up questions (conversation memory).

The target is the **user's existing MySQL 9.0.1 database**, which is reachable from the dev Mac. The app never writes to it.

## Stack (fixed; don't change it without logging a decision in PROGRESS.md)
| Layer | Choice |
|---|---|
| LLM runtime | **Ollama**, installed natively on macOS (not in Docker, which has no Metal GPU). Model `qwen2.5-coder:7b`. The dev machine is a 16 GB Mac, so `14b` is only an eval experiment. Configured with `OLLAMA_MODEL`. |
| Backend | **Python 3.12**, **FastAPI**, **uv** (deps and venv), Pydantic v2 + pydantic-settings |
| SQL safety | **sqlglot** (`dialect="mysql"`): parse → AST checks → **re-render**; then `EXPLAIN FORMAT=JSON` gate; then **user approval**; execute only the re-rendered SQL |
| Target DB access | SQLAlchemy 2 (async) + **asyncmy** driver, as a dedicated **read-only MySQL user** |
| App storage | Separate **SQLite** file (`backend/data/app.db`) for conversations and the audit log. Never the target DB. |
| LLM client | `httpx` → Ollama `/api/chat`, `format` = JSON schema (structured output), `temperature: 0` for SQL |
| Frontend | **Next.js 15** (App Router) + **TypeScript** (strict) + **Tailwind** + **shadcn/ui**, pnpm |
| Streaming | Server-Sent Events from `POST /api/chat` (plan → `preview`) and `POST /api/chat/{turn_id}/run` (results → answer), with a `: ping` heartbeat every 10s; the frontend reads them with `fetch` + a stream parser |
| Tests | pytest + pytest-asyncio + testcontainers (MySQL); Vitest + React Testing Library; Playwright (e2e) |
| Dev infra | `infra/docker-compose.yml`: a dev **MySQL 9.0** (it matches prod 9.0.1) seeded with a sample e-commerce schema (users, orders, products) |

## Repo layout
```
GEMINI.md  PLAN.md  PROGRESS.md  README.md  STARTUP_GUIDE.md  ORCHESTRATOR_PROMPT.md  Makefile  .env.example
.agents/rules/{backend,frontend,testing}.md
backend/   app/{main.py,config.py,errors.py,api/,core/,llm/,services/,store/}  tests/{unit,integration,security}/  evals/  pyproject.toml
frontend/  app/  components/{chat,ui}/  hooks/  lib/  tests/{mocks}/  package.json
infra/     docker-compose.yml  mysql/seed.sql  mysql/create_readonly_user.sql
```

## Key files (where things live)
| Concern | File |
|---|---|
| Settings (all env keys) | `backend/app/config.py` (+ `.env.example`, PLAN §6) |
| SQL safety validator (L4–L10, `SafeSQL`) | `backend/app/core/validator.py`; corpus `backend/tests/security/{attacks,safe}.yaml` |
| EXPLAIN gate (L12) | `backend/app/core/explain.py` |
| Execution (L2, L3, L9, L11) | `backend/app/core/executor.py` |
| Schema introspection / restricted tables | `backend/app/core/schema.py`, `core/table_selector.py` |
| Pipeline: refusal → plan → preview, run after approval, cancel, heartbeat | `backend/app/services/chat.py` |
| Write-request detection (read-only refusal) | `backend/app/core/intent.py` |
| Risk flags on previews | `backend/app/core/risk.py` |
| SQL audit log (DB + JSONL `SQL_LOG_PATH`) / API | `backend/app/store/database.py` (`record_audit_log`, `list_audit_entries`), `backend/app/api/audit.py` |
| HTTP/SSE endpoints | `backend/app/api/chat.py` (`/api/chat`, `/{turn_id}/run`, `/{turn_id}/cancel`), `api/conversations.py`, `api/schema.py` |
| LLM: prompts (PROMPT_VERSION), generator (`SqlDraft.queries`), answerer | `backend/app/llm/{prompts,sql_generator,answerer,client}.py` |
| App DB (turns incl. `queries_json`, audit log, auto-migration) | `backend/app/store/{models,database}.py` |
| Frontend contract types | `frontend/lib/types.ts` (mirror PLAN §5) |
| SSE parsing / API client | `frontend/lib/{sse,api}.ts` |
| Chat state (send, runTurn, cancelTurn) | `frontend/hooks/use-chat.ts` |
| Approval UI / EXPLAIN view / risk flags / refusal / turn rendering | `frontend/components/chat/{query-preview,explain-summary,risk-flags,refused-card,assistant-turn,status-stepper}.tsx` |
| SQL log panel (header "SQL log" button) | `frontend/components/chat/{sql-log-panel,header}.tsx` |
| Dev proxy (proxyTimeout) | `frontend/next.config.ts` |

## Non-negotiable rules (all agents)
1. **LLM output is untrusted input.** No SQL reaches the DB unless it has passed `core/validator.py`. Never add a bypass or a debug flag that skips it.
2. **Defense in depth:** read-only DB user + `START TRANSACTION READ ONLY` + statement timeout + AST validator + table allowlist + row cap + EXPLAIN gate. Removing any one layer is a bug.
3. **Human approval:** generated SQL is only *previewed* (`POST /api/chat`). It executes only via `POST /api/chat/{turn_id}/run` after the user clicks Run, and it's re-validated and re-EXPLAINed there. Never add an auto-run path.
4. **Be honest about read-only:** requests to change data are refused with an explicit "Not performed (read-only)" message (`refused`), never answered with "Are you sure?" or shown as "Completed". Risky previews must show their flags. **Every SQL event is audit-logged** (`record_audit_log(stage=...)`), so never execute or reject SQL without logging it.
5. **The answer must be grounded:** the answer LLM only sees the question, the SQL and the (truncated) rows. It must say so when the result is empty or doesn't answer the question. No invented numbers.
6. **Secrets** live only in `.env` (git-ignored). Keep `.env.example` in sync. Never log DB passwords.
7. **Keep it local:** no calls to cloud LLMs or telemetry. The backend binds to `127.0.0.1`.
8. **Update `PROGRESS.md` at the end of every work session.** See the protocol below.
9. Keep changes small and tested. A task is not done until its tests pass and PROGRESS.md is updated.

## Subagent routing
- Anything in `backend/`, `infra/` or `evals/` → follow `.agents/rules/backend.md`
- Anything in `frontend/` → follow `.agents/rules/frontend.md`
- Any test, eval or CI work → follow `.agents/rules/testing.md` (it applies alongside the other two)
- If a change touches the API contract (`PLAN.md §5`), update the contract in PLAN.md first, then the backend, then the frontend.

## PROGRESS.md protocol (mandatory)
- The **top block** (`STATUS / NEXT / OPEN / BLOCKERS`) always reflects *right now*. Rewrite it; don't append to it.
- `DECISIONS`: one line per decision, `YYYY-MM-DD: decision — reason`. Never delete these; merge them if they're redundant.
- `LOG`: newest first, one line per session. When the log has more than 15 lines, **compact** the older entries into a single "Done so far" summary line per phase.
- Keep the whole file under **~100 lines**. Use terse fragments, not prose. Use file paths and not explanations where you can.
- Use PLAN.md task IDs (e.g. `P2.3`) so that status maps to the plan.

## Common commands
```bash
# infra (dev MySQL)
docker compose -f infra/docker-compose.yml up -d
# LLM
ollama pull qwen2.5-coder:7b && ollama serve
# everything (dev MySQL + backend :8000 + frontend :3000)
make dev
# backend only
cd backend && uv sync && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # gate (integration needs dev MySQL :3307 up)
cd backend && uv run python -m evals.run   # text-to-SQL accuracy eval (needs Ollama)
# frontend
cd frontend && pnpm install && pnpm dev    # http://localhost:3000
cd frontend && pnpm test && pnpm e2e
```
