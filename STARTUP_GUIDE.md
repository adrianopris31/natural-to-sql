# Natural-to-SQL — Startup & Run Guide

This guide covers everything you need to start, run, and stop the Natural-to-SQL application on macOS.

---

## Quick Reference (Single Command)

If Ollama and Docker/Colima are running:
```bash
make dev
```
This boots the dev MySQL database on port `3307`, starts the FastAPI backend on `http://127.0.0.1:8000`, and starts the Next.js frontend on `http://localhost:3000`.

---

## Step-by-Step Walkthrough

### 1. Start Ollama (Native LLM Runtime)

Open a terminal or run in the background:
```bash
ollama serve
```

Verify that Ollama is reachable and `qwen2.5-coder:7b` is available:
```bash
ollama list
```
*(If you ever need to re-download the model: `ollama pull qwen2.5-coder:7b`)*.

---

### 2. Start the Dev MySQL Database (Port 3307)

Ensure Colima or Docker is active:
```bash
# If Colima is not already running:
colima start --cpu 2 --memory 3

# Start the dev MySQL 9.0 container:
make infra-up
# or: docker compose -f infra/docker-compose.yml up -d
```

The container automatically seeds the e-commerce database (`users`, `categories`, `products`, `orders`, `order_items`, `payments`) and creates the read-only user `nl2sql_ro`.

---

### 3. Start the Application

You can start both backend and frontend together or in separate terminals.

#### Option A: Together (Recommended)
```bash
make dev
```
Press `Ctrl+C` at any time to stop both processes cleanly.

#### Option B: Separate Terminals

**Terminal 1 — Backend (FastAPI):**
```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

**Terminal 2 — Frontend (Next.js 15):**
```bash
cd frontend
pnpm dev
```
- Web UI: [http://localhost:3000](http://localhost:3000)

---

## 4. Connecting to Your Real Database

By default, the app connects to the dev MySQL on port `3307` (`mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3307/ecommerce`).

To switch to your real MySQL 9.0.1 database on port `3306`:

1. **Create the Read-Only User on your MySQL 9.0.1 DB:**
   Run the SQL script from [`infra/mysql/create_readonly_user.sql`](infra/mysql/create_readonly_user.sql):
   ```sql
   CREATE USER IF NOT EXISTS 'nl2sql_ro'@'%' IDENTIFIED BY 'YOUR_SECURE_PASSWORD';
   GRANT SELECT ON your_database_name.* TO 'nl2sql_ro'@'%';
   FLUSH PRIVILEGES;
   ```

2. **Update your `.env` file:**
   ```env
   TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:YOUR_SECURE_PASSWORD@127.0.0.1:3306/your_database_name
   ```

3. **Restart the Backend (`make dev` or restart Terminal 1).**
   The app will automatically introspect your tables, cache the schema, and display your tables in the sidebar browser.

---

## 5. Using the App (preview → approve → run)

1. Ask a question in plain language, e.g. *"How many free day requests are there, and which project has the most tasks?"*
2. The assistant writes 1–3 read-only queries, validates them, and checks each with `EXPLAIN`. It then shows a **preview**: the SQL plus an EXPLAIN summary (estimated cost and rows, how each table is read, warnings). **Nothing has run yet.**
3. Choose:
   - **Run query / Run queries**: validates and EXPLAINs again, executes, shows one table per query, then one combined answer.
   - **Edit**: change the SQL first (Revert undoes the edit). Your SQL goes through every safety check again. If it's rejected, the preview stays open with the reason.
   - **Cancel**: nothing runs.
4. A query marked **Blocked** (too expensive per `EXPLAIN_MAX_COST` / `EXPLAIN_MAX_ROWS` in `.env`) can't run until you edit it, for example by adding filters or a LIMIT.

5. **Asking to change data** ("delete the user X", "update…") shows **Not performed (read-only)**. Nothing is run; ask to *see* the data instead.
6. **Red flags**: a red banner means the query looks dangerous or unexpected (for example, the model first wrote a DELETE that was blocked, or a table is cross-joined). Tick "I reviewed…" to enable **Run anyway**, or edit or cancel instead.
7. **SQL log** (header button): every query generated, rejected, edited, blocked or executed, with row counts and timings. It's also saved to `backend/data/sql_log.jsonl`.

If a question hangs on "Generating SQL", check that Ollama is running (`curl http://127.0.0.1:11434/api/tags`). A dropped connection now shows an error instead of spinning forever.

---

## 6. How to Stop Everything

1. **Stop Frontend and Backend:**
   Press `Ctrl+C` in the terminal where `make dev` is running.

2. **Stop the Dev MySQL Container:**
   ```bash
   make infra-down
   # or: docker compose -f infra/docker-compose.yml down
   ```

3. **Stop Ollama:**
   ```bash
   pkill ollama
   ```

4. **Stop Colima (if you want to free RAM):**
   ```bash
   colima stop
   ```

---

## 7. Useful Maintenance Commands

```bash
# Run all unit, security, and integration tests (286 backend + 57 frontend as of 2026-09-29)
make test

# Run strict linters (Ruff, Mypy, ESLint, TypeScript check)
make lint

# Run the 32-query text-to-SQL evaluation benchmark on qwen2.5-coder:7b
make eval

# Clean build and test caches
make clean
```
