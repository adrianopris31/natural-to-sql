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
| Integration | `tests/integration/` | Docker (testcontainers `mysql:9.0` + seed.sql + RO user) | always when Docker is available; marker `@pytest.mark.integration` |
| Evals | `evals/` | Ollama plus the dev DB | on demand: `uv run python -m evals.run` |

- The security corpus format is `{id, sql, reason}` for attacks and `{id, sql}` for the safe cases. The runner parametrizes over the files. The **attack** cases assert rejection, and the **safe** cases assert acceptance *and* that the re-rendered SQL has the same meaning (they parse to equal ASTs, modulo the injected LIMIT).
- The required integration test (P2.4): with the validator bypassed, `INSERT`, `UPDATE`, `DROP` and `CREATE` through the executor all fail, which proves the RO user plus the READ ONLY transaction hold on their own.
- The pipeline tests cover: the happy path, a clarification, repair success, repair exhaustion, a validator rejection, a timeout (`SELECT SLEEP` isn't allowed, so use a heavy cross join with a 1 ms timeout), a follow-up that uses history, and the SSE event order.
- Coverage target: `core/` ≥ 95%, `app/` overall ≥ 85% (`pytest --cov`).

## Evals (text-to-SQL accuracy)
- `evals/questions.yaml` has entries `{id, question, reference_sql, order_matters: bool, tags}`. The metric is execution accuracy (result sets compared, normalized for numeric precision and column order).
- Output goes to `evals/results/<YYYY-MM-DD>-<model>-<prompt_version>.json` with the pass rate, the per-question results, the p50/p95 latency and the repair rate. Put the summary line in PROGRESS.md.
- A prompt or model change is accepted only if the pass rate doesn't regress by more than 2 points.

## Frontend tests
- Vitest + RTL: `lib/sse.ts` (chunk boundaries, multi-line data, malformed events), ResultTable (truncation, NULL, empty state), the SQL block (collapse, copy), and `useChat` (event reducer).
- Playwright e2e against MSW or a fixture SSE server: ask → SQL → table → answer; a follow-up; an error with retry; a clarification; the health banner.

## Commands
```bash
cd backend && uv run pytest --cov=app
cd backend && uv run pytest tests/security -q
cd backend && uv run python -m evals.run --model qwen2.5-coder:7b
cd frontend && pnpm test && pnpm e2e
```
