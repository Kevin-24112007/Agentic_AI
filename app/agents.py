"""The supervisor and its two specialists.

    supervisor  talks to the student, owns no domain tools at all, and can only
                delegate. Whatever it decides, it cannot itself touch the
                database.
      |
      +-- balance  read-only. Balance, holidays, leave history.
      +-- desk     read + write. Apply, withdraw, notify the HOD.

Least privilege is structural, not a promise in a prompt: the balance
specialist is handed a toolset that contains no write tool, so there is nothing
for a confused or prompt-injected model to call.

Idempotency keys are derived from the parent's key, so a delegated tool call
lands on the same key on a replay as it did on the original attempt.
"""
import time
from typing import Any

from app.idempotency import idempotency_key
from app.providers import AgentError
from app.tools.leave_tools import BalanceTools, LeaveDeskTools, Toolset

SPECIALIST_MAX_STEPS = 10

SUPERVISOR_SYSTEM = """You are the Campus Leave Assistant, speaking with student {roll_no}.

You never change leave data yourself. You have two specialists:
- ask_balance  for leave balance, holidays and leave history. Read-only.
- ask_desk     for applying leave, withdrawing leave, or notifying the HOD.

Give a specialist everything it needs in one request, including dates and the
reason. Never invent policy limits or balances; use what the tools return.
When the specialists have reported back, answer the student briefly and plainly."""

BALANCE_SYSTEM = """You are the read-only leave information specialist.

You can inspect the current student's balance, leave requests and the holiday
calendar. You have no tools that change anything, so never say that leave was
applied, approved or withdrawn. Report only what the tools returned."""

DESK_SYSTEM = """You are the leave desk specialist for student {roll_no}.

You may apply leave, withdraw leave and notify the HOD, for this student only.
Do not invent day limits or balances: the database enforces both and will tell
you if a request is refused. After a leave change actually succeeds, notify the
HOD if the request asked for it. If a tool returns an error, report it plainly
instead of retrying with different numbers."""


def run_tool(toolset: Toolset, db: Any, key: str, name: str, args: dict) -> tuple[dict, bool]:
    """Run one tool call. Returns (result, replayed).

    `replayed` is True when nothing new happened because this exact effect had
    already been carried out under this key.
    """
    try:
        if name in toolset.DELEGATES:
            return toolset.delegate(name, args, key), False
        if name in toolset.SIDE_EFFECTS:
            return _run_side_effect(toolset, db, key, name, args)
        return toolset.call(name, args), False
    except AgentError:
        raise                                  # the worker decides about retries
    except Exception as exc:
        # A broken tool must not kill the run: hand the model a readable error
        # and let it respond to the student.
        return {"error": "tool_failed", "hint": f"{type(exc).__name__}: {exc}"}, False


def _run_side_effect(toolset: Toolset, db: Any, key: str, name: str, args: dict) -> tuple[dict, bool]:
    """Every write goes through a key stored alongside the effect.

    Where that happens depends on the backend, and this is the only place in the
    codebase that has to know the difference.
    """
    if hasattr(db, "once"):
        # SQLite: one local transaction writes the effect and its key together.
        result, fresh = db.once(key, name, lambda: toolset.call_side_effect(name, args, key))
        return result, not fresh

    # Supabase: the key lives in the PL/pgSQL function, in the same PostgreSQL
    # transaction as the write, which is the only way to make it atomic over HTTP.
    result = toolset.call_side_effect(name, args, key)
    return result, bool(result.get("replayed") or result.get("duplicate"))


def run_specialist(agent: str, system: str, toolset: Toolset, *, db, provider,
                   task: str, parent_key: str, on_step=None) -> dict:
    """Drive one specialist until it answers or runs out of steps."""
    contents = [{"role": "user", "text": task}]
    used: list[str] = []
    seq = 0

    while seq < SPECIALIST_MAX_STEPS:
        turn = provider.generate(system, contents, list(toolset.functions().values()))
        seq += 1

        if not turn.tool_calls:
            return {"agent": agent, "answer": turn.text or "", "tools_used": used}

        calls = [{"name": c.name, "args": c.args} for c in turn.tool_calls]
        contents.append({"role": "model", "text": turn.text, "raw": turn.raw, "tool_calls": calls})

        for call in calls:
            seq += 1
            # Derived from the supervisor's key, so a replay of the parent step
            # reproduces exactly these child keys.
            key = idempotency_key(parent_key, seq, call["name"], call["args"])
            started = time.perf_counter()
            result, replayed = run_tool(toolset, db, key, call["name"], call["args"])
            used.append(call["name"])

            if on_step:
                on_step({
                    "agent": agent, "kind": "tool", "tool": call["name"], "args": call["args"],
                    "result": result, "ok": "error" not in result, "replayed": replayed,
                    "ms": round((time.perf_counter() - started) * 1000),
                })
            contents.append({"role": "tool", "name": call["name"], "result": result})

    return {"agent": agent, "error": "specialist_step_limit", "tools_used": used}


class SupervisorTools(Toolset):
    """The supervisor's only two tools: ask one specialist, or ask the other."""

    TOOL_NAMES = ("ask_balance", "ask_desk")
    DELEGATES = TOOL_NAMES

    def __init__(self, db, providers: dict, roll_no: str, on_step=None):
        self.db, self.providers, self.roll_no, self.on_step = db, providers, roll_no, on_step

    def ask_balance(self, question: str) -> dict:
        """Ask the read-only information specialist about leave balance, holidays or history.

        Use this for anything the student wants to know. Do not use it to apply
        for or withdraw leave; this specialist has no tools that change data,
        and asking it to write will simply fail. Changes nothing.
        Args: question is a complete, self-contained question.
        """
        raise RuntimeError("delegation is executed by delegate(), not by calling this")

    def ask_desk(self, request: str) -> dict:
        """Ask the leave desk specialist to apply leave, withdraw leave, or notify the HOD.

        Use this only when the student has asked for something to actually
        happen. Do not use it for questions; ask_balance is cheaper and safer.
        It changes leave data.
        Args: request must state the dates, the number of days and the reason.
        """
        raise RuntimeError("delegation is executed by delegate(), not by calling this")

    def delegate(self, name: str, args: dict, key: str) -> dict:
        field = "question" if name == "ask_balance" else "request"
        value = args.get(field)
        if set(args) != {field} or not isinstance(value, str) or not value.strip():
            return {"error": "invalid_arguments",
                    "hint": f"{name} takes exactly one non-empty {field} string."}

        if self.on_step:
            self.on_step({"agent": "supervisor", "kind": "delegate", "tool": name, "args": args})

        if name == "ask_balance":
            return run_specialist(
                "balance", BALANCE_SYSTEM, BalanceTools(self.db, self.roll_no),
                db=self.db, provider=self.providers["balance"],
                task=value, parent_key=key, on_step=self.on_step)

        return run_specialist(
            "desk", DESK_SYSTEM.format(roll_no=self.roll_no),
            LeaveDeskTools(self.db, self.roll_no),
            db=self.db, provider=self.providers["desk"],
            task=value, parent_key=key, on_step=self.on_step)
