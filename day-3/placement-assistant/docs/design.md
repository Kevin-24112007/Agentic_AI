# Sprint — design notes

Answer each in a short paragraph. Point to the code.

1. **Why is the unit of retry the tool call, and not the whole request?**
   Retrying at the tool call level allows the agent to resume execution from the exact point of failure without re-executing prior side effects or wasting LLM token budgets. If we retried the entire request from step 1, every preceding tool call would have to be re-evaluated. By storing intermediate steps in `agent.db` and rebuilding state (`app/runner.py:rebuild`), the runner reconstructs history up to step $N$ and executes only the unrecorded or pending tool call at step $N+1$.

2. **The idempotency key is stored in placement.db, not agent.db. Why there, and why in the same transaction as the side effect?**
   The idempotency key protects business side effects in `placement.db`. Storing the key in `placement.db` within the exact same database transaction as the side effect (`app/placement_db.py:once`) guarantees atomicity: either both the side effect and its key commit together, or both roll back. If the key were stored in `agent.db` (or committed in a separate transaction), a crash between committing the side effect and writing the key would leave the side effect committed without an idempotency record. On recovery, a second worker would find no key and execute the side effect twice.

3. **What happens if the lease is shorter than one model call? What would you change?**
   If the lease expires while a worker is waiting for an LLM provider response, `reap_expired()` (`app/memory.py:reap_expired`) re-queues the run for another worker. When the original worker eventually receives the response and checks `heartbeat()` or attempts `complete()`, it detects that its lease was lost and raises `LeaseLost` (`app/runner.py:between_steps`), discarding its progress. To resolve this, long-running model calls should send periodic heartbeats from a background thread or extend the lease before invoking the provider.

4. **Why do both databases open transactions with BEGIN IMMEDIATE instead of plain BEGIN?**
   Standard `BEGIN` in SQLite starts with a read lock and defers taking a write lock until the first write query. If two concurrent workers execute `BEGIN`, read the database, and then both attempt to write, a lock upgrade deadlock occurs and SQLite aborts one transaction with `database is locked`. `BEGIN IMMEDIATE` (`app/memory.py:transaction` & `app/placement_db.py:transaction`) acquires the write lock at the start of the transaction, ensuring concurrent workers queue sequentially instead of failing with deadlocks.

5. **Name one thing in this system that is still not exactly-once, and what it would take to fix it.**
   External side effects such as real SMS/email notifications sent over network APIs are not strictly exactly-once. If a worker sends an HTTP request to an external SMS service and the SMS is delivered, but the worker crashes before committing `once()` to `placement.db`, a second worker will re-send the SMS. To fix this, external service APIs must support native idempotency keys (e.g. passing `Idempotency-Key` headers) so the external gateway deduplicates network requests, or an outbox pattern with two-phase commit must be implemented.

