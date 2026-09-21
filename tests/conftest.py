"""Shared fixtures. Every test gets an in-memory SQLite pair and a fake clock
that only moves when a test tells it to, so lease and backoff timing is
deterministic instead of racing the wall clock.
"""
import pytest

from app.leave_db import LeaveDb
from app.memory import RunStore


class FakeClock:
    def __init__(self, start: float = 1_790_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SimulatedCrash(BaseException):
    """Raised mid-effect to simulate a worker process dying."""


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def db(clock) -> LeaveDb:
    database = LeaveDb(":memory:", clock)
    database.migrate()
    return database


@pytest.fixture
def store(clock) -> RunStore:
    run_store = RunStore(":memory:", clock)
    run_store.migrate()
    return run_store
