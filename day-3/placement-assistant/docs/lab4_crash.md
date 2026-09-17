# Lab 4 — crash drill

## Before idempotency
If you ran the drill before finishing Part 2 (or with `call_tool` reverted to call tools directly), paste the last lines here.

```
1. queued run 8f12a3b0
2. worker-A started
3. killed worker-A after it sent the notification but before it recorded doing so: run is 'running', leased to worker-A, 6 steps recorded
4. waiting 4 s for worker-A's lease to expire...
5. worker-B finished the run: 'succeeded' after 2 attempts

applications 1   booked slots 1   notifications 2
FAIL: expected exactly one of each and a succeeded run
```

## After
Paste the output of three runs of `python -m scripts.crash_drill`.

```
Run 1:
1. queued run ea5783d6
2. worker-A started
3. killed worker-A after it sent the notification but before it recorded doing so: run is 'running', leased to worker-A, 6 steps recorded
4. waiting 4 s for worker-A's lease to expire...
5. worker-B finished the run: 'succeeded' after 2 attempts

applications 1   booked slots 1   notifications 1
PASS: exactly one of each

Run 2:
1. queued run 92b0c11f
2. worker-A started
3. killed worker-A after it sent the notification but before it recorded doing so: run is 'running', leased to worker-A, 6 steps recorded
4. waiting 4 s for worker-A's lease to expire...
5. worker-B finished the run: 'succeeded' after 2 attempts

applications 1   booked slots 1   notifications 1
PASS: exactly one of each

Run 3:
1. queued run c48d71e2
2. worker-A started
3. killed worker-A after it sent the notification but before it recorded doing so: run is 'running', leased to worker-A, 6 steps recorded
4. waiting 4 s for worker-A's lease to expire...
5. worker-B finished the run: 'succeeded' after 2 attempts

applications 1   booked slots 1   notifications 1
PASS: exactly one of each
```

## Explain
1. **At which moment was worker-A killed, and what had and hadn't been written?**
   Worker-A was killed immediately after executing `notify_student` (and committing the notification record and its idempotency key into `placement.db`), but right before `store.record_tool_call` could log the completion into `agent.db`. Therefore, the notification and its key had been written to `placement.db`, but the tool step record had not been written to `agent.db`.

2. **How did worker-B know where to resume?**
   Worker-B claimed the run after worker-A's lease expired and called `rebuild()`, which replayed the recorded history from `agent.db`. `rebuild()` saw the model step requesting `notify_student` without a matching recorded tool result step. It populated `pending` with this missing tool call at the exact step sequence number (`step_seq`), allowing Worker-B to re-issue the call with the identical idempotency key.

3. **Which line of code stopped the second notification?**
   In `app/placement_db.py`, inside `PlacementDb.once()`:
   `row = conn.execute("SELECT result FROM idempotency WHERE key = ?", (key,)).fetchone()`
   `if row is not None: return json.loads(row["result"]), False`
   When Worker-B attempted the side-effect tool call with the deterministic key, `once()` found the existing key in `placement.db` and immediately returned the stored result without executing `notify_student` again.

