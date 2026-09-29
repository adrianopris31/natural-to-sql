---
trigger: model_decision
description: Testing subagent rules. Apply whenever you write or change tests or evals, or verify a task as done.
---

# Testing Agent Rules

**Scope**: `backend/tests/`, `backend/evals/`, `frontend/tests/`, and CI. These rules apply alongside backend.md and frontend.md.

## Principles
- A task is done only when it has tests and they are green. Report failures honestly in PROGRESS.md; never skip or delete a failing test to get to green (you may mark it `xfail` only with a reason and an OPEN item).
- Tests are deterministic: no real Ollama in unit or integration tests (use `FakeLLMClient` or `respx`), a fixed seed DB, and no dependence on the wall clock (freeze today's date in prompts).

## Backend test layout
| Suite | Path | Needs | Runs |
|---|---|---|---|
| Unit | `tests/unit/` | nothing | always |
| Security | `tests/security/` (`attacks.yaml`, `safe.yaml`, the runner) | nothing (pure validator) | always; **must be 100%** |
| Integration | `tests/integration/` | the **running dev MySQL on :3307** (`make infra-up`; `tests/conftest.py` forces that URL unless `TEST_TARGET_DB_URL` or `USE_ENV_TARGET_DB` is set) | always |
| Evals | `evals/` | Ollama plus the dev DB | on demand: `uv run python -m evals.run` |

- The security corpus format is `{id, sql, reason}` for attacks and `{id, sql}` for the safe cases. The runner parametrizes over the files. The **attack** cases assert rejection, and the **safe** cases assert acceptance *and* that the re-rendered SQL has the same meaning (they parse to equal ASTs, modulo the injected LIMIT).
- The required integration test (P2.4): with the validator bypassed, `INSERT`, `UPDATE`, `DROP` and `CREATE` through the executor all fail, which proves the RO user plus the READ ONLY transaction hold on their own. ⏳ The current `test_defense_in_depth.py` opens the READ ONLY txn itself; add a variant *without* the txn to prove the RO user alone.
- The pipeline tests (`tests/integration/test_chat_pipeline.py`) cover: **the preview never executes** (no `result`/answer before `/run`), run after approval, run only once (`INVALID_STATE`), cancel, user-edited SQL is re-validated and executed, a dangerous edit is refused with nothing run, EXPLAIN `blocked` refuses the run, repair after a validation error, repair after an EXPLAIN error (unknown column), repair exhaustion, multi-query preview + run + combined answer, clarification, history includes only `done` turns, and the HTTP endpoints (`/api/chat`, `/run`, `/cancel` 204/409). Keep all of these when changing the pipeline.
- Also covered: "delete …" refused with **no LLM call** and a `refused` audit entry; model `write_intent` refused; a preview whose first draft was a DELETE gets high risk `UNSAFE_DRAFT_BLOCKED`; the audit stage sequence `rejected → validated → edited → validated → executed` (+ JSONL file); `GET /api/audit`. Unit: `tests/unit/test_intent.py` (positives and **false-positive guards**), `tests/unit/test_risk.py`. `tests/conftest.py` points `SQL_LOG_PATH` at a temp file, so tests never write the real log.
- EXPLAIN summarization is tested without a DB (`tests/unit/test_explain.py`, using captured MySQL 9 plans). Add a captured plan whenever you change the gate logic.
- Still missing: a timeout test (heavy cross join with a 1 ms timeout) and Playwright e2e (P8.10).
- Coverage target: `core/` ≥ 95%, `app/` overall ≥ 85% (`pytest --cov`).

## Evals (text-to-SQL accuracy)
- `evals/questions.yaml` has entries `{id, question, reference_sql, order_matters: bool, tags}`. The metric is execution accuracy (result sets compared, normalized for numeric precision and column order).
- Output goes to `evals/results/<YYYY-MM-DD>-<model>-<prompt_version>.json` with the pass rate, the per-question results, the p50/p95 latency and the repair rate. Put the summary line in PROGRESS.md.
- A prompt or model change is accepted only if the pass rate doesn't regress by more than 2 points.

## Frontend tests
- Vitest + RTL: `lib/sse.ts` (chunk boundaries, multi-line data, malformed events, `preview`, indexed `result`/`error`), ResultTable (truncation, NULL, empty state), the SQL block (collapse, copy), `QueryPreview` (EXPLAIN shown, edits sent only for edited queries, Run disabled on blocked, cancel, run error shown), and `useChat` (preview → runTurn → done, edit, recoverable error keeps the preview, cancel, stream cutoff, clarification survives `done`, refused), QueryPreview risk (banner + confirmation), `SqlLogPanel`.
- Playwright e2e (P8.10, **not written yet**; config expects `frontend/tests/e2e/`) against MSW or a fixture SSE server: ask → preview → Run → tables → answer; Edit then Run; Cancel; blocked query (Run disabled); a follow-up; an error with retry; a clarification; the health banner.

## Commands
```bash
cd backend && uv run pytest --cov=app
cd backend && uv run pytest tests/security -q
cd backend && uv run python -m evals.run --model qwen2.5-coder:7b
cd frontend && pnpm test && pnpm e2e
```
