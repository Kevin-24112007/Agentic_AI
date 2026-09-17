"""Lab 3 — two runs booking the same slot; one wins cleanly."""
import threading
from app.memory import RunStore
from app.placement_db import PlacementDb
from app.providers import ModelTurn, PositionalMock, ToolCall
from app.worker import Worker


def make_mock(roll_no: str) -> PositionalMock:
    return PositionalMock([
        ModelTurn(text=None, tool_calls=[ToolCall("apply_to_drive", {"student_id": roll_no, "drive_id": 2})],
                  tokens_in=100, tokens_out=10),
        ModelTurn(text=None, tool_calls=[ToolCall("book_interview_slot", {"student_id": roll_no, "slot_id": 3})],
                  tokens_in=150, tokens_out=15),
        ModelTurn(text="Done", tokens_in=200, tokens_out=10),
    ])


def test_two_workers_two_runs_one_slot(db_files):
    agent_path, placement_path = db_files

    store1 = RunStore(agent_path)
    store2 = RunStore(agent_path)
    db1 = PlacementDb(placement_path)
    db2 = PlacementDb(placement_path)

    thread1 = store1.create_thread("22IT017")
    thread2 = store2.create_thread("22CS045")

    run1_id = store1.enqueue(thread1, "Apply to TCS and book slot 3", "mock")
    run2_id = store2.enqueue(thread2, "Apply to TCS and book slot 3", "mock")

    worker1 = Worker(store1, db1, make_mock("22IT017"), worker_id="w1")
    worker2 = Worker(store2, db2, make_mock("22CS045"), worker_id="w2")

    res1 = worker1.run_once()
    res2 = worker2.run_once()

    # Both runs must succeed
    assert res1 == (run1_id, "succeeded")
    assert res2 == (run2_id, "succeeded")

    run1_steps = store1.load_steps(run1_id)
    run2_steps = store2.load_steps(run2_id)

    book_step1 = next(s for s in run1_steps if s["kind"] == "tool" and s["tool_name"] == "book_interview_slot")
    book_step2 = next(s for s in run2_steps if s["kind"] == "tool" and s["tool_name"] == "book_interview_slot")

    res_statuses = sorted([
        book_step1["result"].get("status", book_step1["result"].get("error")),
        book_step2["result"].get("status", book_step2["result"].get("error")),
    ])
    assert res_statuses == ["booked", "slot_taken"]

    slot3 = db1.get_slot(3)
    assert slot3.student_id is not None
    assert slot3.student_id in (1, 2)


def test_truly_concurrent_claims_have_one_winner(tmp_path):
    db_path = str(tmp_path / "placement.db")
    db = PlacementDb(db_path)
    db.migrate()

    # Apply both students to drive 2 first so eligibility/application prerequisites pass if checked
    db.create_application(1, 2)
    db.create_application(2, 2)

    version = db.slot_version(3)
    assert version is not None

    barrier = threading.Barrier(8)
    results = []
    lock = threading.Lock()

    def worker_thread(student_id: int):
        conn = PlacementDb(db_path)
        barrier.wait()
        res = conn.claim_slot(3, student_id, version)
        with lock:
            results.append(res)

    threads = [threading.Thread(target=worker_thread, args=(i % 2 + 1,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == 7
    assert db.slot_version(3) == version + 1

