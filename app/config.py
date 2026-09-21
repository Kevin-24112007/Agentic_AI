"""Which storage and which model the process should use.

Two backends, same interfaces:

  sqlite    two local files, no key, no network. This is what `python -m
            scripts.demo` and `pytest` use, so a clean machine can grade the
            project with nothing installed but the requirements.

  supabase  the hosted PostgreSQL project. Same agents, same tools, same
            worker; only the two repository classes change.

Secrets come from a local `.env` that is gitignored. Nothing here ever prints a
key, and `.env.example` is the only file with the variable names in it.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Read KEY=value lines from .env into the environment.

    A real environment variable always wins, so CI and `export` still override
    the file. Written by hand because a one-file parser is not worth a
    dependency, and it keeps `pip install -r requirements.txt` to two packages.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in ("'", '"'):
            value = value[1:-1]           # tolerate quoted values
        os.environ.setdefault(key, value)


load_env()

LEAVE_DB = os.environ.get("LEAVE_DB", "leave.db")
AGENT_DB = os.environ.get("AGENT_DB", "agent.db")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def storage_backend() -> str:
    """'sqlite' or 'supabase'.

    Read on every call rather than frozen at import, because the demo decides
    the backend from its own flags before opening anything. If STORAGE_BACKEND
    is not set we infer it: having SUPABASE_URL configured means you meant it.
    """
    explicit = os.environ.get("STORAGE_BACKEND", "").strip().lower()
    if explicit in ("sqlite", "supabase"):
        return explicit
    if explicit:
        raise ValueError(f"STORAGE_BACKEND must be 'sqlite' or 'supabase', got {explicit!r}")
    return "supabase" if os.environ.get("SUPABASE_URL") else "sqlite"


def open_stores():
    """Return (RunStore, LeaveDb) for the selected backend, ready to use."""
    if storage_backend() == "supabase":
        from app.supabase_client import SupabaseClient
        from app.supabase_leave_db import LeaveDb
        from app.supabase_memory import RunStore
        client = SupabaseClient()
        return RunStore(client), LeaveDb(client)

    from app.leave_db import LeaveDb
    from app.memory import RunStore
    store, db = RunStore(AGENT_DB), LeaveDb(LEAVE_DB)
    store.migrate()
    db.migrate()
    return store, db


def make_providers(mock: bool, slow: float = 0.0) -> dict:
    """One provider per agent. Scripted by default; real Gemini with --real."""
    if mock:
        from app.providers import demo_providers
        return demo_providers(slow)

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit(
            "GEMINI_API_KEY is not set, so --real cannot run.\n"
            "Put it in .env, or drop --real to use the scripted models.")
    from app.providers import GeminiProvider
    gemini = GeminiProvider(GEMINI_MODEL)
    return {"supervisor": gemini, "balance": gemini, "desk": gemini}
