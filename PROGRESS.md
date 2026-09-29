# PROGRESS.md
<!-- Agents: rewrite the top block each session. Keep this file under ~100 lines. Protocol: GEMINI.md → "PROGRESS.md protocol". -->

## STATUS
Phase 0 through Phase 7 complete. Core MVP fully built and independently verified. Backend: 213/213 tests green, 97.7% core coverage, 91% overall coverage, 100% attack corpus rejected (68/68), 100% safe corpus passed (42/42), P2.4 defense-in-depth verified. Frontend: Next.js 15, TypeScript strict, ESLint clean, 36/36 Vitest tests green, production build green. Evals: 87.5% execution accuracy (28/32) on native Ollama `qwen2.5-coder:7b`.

## NEXT
1. Connect to user's real MySQL 9.0.1 DB via read-only user in `.env` (awaiting user confirmation).
2. P6.4: Add 10–20 user-provided example questions for custom schema eval.
3. Run `make dev` for local pair testing.

## OPEN (need user input)
- Confirm before first connection to user's real DB (`/usr/local/mysql/bin/mysql` 9.0.1 on `:3306`).
- User to run `infra/mysql/create_readonly_user.sql` on the real DB and update `TARGET_DB_URL` in `.env`.
- User to provide 10–20 real example questions for real DB evaluation (P6.4).
- Real DB table count check (does it exceed 40 tables to trigger table selector?).

## BLOCKERS
none

## DECISIONS
- 2026-09-28: Target DB = user's existing MySQL/MariaDB; dev/test uses a seeded MySQL in Docker — agents can't access the real DB.
- 2026-09-28: LLM = Ollama (native on macOS) + qwen2.5-coder:7b — local, strong at SQL.
- 2026-09-28: Backend FastAPI+uv+sqlglot+asyncmy; frontend Next.js 15+TS+Tailwind+shadcn — user choice.
- 2026-09-28: Safety = RO DB user + READ ONLY txn + timeout + sqlglot AST validator + table allowlist + LIMIT cap; execute re-rendered SQL only.
- 2026-09-28: v1 scope = show SQL + table + answer, conversation memory. No auth, no charts.
- 2026-09-28: Real DB = MySQL 9.0.1, reachable from the dev Mac → dev/test container pinned to mysql:9.0; MariaDB support dropped.
- 2026-09-28: Mac has 16 GB RAM → qwen2.5-coder:7b, OLLAMA_NUM_CTX=8192; 14b only as an eval experiment.
- 2026-09-28: No PII denylist needed (user); keep the DENY_* env hooks, empty.
- 2026-09-28: App data (conversations/audit) in separate SQLite, never in the target DB.
- 2026-09-29: Added Colima container runtime for Docker dev container & testcontainers on dev Mac.
- 2026-09-29: P6.1 TableSelector uses 1-hop bidirectional FK graph expansion when schema > 40 tables.

## LOG (newest first; compact when more than 15 lines)
- 2026-09-29: Full-suite quality gate passed: 213 backend tests, 36 frontend tests, 87.5% eval accuracy on qwen2.5-coder:7b, 100% security corpus passed, Next.js build green.
- 2026-09-29: Phase 6 & 7 complete: table_selector.py with FK expansion, questions.yaml (32 questions), evals/run.py, root Makefile, root README.md.
- 2026-09-29: Phase 4 complete: store/ (SQLite app.db), services/chat.py (pipeline, repair loop, history), api/chat.py (SSE streaming), api/conversations.py (CRUD).
- 2026-09-29: Phase 3 complete: llm/client.py (Ollama + FakeLLM), llm/prompts.py (v1.0 prompts), llm/sql_generator.py (SqlDraft), llm/answerer.py, /api/health Ollama check.
- 2026-09-29: Phase 2 complete: core/validator.py (L4-L10 pure AST safety, SafeSQL token), core/executor.py (L2, L3, L9, L11), 68 attacks rejected (100%), 42 safe queries passed, P2.4 defense-in-depth verified.
- 2026-09-29: Phase 5 frontend complete: lib/sse.ts, lib/api.ts, ChatLayout, Sidebar, SchemaBrowser, SqlBlock, ResultTable, MarkdownAnswer, useChat hook, 36 Vitest tests green.
- 2026-09-29: Phase 1 complete: config.py (Settings), core/db.py (asyncmy engine), core/schema.py (introspection + to_prompt), /api/schema & real /api/health.
- 2026-09-29: Phase 0 complete: P0.1 repo skeleton & git init, P0.2 backend scaffold (uv, FastAPI, ruff, mypy), P0.3 frontend scaffold (Next.js 15, TS, Tailwind, shadcn), P0.4 dev MySQL 9.0 on :3307 & e-commerce seed.
