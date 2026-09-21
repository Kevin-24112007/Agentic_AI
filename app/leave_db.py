"""leave.db: students, holidays, leave policy and leave requests."""
import json
import time
from collections.abc import Callable
from pathlib import Path

from app.db import connect, transaction

SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "leave.sql"


class LeaveDb:
    def __init__(self, path: str = ":memory:", clock: Callable[[], float] = time.time):
        self.conn = connect(path)
        self.clock = clock

    def transaction(self):
        return transaction(self.conn)

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA.read_text())
        if self.conn.execute("SELECT count(*) FROM student").fetchone()[0]:
            return
        with self.transaction() as c:
            c.executemany("INSERT INTO student VALUES (?, ?, ?, ?, ?)", [
                (1, "22CS045", "Priya Raman", "CSE", 8),
                (2, "22IT017", "Arjun Kumar", "IT", 1),
                (3, "22EC031", "Divya Sekar", "ECE", 0),
            ])
            c.executemany("INSERT INTO holiday VALUES (?, ?, ?)", [
                (1, "2026-09-25", "Founders Day"),
                (2, "2026-10-02", "Gandhi Jayanti"),
                (3, "2026-10-20", "Campus Festival"),
            ])
            c.executemany("INSERT INTO policy VALUES (?, ?)", [
                ("max_days_per_application", 5),
            ])
            c.execute(
                "INSERT INTO leave_request(student_id,start_date,end_date,days,reason,status,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (3, "2026-09-15", "2026-09-15", 1, "Already seeded leave", "approved", self.clock()),
            )

    def get_student(self, roll_no: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM student WHERE roll_no = ?", (roll_no,)).fetchone()
        return dict(r) if r else None

    def policy(self, name: str) -> int:
        row = self.conn.execute("SELECT value FROM policy WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        return row[0]

    def holidays(self, start_date: str | None = None, end_date: str | None = None) -> list[dict]:
        sql = "SELECT holiday_date, name FROM holiday"
        args = []
        clauses = []
        if start_date:
            clauses.append("holiday_date >= ?"); args.append(start_date)
        if end_date:
            clauses.append("holiday_date <= ?"); args.append(end_date)
        if clauses: sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY holiday_date"
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def active_requests(self, student_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,start_date,end_date,days,reason,status FROM leave_request "
            "WHERE student_id = ? AND status = 'approved' ORDER BY start_date, id", (student_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def leave_requests(self, student_id: int) -> list[dict]:
        """Every request, whatever its status. `active_requests` is the approved subset.

        The read-only specialist's `get_leave_requests` tool calls this. It was
        missing here while the Supabase twin had it, so any question about leave
        history raised AttributeError instead of answering.
        """
        rows = self.conn.execute(
            "SELECT id, start_date, end_date, days, reason, status FROM leave_request "
            "WHERE student_id = ? ORDER BY id", (student_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_request(self, request_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM leave_request WHERE id = ?", (request_id,)).fetchone()
        return dict(r) if r else None

    def apply_leave(self, student_id: int, start_date: str, end_date: str, days: int, reason: str, idempotency_key: str | None = None) -> dict:
        """Atomic balance check + deduction + request creation. Safe to repeat for same dates."""
        with self.transaction() as c:
            existing = c.execute(
                "SELECT * FROM leave_request WHERE student_id=? AND start_date=? AND end_date=?",
                (student_id, start_date, end_date)).fetchone()
            if existing:
                return {"request_id": existing["id"], "status": "already_applied", "days": existing["days"]}
            student = c.execute("SELECT leave_balance FROM student WHERE id=?", (student_id,)).fetchone()
            if not student:
                return {"error": "unknown_student"}
            if days > student["leave_balance"]:
                return {"error": "insufficient_balance", "balance": student["leave_balance"], "requested": days}
            c.execute("UPDATE student SET leave_balance = leave_balance - ? WHERE id=? AND leave_balance >= ?",
                      (days, student_id, days))
            if c.execute("SELECT changes()").fetchone()[0] != 1:
                return {"error": "insufficient_balance"}
            cur = c.execute(
                "INSERT INTO leave_request(student_id,start_date,end_date,days,reason,status,created_at) "
                "VALUES (?,?,?,?,?,'approved',?)",
                (student_id,start_date,end_date,days,reason,self.clock()))
            return {"request_id": cur.lastrowid, "status": "approved", "days": days}

    def withdraw_leave(self, student_id: int, request_id: int, idempotency_key: str | None = None) -> dict:
        """Atomic restore + status update. Safe to repeat."""
        with self.transaction() as c:
            row = c.execute("SELECT * FROM leave_request WHERE id=? AND student_id=?", (request_id, student_id)).fetchone()
            if not row:
                return {"error": "unknown_request"}
            if row["status"] == "withdrawn":
                return {"request_id": request_id, "status": "already_withdrawn", "days_restored": 0}
            c.execute("UPDATE student SET leave_balance = leave_balance + ? WHERE id=?", (row["days"], student_id))
            c.execute("UPDATE leave_request SET status='withdrawn' WHERE id=?", (request_id,))
            return {"request_id": request_id, "status": "withdrawn", "days_restored": row["days"]}

    def record_notification(self, roll_no: str, message: str, dedupe_key: str) -> tuple[int, bool]:
        cur = self.conn.execute(
            "INSERT INTO notification(roll_no,message,dedupe_key,created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(dedupe_key) DO NOTHING", (roll_no,message,dedupe_key,self.clock()))
        if cur.rowcount == 1:
            return cur.lastrowid, True
        return self.conn.execute("SELECT id FROM notification WHERE dedupe_key=?", (dedupe_key,)).fetchone()[0], False

    def once(self, key: str, tool_name: str, effect: Callable[[], dict]) -> tuple[dict, bool]:
        with self.transaction() as c:
            row = c.execute("SELECT result FROM idempotency WHERE key=?", (key,)).fetchone()
            if row:
                return json.loads(row["result"]), False
            result = effect()
            c.execute("INSERT INTO idempotency(key,tool_name,result,created_at) VALUES (?,?,?,?)",
                      (key,tool_name,json.dumps(result,default=str),self.clock()))
            return result, True

    def count(self, table: str) -> int:
        assert table.isidentifier()
        return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def counts(self) -> dict[str, int]:
        """The three numbers the demo prints, under names that mean the same
        thing on both backends. The Supabase tables are prefixed (`leave_*`),
        so callers that hardcoded `notification` printed nothing in the cloud."""
        return {
            "leave requests": self.count("leave_request"),
            "notifications": self.count("notification"),
            "idempotency keys": self.count("idempotency"),
        }
