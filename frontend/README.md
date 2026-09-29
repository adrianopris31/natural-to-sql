# 💻 Natural-to-SQL Frontend

Next.js 15 App Router frontend for the Natural-to-SQL system.

## Features
- **Next.js 15 + React 19 + TypeScript**: Strict type safety and responsive performance.
- **Tailwind CSS + shadcn/ui**: Modern, accessible UI components.
- **Server-Sent Events (SSE) Stream Reader**: Robust parser supporting heartbeats, status steppers, and streaming answers.
- **SQL Preview & Approval Card**: Interactive EXPLAIN plan display, query editing, and approval workflow.
- **ResultTable**: Virtualized/sticky table headers, pagination, and CSV export.
- **Audit Log Panel**: View historical query executions, timings, and approval decisions.

## Quickstart (Development)

```bash
# Install dependencies
pnpm install

# Run development server
pnpm dev
```

The frontend runs on [http://localhost:3000](http://localhost:3000) and proxies `/api/*` requests to the FastAPI backend (`http://127.0.0.1:8000`).

## Testing & Linting

```bash
# Run unit & component tests (Vitest)
pnpm test

# Run linter and typecheck
pnpm lint
pnpm typecheck
```
