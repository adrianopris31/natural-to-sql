---
trigger: glob
globs: frontend/**
description: Frontend subagent rules (Next.js chat UI)
---

# Frontend Agent Rules

**Scope**: `frontend/`. Source of truth: `PLAN.md` §2 (SSE events), §5 (API) and §7 Phases 5 and 8. Read `PROGRESS.md` before you start and update it when you finish.

## Stack & style
- Next.js 15 App Router, React 19, TypeScript `strict` (no `any`; use `unknown` and narrow it), Tailwind, shadcn/ui components, pnpm only.
- The chat page is a client component. Keep server components for the static shell only. There's no Next.js API logic: `/api/*` is proxied to FastAPI through `next.config` rewrites.
- Folders: `app/` (routes/layout), `components/chat/*`, `components/ui/*` (shadcn), `lib/api.ts` (fetch + SSE parser), `lib/types.ts` (mirrors PLAN.md §5 exactly), `hooks/` (`useChat`, `useConversations`).
- State: local React state plus a `useChat` hook that owns the streaming turn. Use TanStack Query for the conversation list and history. Don't add another state library unless you log a decision.
- Streaming: `fetch` POST + `ReadableStream` + a hand-written SSE parser (`lib/sse.ts`, unit-tested). Support cancelling with `AbortController`. Don't use `EventSource`, which is GET-only.

## UX requirements
- **Approval flow (PLAN §2, Phase 8). Never call `/run` without an explicit user click.**
  - Plan stream ends in `preview` → the turn gets the server `turn_id`, `status: "awaiting_approval"` and `queries[]`. Render `QueryPreview`: per query, the purpose, the SQL (Edit/Revert via textarea), and `ExplainSummary` (cost, rows, table accesses, warnings, blocked reason); then **Run** and **Cancel**.
  - Run is disabled while any *unedited* query is `explain.blocked`. Edited SQL is sent as `queries[i]` (null = unchanged).
  - Run errors with code `VALIDATION_FAILED` / `EXPLAIN_FAILED` / `BLOCKED_BY_EXPLAIN` keep the preview open with the error shown. Other errors → error state.
  - After a run, each query shows: SQL block (collapsed), compact EXPLAIN line, then the ResultTable or its per-query error; then **one** streamed answer.
  - Statuses: generating_sql → validating → explaining (→ repairing) → awaiting_approval → executing → answering → done | cancelled | clarification | error.
- **Refused** (`refused` event / `status: "refused"`): render `RefusedCard` ("Not performed (read-only)") and stepper "Not performed". Never show "Completed" for it.
- `done` arriving after `clarification`/`refused` must **not** overwrite that status (a real bug that hid "Are you sure you want to delete…?").
- **Risk flags**: render `RiskFlags` per unedited query. Any `risk.level === "high"` → red banner, a confirmation checkbox, and the Run button becomes destructive "Run anyway" (disabled until checked).
- **SQL log**: the header "SQL log" button opens `SqlLogPanel` (`GET /api/audit`), with stage badges, SQL, reason, rows and ms. Keep it working when adding new audit stages.
- Legacy turns (no `queries`) still render the old single SQL block + table.
- In `use-chat.ts`, capture the target turn id **when the event arrives** (not inside the deferred `setTurns` updater); the preview changes the id mid-stream.
- ResultTable: sticky header, horizontal scroll, number formatting, `NULL` rendered in a muted style, "Showing N of M (truncated)" when it's truncated, CSV export, and an empty state that says "Query returned no rows".
- Clarification events render as an assistant question. Error events render as an inline alert with a retry button.
- Health banner when `/api/health` reports Ollama or the DB is down.
- Accessibility: semantic HTML, focus rings, `aria-live="polite"` on the streaming answer, and every control reachable by keyboard. Enter sends and Shift+Enter adds a newline.
- Light and dark mode. Responsive down to 375px, where the sidebar becomes a sheet.
- Never render LLM or DB content as raw HTML. Markdown is rendered with `react-markdown`, without `rehype-raw`.

## Contract discipline
- If the backend contract changes (PLAN.md §5 changes), update `lib/types.ts` first, then fix the type errors. Don't guess field names. If a field you need is missing, add it to PROGRESS.md OPEN for the backend agent.
- MSW mocks (`tests/mocks/handlers.ts`) implement the current contract: `/api/chat` → preview (messages containing "two things", "blocked", "clarify", "error" or "cutoff" trigger variants), `/api/chat/:id/run` (an edit containing DROP → VALIDATION_FAILED), `/api/chat/:id/cancel`. Keep them in sync with PLAN §5.

## Done checklist
`pnpm lint && pnpm typecheck && pnpm test` is green (plus `pnpm e2e` for UI flows) → PROGRESS.md is updated.
