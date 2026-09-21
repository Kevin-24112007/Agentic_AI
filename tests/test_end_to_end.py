"""Tests that drive the queue and the worker together, the way a real deployment would."""
import threading

import pytest

from app.memory import RunStore
from app.providers import demo_providers
from app.worker import Worker
from tests.conftest import SimulatedCrash


def ask(store, roll_no, text):
    thread_id = store.create_thread(roll_no)
    return thread_id, store.enqueue(thread_id, text, "mock")


def test_a_question_goes_end_to_end(store, db):
    thread_id, run_id = ask(store, "22CS045", "Apply leave for me")
    outcome = Worker(store, db, demo_providers(), worker_id="w").run_until_idle()
    assert outcome == [(run_id, "succeeded")]
    assert db.count("leave_request") == 2
    assert db.count("notification") == 1
    assert "applied" in store.load_history(thread_id)[-1]["text"]


def test_a_balance_question_changes_nothing(store, db):
    _thread_id, run_id = ask(store, "22CS045", "Check my leave balance")
    Worker(store, db, demo_providers(), worker_id="w").run_until_idle()
    assert store.get_run(run_id)["status"] == "succeeded"
    assert db.get_student("22CS045")["leave_balance"] == 8


def test_crash_after_the_effect_replays_instead_of_repeating(store, db, clock):
    """worker-A applies the leave, then dies before recording that it did.
    worker-B must not apply it a second time when it resumes the run."""
    _thread_id, run_id = ask(store, "22CS045", "Apply leave for me")
    original_once = db.once

    def die_right_after_apply_leave(key, tool_name, effect):
        result = original_once(key, tool_name, effect)
        if tool_name == "apply_leave":
            raise SimulatedCrash()
        return result

    db.once = die_right_after_apply_leave
    with pytest.raises(SimulatedCrash):
        Worker(store, db, demo_providers(), worker_id="worker-A", lease_seconds=30).run_once()
    db.once = original_once

    assert db.count("leave_request") == 2                     # the effect happened once
    assert store.get_run(run_id)["status"] == "running"        # but was never marked done

    clock.advance(31)                                           # worker-A's lease has now expired
    outcome = Worker(store, db, demo_providers(), worker_id="worker-B", lease_seconds=30).run_until_idle()
    assert outcome == [(run_id, "succeeded")]
    assert db.count("leave_request") == 2                       # still one request, not two
    assert db.count("notification") == 1


def test_the_same_question_asked_twice_does_not_double_apply(store, db):
    ask(store, "22CS045", "Apply leave for me")
    ask(store, "22CS045", "Apply leave for me")
    Worker(store, db, demo_providers(), worker_id="w").run_until_idle()
    assert db.count("leave_request") == 2
    assert db.count("notification") == 1


def test_an_expired_lease_is_requeued_and_finished_by_another_worker(store, db, clock):
    """worker-A claims a run and then never comes back (crashes, network
    partition, doesn't matter which). Once its lease has expired, worker-B
    must be able to pick the same run up and finish it."""
    _thread_id, run_id = ask(store, "22CS045", "Check my leave balance")

    claimed = store.claim_next("worker-A", lease_seconds=10)
    assert claimed is not None
    assert store.get_run(run_id)["status"] == "running"

    clock.advance(11)                                           # worker-A's lease is now stale
    assert store.reap_expired() == [run_id]
    assert store.get_run(run_id)["status"] == "queued"

    outcome = Worker(store, db, demo_providers(), worker_id="worker-B").run_until_idle()
    assert outcome == [(run_id, "succeeded")]


def test_cancelling_a_queued_run_stops_it_before_any_work_happens(store, db):
    """A queued run is cancelled the instant the request arrives - it never
    becomes claimable, so no worker ever touches it."""
    _thread_id, run_id = ask(store, "22CS045", "Apply leave for me")
    assert store.request_cancel(run_id) == "cancelled"
    assert store.get_run(run_id)["status"] == "cancelled"

    outcome = Worker(store, db, demo_providers(), worker_id="w").run_until_idle()
    assert outcome == []                                         # nothing left to claim
    assert db.count("leave_request") == 1                        # only the seeded row: nothing ran


def test_cancelling_a_running_run_stops_it_between_steps(store, db):
    """Once a worker has already claimed the run, cancelling only sets a flag.
    The worker notices it before its next model call and stops there, never
    mid tool call, and marks the run cancelled itself."""
    _thread_id, run_id = ask(store, "22CS045", "Apply leave for me")
    worker = Worker(store, db, demo_providers(), worker_id="w")

    claimed = store.claim_next(worker.worker_id, lease_seconds=30)
    assert claimed is not None
    store.request_cancel(run_id)
    assert store.get_run(run_id)["status"] == "running"          # not touched yet
    assert store.cancel_requested(run_id) is True

    from app.runner import execute_run
    outcome = execute_run(claimed, store=store, db=db, providers=demo_providers(),
                          worker_id=worker.worker_id, lease_seconds=30)
    assert outcome == "cancelled"
    assert store.get_run(run_id)["status"] == "cancelled"
    assert db.count("leave_request") == 1                        # cancelled before any tool ran


def test_cancelling_an_unknown_run_reports_none(store):
    assert store.request_cancel("not-a-real-run-id") is None


def test_concurrent_workers_never_claim_the_same_run(tmp_path):
    """Several real worker processes would each open their own connection to
    the same database file; this test does the same, one connection per
    thread. BEGIN IMMEDIATE plus the claimable index must give each run to
    exactly one worker, never zero and never two, under genuine contention.

    (A single sqlite3.Connection shared across threads is a different, and
    unsupported, scenario: it tracks one transaction at a time regardless of
    which thread started it, so two threads racing BEGIN IMMEDIATE on it can
    raise "cannot start a transaction within a transaction" - that failure
    would be about sharing a connection, not about the queue's own locking.)"""
    db_path = str(tmp_path / "agent.db")
    RunStore(db_path).migrate()

    seed = RunStore(db_path)
    thread_id = seed.create_thread("22CS045")
    run_ids = [seed.enqueue(thread_id, f"question {i}", "mock") for i in range(30)]

    claims: list[str] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def drain(name: str):
        try:
            worker_store = RunStore(db_path)          # this worker's own connection
            while True:
                claimed = worker_store.claim_next(name, lease_seconds=30)
                if claimed is None:
                    return
                with lock:
                    claims.append(claimed.run_id)
        except Exception as exc:                        # surfaced below, not swallowed
            with lock:
                errors.append(exc)

    workers = [threading.Thread(target=drain, args=(f"worker-{i}",)) for i in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=10)

    assert not errors, f"worker threads raised: {errors}"
    assert sorted(claims) == sorted(run_ids), "every run must be claimed exactly once"
    assert len(claims) == len(set(claims)), "no run may be claimed twice"
