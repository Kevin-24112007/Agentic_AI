"""Run the leave assistant end to end, with scripted models, no key required.

    python -m scripts.demo             happy path, SQLite
    python -m scripts.demo --crash     kill a worker mid-effect, prove no duplicate
    python -m scripts.demo --cloud     same two, against Supabase
    python -m scripts.demo --real      use actual Gemini instead of the script

Cloud mode needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (see
.env.example and SUPABASE_SETUP.md). --real additionally needs GEMINI_API_KEY.
"""
import argparse
import os
import tempfile
import time

from scripts._term import CYAN, DIM, GREEN, RED, RESET, print_step


class Crash(BaseException):
    """Simulates a worker process dying. Caught by the demo, not the worker."""


def format_counts(db) -> str:
    return "   ".join(f"{label} {n}" for label, n in db.counts().items())


def use_sqlite_scratch_dir() -> None:
    """A fresh temp directory per run, so repeated demo runs never collide."""
    tmp = tempfile.mkdtemp(prefix="leave-demo-")
    os.environ["AGENT_DB"] = os.path.join(tmp, "agent.db")
    os.environ["LEAVE_DB"] = os.path.join(tmp, "leave.db")


def run_happy_path(store, db, providers, roll_no: str, text: str) -> str:
    from app.worker import Worker

    thread = store.create_thread(roll_no)
    run_id = store.enqueue(thread, text, providers["supervisor"].model)
    print(f"{CYAN}{roll_no}>{RESET} {text}")
    Worker(store, db, providers, worker_id="demo-worker", on_step=print_step).run_until_idle()
    return run_id


def run_crash_drill(store, db, providers, roll_no: str, text: str) -> str:
    """Kill worker-A right after apply_leave takes effect but before its
    result is recorded, then let worker-B pick the run back up. If the
    idempotency key did its job, worker-B replays apply_leave instead of
    running it again."""
    from app.worker import Worker

    thread = store.create_thread(roll_no)
    run_id = store.enqueue(thread, text, providers["supervisor"].model)
    print(f"{CYAN}{roll_no}>{RESET} {text}")

    restore = _rig_crash_after_apply(db)
    try:
        Worker(store, db, providers, worker_id="worker-A", lease_seconds=1,
               on_step=print_step).run_once()
    except Crash:
        print(f"\n{RED}worker-A died right after applying leave{RESET}")
        print(f"{DIM}{format_counts(db)}; run status = {store.get_run(run_id)['status']}{RESET}")
        time.sleep(1.2)          # let the lease actually expire before worker-B looks
    finally:
        restore()

    Worker(store, db, providers, worker_id="worker-B", lease_seconds=1,
           on_step=print_step).run_until_idle()
    return run_id


def _rig_crash_after_apply(db):
    """Patch whichever side-effect path this backend uses so it raises Crash
    right after apply_leave's effect lands, and return a function that undoes it."""
    from app.tools.leave_tools import LeaveDeskTools

    if hasattr(db, "once"):
        original = db.once

        def once_then_die(key, tool_name, effect):
            result = original(key, tool_name, effect)
            if tool_name == "apply_leave":
                raise Crash()
            return result

        db.once = once_then_die
        return lambda: setattr(db, "once", original)

    original_call = LeaveDeskTools.call_side_effect

    def call_then_die(self, name, args, key):
        result = original_call(self, name, args, key)
        if name == "apply_leave":
            raise Crash()
        return result

    LeaveDeskTools.call_side_effect = call_then_die
    return lambda: setattr(LeaveDeskTools, "call_side_effect", original_call)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real", action="store_true", help="use real Gemini instead of the script")
    parser.add_argument("--crash", action="store_true", help="run the crash-and-replay drill")
    parser.add_argument("--cloud", action="store_true", help="use Supabase instead of SQLite")
    args = parser.parse_args()

    if args.cloud:
        os.environ["STORAGE_BACKEND"] = "supabase"
    elif not os.environ.get("SUPABASE_URL"):
        os.environ["STORAGE_BACKEND"] = "sqlite"
    if os.environ.get("STORAGE_BACKEND", "").lower() == "sqlite":
        use_sqlite_scratch_dir()

    from app.config import make_providers, open_stores

    store, db = open_stores()
    providers = make_providers(mock=not args.real)

    print(f"{DIM}storage={os.environ.get('STORAGE_BACKEND')} model={providers['supervisor'].model}{RESET}")
    print(f"before: {format_counts(db)}\n")

    roll_no, text = "22CS045", "Apply leave for me"
    run_id = run_crash_drill(store, db, providers, roll_no, text) if args.crash \
        else run_happy_path(store, db, providers, roll_no, text)

    run = store.get_run(run_id)
    reply = store.load_history(run["thread_id"])[-1]["text"] \
        if run["status"] == "succeeded" else run["error_code"]
    print(f"{GREEN}assistant>{RESET} {reply}\n")
    print("after:", format_counts(db))

    if args.crash:
        counts = db.counts()
        ok = counts["leave requests"] == 2 and counts["notifications"] == 1
        print(f"{GREEN}PASS: one leave request, one notification despite the crash{RESET}"
              if ok else f"{RED}FAIL: the crash produced a duplicate side effect{RESET}")


if __name__ == "__main__":
    main()
