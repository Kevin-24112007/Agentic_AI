"""The leave domain, stored in Supabase.

This is the cloud twin of `app/leave_db.py`. It exposes exactly the same method
names, so `app/tools/leave_tools.py` never learns which one it is talking to.

The one real difference: every side effect is a single `rpc` call, because the
check, the write and the idempotency record have to happen in one PostgreSQL
transaction. Doing it in three HTTP calls from Python would leave a window where
a crash loses the key but keeps the effect.
"""
from __future__ import annotations

from app.supabase_client import SupabaseClient


class LeaveDb:
    def __init__(self, client: SupabaseClient):
        self.client = client

    def migrate(self) -> None:
        """Nothing to do: `schema/supabase.sql` is applied once in the SQL Editor."""
        return None

    # ------------------------------------------------------------- read only

    def get_student(self, roll_no: str) -> dict | None:
        rows = self.client.select("leave_student", filters={"roll_no": f"eq.{roll_no}"}, limit=1)
        return rows[0] if rows else None

    def policy(self, name: str) -> int:
        rows = self.client.select("leave_policy", filters={"name": f"eq.{name}"}, limit=1)
        if not rows:
            raise KeyError(name)
        return rows[0]["value"]

    def holidays(self, start_date: str | None = None, end_date: str | None = None) -> list[dict]:
        # Both bounds are conditions on the SAME column, so they go in as a
        # list. A plain dict would keep only the second one and quietly widen
        # the range.
        conditions: list[str] = []
        if start_date:
            conditions.append(f"gte.{start_date}")
        if end_date:
            conditions.append(f"lte.{end_date}")
        filters = {"holiday_date": conditions} if conditions else None
        return self.client.select(
            "leave_holiday", columns="holiday_date,name",
            filters=filters, order="holiday_date.asc")

    def active_requests(self, student_id: int) -> list[dict]:
        return self.client.select(
            "leave_request", columns="id,start_date,end_date,days,reason,status",
            filters={"student_id": f"eq.{student_id}", "status": "eq.approved"},
            order="start_date.asc,id.asc")

    def leave_requests(self, student_id: int) -> list[dict]:
        return self.client.select(
            "leave_request", columns="id,start_date,end_date,days,reason,status",
            filters={"student_id": f"eq.{student_id}"}, order="id.asc")

    def get_request(self, request_id: int) -> dict | None:
        rows = self.client.select("leave_request", filters={"id": f"eq.{request_id}"}, limit=1)
        return rows[0] if rows else None

    # ---------------------------------------------------------- side effects

    def apply_leave(self, student_id: int, start_date: str, end_date: str,
                    days: int, reason: str, idempotency_key: str) -> dict:
        return self.client.rpc("apply_leave", {
            "p_student_id": student_id,
            "p_start_date": start_date,
            "p_end_date": end_date,
            "p_days": days,
            "p_reason": reason,
            "p_idempotency_key": idempotency_key,
        })

    def withdraw_leave(self, student_id: int, request_id: int, idempotency_key: str) -> dict:
        return self.client.rpc("withdraw_leave", {
            "p_student_id": student_id,
            "p_request_id": request_id,
            "p_idempotency_key": idempotency_key,
        })

    def notify_hod(self, roll_no: str, message: str, idempotency_key: str) -> dict:
        return self.client.rpc("notify_hod", {
            "p_roll_no": roll_no,
            "p_message": message,
            "p_idempotency_key": idempotency_key,
        })

    # --------------------------------------------------------------- counting

    def count(self, table: str) -> int:
        """Row count, via an RPC.

        Counting by fetching `id` breaks on `leave_policy` (keyed by name) and
        `leave_idempotency` (keyed by key), because neither has an `id` column.
        The RPC counts server-side and only accepts known table names.
        """
        return int(self.client.rpc("table_count", {"p_table": table}))

    def counts(self) -> dict[str, int]:
        """Same three numbers, same labels as the SQLite backend."""
        return {
            "leave requests": self.count("leave_request"),
            "notifications": self.count("leave_notification"),
            "idempotency keys": self.count("leave_idempotency"),
        }
