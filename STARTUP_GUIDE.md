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

## 5. How to Stop Everything

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

## 6. Useful Maintenance Commands

```bash
# Run all unit, security, and integration tests (213 backend + 36 frontend)
make test

# Run strict linters (Ruff, Mypy, ESLint, TypeScript check)
make lint

# Run the 32-query text-to-SQL evaluation benchmark on qwen2.5-coder:7b
make eval

# Clean build and test caches
make clean
```
