"""Queue one question for a student and wait for the answer.

    python -m scripts.ask "How many leave days do I have?"
    python -m scripts.ask --student 22IT017 "Apply leave for 2 days, sick"
    python -m scripts.ask --thread <thread-id> "and withdraw that"   # continue a thread

Needs a worker running somewhere to actually pick the run up:
    python -m scripts.worker --mock
"""
import argparse
import time

from app.config import GEMINI_MODEL, open_stores
from scripts._term import CYAN, DIM, GREEN, RED, RESET

DONE_STATUSES = ("succeeded", "failed", "cancelled", "dead")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text")
    parser.add_argument("--student", default="22CS045")
    parser.add_argument("--thread", help="continue an existing thread instead of starting one")
    args = parser.parse_args()

    store, _ = open_stores()
    thread_id = args.thread or store.create_thread(args.student)
    run_id = store.enqueue(thread_id, args.text, GEMINI_MODEL)
    print(f"{DIM}thread {thread_id}{RESET}\n{CYAN}run {run_id}{RESET} queued; waiting for a worker...")

    while (run := store.get_run(run_id))["status"] not in DONE_STATUSES:
        time.sleep(0.5)

    if run["status"] == "succeeded":
        print(f"{GREEN}assistant>{RESET} {store.load_history(thread_id)[-1]['text']}")
    else:
        print(f"{RED}run ended: {run['status']} ({run['error_code']}){RESET}")


if __name__ == "__main__":
    main()
