# GEMINI.md — Natural-to-SQL Chatbot

> Read this first, then read `PROGRESS.md` (current state), then `PLAN.md` (the full plan).
> Domain rules are in `.agents/rules/` (backend, frontend, testing).

## What this project is
A local chatbot. The user asks a question about their data in plain language (for example, *"give me the top users by revenue"*). The app:
1. turns the question into **one read-only MySQL `SELECT`**, using a **local LLM** (Ollama),
2. **validates** that SQL with an AST-based safety layer and **runs** it through a **read-only DB user** with a timeout and a row cap,
3. answers in natural language **based only on the returned rows**,
4. shows the user the generated SQL, the result table and the answer, and supports follow-up questions (conversation memory).

The target is the **user's existing MySQL 9.0.1 database**, which is reachable from the dev Mac. The app never writes to it.

## Stack (fixed; don't change it without logging a decision in PROGRESS.md)
| Layer | Choice |
|---|---|
| LLM runtime | **Ollama**, installed natively on macOS (not in Docker, which has no Metal GPU). Model `qwen2.5-coder:7b`. The dev machine is a 16 GB Mac, so `14b` is only an eval experiment. Configured with `OLLAMA_MODEL`. |
| Backend | **Python 3.12**, **FastAPI**, **uv** (deps and venv), Pydantic v2 + pydantic-settings |
| SQL safety | **sqlglot** (`dialect="mysql"`): parse → AST checks → **re-render** → execute the re-rendered SQL |
| Target DB access | SQLAlchemy 2 (async) + **asyncmy** driver, as a dedicated **read-only MySQL user** |
| App storage | Separate **SQLite** file (`backend/data/app.db`) for conversations and the audit log. Never the target DB. |
| LLM client | `httpx` → Ollama `/api/chat`, `format` = JSON schema (structured output), `temperature: 0` for SQL |
| Frontend | **Next.js 15** (App Router) + **TypeScript** (strict) + **Tailwind** + **shadcn/ui**, pnpm |
| Streaming | Server-Sent Events from `POST /api/chat`; the frontend reads them with `fetch` + a stream parser |
| Tests | pytest + pytest-asyncio + testcontainers (MySQL); Vitest + React Testing Library; Playwright (e2e) |
| Dev infra | `infra/docker-compose.yml`: a dev **MySQL 9.0** (it matches prod 9.0.1) seeded with a sample e-commerce schema (users, orders, products) |

## Repo layout (target)
```
GEMINI.md  PLAN.md  PROGRESS.md  .env.example
.agents/rules/{backend,frontend,testing}.md
backend/   app/{main.py,config.py,api/,core/,llm/,services/,store/}  tests/  evals/  pyproject.toml
frontend/  app/  components/  lib/  tests/  package.json
infra/     docker-compose.yml  mysql/seed.sql  mysql/create_readonly_user.sql
```

## Non-negotiable rules (all agents)
1. **LLM output is untrusted input.** No SQL reaches the DB unless it has passed `core/validator.py`. Never add a bypass or a debug flag that skips it.
2. **Defense in depth:** read-only DB user + `START TRANSACTION READ ONLY` + statement timeout + AST validator + table allowlist + row cap. Removing any one layer is a bug.
3. **The answer must be grounded:** the answer LLM only sees the question, the SQL and the (truncated) rows. It must say so when the result is empty or doesn't answer the question. No invented numbers.
4. **Secrets** live only in `.env` (git-ignored). Keep `.env.example` in sync. Never log DB passwords.
5. **Keep it local:** no calls to cloud LLMs or telemetry. The backend binds to `127.0.0.1`.
6. **Update `PROGRESS.md` at the end of every work session.** See the protocol below.
7. Keep changes small and tested. A task is not done until its tests pass and PROGRESS.md is updated.

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
# backend
cd backend && uv sync && uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000
cd backend && uv run pytest            # unit + integration
cd backend && uv run python -m evals.run   # text-to-SQL accuracy eval (needs Ollama)
# frontend
cd frontend && pnpm install && pnpm dev    # http://localhost:3000
cd frontend && pnpm test && pnpm e2e
```
