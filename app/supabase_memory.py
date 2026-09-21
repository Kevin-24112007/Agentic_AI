"""The agent's memory and job queue, stored in Supabase.

The cloud twin of `app/memory.py`, method for method, so `app/worker.py` and
`app/runner.py` work against either one unchanged.

Anything that has to be atomic (claim a run, append a message at the next seq,
finish a run only if you still own it) is an RPC, because PostgREST has no
transactions across requests. The functions in `schema/supabase.sql` return
plain scalars wherever there is one answer, so nothing here has to guess whether
it received a row, a list of rows, or an empty set.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from app.supabase_client import SupabaseClient


@dataclass(frozen=True)
class Claimed:
    run_id: str
    thread_id: str
    attempts: int


def _first(rows):
    """PostgREST gives a set-returning function a list. Take row one, or None."""
    if isinstance(rows, list):
        return rows[0] if rows else None
    return rows


class RunStore:
    def __init__(self, client: SupabaseClient, clock=time.time):
        self.client, self.clock = client, clock

    def migrate(self) -> None:
        """Nothing to do: `schema/supabase.sql` is applied once in the SQL Editor."""
        return None

    # --------------------------------------------------------- conversations

    def create_thread(self, student_id: str) -> str:
        thread_id = str(uuid.uuid4())
        self.client.rpc("create_thread", {"p_id": thread_id, "p_student_id": student_id})
        return thread_id

    def get_thread(self, thread_id: str) -> dict | None:
        rows = self.client.select("agent_thread", filters={"id": f"eq.{thread_id}"}, limit=1)
        return rows[0] if rows else None

    def append_message(self, thread_id: str, role: str, text: str) -> int:
        return int(self.client.rpc("append_message", {
            "p_thread_id": thread_id, "p_role": role, "p_text": text}))

    def load_history(self, thread_id: str) -> list[dict]:
        return self.client.select(
            "agent_message", columns="seq,role,text",
            filters={"thread_id": f"eq.{thread_id}"}, order="seq.asc")

    # ------------------------------------------------------------- run steps

    def record_model_step(self, run_id: str, seq: int, tokens_in: int, tokens_out: int,
                          text: str | None, tool_calls: list[dict]) -> int:
        return int(self.client.rpc("record_model_step", {
            "p_run_id": run_id, "p_seq": seq, "p_tokens_in": tokens_in,
            "p_tokens_out": tokens_out, "p_text": text, "p_tool_calls": tool_calls}))

    def record_tool_call(self, run_id: str, seq: int, name: str, args: dict, result: dict,
                         ok: bool, latency_ms: int, idempotency_key: str | None = None) -> int:
        return int(self.client.rpc("record_tool_call", {
            "p_run_id": run_id, "p_seq": seq, "p_name": name, "p_args": args,
            "p_result": result, "p_ok": ok, "p_latency_ms": latency_ms,
            "p_idempotency_key": idempotency_key}))

    def load_steps(self, run_id: str) -> list[dict]:
        """Every recorded step, in order. This is what a replay is rebuilt from."""
        rows = self.client.rpc("load_run_steps", {"p_run_id": run_id}) or []
        # The SQL column is `step_text`, because a column literally named `text`
        # inside RETURNS TABLE shadows the type name. The rest of the codebase
        # expects `text`, so rename it here rather than leaking SQL trivia.
        return [{**row, "text": row.pop("step_text", None)} for row in rows]

    def get_run(self, run_id: str) -> dict | None:
        rows = self.client.select("agent_run", filters={"id": f"eq.{run_id}"}, limit=1)
        if not rows:
            return None
        return {**rows[0], "steps": self.load_steps(run_id)}

    # ----------------------------------------------------------- the queue

    def enqueue(self, thread_id: str, text: str, model: str, max_attempts: int = 3) -> str:
        run_id = str(uuid.uuid4())
        self.client.rpc("enqueue_run", {
            "p_run_id": run_id, "p_thread_id": thread_id, "p_text": text,
            "p_model": model, "p_max_attempts": max_attempts})
        return run_id

    def claim_next(self, worker_id: str, lease_seconds: float) -> Claimed | None:
        row = _first(self.client.rpc("claim_next_run", {
            "p_worker_id": worker_id, "p_lease_seconds": lease_seconds}))
        if not row:
            return None
        return Claimed(row["run_id"], row["thread_id"], row["attempts"])

    def heartbeat(self, run_id: str, worker_id: str, lease_seconds: float) -> bool:
        return bool(self.client.rpc("heartbeat_run", {
            "p_run_id": run_id, "p_worker_id": worker_id, "p_lease_seconds": lease_seconds}))

    def reap_expired(self) -> list[str]:
        rows = self.client.rpc("reap_expired") or []
        return [row["id"] for row in rows]

    def complete(self, run_id: str, worker_id: str, reply: str) -> bool:
        return bool(self.client.rpc("complete_run", {
            "p_run_id": run_id, "p_worker_id": worker_id, "p_reply": reply}))

    # ------------------------------------------------------------ cancelling

    def request_cancel(self, run_id: str) -> str | None:
        return self.client.rpc("request_cancel", {"p_run_id": run_id})

    def cancel_requested(self, run_id: str) -> bool:
        rows = self.client.select(
            "agent_run", columns="cancel_requested",
            filters={"id": f"eq.{run_id}"}, limit=1)
        return bool(rows and rows[0]["cancel_requested"])

    def mark_cancelled(self, run_id: str, worker_id: str) -> bool:
        return bool(self.client.rpc("mark_cancelled", {
            "p_run_id": run_id, "p_worker_id": worker_id}))

    # --------------------------------------------------- retry / dead letter

    def fail_attempt(self, run_id: str, worker_id: str, error_code: str,
                     retryable: bool, backoff_seconds: float = 2.0) -> str | None:
        return self.client.rpc("fail_attempt", {
            "p_run_id": run_id, "p_worker_id": worker_id, "p_error_code": error_code,
            "p_retryable": retryable, "p_backoff_seconds": backoff_seconds})
