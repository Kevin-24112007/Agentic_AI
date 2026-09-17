# Placement Assistant: Day 3 programming kit

SoDak EduTech, Agentic AI Track, Day 3: durable execution. Open `HANDOUT.html` for the exercise sheet.

Day 3 starts from where Day 2 ended: the tools, the agent loop and the memory are finished and given.
Still no database server: two SQLite files, `agent.db` (conversations, runs, the job queue) and
`placement.db` (the college's data). Python 3.10+.

## What you build

| Part | You write | Where |
|---|---|---|
| 1 A run is a job | `enqueue`, `claim_next`, `heartbeat`, `reap_expired` | `app/memory.py` |
| 2 Idempotency keys | `canonical_json`, `idempotency_key`, `PlacementDb.once`, `call_tool` | `app/idempotency.py`, `app/placement_db.py`, `app/runner.py` |
| 3 Safe side effects | duplicate application is a success, optimistic slot booking, deduplicated notifications | `app/placement_db.py`, `app/idempotency.py` |
| Lab | cancel, retry and dead-letter, a race test you write, the kill -9 drill | see the handout |

## Start

```bash
python -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

pytest tests/test_day2_tools.py            # Day 2's tools, already green

# after Part 1, in two terminals:
python -m scripts.worker --mock            # terminal 1: a worker
python -m scripts.ask "Apply me to Zoho"   # terminal 2: queue a question and watch it run
python -m scripts.status                   # runs, and counts of every side effect
python -m scripts.crash_drill              # kill -9 a worker mid-run and count
```

Tests and `--mock` never call Gemini. Delete `agent.db` and `placement.db` any time to start fresh.
