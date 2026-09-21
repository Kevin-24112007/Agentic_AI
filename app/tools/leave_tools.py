"""The tools the specialists can call.

Two toolsets, deliberately unequal:

  BalanceTools     three read-only tools and nothing else. No write tool is
                   reachable from this class, so the read-only specialist
                   cannot change leave data even if the model asks it to.

  LeaveDeskTools   one read tool plus three writes.

Both are constructed with a single roll number and neither takes a roll number
as a tool argument, so a specialist physically cannot act for another student.

Every docstring says when to use the tool, when not to, and what it changes;
that text is what the model sees as the tool description.
"""
from datetime import date

from app.idempotency import notification_dedupe_key
from app.tools.dispatch import dispatch


class Toolset:
    """Names a set of callables and hands model tool calls to them."""

    SIDE_EFFECTS: tuple[str, ...] = ()      # tools that change data
    DELEGATES: tuple[str, ...] = ()         # tools that run another agent
    TOOL_NAMES: tuple[str, ...] = ()

    def functions(self) -> dict:
        return {name: getattr(self, name) for name in self.TOOL_NAMES}

    def call(self, name: str, args: dict) -> dict:
        return dispatch(self.functions(), name, args)


class _StudentScoped(Toolset):
    """Bound to one student for its whole life."""

    def __init__(self, db, roll_no: str):
        self.db, self.roll_no = db, roll_no

    def _student(self) -> dict:
        student = self.db.get_student(self.roll_no)
        if not student:
            raise LookupError(f"no student with roll number {self.roll_no}")
        return student


class BalanceTools(_StudentScoped):
    """The read-only specialist's tools. There is no write tool here at all."""

    TOOL_NAMES = ("get_leave_balance", "holiday_calendar", "get_leave_requests")

    def get_leave_balance(self) -> dict:
        """Read the current student's remaining leave balance and their approved leave.

        Use this for any question about how many days are left, and before
        explaining whether a leave request is likely to fit. Do not use it to
        apply for or withdraw leave; it has no way to do either. Changes nothing.
        Returns the balance and the list of currently approved requests.
        """
        student = self._student()
        return {
            "roll_no": student["roll_no"],
            "name": student["name"],
            "leave_balance": student["leave_balance"],
            "active_requests": self.db.active_requests(student["id"]),
        }

    def holiday_calendar(self, start_date: str = "", end_date: str = "") -> dict:
        """List campus holidays, optionally inside a date range.

        Use this when the student asks about holidays, or when planning leave
        around them. Do not use it to check leave balance. Changes nothing.
        Args: start_date and end_date are YYYY-MM-DD, or empty strings for no bound.
        Returns the matching holidays in date order.
        """
        return {"holidays": self.db.holidays(start_date or None, end_date or None)}

    def get_leave_requests(self) -> dict:
        """List all of the current student's leave requests and their statuses.

        Use this for leave history, and to find the request id that a
        withdrawal will need. Do not use it to perform the withdrawal itself.
        Changes nothing. Returns request ids, dates, days, reasons and status.
        """
        return {"requests": self.db.leave_requests(self._student()["id"])}


class LeaveDeskTools(_StudentScoped):
    """The write-capable specialist's tools, bound to one student."""

    TOOL_NAMES = ("get_leave_balance", "apply_leave", "withdraw_leave", "notify_hod")
    SIDE_EFFECTS = ("apply_leave", "withdraw_leave", "notify_hod")

    def __init__(self, db, roll_no: str):
        super().__init__(db, roll_no)
        # Set for the duration of one side-effect call by call_side_effect().
        self._current_key: str | None = None

    def call_side_effect(self, name: str, args: dict, key: str) -> dict:
        """Run a write tool with the caller's idempotency key attached."""
        self._current_key = key
        try:
            return self.call(name, args)
        finally:
            self._current_key = None

    def _key(self) -> str:
        # A direct call (a test, or a human poking at the class) has no run
        # behind it, so it gets a stable local label instead of a run key.
        return self._current_key or "direct-call"

    def get_leave_balance(self) -> dict:
        """Read the current student's remaining leave balance.

        Use this before applying for leave, or when the student asks how many
        days they have. Do not use it to apply or withdraw. Changes nothing.
        Returns the roll number and the balance.
        """
        student = self._student()
        return {"roll_no": student["roll_no"], "leave_balance": student["leave_balance"]}

    def apply_leave(self, start_date: str, end_date: str, days: int, reason: str) -> dict:
        """Apply for leave for the current student.

        Use this only when the student has explicitly asked to apply. Do not use
        it to check a balance or to withdraw. It changes data: it deducts days
        from the balance and creates an approved leave request.

        The database enforces the day limit and refuses to let the balance go
        negative inside the same transaction as the write, so a model that skips
        the checks still cannot break either rule. Applying the same dates twice
        returns the first request instead of creating a second.
        """
        if days <= 0:
            return {"error": "invalid_days"}
        if not start_date or not end_date or start_date > end_date:
            return {"error": "invalid_date_range"}
        if not reason.strip():
            return {"error": "invalid_reason"}

        # Checked here for a clear message, and again inside the database, which
        # is the check that actually counts.
        max_days = self.db.policy("max_days_per_application")
        if days > max_days:
            return {"error": "policy_limit", "max_days": max_days}

        return self.db.apply_leave(
            self._student()["id"], start_date, end_date, days, reason.strip(), self._key())

    def withdraw_leave(self, request_id: int) -> dict:
        """Withdraw one existing leave request belonging to the current student.

        Use this only when the student has explicitly asked to withdraw a
        specific request; get the id from the leave history first. Do not use it
        to apply for leave. It changes data: it marks the request withdrawn and
        restores its days. Withdrawing an already-withdrawn request restores
        nothing, so repeating it is safe.
        """
        return self.db.withdraw_leave(self._student()["id"], request_id, self._key())

    def notify_hod(self, message: str) -> dict:
        """Record a short notification to the HOD for the current student.

        Use this after a leave application or withdrawal has actually succeeded,
        or when the request explicitly asks for the HOD to be told. Do not use it
        to tell the student something. It changes data by storing the outgoing
        message. The same message to the same HOD about the same student on the
        same day is stored once, so repeating it is safe.
        Args: message is at most 160 characters.
        """
        message = message.strip()
        if not message or len(message) > 160:
            return {"error": "invalid_message"}

        if hasattr(self.db, "notify_hod"):
            # Supabase: the RPC stores the run key in its ledger AND computes
            # the same-day dedupe key internally, in one transaction.
            return self.db.notify_hod(self.roll_no, message, self._key())

        # SQLite: the run key is handled a layer up by LeaveDb.once(). The row
        # itself is keyed by student + message + day, which is what makes this
        # effect safe to repeat on its own, with no run key in sight.
        dedupe = notification_dedupe_key(self.roll_no, message, date.today())
        notification_id, created = self.db.record_notification(self.roll_no, message, dedupe)
        return {"notification_id": notification_id, "status": "queued", "duplicate": not created}
