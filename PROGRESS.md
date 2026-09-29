# PROGRESS.md
<!-- Agents: rewrite the top block each session. Keep this file under ~100 lines. Protocol: GEMINI.md → "PROGRESS.md protocol". -->

## STATUS
v1 + Phase 8 done: SQL preview/approval, EXPLAIN gate, multi-query (≤3), **read-only refusal of write requests, risk red flags, full SQL audit log (DB + JSONL + UI panel)**. Validator holes H1–H5 fixed. Real DB `easybiz_data_1` (MySQL 9.0.1) + dev DB :3307. Backend 286 tests, frontend 57; ruff/mypy/eslint/tsc clean. Pending: a live test with the real model (Ollama was down; verified on the real DB with scripted model output).

## NEXT
1. **P8.8** Live check with Ollama (`ollama serve`, `make dev`) on `easybiz_data_1`: preview → Run / Edit / Cancel; "delete user" → Not performed; a risky query → red banner + Run anyway; SQL log panel.
2. **P8.9/P8.16** `make eval` with prompt v1.2; accept if ≥ 85.5% (v1.0 = 87.5%). Check the keyword refusal has no false positives on real questions.
3. **P8.10** Playwright e2e (`frontend/tests/e2e/`, missing): preview → Run, Edit, Cancel, blocked, refused, risky → Run anyway, SQL log.
4. **P2.4** Defense-in-depth test *without* opening the READ ONLY txn (prove the RO user alone blocks writes).
5. Merge `feat/sql-preview-safety` into `main` once P8.8 passes (all work incl. Antigravity's last fixes is committed there); delete stray untracked `backend/backend/data/app.db`, `backend/test_dt.db`.
6. **P6.4** real-DB evals; pass history to repair(); **P8.11** tune EXPLAIN thresholds (real-DB costs so far: 5–230).

## OPEN (need user input)
- Verify `SHOW GRANTS FOR 'nl2sql_ro'@'%'` on the real DB = SELECT on `easybiz_data_1`.* only.
- `.env`: the active TARGET_DB_URL = real DB `easybiz_data_1` :3306 (dev :3307 is commented out). Restart the backend after switching (settings are cached; `--reload` ignores `.env`).
- Any more tables to exclude via DENY_TABLES?

## BLOCKERS
none

<!-- Agents: Claude's work below is committed on branch feat/sql-preview-safety. Once it's merged to main, compact this section into one LOG line. -->
## CHANGES MADE BY CLAUDE (2026-09-29, committed on branch `feat/sql-preview-safety`; the agents keep these)
**A. Hang fix.** On the real DB the UI hung on "generating": the Next proxy's 30s idle timeout closed the SSE stream while the LLM was generating.
- `services/chat.py` `with_heartbeat()` (`: ping` every 10s, used by `api/chat.py`); CancelledError → turn marked error. `frontend/next.config.ts` `experimental.proxyTimeout: 300_000`. `use-chat.ts`: a stream ending without a terminal event → error. Tests: `tests/unit/test_heartbeat.py`.

**B. Validator holes H1–H5 fixed** (`core/validator.py`, `core/schema.py`, `core/table_selector.py`):
- H1 `SELECT *`/`t.*` rejected on tables with DENY_COLUMNS (`TableModel.has_restricted_columns`). H2 CTE refs resolved by scope (`_cte_reference_ids`); CTE names can't shadow real tables. H3 any db/catalog qualifier ≠ target DB is rejected (`SchemaModel.database`). H4 `SafeSQL` has no default token. H5 typed funcs are checked by `sql_name()`.
- Tests: 7 new attacks in `attacks.yaml`, 3 safe cases in `safe.yaml`, and star/forge/cross-db tests in `tests/security/test_validator.py`.

**C. Feature: preview + EXPLAIN + multi-query** (contract in PLAN.md §2/§3/§5; GEMINI rule 3)
- Backend: `core/explain.py` (EXPLAIN FORMAT=JSON in an RO txn → `ExplainSummary`, the gate via `EXPLAIN_MAX_COST`/`EXPLAIN_MAX_ROWS`, warnings via `EXPLAIN_WARN_ROWS`). `services/chat.py`: `process_chat` = plan only → `preview`; `run_approved_turn` (re-validate + re-EXPLAIN, blocked = refused, edited SQL allowed but not repaired); `cancel_turn`. `api/chat.py`: `POST /api/chat/{id}/run`, `/cancel`. `llm/sql_generator.py` `SqlDraft.queries` (legacy `sql` accepted, capped to `MAX_QUERIES`). `llm/prompts.py` v1.1 (multi-query, no `SELECT *`, `AnswerResult` multi-result answer prompt). `llm/answerer.py` temp 0.2. `store/`: `turns.queries_json` + auto-migration, `get_turn`. `api/conversations.py`: `queries` on turns. `config.py` + `.env.example`: MAX_QUERIES, EXPLAIN_*.
- Frontend: `lib/types.ts` (TurnQuery, ExplainSummary, preview event, new statuses), `lib/sse.ts`, `lib/api.ts` (`runTurnStream`, `cancelTurn`), `hooks/use-chat.ts` (`runTurn`, `cancelTurn`, id captured per update), `components/chat/query-preview.tsx` (Edit/Revert/Run/Cancel; Run disabled for unedited blocked queries), `explain-summary.tsx`, `assistant-turn.tsx` (per-query SQL + plan + table), `status-stepper.tsx` (Checking plan / Your approval / Cancelled), `chat-layout.tsx`.
- Tests: `tests/unit/test_explain.py`; `tests/integration/test_chat_pipeline.py` rewritten (preview never executes, run once, edit, dangerous edit refused, EXPLAIN block, EXPLAIN-error repair, multi-query, cancel, history = done turns only, HTTP). Frontend: `tests/query-preview.test.tsx`, updated `use-chat`/`api`/`sse` tests and MSW mocks.
- Verified on the real DB (scripted model output): 2 queries previewed with EXPLAIN (costs 5.15 / 229), run after approval, correct rows; an edit to `UPDATE` was refused; `SELECT * FROM users` rejected.

**E. Read-only honesty, red flags, SQL log** (PLAN P8.12–P8.15). Bug: "delete user" showed "Completed": the model asked "Are you sure you want to delete…?" (clarification), then the backend's `done` overwrote the status in the frontend, so the question was hidden. Nothing was deleted, but the user couldn't tell.
- Backend: `core/intent.py` (`detect_write_request` before the LLM → `refused`, no LLM call); `SqlDraft.write_intent` + prompt **v1.2** (rule 10 + few-shot 4); `core/risk.py` (`assess_risk` → `queries[].risk`, flags listed in PLAN §2 step 5); audit `stage/row_count/elapsed_ms` columns (auto-migrated) on every event + JSONL mirror `SQL_LOG_PATH` (`backend/data/sql_log.jsonl`); `GET /api/audit` (`api/audit.py`); `status=refused`.
- Frontend: `refused` event/status + `refused-card.tsx`; `done` no longer overwrites clarification/refused; `risk-flags.tsx`; `query-preview.tsx` red banner + "I reviewed…" checkbox + destructive "Run anyway"; `sql-log-panel.tsx` + header "SQL log" button; `fetchAuditLog`.
- Tests: `tests/unit/test_intent.py`, `tests/unit/test_risk.py`, pipeline refusal/risk/audit-stage/JSONL/`/api/audit` tests; `conftest.py` sends the SQL log to a temp file. Frontend: refused, clarification-survives-done, risk confirmation, `sql-log-panel.test.tsx`.
- Verified on the real DB: "delete user" refused (0 LLM calls); a DELETE draft blocked → preview high risk; a cross join `tasks × timesheet_item` (~357K rows) flagged high; audit stages logged to DB + JSONL.

**D. Docs updated to match** (so agents don't rely on stale context):
- `GEMINI.md`: project flow (preview/approval), stack rows, a **Key files** map, rule 3 (human approval, no auto-run), a notice about the external changes, and commands.
- `PLAN.md`: §1 goals/non-goals, §2 two-phase pipeline + SSE events + error codes, §3 L8 rewritten + L12 EXPLAIN + L13 approval, §4 prompts v1.1, §5 API (`/run`, `/cancel`, `queries` on turns), §6 new env keys, **§7 Phase 8 (P8.1–P8.11 with ✅/⏳)**, §8 DoD, §9 risks.
- `.agents/rules/backend.md` (execution path via approval, validator invariants, heartbeat, app-DB migrations), `frontend.md` (approval UX, statuses, mocks), `testing.md` (pipeline test list, EXPLAIN tests, integration uses dev MySQL :3307, missing e2e/P2.4).
- (Updated again for E: PLAN §2/§3 L14 + Audit/§5 `/api/audit`/§6 `SQL_LOG_PATH`/P8.12–P8.16; GEMINI rule 4 + key files; agent rules; README; STARTUP_GUIDE §5.)
- `README.md` (architecture + 13-layer model; it wrongly claimed "formula-injection sanitization", which isn't implemented, so that was removed) and `STARTUP_GUIDE.md` (§5 Using the app: preview → approve → run).

## DECISIONS
- 2026-09-29: Write requests are refused up front (keyword check + model `write_intent`), never answered with a confirmation question; risky previews are red-flagged and need an explicit "Run anyway"; every SQL event is audit-logged (DB + JSONL + UI). User request.
- 2026-09-29: Every generated query needs explicit user approval (always preview); EXPLAIN is shown and gates execution (blocked = can't run unless edited); up to 3 independent queries per question, answered together. User choice.
- 2026-09-29: Auto-encode `@` in DB URL passwords and allow string-or-list in Settings to avoid pydantic validation halts.
- 2026-09-29: Absolute path normalization for `APP_DB_PATH` to avoid split SQLite databases across subdirectories.
- 2026-09-29: Added `DENY_TABLES=migrations` and `DENY_COLUMNS=password,remember_token,two_factor_secret,two_factor_recovery_codes` for real DB safety.
- 2026-09-28: Dev/test on seeded MySQL in Docker; real DB only via RO user.
- 2026-09-28: LLM = Ollama (native on macOS) + qwen2.5-coder:7b — local, strong at SQL.
- 2026-09-28: Backend FastAPI+uv+sqlglot+asyncmy; frontend Next.js 15+TS+Tailwind+shadcn — user choice.
- 2026-09-28: Safety = RO DB user + READ ONLY txn + timeout + sqlglot AST validator + table allowlist + LIMIT cap; execute re-rendered SQL only.
- 2026-09-28: v1 scope = show SQL + table + answer, conversation memory. No auth, no charts.
- 2026-09-28: Real DB = MySQL 9.0.1, reachable from the dev Mac → dev/test container pinned to mysql:9.0; MariaDB support dropped.
- 2026-09-28: Mac has 16 GB RAM → qwen2.5-coder:7b, OLLAMA_NUM_CTX=8192; 14b only as an eval experiment.
- 2026-09-28: App data (conversations/audit) in separate SQLite, never in the target DB.
- 2026-09-29: Added Colima container runtime for Docker dev container & testcontainers on dev Mac.
- 2026-09-29: SSE `: ping` heartbeat every 10s (api/chat.py `with_heartbeat`) + Next `experimental.proxyTimeout=300s`; frontend treats stream end without done/error/clarification as error; backend marks turn error on client disconnect.
- 2026-09-29: P6.1 TableSelector uses 1-hop bidirectional FK graph expansion when schema > 40 tables.

## LOG (newest first; compact when more than 15 lines)
- 2026-09-29: Claude: read-only refusal (fixes "delete user" → "Completed"), risk red flags + Run-anyway confirmation, full SQL audit log + UI panel; docs updated (see E).
- 2026-09-29: Claude: fixed validator H1–H5; built preview/approval + EXPLAIN gate + multi-query (backend + frontend + tests); updated PLAN §2/§3/§5/§6 and GEMINI rules.
- 2026-09-29: Claude review + fix: diagnosed real-DB hang (introspection 0.1s, LLM gen 10–30s+, Next proxy dropped idle SSE at 30s → turns stuck `generating_sql`). Added heartbeat, proxyTimeout, stream-cutoff handling + tests (see CHANGES MADE BY CLAUDE). The review found validator holes H1–H5.
- 2026-09-29: Diagnosed and resolved DB connection & latency on real DB (`easybiz_data_1`): fixed URL password escaping, normalized APP_DB_PATH, wrapped SSE pipeline with global error handler, verified real queries in ~6.9-14s.
- 2026-09-29: Full-suite quality gate passed: 213 backend tests, 36 frontend tests, 87.5% eval accuracy on qwen2.5-coder:7b, 100% security corpus passed, Next.js build green.
- 2026-09-29: Phase 6 & 7 complete: table_selector.py with FK expansion, questions.yaml (32 questions), evals/run.py, root Makefile, root README.md.
- 2026-09-29: Phase 4 complete: store/ (SQLite app.db), services/chat.py (pipeline, repair loop, history), api/chat.py (SSE streaming), api/conversations.py (CRUD).
- 2026-09-29: Phase 3 complete: llm/client.py (Ollama + FakeLLM), llm/prompts.py (v1.0 prompts), llm/sql_generator.py (SqlDraft), llm/answerer.py, /api/health Ollama check.
- 2026-09-29: Phase 2 complete: core/validator.py (L4-L10 pure AST safety, SafeSQL token), core/executor.py (L2, L3, L9, L11), 68 attacks rejected (100%), 42 safe queries passed, P2.4 defense-in-depth verified.
- 2026-09-29: Phase 5 frontend complete: lib/sse.ts, lib/api.ts, ChatLayout, Sidebar, SchemaBrowser, SqlBlock, ResultTable, MarkdownAnswer, useChat hook, 36 Vitest tests green.
- 2026-09-29: Phase 1 complete: config.py (Settings), core/db.py (asyncmy engine), core/schema.py (introspection + to_prompt), /api/schema & real /api/health.
- 2026-09-29: Phase 0 complete: P0.1 repo skeleton & git init, P0.2 backend scaffold (uv, FastAPI, ruff, mypy), P0.3 frontend scaffold (Next.js 15, TS, Tailwind, shadcn), P0.4 dev MySQL 9.0 on :3307 & e-commerce seed.
