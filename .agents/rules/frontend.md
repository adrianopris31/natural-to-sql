---
trigger: glob
globs: frontend/**
description: Frontend subagent rules (Next.js chat UI)
---

# Frontend Agent Rules

**Scope**: `frontend/`. Source of truth: `PLAN.md` §2 (SSE events), §5 (API) and §7 Phase 5. Read `PROGRESS.md` before you start and update it when you finish.

## Stack & style
- Next.js 15 App Router, React 19, TypeScript `strict` (no `any`; use `unknown` and narrow it), Tailwind, shadcn/ui components, pnpm only.
- The chat page is a client component. Keep server components for the static shell only. There's no Next.js API logic: `/api/*` is proxied to FastAPI through `next.config` rewrites.
- Folders: `app/` (routes/layout), `components/chat/*`, `components/ui/*` (shadcn), `lib/api.ts` (fetch + SSE parser), `lib/types.ts` (mirrors PLAN.md §5 exactly), `hooks/` (`useChat`, `useConversations`).
- State: local React state plus a `useChat` hook that owns the streaming turn. Use TanStack Query for the conversation list and history. Don't add another state library unless you log a decision.
- Streaming: `fetch` POST + `ReadableStream` + a hand-written SSE parser (`lib/sse.ts`, unit-tested). Support cancelling with `AbortController`. Don't use `EventSource`, which is GET-only.

## UX requirements
- Every assistant turn shows, in this order: a status stepper, a **SQL block** (collapsed by default after it finishes; syntax-highlighted; copy button), a **ResultTable**, then the **answer** (markdown, streamed).
- ResultTable: sticky header, horizontal scroll, number formatting, `NULL` rendered in a muted style, "Showing N of M (truncated)" when it's truncated, CSV export, and an empty state that says "Query returned no rows".
- Clarification events render as an assistant question. Error events render as an inline alert with a retry button.
- Health banner when `/api/health` reports Ollama or the DB is down.
- Accessibility: semantic HTML, focus rings, `aria-live="polite"` on the streaming answer, and every control reachable by keyboard. Enter sends and Shift+Enter adds a newline.
- Light and dark mode. Responsive down to 375px, where the sidebar becomes a sheet.
- Never render LLM or DB content as raw HTML. Markdown is rendered with `react-markdown`, without `rehype-raw`.

## Contract discipline
- If the backend contract changes (PLAN.md §5 changes), update `lib/types.ts` first, then fix the type errors. Don't guess field names. If a field you need is missing, add it to PROGRESS.md OPEN for the backend agent.
- Before Phase 4 exists, develop against MSW mocks (`tests/mocks/`) that emit realistic SSE sequences, including errors and clarifications.

## Done checklist
`pnpm lint && pnpm typecheck && pnpm test` is green (plus `pnpm e2e` for UI flows) → PROGRESS.md is updated.
