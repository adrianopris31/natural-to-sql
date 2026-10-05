# 🚀 Natural-to-SQL Assistant

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=FastAPI&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js 15](https://img.shields.io/badge/Next.js-15.5-black.svg?style=flat&logo=next.js&logoColor=white)](https://nextjs.org/)
[![MySQL 9.0](https://img.shields.io/badge/MySQL-9.0-4479A1.svg?style=flat&logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Ollama](https://img.shields.io/badge/Ollama-qwen2.5--coder:7b-black.svg)](https://ollama.com/)
[![Security Suite](https://img.shields.io/badge/security%20corpus-100%25%20rejected-success.svg)](backend/tests/security/)
[![Tests](https://img.shields.io/badge/tests-453%20passed-brightgreen.svg)](#testing--verification)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-grade, local-first **Natural Language to SQL** analytics assistant. Ask questions about your business data in plain English and receive safe, validated MySQL queries, detailed query execution plans, interactive data tables, and grounded conversational answers—**with zero cloud data leakage**.

Built for **MySQL 9.0 / 8.0+**, powered by native **Ollama (`qwen2.5-coder:7b`)**, orchestrated by **FastAPI**, and presented in a modern **Next.js 15** chat interface.

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Architecture & Data Pipeline](#-architecture--data-pipeline)
- [14-Layer Defense-in-Depth Security Matrix](#-14-layer-defense-in-depth-security-matrix)
- [Knowledge-Bot Integration (Jira / Slack / Docs Q&A)](#-knowledge-bot-integration-jira--slack--docs-qa)
- [Headless External REST API & Key Management (/v1)](#-headless-external-rest-api--key-management-v1)
- [Prerequisites](#-prerequisites)
- [Quickstart (Local Native Mac / Linux)](#-quickstart-local-native-mac--linux)
- [Quickstart (Native Windows Setup)](#-quickstart-native-windows-setup-no-wsl-no-docker-required)
- [Docker Deployment Guide](#-docker-deployment-guide)
- [Running on Other Machines & Remote Environments](#-running-on-other-machines--remote-environments)
- [Connecting to Your Own Database](#-connecting-to-your-own-database)
- [UI Walkthrough & Approval Flow](#-ui-walkthrough--approval-flow)
- [Configuration Reference (`.env`)](#-configuration-reference-env)
- [Testing & Verification](#-testing--verification)
- [Evaluation Benchmark](#-evaluation-benchmark)
- [Roadmap & Future Extensions](#-roadmap--future-extensions)
- [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## ✨ Key Features

- 🛡️ **14-Layer Defense-in-Depth Security**: AST parsing (`sqlglot`), statement allowlists, prohibited function checks, catalog restriction, strict row limits, and non-bypassable `START TRANSACTION READ ONLY` enforcement.
- 👁️ **Human-in-the-Loop Preview & Approval**: Generated SQL is **never executed automatically**. Review the proposed query, inspect its estimated cost and row counts, edit the query if desired, or cancel.
- ⚡ **MySQL `EXPLAIN FORMAT=JSON` Gate**: Every query is cost-analyzed prior to preview and prior to execution. Queries exceeding cost or row thresholds are automatically blocked from execution.
- 📚 **Unified Knowledge-Bot Integration (Jira / Slack / Docs)**: Seamlessly switch between structured SQL data queries and unstructured team documentation, Jira issues, and Slack threads with direct source citation links.
- 🔍 **Multi-Query Intelligence**: Complex questions with multiple components automatically generate up to 3 independent `SELECT` queries that run in parallel and are synthesized into a single cohesive answer.
- 🚫 **Proactive Write Refusal**: Intent detection identifies destructive requests (e.g., *"delete user 42"*, *"drop table orders"*) up front, immediately returning an explicit *"Not performed (read-only)"* notice without invoking LLM tokens.
- 🚩 **Automated Risk Assessment**: Queries involving Cartesian products (`CROSS JOIN`), missing `LIMIT` clauses on large tables, or full table scans display warning badges and require explicit *"Run anyway"* confirmation.
- 📜 **Complete SQL Audit Logging**: Every query lifecycle event (`validated`, `rejected`, `blocked`, `edited`, `executed`) is recorded in SQLite, mirrored to a JSONL file, and inspectable inside the UI via the **SQL Log** panel.
- 🧠 **Zero Hallucination Grounding**: Natural-language answers stream directly from returned database rows. The LLM is strictly prohibited from inventing numbers or extrapolating beyond returned records.

---

## 🏗️ Architecture & Data Pipeline

```
+-----------------------------------------------------------------------------------+
|                                Next.js 15 Web UI                                  |
|   - Chat Interface & Status Stepper (Planning -> Preview -> Running -> Answering) |
|   - Query Preview Card: Syntax-Highlighted SQL, Purpose, EXPLAIN Summary, Risk    |
|   - Interactive Approval: Run / Edit SQL / Cancel / "Run anyway" Confirmation     |
|   - Responsive Data Table: Pagination, Truncation Indicator, CSV Export           |
|   - Sidebar: Database Schema Browser & Multi-Turn Conversation History            |
|   - Audit Log Modal: Live stream of all database operations and latency           |
+-----------------------------------------+-----------------------------------------+
                                          |
        POST /api/chat                    |  POST /api/chat/{turn_id}/run
        (Plan phase: SSE preview)         |  (Run phase: SSE execution & answer)
                                          |  POST /api/chat/{turn_id}/cancel
+-----------------------------------------v-----------------------------------------+
|                               FastAPI Async Backend                               |
|   1. Write-Intent Gate (intent.py)      -> Refuses write requests immediately    |
|   2. Context Loader (prompts.py)        -> DB Schema + 4-turn done history        |
|   3. Local LLM Generator (Ollama)       -> Structured JSON: 1-3 SELECT queries    |
|   4. AST Safety Validator (validator.py)-> AST parse -> Verify -> Re-render SQL   |
|   5. EXPLAIN Gate (explain.py)          -> MySQL cost & row estimation check      |
|   6. Risk Assessor (risk.py)            -> Evaluates join complexity & scan depth |
|   7. Audit Logger (database.py)         -> Logs every event to app.db + JSONL     |
+-------------------+-----------------------------------+---------------------------+
                    |                                   |
         Re-rendered SafeSQL (Read Only)        Ollama API (:11434)
                    |                                   |
+-------------------v-------------------+   +-----------v---------------------------+
|          Target MySQL Database        |   |       Ollama LLM Runtime              |
|  - Dedicated read-only user (nl2sql_ro)  |   |  - Model: qwen2.5-coder:7b            |
|  - START TRANSACTION READ ONLY        |   |  - JSON structured output (temp: 0)   |
|  - max_execution_time timeout (10s)   |   |  - Token streaming answer (temp: 0.2) |
|  - Strict row cap (MAX_ROWS + 1)      |   |  - Metal / CUDA GPU acceleration      |
+---------------------------------------+   +---------------------------------------+
```

---

## 🛡️ 14-Layer Defense-in-Depth Security Matrix

No single security measure is relied upon. Even if the LLM produces malicious or malformed SQL, multiple independent defensive layers prevent unauthorized access, data mutation, or denial of service:

| # | Security Layer | Component | Mechanism & Enforcement | Attack / Vulnerability Prevented |
|---|---|---|---|---|
| **L1** | **Read-Only Database User** | MySQL Engine | Dedicated user `nl2sql_ro` granted only `SELECT` privileges. | Write/mutation bypass even if application is compromised. |
| **L2** | **Read-Only Transaction** | `app/core/executor.py` | Wrapped in `START TRANSACTION READ ONLY; ... ROLLBACK;`. | Prevents any writes even if MySQL user permissions are misconfigured. |
| **L3** | **Execution Timeout** | `app/core/executor.py` | `SET SESSION max_execution_time = 10000;` + client asyncio timeout. | Denial-of-service via resource-locking or runaway queries. |
| **L4** | **AST Grammar Parsing** | `app/core/validator.py` | `sqlglot.parse(sql, read="mysql")` enforces exactly 1 valid statement. | Stacked queries, SQL injection delimiters (`; DROP TABLE...`). |
| **L5** | **Statement Type Verification** | `app/core/validator.py` | Root AST must be `exp.Select` or set operations (`UNION`, `INTERSECT`). | `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `REPLACE`. |
| **L6** | **Forbidden AST Node Walk** | `app/core/validator.py` | Traverses AST rejecting `Into`, `Command`, `Set`, `Use`, `Commit`. | `SELECT ... INTO OUTFILE`, `DUMPFILE`, session variable hijacking. |
| **L7** | **Function Whitelist/Blacklist** | `app/core/validator.py` | Blocks `SLEEP`, `BENCHMARK`, `LOAD_FILE`, `GET_LOCK`, `SYS_EVAL`. | Time-based exfiltration, file system reads, arbitrary execution. |
| **L8** | **Catalog & Table Restriction** | `app/core/validator.py` | Restricts access strictly to introspected tables. CTE scope resolved. | System schema access (`mysql.*`, `information_schema.*`), CTE shadowing. |
| **L9** | **Row Fetch Cap** | `app/core/validator.py` | Injects `LIMIT 501` to enforce `MAX_ROWS` bounds. | Memory exhaustion from unbounded full table dumping. |
| **L10** | **AST Re-Rendering** | `app/core/validator.py` | Returns `SafeSQL` produced strictly by `ast.sql(dialect="mysql")`. | Inline comment tricks (`/*!50000...*/`, `-- `, `/* */`), payload hiding. |
| **L11** | **Output Sanitization** | `app/core/executor.py` | Cells truncated at 500 characters; types converted to JSON-safe primitives. | Large binary payload delivery, browser memory overflow. |
| **L12** | **`EXPLAIN` Cost Gate** | `app/core/explain.py` | Runs `EXPLAIN FORMAT=JSON` in read-only transaction; blocks if cost > threshold. | Catastrophic query complexity, combinatorial explosion, DB lockups. |
| **L13** | **Human-in-the-Loop Approval** | `app/api/chat.py` | Queries are previewed only; execution requires explicit `POST .../run`. | Accidental execution of unintended, expensive, or misunderstood queries. |
| **L14** | **Write Refusal & Risk Warnings**| `app/core/intent.py` | Rejects mutation prompts up front; flags risky queries with red banners. | Social engineering prompts, confusing confirmation dialogs. |

---

## 📚 Knowledge-Bot Integration (Jira / Slack / Docs Q&A)

`natural-to-sql` integrates with **knowledge-bot** (running on port `8100`), serving as a single unified chat application for both **structured tabular data** and **unstructured team knowledge**:

```
                                 +-------------------------+
                                 |    Next.js 15 Web UI    |
                                 |    [ Data | Docs ]      |
                                 +------------+------------+
                                              |
                   +--------------------------+--------------------------+
                   | Mode: "sql"                                         | Mode: "docs"
                   v                                                     v
      +------------------------+                             +------------------------+
      |  FastAPI Backend :8000 |                             |  FastAPI Backend :8000 |
      |  - Ollama LLM (:11434) |                             |  - integrations/       |
      |  - 14-layer SQL Safety |                             |    knowledge_bot.py    |
      |  - EXPLAIN Cost Gate   |                             +-----------+------------+
      |  - Preview & Approval  |                                         | HTTP /v1/ask (X-API-Key)
      +-----------+------------+                                         v
                  |                                          +------------------------+
                  v                                          |  Knowledge-Bot :8100   |
      +------------------------+                             |  - Jira Tickets        |
      | Target MySQL Database  |                             |  - Slack Channels      |
      | (Dedicated Read-Only)  |                             |  - Markdown Runbooks   |
      +------------------------+                             +------------------------+
```

### How Docs Mode Works
1. **Segmented Mode Toggle**: Switch between **Data** (database analytics) and **Docs** (Jira/Slack/documentation Q&A) directly above the prompt bar. Your active mode is saved in `localStorage`.
2. **Source Filter Chips**: In Docs mode, filter chips (**All**, **Jira**, **Slack**, **Docs**) allow targeting specific sources by prepending `jira:`, `slack:`, or `doc:`.
3. **Interactive Citation Badges**: Answers display Markdown along with interactive source chips linking directly to Jira tickets, Slack threads, or team documents.
4. **Honest Refusal Handling**: When documentation does not contain an answer, a distinct *"Not found in the documents"* notice is displayed instead of hallucinating.
5. **Zero SQL Footprint**: Docs turns never generate SQL, touch the database, or trigger the approval gate.
6. **Non-Blocking Health Check**: If Knowledge-Bot is offline, a warning banner alerts the user, while Data mode queries continue functioning without interruption.

### Starting Knowledge-Bot
To run the companion service:
```bash
cd /path/to/knowledge-bot-2
venv/bin/uvicorn knowledge_bot.serving.api:app --host 127.0.0.1 --port 8100
```
Configure your `.env`:
```ini
KNOWLEDGE_BOT_URL=http://127.0.0.1:8100
KNOWLEDGE_BOT_API_KEY=your_api_key_here
KNOWLEDGE_BOT_ADMIN_KEY=your_admin_api_key_here
KNOWLEDGE_BOT_TIMEOUT_SEC=90.0
KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC=900.0
ENABLE_SETTINGS_UI=true
```

### Jira & Slack Settings UI
When `ENABLE_SETTINGS_UI=true` and the app is opened on the backend's own machine (`localhost` / `127.0.0.1`), a gear icon appears in the header allowing configuration of Jira and Slack data sources directly from the UI without modifying server `.env` files:

1. **Origin Badges**: Displays credential source (`Stored`, `From .env`, or `Not set`) along with last synchronization timestamp.
2. **Write-Only Secrets**: Sensitive tokens (`api_token`, `bot_token`) are write-only and never returned, not even masked (knowledge-bot always sends `secret_hint: null`). For a **stored** connection, leaving the token empty keeps it. A connection running on the `.env` token needs a token typed in to save, since `.env` tokens are never copied into storage. Moving Jira's base URL to another site also asks for the token again: a stored token is never sent to a new site.
3. **Live Connection Testing**: Test Jira and Slack configurations before saving with instant validation feedback.
4. **On-Demand Document Refresh**: Re-fetch documents from the configured sources. knowledge-bot answers only when the refresh has finished, so this call uses `KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC` (900s) instead of the normal timeout; a refresh already running shows knowledge-bot's "already running" message.
5. **Localhost & Flag Security Guard** (until login exists): `/api/settings/*` returns 404 unless `ENABLE_SETTINGS_UI=true`, and 403 unless **all** of these hold:
   - the peer is a loopback address (`127.0.0.0/8`, `::1`, IPv4-mapped `::ffff:127.0.0.1`);
   - **no proxy** was involved (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP` absent). The Next.js `/api` rewrite sends no `X-Forwarded-For`, so a proxied request arrives from `127.0.0.1` whoever made it, including other machines on the network. The settings page therefore calls the backend **directly** at `NEXT_PUBLIC_SETTINGS_API_BASE` (default `http://127.0.0.1:8000/api`), so the app must be opened from an origin listed in `CORS_ORIGINS`;
   - the `Host` header names this machine (blocks DNS rebinding);
   - the request carries `X-Requested-With: natural-to-sql`, which forces a CORS preflight so other websites cannot fire settings requests (CSRF).

   Under Docker Compose the backend sees the Docker gateway rather than loopback, so the settings page is unavailable there by design. Validation errors on these routes never echo the request body.

---

## 🔌 Headless External REST API & Key Management (/v1)

Natural-to-SQL provides a production-ready headless REST API mounted under `/v1/`, allowing external automation tools, Slack/Discord bots, CI/CD pipelines, and microservices to run queries programmatically.

### Architecture & Security Policies
- **Database Scope**: The API queries the single target database configured via `TARGET_DB_URL` in `.env`. Connection strings are **never accepted in API requests** to prevent SSRF and credential leaks. *(Dynamic database switching via UI and multi-tenant key mapping is planned on the future roadmap).*
- **Authentication**: Secured via `X-API-Key: nl_live_...` or standard `Authorization: Bearer nl_live_...`.
- **Zero Plaintext Storage**: Keys are hashed with SHA-256 before storage in SQLite (`app.db`).
- **Scopes**:
  - `query`: Access to `/v1/query`, `/v1/query/{turn_id}/approve`, `/v1/query/{turn_id}/cancel`, and `/v1/health`.
  - `admin`: Key provisioning (`POST/GET/DELETE /v1/keys`) and audit log inspection (`GET /v1/audit`).
- **Rate Limiting & Quotas**:
  - In-memory sliding-window rate limiter: **60 requests per minute** per key (returns HTTP 429 when exceeded).
  - Configurable daily quotas: tracked per UTC calendar day (returns HTTP 429 when exceeded; `0` = unlimited).
- **Automated Risk Gating (`auto_approve: true`)**:
  - **Safe queries** (no EXPLAIN block, low/medium risk) execute immediately in `START TRANSACTION READ ONLY` and return grounded natural-language answers and data tables.
  - **High-risk queries** (Cartesian joins, draft blocked) or **EXPLAIN-blocked queries** halt execution and return `status="blocked"`, `blocked: true` with a preview. Callers can inspect the proposed query and explicitly approve it via `POST /v1/query/{turn_id}/approve`.
  - **Destructive requests** (`DROP`, `DELETE`, `UPDATE`) are refused up front with `status="refused"`, `blocked: true`.

---

### Managing API Keys via CLI

Use [`scripts/manage_keys.py`](scripts/manage_keys.py) for terminal key lifecycle management:

```bash
# Issue a query key with a daily quota of 1,000 requests
uv run python scripts/manage_keys.py new "Slack Bot" --scope query --quota 1000

# Issue an admin key
uv run python scripts/manage_keys.py new "Admin CI" --scope admin

# List active keys (shows prefix, label, scope, quota, last used)
uv run python scripts/manage_keys.py list

# List all keys including revoked ones
uv run python scripts/manage_keys.py list --all

# Revoke an API key by its hash prefix (at least 8 characters)
uv run python scripts/manage_keys.py revoke da37658e346b
```

---

### API Endpoints Reference

| Method | Endpoint | Scope | Description |
|---|---|---|---|
| `POST` | `/v1/query` | `query` | Single-shot headless query execution (`sql` or `docs`). |
| `POST` | `/v1/query/{turn_id}/approve` | `query` | Execute an approved turn after preview or edits. |
| `POST` | `/v1/query/{turn_id}/cancel` | `query` | Discard a blocked or previewed turn. |
| `GET` | `/v1/health` | *Public* | Health status of backend and target MySQL connection. |
| `POST` | `/v1/keys` | `admin` | Create a new API key (returns plaintext secret once). |
| `GET` | `/v1/keys` | `admin` | List registered API keys with metadata (no secrets). |
| `DELETE` | `/v1/keys/{prefix}` | `admin` | Revoke an active API key by prefix. |
| `GET` | `/v1/audit` | `admin` | Query recent SQL lifecycle audit log entries. |

---

### cURL Examples

#### 1. Execute Natural-to-SQL Query (Auto-Approve Safe Queries)
```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H "X-API-Key: nl_live_YOUR_KEY_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are our top 5 products by revenue?",
    "mode": "sql",
    "auto_approve": true
  }'
```

**Response (Safe Query - Status Done):**
```json
{
  "turn_id": "c1f7a308-410a-4ff1-a20c-b26a63d9154a",
  "conversation_id": "90e909a3-5c54-47be-9e7f-bd02a3a5f782",
  "mode": "sql",
  "status": "done",
  "answer": "The top product by revenue is iPhone 15 Pro ($45,000)...",
  "queries": [
    {
      "index": 0,
      "purpose": "Find top products by revenue",
      "sql": "SELECT p.name, SUM(oi.price * oi.quantity) AS total_revenue FROM products p JOIN order_items oi ON p.id = oi.product_id GROUP BY p.id ORDER BY total_revenue DESC LIMIT 5",
      "columns": ["name", "total_revenue"],
      "rows": [["iPhone 15 Pro", 45000], ["MacBook Pro 16", 32000]],
      "row_count": 2,
      "truncated": false
    }
  ],
  "timings": { "execution_ms": 4.12, "answer_ms": 420.5 }
}
```

#### 2. Query Requiring Approval (High Risk or Auto-Approve Disabled)
If a query produces a Cartesian join or `auto_approve` is set to `false`:
```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H "X-API-Key: nl_live_YOUR_KEY_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Calculate customer metrics",
    "auto_approve": false
  }'
```

**Response (Awaiting Approval):**
```json
{
  "turn_id": "b3e811f0-08c3-4f9e-a6c3-1ef96c68a4bb",
  "conversation_id": "90e909a3-5c54-47be-9e7f-bd02a3a5f782",
  "mode": "sql",
  "status": "awaiting_approval",
  "blocked": false,
  "queries": [
    {
      "index": 0,
      "sql": "SELECT u.id, COUNT(o.id) AS orders_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.id",
      "explain": { "cost": 12.5, "rows": 150, "blocked": false },
      "risk": { "level": "none", "flags": [] }
    }
  ]
}
```

**Approve and Execute the Turn:**
```bash
curl -X POST http://127.0.0.1:8000/v1/query/b3e811f0-08c3-4f9e-a6c3-1ef96c68a4bb/approve \
  -H "X-API-Key: nl_live_YOUR_KEY_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"queries": null}'
```

#### 3. Execute Documentation Query (Docs Mode)
```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H "X-API-Key: nl_live_YOUR_KEY_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the SLA for P1 production incidents?",
    "mode": "docs"
  }'
```

**Response (Docs Mode):**
```json
{
  "turn_id": "f5d93e11-e408-410a-a03d-82d22b6219ff",
  "conversation_id": "90e909a3-5c54-47be-9e7f-bd02a3a5f782",
  "mode": "docs",
  "status": "done",
  "answer": "P1 production incidents require an initial response within 15 minutes...",
  "sources": [
    {
      "id": "runbook-incident-mgmt",
      "title": "Incident Management Runbook",
      "url": "https://wiki.example.com/incident-management",
      "source_type": "doc",
      "score": 0.94
    }
  ],
  "queries": []
}
```

---


## 📋 Prerequisites

| Component | Minimum Requirement | Notes |
|---|---|---|
| **OS** | macOS (Apple Silicon M1-M4), Linux (x86_64/ARM64), or Windows 10/11 (Native or WSL2) | Runs 100% natively on macOS, Linux, and Windows without virtualization. |
| **Python** | 3.12+ | Managed via [**uv**](https://github.com/astral-sh/uv) (ultra-fast Python package manager). |
| **Node.js** | 20.0+ | Managed via [**pnpm**](https://pnpm.io/) (`corepack enable pnpm`). |
| **Container Engine**| **Optional** (Docker Desktop / Colima) | **Not needed** if you connect to your own MySQL database. |
| **Ollama** | Latest release | Native host install: [ollama.com](https://ollama.com). Runs with GPU acceleration on macOS, Windows, and Linux. |

---

## ⚡ Quickstart (Local Native Mac / Linux)

### 1. Clone & Setup Repository
```bash
git clone https://github.com/adrianopris31/natural-to-sql.git
cd natural-to-sql
cp .env.example .env
```

### 2. Pull the Local LLM Model
Ensure Ollama is running, then pull `qwen2.5-coder:7b`:
```bash
ollama serve &
ollama pull qwen2.5-coder:7b
```

### 3. Launch Development Environment
A single command spins up the sample e-commerce MySQL database (port 3307), runs backend migrations, and starts both backend (`:8000`) and frontend (`:3000`):
```bash
make dev
```
*(Or without Docker / connecting to your own database: run `cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000` in one terminal, and `cd frontend && pnpm install && pnpm dev` in a second terminal).*

Open **[http://localhost:3000](http://localhost:3000)** in your browser!

---

## 🪟 Quickstart: Native Windows Setup (No WSL, No Docker Required)

If you are developing on Windows 10 or 11, the app runs **100% natively in PowerShell** without needing WSL or Docker. All components (`uv`, `pnpm`, `asyncmy`, `sqlglot`, and Ollama) have native Windows support.

### 1. Install Prerequisites (PowerShell)
1. **Ollama for Windows**: Download installer from [ollama.com/download/windows](https://ollama.com/download/windows).
2. **Node.js 20+ (LTS)**: Download installer from [nodejs.org](https://nodejs.org).
3. **`uv` (Python manager)**: In PowerShell, run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
4. **`pnpm`**: In PowerShell, install globally via npm:
   ```powershell
   npm install -g pnpm
   ```
   *(Note: `npm install -g pnpm` is recommended over `corepack enable pnpm` to avoid Node 24 corepack module resolution issues).*
5. **MySQL Server**: You can use native MySQL 8.0/9.0, or [WampServer 64-bit](https://www.wampserver.com/), or XAMPP.
6. **Database GUI (Recommended)**: [HeidiSQL](https://www.heidisql.com/) or MySQL Workbench.

---

### 2. Configure MySQL & HeidiSQL on Windows

If using **WampServer** or local MySQL:

1. **Start the MySQL Service**:
   - Launch **WampServer** (run as Administrator if prompted). Ensure the notification tray icon turns **Green**.
   - If MySQL is stopped, click the Wamp icon $\rightarrow$ **MySQL** $\rightarrow$ **Service administration** $\rightarrow$ **Start / Resume Service** (or open `services.msc` and start `wampmysqld64`).
2. **Connect via HeidiSQL**:
   - **Network type**: `MariaDB or MySQL (TCP/IP)`
   - **Hostname / IP**: `127.0.0.1` (or `localhost`)
   - **User**: `root`
   - **Password**: *(Leave blank/empty by default on WampServer, or enter your MySQL root password)*
   - **Port**: `3306` (Note: Wamp MariaDB defaults to 3307; MySQL defaults to 3306)
   - Click **Open**.
3. **Seed Database & Create Read-Only User**:
   - **Option A (Sample Store DB)**: In HeidiSQL, go to **File $\rightarrow$ Load SQL file...**, select [`infra/mysql/seed.sql`](infra/mysql/seed.sql), and press **F9** (Run) to create and populate the `ecommerce` database.
   - **Option B (Your Own DB)**: Use your existing database (e.g. `your_database`).
   - **Create the Bot's Read-Only User**: In a new HeidiSQL query tab (`Ctrl + T`), run:
     ```sql
     CREATE USER IF NOT EXISTS 'nl2sql_ro'@'%' IDENTIFIED BY 'nl2sql_ro_pass';
     GRANT SELECT ON `ecommerce`.* TO 'nl2sql_ro'@'%';
     FLUSH PRIVILEGES;
     ```
     *(Replace `ecommerce` with your database name if using your own DB, and choose a secure password).*

---

### 3. Download Model & Configure Environment

In PowerShell:
```powershell
# 1. Pull the AI model in Ollama
ollama pull qwen2.5-coder:7b

# 2. Clone repo & create .env
git clone https://github.com/adrianopris31/natural-to-sql.git
cd natural-to-sql
copy .env.example .env
```

Open `.env` in an editor and update `TARGET_DB_URL` to match your local Windows MySQL credentials on port **3306**:
```env
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:nl2sql_ro_pass@127.0.0.1:3306/ecommerce
```

Initialize the Backend and Frontend dependencies:
```powershell
# 1. Initialize Backend (Python 3.12 via uv):
cd backend
uv python install 3.12
uv sync
cd ..

# 2. Initialize Frontend (using pnpm):
cd frontend
pnpm install
cd ..
```

> [!IMPORTANT]
> **Use `pnpm install`, NOT `npm install`**: The repository tracks dependencies via `pnpm-lock.yaml`. Running `npm install` creates conflicting lockfiles and can cause React 19 peer-dependency issues. Always use `pnpm` for frontend package management (`npm install -g pnpm` is only used once to install the CLI).

---

### 4. Start Application

Make sure Ollama is running (`ollama serve`), then start the app using either method:

#### Option A: Single Command Launcher (Recommended)
In PowerShell:
```powershell
.\dev.ps1
```
*(Alternatively, you can double-click `dev.bat` in Windows File Explorer).*
This automatically launches both the FastAPI backend (`http://127.0.0.1:8000`) and Next.js frontend (`http://localhost:3000`) concurrently in separate console windows.

#### Option B: Manual Launch (Two Terminals)
- **Terminal 1 (Backend)**:
  ```powershell
  cd backend
  uv run uvicorn app.main:app --reload --port 8000
  ```
- **Terminal 2 (Frontend)**:
  ```powershell
  cd frontend
  pnpm dev
  ```

Open **[http://localhost:3000](http://localhost:3000)** in your browser!

---

### 💡 Windows Troubleshooting Tips

- **HeidiSQL / MySQL Connection Refused (`10061` / Can't connect to MySQL server)**:
  The MySQL Windows service is offline. Open `services.msc`, locate `wampmysqld64` (or `MySQL`), right-click and select **Start**. On WampServer, ensure the system tray icon is Green.
- **Port 3306 vs 3307**:
  The `.env.example` file defaults to port `3307` for Docker. On native Windows MySQL installations (including WampServer's MySQL), the default port is **`3306`**. Make sure your `.env` has `127.0.0.1:3306`.
- **`pnpm` MODULE_NOT_FOUND (Corepack issue in Node 24)**:
  If `pnpm` errors out with `Cannot find module ... pnpm.cjs`, run:
  ```powershell
  npm install -g pnpm
  ```
- **PowerShell Execution Policy Error**:
  If running `.\dev.ps1` gives an execution policy error, run:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\dev.ps1
  ```

---

## 🐳 Docker Deployment Guide

The repository includes complete Docker configurations for both standalone services and the entire application stack.

### Docker Topology Overview

```
                      +-----------------------------+
                      |       Host Machine / LAN     |
                      |   Ollama (:11434) [Native]  |
                      +--------------^--------------+
                                     |
                          host.docker.internal
                                     |
+------------------------------------+-------------------------------------+
| Docker Network: natural_to_sql_net                                       |
|                                                                          |
|  +---------------------+      +------------------+     +---------------+ |
|  | Frontend Container  | ---> | Backend Container| --> | MySQL 9.0     | |
|  | Next.js 15 (:3000)  |      | FastAPI (:8000)  |     | Dev DB (:3306)| |
|  +---------------------+      +--------+---------+     +---------------+ |
|             ^                          |                                 |
|             |                          v                                 |
|      Host: Port 3000         Volume: ./backend/data                      |
|                              (app.db, sql_log.jsonl)                     |
+--------------------------------------------------------------------------+
```

### 1. Build and Run the Complete Stack with Docker Compose

To run the entire system (Frontend, Backend, and Seed MySQL) in Docker:
```bash
# Build all container images
make docker-build
# or: docker compose build

# Start all services in background
make docker-up
# or: docker compose up -d
```

Check the health status of all containers:
```bash
docker compose ps
```

View aggregated application logs:
```bash
docker compose logs -f backend frontend
```

To stop all services:
```bash
make docker-down
# or: docker compose down
```

### 2. How Networking Works in Docker

1. **Frontend $\rightarrow$ Backend**:
   The frontend communicates with the backend over the internal Docker network via `BACKEND_INTERNAL_URL=http://backend:8000`. Next.js proxies all `/api/*` calls directly to the backend container.
2. **Backend $\rightarrow$ MySQL**:
   The backend connects to MySQL using `mysql:3306` inside the Docker bridge network.
3. **Backend $\rightarrow$ Host Ollama**:
   The backend connects to Ollama on your host machine using:
   - macOS / Windows: `http://host.docker.internal:11434`
   - Linux: `http://host.docker.internal:11434` (enabled via `extra_hosts: ["host.docker.internal:host-gateway"]` in `docker-compose.yml`).

---

## 🌐 Running on Other Machines & Remote Environments

### Scenario A: Running on a Linux GPU Server (Ubuntu / Debian)

On Linux servers with NVIDIA GPUs, you can run Ollama directly with CUDA support:

1. **Install NVIDIA Container Toolkit & Docker** on the server.
2. **Run Ollama with GPU acceleration**:
   ```bash
   ollama serve &
   ollama pull qwen2.5-coder:7b
   ```
3. **Configure `.env`**:
   ```env
   OLLAMA_URL=http://127.0.0.1:11434
   TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:YOUR_PASSWORD@YOUR_DB_HOST:3306/your_database
   CORS_ORIGINS=http://YOUR_SERVER_IP:3000
   ```
4. **Start the containers**:
   ```bash
   docker compose up -d --build
   ```

### Scenario B: Running on Windows (Native vs WSL2)

#### Option 1: 100% Native Windows (Recommended - No WSL, No Docker)
The entire stack runs directly on Windows without virtualization:
1. Install native tools in PowerShell: `ollama.exe`, `uv`, and `pnpm`.
2. Pull model: `ollama pull qwen2.5-coder:7b`.
3. Start backend: `cd backend && uv run uvicorn app.main:app --port 8000`.
4. Start frontend: `cd frontend && pnpm dev`.
*(See the [Native Windows Quickstart](#-quickstart-native-windows-setup-no-wsl-no-docker-required) above for full details).*

#### Option 2: Windows via WSL2 (For Linux Bash Developers)
If you prefer running inside an Ubuntu terminal on Windows:
1. Open Ubuntu in **WSL2**.
2. Install Ollama natively on Windows (or inside WSL2).
3. In `.env`, set `OLLAMA_URL=http://host.docker.internal:11434` (if Ollama is installed on Windows host) or `http://127.0.0.1:11434` (if running inside WSL2).
4. Run `make dev` or `make docker-up`.

### Scenario C: Distributing Components Across Different Machines

You can host each layer on separate infrastructure:

```
[Machine 1: LLM Server]        [Machine 2: App Host]           [Machine 3: Production DB]
Ollama on Port 11434    <---   FastAPI + Next.js App   --->    MySQL 9.0 Database
(Dedicated GPU Box)            (Docker / Cloud VM)             (AWS RDS / On-Premise)
```

In `.env` on Machine 2, point to the respective external hosts:
```env
# Remote Ollama Instance
OLLAMA_URL=http://192.168.1.50:11434

# Remote MySQL Database
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:SecurePassword@192.168.1.100:3306/analytics_db
```

---

## 🔌 Connecting to Your Own Database

By default, the application runs against the local seeded e-commerce database on port 3307. To connect your real MySQL 8.0+ or 9.0+ database:

### 1. Create the Dedicated Read-Only User

Execute the following script on your target MySQL database (also found in [`infra/mysql/create_readonly_user.sql`](infra/mysql/create_readonly_user.sql)):

```sql
-- Create read-only user restricted to SELECT privileges
CREATE USER IF NOT EXISTS 'nl2sql_ro'@'%' IDENTIFIED BY 'YOUR_STRONG_PASSWORD';

-- Grant SELECT permissions on your target database only
GRANT SELECT ON your_database_name.* TO 'nl2sql_ro'@'%';

-- Ensure privileges take effect immediately
FLUSH PRIVILEGES;

-- Verify permissions
SHOW GRANTS FOR 'nl2sql_ro'@'%';
```

### 2. Update `.env`

Update your `.env` file with your target database credentials:
```env
TARGET_DB_URL=mysql+asyncmy://nl2sql_ro:YOUR_STRONG_PASSWORD@127.0.0.1:3306/your_database_name
```
*(Special characters like `@` inside your password are automatically URL-encoded by the backend configuration loader).*

### 3. Exclude Sensitive Columns & Tables

Protect internal framework tables and sensitive user credentials by configuring deny lists in `.env`:
```env
DENY_TABLES=migrations,failed_jobs,personal_access_tokens
DENY_COLUMNS=password,remember_token,two_factor_secret,two_factor_recovery_codes
```

### 4. Restart Backend
Restart the application (`make dev` or `make docker-up`). The application will:
1. Automatically introspect all tables, column types, primary keys, and foreign keys in < 0.1s.
2. Render your tables in the sidebar schema browser.
3. Cache schema structure in memory for instant query generation.

---

## 🖥️ UI Walkthrough & Approval Flow

```
[ User asks: "Which 5 customers generated the highest total revenue?" ]
                                  │
                                  ▼
[ Step 1: Status Stepper ]
  "Planning queries..." -> "Validating AST..." -> "Checking EXPLAIN plan..."
                                  │
                                  ▼
[ Step 2: Query Preview Card ]
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Purpose: Rank top 5 customers by cumulative completed order amount     │
  │                                                                        │
  │ SELECT u.id, u.name, SUM(o.total_amount) AS revenue                   │
  │ FROM users AS u                                                        │
  │ JOIN orders AS o ON u.id = o.user_id                                   │
  │ WHERE o.status = 'completed'                                           │
  │ GROUP BY u.id, u.name ORDER BY revenue DESC LIMIT 5;                  │
  ├────────────────────────────────────────────────────────────────────────┤
  │ EXPLAIN Cost: 48.20 | Est. Rows: 1,240 | Key: idx_orders_user_id       │
  │ Risk: Low                                                              │
  ├────────────────────────────────────────────────────────────────────────┤
  │ [ Run Query ]            [ Edit SQL ]            [ Cancel ]            │
  └────────────────────────────────────────────────────────────────────────┘
                                  │ (User clicks "Run Query")
                                  ▼
[ Step 3: Re-Validation & Execution ]
  "Executing via read-only transaction..." -> "Streaming grounded answer..."
                                  │
                                  ▼
[ Step 4: Results & Grounded Explanation ]
  - Collapsible SQL snippet
  - TanStack Result Table (columns, formatted numbers, CSV export)
  - Natural Language Answer: "The top 5 customers by revenue are Alice ($14,200)..."
```

### Actions Available in Preview Mode

- **Run Query**: Executes the re-validated query through the read-only user and streams the answer.
- **Edit SQL**: Directly modify the generated SQL inside an inline editor. When you click Run, your edited SQL passes through the full 14-layer validator and EXPLAIN gate.
- **Cancel**: Terminates the turn without executing any SQL against your database.
- **High-Risk Banner & "Run anyway"**: If a query has a Cartesian product (`CROSS JOIN`) or very high estimated rows, a warning banner appears and requires checking an *"I reviewed the query plan"* acknowledgment before running.
- **SQL Log Panel**: Click **SQL Log** in the top navigation bar to inspect every query attempted, validation status, execution timings, and row counts.

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Default Value | Description |
|---|---|---|
| `TARGET_DB_URL` | `mysql+asyncmy://...` | Connection URI for the target database using `asyncmy`. |
| `APP_DB_PATH` | `backend/data/app.db` | Path to internal SQLite DB for conversations & audit storage. |
| `SQL_LOG_PATH` | `backend/data/sql_log.jsonl` | Path to JSON Lines file mirroring all SQL audit events. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | HTTP endpoint of the Ollama server. |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | Model used for SQL generation and grounded answering. |
| `OLLAMA_NUM_CTX` | `8192` | Context window size in tokens. |
| `MAX_ROWS` | `500` | Hard cap on rows fetched from MySQL before truncation. |
| `ANSWER_MAX_ROWS` | `50` | Maximum rows passed into the LLM answering context. |
| `QUERY_TIMEOUT_MS`| `10000` | MySQL session statement timeout in milliseconds. |
| `MAX_REPAIR_ATTEMPTS` | `2` | Automated self-repair retry loops if SQL fails validation. |
| `MAX_QUERIES` | `3` | Maximum independent `SELECT` queries per user question. |
| `EXPLAIN_MAX_COST`| `5000000` | Maximum MySQL EXPLAIN query cost before blocking execution. |
| `EXPLAIN_MAX_ROWS`| `10000000` | Maximum estimated rows examined before blocking execution. |
| `EXPLAIN_WARN_ROWS`| `100000` | Threshold for flagging large table scans with risk warnings. |
| `HISTORY_TURNS` | `4` | Number of previous conversation turns included in prompt. |
| `SCHEMA_FULL_MAX_TABLES` | `40` | Threshold above which FK-graph table selector activates. |
| `SCHEMA_SAMPLE_VALUES` | `true` | Fetch distinct values for low-cardinality text columns. |
| `DENY_TABLES` | `migrations` | Comma-separated table names hidden from model context. |
| `DENY_COLUMNS` | `password,...` | Comma-separated columns hidden from model context. |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed origins for FastAPI CORS middleware. |
| `KNOWLEDGE_BOT_URL` | `http://127.0.0.1:8100` | HTTP endpoint of the Knowledge-Bot Q&A service. |
| `KNOWLEDGE_BOT_API_KEY` | `""` | API authentication key (`X-API-Key`) for Knowledge-Bot. |
| `KNOWLEDGE_BOT_ADMIN_KEY` | `""` | Admin-scope API key for managing Knowledge-Bot sources & refresh. |
| `KNOWLEDGE_BOT_TIMEOUT_SEC` | `90.0` | Timeout in seconds for docs/Jira/Slack retrieval requests. |
| `KNOWLEDGE_BOT_REFRESH_TIMEOUT_SEC` | `900.0` | Timeout for the settings page's Refresh, which waits for the whole fetch. |
| `ENABLE_SETTINGS_UI` | `false` | Enable Jira/Slack Settings UI gear in header and `/api/settings/*` routes. |
| `NEXT_PUBLIC_SETTINGS_API_BASE` | `http://127.0.0.1:8000/api` | Frontend: where the settings page calls the backend directly (never through the Next.js proxy). |

---

## 🧪 Testing & Verification

The project includes an exhaustive test suite covering security, integration, unit tests, and frontend components:

```bash
# Run all tests across backend and frontend
make test

# Run backend quality checks (Ruff, Format, Mypy)
make lint
```

### Test Suite Structure

- **Security Tests (`backend/tests/security/`)**:
  - `attacks.yaml`: 75+ malicious attack payloads (DML, DDL, comment injection, `UNION` into system tables, time-based attacks, `SELECT ... INTO OUTFILE`). **100% rejection required.**
  - `safe.yaml`: 45+ legitimate complex SQL queries verifying zero false positives.
  - `test_defense_in_depth.py`: Verifies that read-only transactions and read-only users block writes even if the AST validator were bypassed.
- **Backend Unit & Integration (`backend/tests/`)**:
  - `test_chat_pipeline.py`: Tests preview creation, run approvals, edited queries, EXPLAIN gate blocking, and cancellation.
  - `test_explain.py`: Tests JSON plan parsing, cost extraction, and warning flags.
  - `test_intent.py`: Tests write-intent detection and false-positive prevention on read-only queries.
  - `test_risk.py`: Tests Cartesian product and high-severity risk heuristics.
- **Frontend Vitest (`frontend/tests/`)**:
  - `query-preview.test.tsx`: Tests rendering of SQL previews, EXPLAIN plans, risk confirmations, and approval events.
  - `sql-log-panel.test.tsx`: Tests audit log table display and filtering.
  - `sse.test.ts`: Verifies resilient Server-Sent Events parsing across arbitrary chunk boundaries.

---

## 📊 Evaluation Benchmark

Evaluate text-to-SQL generation accuracy against a deterministic 32-query benchmark:

```bash
make eval
# Or directly:
cd backend && uv run python -m evals.run --model qwen2.5-coder:7b
```

Evaluation compares the actual database results of generated queries against ground-truth reference queries across:
- Simple single-table aggregations (`COUNT`, `SUM`, `AVG`)
- Multi-table `JOIN` operations
- Date truncation and calendar intervals
- Subqueries and window rankings
- Multi-turn conversational follow-ups

Results are stored in `backend/evals/results/<timestamp>-<model>-<prompt_version>.json`.

---

## 🚀 Roadmap & Future Extensions

### 1. Headless External API Service (`POST /v1/query`)
- **Headless Querying**: Allow external clients (backend services, Slack bots, scripts, automated workflows) to query the database programmatically via `X-API-Key` authentication.
- **Automated Risk Gating**: Safe queries (`risk.level < high` and `explain.blocked == false`) execute automatically inside read-only transactions; high-risk queries return an explicit `EXPLAIN_BLOCKED` response without running.
- **Unified Querying**: Supports both `mode: "sql"` and `mode: "docs"`, delivering structured answers, SQL queries, and rows over standard JSON responses.

### 2. Multi-Database Architecture & Dynamic Switching
- **Current State**: Single target database configured via `TARGET_DB_URL` in `.env`.
- **UI Database Selector**: Enable switching between configured databases directly from the Web UI (e.g., `ecommerce`, `analytics`, `crm`).
- **Connection Registry**: Maintain safe, pre-introspected connection pools with strict read-only guarantees without passing untrusted connection strings over the network.

---

## ❓ Troubleshooting & FAQ

### 1. Frontend shows "Generating SQL..." or hangs
- Check if Ollama is running: `curl http://127.0.0.1:11434/api/tags`
- The first query on a cold start loads the 7B model into memory (~15–20s). Subsequent queries take ~4–8 seconds.
- Check backend logs: `docker compose logs -f backend` or review terminal output.

### 2. "Connection refused" when running Backend in Docker connecting to Host Ollama
- Ensure Ollama on the host is bound to `0.0.0.0` or `127.0.0.1`.
- On macOS/Windows, the backend reaches the host via `http://host.docker.internal:11434`.
- On Linux, ensure `OLLAMA_URL=http://host.docker.internal:11434` and verify Docker host-gateway mapping.

### 3. Password contains special characters like `@` or `:`
- The backend configuration loader automatically URL-encodes special characters in passwords. Simply provide your raw password in `TARGET_DB_URL`.

### 4. Query is marked as "Blocked by EXPLAIN"
- The query's estimated cost or row scan exceeds `EXPLAIN_MAX_COST` or `EXPLAIN_MAX_ROWS`.
- Click **Edit SQL** in the preview card, add specific `WHERE` filters or an index-backed condition, and click **Run Query**.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
