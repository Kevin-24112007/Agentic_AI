import json  # noqa: F401
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"


class ConversationStore:
    """The agent's memory in SQLite. All SQL for threads, messages, runs and steps lives here."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, isolation_level=None)   # autocommit; transactions are explicit
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------------------ given

    def migrate(self) -> None:
        for name in ("agent.sql", "append_only.sql"):
            sql = (SCHEMA_DIR / name).read_text()
            if sql.strip():
                self.conn.executescript(sql)

    @contextmanager
    def transaction(self):
        """Everything inside commits together, or nothing does."""
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def create_thread(self, student_id: str) -> str:
        thread_id = str(uuid.uuid4())
        self.conn.execute("INSERT INTO thread (id, student_id) VALUES (?, ?)", (thread_id, student_id))
        return thread_id

    def get_thread(self, thread_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM thread WHERE id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def get_run(self, run_id: str) -> dict | None:
        run = self.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        steps = self.conn.execute(
            """SELECT s.seq, s.kind, s.tokens_in, s.tokens_out,
                      t.tool_name, t.args, t.result, t.ok, t.latency_ms
                 FROM run_step s LEFT JOIN tool_call t ON t.run_step_id = s.id
                WHERE s.run_id = ? ORDER BY s.seq""", (run_id,)).fetchall()
        return {**dict(run), "steps": [dict(s) for s in steps]}

    # ------------------------------------------------------------------ Part 3.2: your SQL

    def append_message(self, thread_id: str, role: str, text: str) -> int:
        """TODO: insert with seq = this thread's highest seq + 1 (computed in the same INSERT). Return the seq."""
        raise NotImplementedError

    def load_history(self, thread_id: str) -> list[dict]:
        """TODO: [{"seq", "role", "text"}, ...] in seq order."""
        raise NotImplementedError

    def start_run(self, thread_id: str, model: str) -> str:
        """TODO: new run with a uuid4 id and status 'running'. Return the id."""
        raise NotImplementedError

    def record_model_step(self, run_id: str, seq: int, tokens_in: int, tokens_out: int) -> int:
        """TODO: insert a 'model' run_step AND add its tokens to the run, in ONE transaction. Return the step id."""
        raise NotImplementedError

    def record_tool_call(self, run_id: str, seq: int, name: str, args: dict, result: dict,
                         ok: bool, latency_ms: int) -> int:
        """TODO: insert a 'tool' run_step and its tool_call (args and result as JSON) in ONE transaction.
        Return the step id. Use `with self.transaction() as conn:`."""
        raise NotImplementedError

    def finish_run(self, run_id: str, status: str, error_code: str | None = None) -> None:
        """TODO: set status, error_code and finished_at."""
        raise NotImplementedError

    # ------------------------------------------------------------------ Lab 3

    def page_messages(self, thread_id: str, after_seq: int = 0, limit: int = 20) -> tuple[list[dict], int | None]:
        """TODO (lab 3): up to `limit` messages with seq > after_seq, as {"seq", "role", "text", "created_at"}.
        Also return the after_seq for the next page, or None if this is the last page.
        No OFFSET. limit below 1 raises ValueError."""
        raise NotImplementedError
