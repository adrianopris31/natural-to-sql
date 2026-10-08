# PROGRESS.md
<!-- Agents: rewrite the top block each session. Keep this file under ~100 lines. Protocol: GEMINI.md → "PROGRESS.md protocol". -->

## STATUS
All phases completed (Phases 0 through 12, Phase 8/6/7 follow-ups). 385 backend tests and 93 frontend tests (478 total) passing with zero lint or type errors. Benchmark accuracy 90.62% on seed DB (prompt v1.2), live Ollama check verified on easybiz_data_1.

## NEXT
Production deployment / optional model eval experiments (e.g. qwen2.5-coder:14b comparison if requested).

## OPEN (need user input)
none

## BLOCKERS
none

## DECISIONS
- 2026-10-08: evals/run.py CLI supports --db-url / --database and auto-resolves ecommerce test container for benchmark questions when TARGET_DB_URL points to user DB.
- 2026-10-08: Added Layer L3 statement timeout integration test using non-equi self-join to trigger MySQL 3024 execution interrupt reliably across macOS/Docker timer resolutions.
- 2026-10-07: Phase 12 Dynamic Multi-Database Switching: multi-engine pooling via get_engine(db_name), discovery via SHOW DATABASES, schema caching per db, database column on conversations/turns.
- 2026-10-05: Phase 11 Settings security hardening: direct frontend base with CSRF header X-Requested-With, loopback IP parsing with ipaddress, DNS rebinding Host check, proxy header rejection.
- 2026-10-01: Phase 10 External API: SHA-256 hashed API keys (`nl_live_`), scopes (`query`, `admin`), sliding window rate limiter (60 req/min), daily quota tracking, auto-approve risk gate.
- 2026-10-01: Knowledge-bot integration: Docs mode streams directly to done with source links, handles missing docs as refusal cards, non-blocking health check degradation.
- 2026-09-30: On confirmation, UI state transitions immediately to `executing` and suppresses intermediate re-validation SSE events.
- 2026-09-29: Write requests are refused up front (keyword check + model `write_intent`); risky previews are red-flagged; every SQL event is audit-logged (DB + JSONL + UI).
- 2026-09-29: Every generated query needs explicit user approval; EXPLAIN gates execution (blocked = can't run unless edited); up to 3 queries per question.
- 2026-09-28: Dev/test on seeded MySQL in Docker; real DB only via RO user. Local Ollama + qwen2.5-coder:7b.

## LOG (newest first; compact when more than 15 lines)
- 2026-10-08: Completed all remaining phase items. P8.9/P8.16: full 32-question eval benchmark ran on qwen2.5-coder:7b prompt v1.2 achieving 90.62% accuracy (29/32 pass, 0 repairs, 7.5s avg latency). P6.4: created evals/questions_user_db.yaml (11 questions for easybiz_data_1, 8/11 passed). P8.8: live plan->preview->run turn & write refusal verified on easybiz_data_1. Added L3 timeout test to test_executor.py (385 backend + 93 frontend = 478 tests passing). Updated testing.md and PLAN.md.
- 2026-10-07: Phase 12 (Dynamic Multi-Database Switching) complete and merged into main. Multi-engine pooling, db discovery, schema cache per db, /api/databases, DatabaseSelector UI dropdown. 384 backend + 93 frontend tests green.
- 2026-10-05: Phase 11 review fixes & UI complete. Closed Next proxy localhost bypass, added CSRF header, ipaddress loopback validation, 900s timeout, write-only UX. 369 backend + 84 frontend tests green.
- 2026-10-01: Phase 10 complete on branch `feat/external-api-service`. Headless REST API (/v1/query, /v1/keys, /v1/audit), API key auth, rate limiting, quota tracking, CLI manage_keys.py. 332 backend + 69 frontend tests green.
- 2026-10-01: Phase 9 complete. Knowledge-bot integration for Jira/Slack/Docs Q&A, segmented control, source filter chips, docs pipeline. 314 backend + 69 frontend tests green.
- 2026-09-30: Windows Corepack fixes; completed P2.4 (L1 isolation tests), history-in-repair loop, Playwright E2E suite (P8.10), fixed post-approval state regression. 293 backend + 57 frontend tests green.
- 2026-09-29: Phase 8 safety review & features: preview/approval, EXPLAIN gate, multi-query, write refusal, audit log, validator H1–H5, SSE heartbeat.
- 2026-09-28: Phases 0–7 completed: scaffold, DB/schema, AST validator (L4–L10), LLM client, pipeline/SSE, frontend, evals & table selection.
