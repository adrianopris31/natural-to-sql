# PROGRESS.md
<!-- Agents: rewrite the top block each session. Keep this file under ~100 lines. Protocol: GEMINI.md → "PROGRESS.md protocol". -->

## STATUS
Phase 11 (Jira/Slack Settings UI / Knowledge-Bot Phase 3) is 100% completed, verified, and ready on branch `feat/jira-slack-settings-ui`. All 358 backend tests and 79 frontend tests (437 total) pass with zero lint or type errors.

## NEXT
1. **Dynamic Database Switching (P10.7)**: Allow users to switch databases from the UI or assign databases per API key tenant.
2. **Phase 8 follow-ups / Evals**: Re-run eval benchmark (`make eval`) on real schema, live checks with Ollama.

## OPEN (need user input)
- Prioritize dynamic DB switching vs live eval tuning on real MySQL?

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
- 2026-10-05: Phase 11 Settings UI: write-only secrets (never stored/echoed/pre-filled), /api/settings/* guarded by ENABLE_SETTINGS_UI & strict localhost check (403), 422 handler sanitizes sensitive input.
- 2026-10-01: Phase 10 External API: SHA-256 hashed API keys (`nl_live_`), scopes (`query`, `admin`), in-memory sliding window rate limiter (60 req/min), daily quota tracking, auto-approve risk gate (safe queries execute immediately in RO transaction; high-risk/Cartesian/blocked queries require explicit approval via /approve), CLI manage_keys.py tool.
- 2026-10-01: Target DB architecture: remain on single database configured via TARGET_DB_URL in .env for now; dynamic database switching from UI / headless external API is planned for future phase.
- 2026-10-01: Knowledge-bot integration: Docs mode bypasses SQL validation/approval gates, streams directly to done, handles missing docs as refusal cards without erroring; health check reports non-blocking degradation if knowledge-bot is down.
- 2026-09-30: On confirmation, UI state transitions immediately to `executing` and suppresses intermediate re-validation SSE events to prevent backward stepper regression.
- 2026-09-30: Pass conversation history into `repair()` and `build_repair_prompt` so multi-turn context is preserved during SQL repair attempts.
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
- 2026-10-05: Phase 11 complete on branch `feat/jira-slack-settings-ui`. Implemented Jira/Slack settings UI modal, write-only secrets, localhost & feature-flag security guards, /api/settings/sources & /refresh, 358 backend + 79 frontend tests green.
- 2026-10-01: Phase 10 complete on branch `feat/external-api-service`. Implemented `/v1/query`, `/v1/query/{turn_id}/approve`, `/v1/query/{turn_id}/cancel`, `/v1/keys`, `/v1/audit`, `/v1/health`. Added API key auth, rate limiting, daily quota tracking, auto-approve risk gate, and CLI `scripts/manage_keys.py`. 332 backend tests and 69 frontend tests passing.
- 2026-10-01: Completed Knowledge-Bot Phases 1 & 2 on branch `feat/knowledge-bot-integration`. Backend: `integrations/knowledge_bot.py`, `services/docs.py`, `app.db` auto-migrations for `kind`/`sources_json`, 314 pytest passing. Frontend: Data/Docs segmented control, source filters, `DocsAnswer` with source links & refusal view, sidebar icons, health banner, 69 Vitest passing.
- 2026-09-30 (Windows chat session): Fixed Windows Corepack pnpm.cjs shim & installed frontend dependencies; normalized config.py paths with as_posix() for macOS/Windows parity; updated dev.ps1 pnpm fallback; documented Windows WampServer/HeidiSQL walkthrough & troubleshooting in README.md.
- 2026-09-30: Completed P2.4 (L1-only isolation tests), history-in-repair loop, Playwright E2E suite (P8.10), and fixed post-approval state regression to "validating" (now "executing"). 293 backend + 57 frontend tests passing.
- 2026-09-29: Claude: read-only refusal (fixes "delete user" → "Completed"), risk red flags + Run-anyway confirmation, full SQL audit log + UI panel; docs updated (see E).
- 2026-09-29: Claude: fixed validator H1–H5; built preview/approval + EXPLAIN gate + multi-query (backend + frontend + tests); updated PLAN §2/§3/§5/§6 and GEMINI rules.
- 2026-09-29: Claude review + fix: diagnosed real-DB hang (introspection 0.1s, LLM gen 10–30s+, Next proxy dropped idle SSE at 30s → turns stuck `generating_sql`). Added heartbeat, proxyTimeout, stream-cutoff handling + tests (see CHANGES MADE BY CLAUDE). The review found validator holes H1–H5.
- 2026-09-29: Diagnosed and resolved DB connection & latency on real DB (`easybiz_data_1`): fixed URL password escaping, normalized APP_DB_PATH, wrapped SSE pipeline with global error handler, verified real queries in ~6.9-14s.
- 2026-09-29: Full-suite quality gate passed: 213 backend tests, 36 frontend tests, 87.5% eval accuracy on qwen2.5-coder:7b, 100% security corpus passed, Next.js build green.
- 2026-09-29: Phases 0–7 completed: scaffold, DB/schema, AST validator (L4–L10), LLM client, pipeline/SSE, frontend, evals & table selection. 213 backend + 36 frontend tests passing.
