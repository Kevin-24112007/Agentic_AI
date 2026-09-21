# 🎓 Campus Leave Agent

> An end-to-end, multi-agent student leave management system featuring **durable execution**, **atomic state transitions**, **idempotency**, and support for both **SQLite** and **Supabase (PostgreSQL)** backends.

---

## 📌 Overview

**Campus Leave Agent** is an autonomous AI agent application designed to handle student leave applications and balance inquiries with zero data corruption. It features a robust multi-agent architecture (Supervisor and Specialist agents) backed by a durable job queue, enabling tasks to recover seamlessly from worker crashes or network interruptions.

### Key Highlights
- 🛡️ **Database-Enforced Policy**: Policy limits (e.g. max 3 days per application) and balance rules are enforced directly inside database transactions—not in LLM prompts.
- 🔁 **Crash Replay & Idempotency**: Every tool execution carries a deterministic idempotency key. If a worker crashes mid-task, it resumes from the exact state without repeating side effects.
- 👥 **Multi-Agent Design with Least Privilege**: The Supervisor delegates work to dedicated specialists: a **Read-Only Balance Specialist** and a **Bound Leave Desk Specialist**.
- ☁️ **Dual Backend Support**: Runs out of the box with zero external dependencies using local SQLite databases (`leave.db` and `agent.db`), or seamlessly connects to a cloud-hosted Supabase PostgreSQL instance.

---

## 🛠️ Architecture & Multi-Agent Flow

```text
Student Request
      │
      ▼
Job Queue ──► Worker (Lease + Replay Engine) ──► Supervisor Agent
                                                    │
                                      ┌─────────────┴─────────────┐
                                      ▼                           ▼
                              Balance Specialist          Leave Desk Specialist
                                 (Read-Only)                (Read + Write)
                                      │                           │
                                      ▼                           ▼
                                Read Tools                  Write Tools
                                      │                           │
                                      └─────────────┬─────────────┘
                                                    ▼
                                          Leave Domain Database
                                     (Policy, Balance, Requests)
```

---

## 🚀 Quick Start Guide (Local Setup)

No external API keys or cloud services are required to run and test the application locally.

### 1. Installation

Clone the repository and set up a virtual environment:

```bash
# Clone the repository
git clone https://github.com/Kevin-24112007/agentic_ai.git
cd leave-agent

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Automated Tests

Run the complete test suite (31 tests passing, including crash replay and multi-threaded race conditions):

```bash
pytest -q
```

### 3. Run the Interactive Demo

See the full end-to-end user flow and crash recovery in action:

```bash
# Normal end-to-end execution
python -m scripts.demo

# Crash recovery demonstration (simulates a worker crash mid-execution and resumes safely)
python -m scripts.demo --crash
```

---

## 💬 Using the Interactive CLI

You can interact with the system via CLI using a background worker and the `ask` script.

### Step 1: Start the Background Worker
In **Terminal 1**, start a local worker:
```bash
python -m scripts.worker --mock
```

### Step 2: Submit Student Requests
In **Terminal 2**, ask questions or apply for leave:

```bash
# Check leave balance
python -m scripts.ask "How many leave days do I have?"

# Apply for leave for a specific student
python -m scripts.ask --student 22IT017 "Apply leave from 2026-10-05 to 2026-10-06 for 2 days, family event"
```

### Step 3: Cooperative Task Cancellation (Optional)
To test cancelling a running request in real-time from a second terminal:

```bash
# Terminal 1: Run worker in slow mode (simulates latency)
python -m scripts.worker --mock --slow 2

# Terminal 2: Enqueue a request and cancel it
python -m scripts.ask "Apply leave for me" &
python -m scripts.cancel <run-id-printed-by-ask>
```

---

## ☁️ Supabase Cloud Deployment Setup

To point the application to a cloud-hosted Supabase PostgreSQL database:

1. **Create a Supabase Project** on [supabase.com](https://supabase.com).
2. **Apply Database Migration**:
   - Open **SQL Editor** in Supabase.
   - Paste the contents of [`schema/supabase.sql`](file:///c:/Users/Kevin%20Jonathan%20AK/Downloads/weekend-leave-agent-fixed/leave-agent/schema/supabase.sql) and click **Run**.
   - *(Note: All statements are idempotent and safe to run multiple times).*
3. **Configure Environment Variables**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Fill in your Supabase credentials in `.env`:
     ```env
     STORAGE_BACKEND=supabase
     SUPABASE_URL=https://<your-project-ref>.supabase.co
     SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
     ```
     *(Use the `service_role` key to bypass RLS policies safely on the backend).*
4. **Verify Cloud Connection**:
   ```bash
   python -m scripts.cloud_check
   ```
5. **Run Cloud Demos**:
   ```bash
   python -m scripts.demo --cloud
   python -m scripts.demo --cloud --crash
   ```

---

## 🤖 Using Real Gemini Models (Optional)

By default, tests and CLI demos use deterministic mock LLM providers (`app/providers.py::RoutedMock`) to run offline without quota limitations.

To use Google Gemini LLMs:
1. Add your API key to `.env`:
   ```env
   GEMINI_API_KEY=your-gemini-api-key
   ```
2. Pass the `--real` flag to the demo script:
   ```bash
   python -m scripts.demo --real
   # Or combined with Supabase:
   python -m scripts.demo --cloud --real
   ```

---

## 📂 Project Structure

```text
leave-agent/
├── app/
│   ├── agents.py              # Supervisor + Specialist agents (least privilege)
│   ├── config.py              # Configuration & backend selector (sqlite vs supabase)
│   ├── db.py                  # SQLite database connection helper
│   ├── idempotency.py         # Deterministic idempotency key generator
│   ├── leave_db.py            # Domain database methods (SQLite)
│   ├── memory.py              # Runtime queue & state store (SQLite)
│   ├── providers.py           # Scripted mock models & Google Gemini provider
│   ├── runner.py              # Replayable run execution engine
│   ├── supabase_client.py     # PostgREST/RPC HTTP client for Supabase
│   ├── supabase_leave_db.py   # Domain database implementation for Supabase
│   ├── supabase_memory.py     # Runtime queue implementation for Supabase
│   ├── worker.py              # Background queue worker (claim, execute, record)
│   └── tools/
│       ├── dispatch.py        # Model tool call router
│       └── leave_tools.py     # Domain tool implementations with docstrings
├── schema/
│   ├── leave.sql              # SQLite domain schema & seed data
│   ├── agent.sql              # SQLite agent runtime schema
│   └── supabase.sql           # Unified PostgreSQL migration script for Supabase
├── scripts/
│   ├── ask.py                 # Interactive CLI client
│   ├── cancel.py              # Cooperative run cancellation CLI
│   ├── cloud_check.py         # Verification tool for Supabase connection
│   ├── demo.py                # End-to-end execution & crash recovery demo
│   └── worker.py              # CLI runner for background queue worker
└── tests/                    # Comprehensive unit and end-to-end test suite
```

---

## 🔒 Security & Best Practices

- **Row Level Security (RLS)**: Row Level Security is enabled on every Supabase table with public access revoked (`anon` and `authenticated` keys are denied access). Only the backend service-role key has access.
- **Git Safety**: Secrets are managed via `.env` which is git-ignored by default. `.env.example` serves as a clean template.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
