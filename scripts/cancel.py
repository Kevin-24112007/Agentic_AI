"""Cancel a run from a second terminal while a worker is still working on it.

Terminal 1:
    python -m scripts.worker --mock --slow 2

Terminal 2:
    python -m scripts.ask "Apply leave for me" &
    python -m scripts.cancel <run-id>       # run id printed by scripts.ask

`--slow 2` on the worker gives you a couple of seconds to run the cancel before
the run finishes, so you can see it land while the run is still `running`.

This only sets a flag. The worker in terminal 1 checks that flag *between*
tool calls and stops there - never in the middle of a side effect - which is
why a leave application that has already been applied is never left half-done.
"""
import argparse

from app.config import open_stores
from scripts._term import CYAN, DIM, GREEN, RED, RESET, YELLOW


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="the run id printed by scripts.ask")
    args = parser.parse_args()

    store, _ = open_stores()
    status = store.request_cancel(args.run_id)

    if status is None:
        print(f"{RED}No run with id {args.run_id}.{RESET}")
    elif status == "cancelled":
        print(f"{GREEN}Run {args.run_id[:8]} was still queued: cancelled immediately.{RESET}")
    elif status == "running":
        print(f"{YELLOW}Run {args.run_id[:8]} is running: cancel requested.{RESET}")
        print(f"{DIM}Its worker will stop after the step it is on and mark it cancelled.{RESET}")
    else:
        print(f"{CYAN}Run {args.run_id[:8]} had already finished "
              f"(status: {status}). Nothing to do.{RESET}")


if __name__ == "__main__":
    main()
