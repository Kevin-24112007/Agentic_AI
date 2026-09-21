"""Tests for the supervisor/specialist split, using the scripted providers."""
from app.agents import SupervisorTools, run_tool
from app.providers import demo_providers


def test_supervisor_can_only_delegate(db):
    tools = SupervisorTools(db, demo_providers(), "22CS045")
    assert set(tools.functions()) == {"ask_balance", "ask_desk"}


def test_balance_delegation_never_touches_a_write_tool(db):
    providers = demo_providers()
    tools = SupervisorTools(db, providers, "22CS045")
    result, _replayed = run_tool(tools, db, "k1", "ask_balance", {"question": "Check my leave balance"})
    assert result["agent"] == "balance"
    assert result["tools_used"] == ["get_leave_balance"]


def test_desk_delegation_applies_and_notifies(db):
    providers = demo_providers()
    tools = SupervisorTools(db, providers, "22CS045")
    request = "Apply leave from 2026-09-21 to 2026-09-23 for a family function and notify the HOD."
    result, _replayed = run_tool(tools, db, "k2", "ask_desk", {"request": request})
    assert "apply_leave" in result["tools_used"]
    assert "notify_hod" in result["tools_used"]
    assert db.count("notification") == 1


def test_history_delegation_is_read_only(db):
    providers = demo_providers()
    tools = SupervisorTools(db, providers, "22CS045")
    result, _replayed = run_tool(tools, db, "k-hist", "ask_balance", {"question": "Show my leave requests"})
    assert result["agent"] == "balance"
    assert result["tools_used"] == ["get_leave_requests"]


def test_repeated_delegation_with_the_same_key_is_idempotent(db):
    providers = demo_providers()
    tools = SupervisorTools(db, providers, "22CS045")
    request = "Apply leave from 2026-09-21 to 2026-09-23 for a family function and notify the HOD."
    run_tool(tools, db, "same-key", "ask_desk", {"request": request})
    run_tool(tools, db, "same-key", "ask_desk", {"request": request})
    assert db.count("notification") == 1
    # Two child tool calls (apply_leave, notify_hod) recorded once each.
    assert db.count("idempotency") == 2


def test_malformed_delegation_arguments_are_rejected(db):
    tools = SupervisorTools(db, demo_providers(), "22CS045")
    result, _replayed = run_tool(tools, db, "k", "ask_desk", {"request": ""})
    assert result["error"] == "invalid_arguments"


def test_extra_delegation_arguments_are_rejected(db):
    tools = SupervisorTools(db, demo_providers(), "22CS045")
    result, _replayed = run_tool(tools, db, "k", "ask_desk", {"request": "hi", "extra": 1})
    assert result["error"] == "invalid_arguments"
