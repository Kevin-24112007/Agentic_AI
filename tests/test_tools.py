"""Tests for the tools themselves, with no agent or queue involved."""
import inspect

from app.tools.leave_tools import BalanceTools, LeaveDeskTools


def test_every_tool_has_a_real_description():
    """A short docstring is a sign the model won't know when to use the tool."""
    for cls in (BalanceTools, LeaveDeskTools):
        for name in cls.TOOL_NAMES:
            doc = inspect.getdoc(getattr(cls, name)) or ""
            assert len(doc) >= 120, f"{cls.__name__}.{name} needs a fuller description"


def test_desk_tools_take_no_roll_number_argument():
    """The desk specialist is bound to one student at construction time; none
    of its tools accept a roll number, so it has no way to act for anyone else."""
    for name in LeaveDeskTools.TOOL_NAMES:
        assert "roll_no" not in inspect.signature(getattr(LeaveDeskTools, name)).parameters


def test_balance_tools_change_nothing(db):
    before = db.get_student("22CS045")["leave_balance"]
    result = BalanceTools(db, "22CS045").get_leave_balance()
    assert result["leave_balance"] == 8
    assert db.get_student("22CS045")["leave_balance"] == before


def test_holiday_calendar_range(db):
    result = BalanceTools(db, "22CS045").holiday_calendar("2026-09-20", "2026-09-30")
    assert [h["name"] for h in result["holidays"]] == ["Founders Day"]


def test_holiday_calendar_with_no_bounds_returns_everything(db):
    result = BalanceTools(db, "22CS045").holiday_calendar()
    assert len(result["holidays"]) == 3


def test_leave_history_lists_every_status(db):
    tools = LeaveDeskTools(db, "22CS045")
    applied = tools.apply_leave("2026-09-21", "2026-09-23", 3, "family")
    tools.withdraw_leave(applied["request_id"])
    history = {r["id"]: r["status"] for r in BalanceTools(db, "22CS045").get_leave_requests()["requests"]}
    assert history[applied["request_id"]] == "withdrawn"


def test_policy_limit_comes_from_the_database_not_the_prompt(db):
    db.conn.execute("UPDATE policy SET value = 2 WHERE name = 'max_days_per_application'")
    result = LeaveDeskTools(db, "22CS045").apply_leave("2026-09-21", "2026-09-23", 3, "x")
    assert result["error"] == "policy_limit"
    assert result["max_days"] == 2


def test_balance_is_enforced_even_if_the_model_never_checks_it(db):
    """22EC031 starts with balance 0; the tool must refuse on its own."""
    result = LeaveDeskTools(db, "22EC031").apply_leave("2026-09-21", "2026-09-25", 5, "exam")
    assert result["error"] == "insufficient_balance"
    assert db.get_student("22EC031")["leave_balance"] == 0


def test_apply_leave_deducts_the_balance(db):
    result = LeaveDeskTools(db, "22CS045").apply_leave("2026-09-21", "2026-09-23", 3, "family")
    assert result["status"] == "approved"
    assert db.get_student("22CS045")["leave_balance"] == 5


def test_applying_the_same_dates_twice_is_a_safe_no_op(db):
    tools = LeaveDeskTools(db, "22CS045")
    first = tools.apply_leave("2026-09-21", "2026-09-23", 3, "family")
    second = tools.apply_leave("2026-09-21", "2026-09-23", 3, "family")
    assert first["request_id"] == second["request_id"]
    assert second["status"] == "already_applied"
    assert db.count("leave_request") == 2          # the seeded row plus this one


def test_withdraw_restores_balance_then_is_a_safe_no_op(db):
    tools = LeaveDeskTools(db, "22CS045")
    applied = tools.apply_leave("2026-09-21", "2026-09-23", 3, "family")
    first = tools.withdraw_leave(applied["request_id"])
    second = tools.withdraw_leave(applied["request_id"])
    assert first["status"] == "withdrawn"
    assert second["status"] == "already_withdrawn"
    assert db.get_student("22CS045")["leave_balance"] == 8


def test_notification_is_deduplicated_by_student_message_and_day(db):
    tools = LeaveDeskTools(db, "22CS045")
    first = tools.notify_hod("Leave request received.")
    second = tools.notify_hod("Leave  request   received.")     # extra whitespace
    assert first["notification_id"] == second["notification_id"]
    assert second["duplicate"] is True


def test_invalid_message_is_rejected(db):
    assert LeaveDeskTools(db, "22CS045").notify_hod("")["error"] == "invalid_message"
    assert LeaveDeskTools(db, "22CS045").notify_hod("x" * 200)["error"] == "invalid_message"


def test_invalid_date_range_is_rejected(db):
    result = LeaveDeskTools(db, "22CS045").apply_leave("2026-09-25", "2026-09-20", 2, "typo dates")
    assert result["error"] == "invalid_date_range"


def test_zero_days_is_rejected(db):
    result = LeaveDeskTools(db, "22CS045").apply_leave("2026-09-21", "2026-09-23", 0, "family")
    assert result["error"] == "invalid_days"
