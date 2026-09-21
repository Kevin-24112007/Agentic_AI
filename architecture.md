# System architecture

Same design locally and in the cloud: two logical stores (leave domain, agent
runtime), a durable queue between the student and the model, and two
specialists with different privileges behind one supervisor. Only the
implementation of the two stores changes — SQLite files locally, PostgreSQL
tables + RPC functions in one Supabase project.

```mermaid
flowchart TD
    U[Student] -->|scripts.ask / scripts.cancel| Q[(Job queue\nagent_run)]
    Q -->|claim_next: BEGIN IMMEDIATE\nor FOR UPDATE SKIP LOCKED| W[Worker\nlease + heartbeat]
    W --> S[Supervisor Agent\nno domain tools]
    S -->|ask_balance| B[Balance Specialist\nREAD ONLY - no write tool exists]
    S -->|ask_desk| D[Leave Desk Specialist\nbound to one student]

    B --> RT[get_leave_balance\nholiday_calendar\nget_leave_requests]
    D --> WT[get_leave_balance\napply_leave\nwithdraw_leave\nnotify_hod]

    RT --> LEAVE[(Leave domain\nleave.db / leave_*)]
    WT --> LEAVE
    LEAVE --> POLICY[policy / leave_policy\nmax_days_per_application]
    LEAVE --> IDEM[idempotency / leave_idempotency\nkey -> result, same transaction as effect]
    WT --> NOTIFY[notification / leave_notification\nsame-day dedupe]

    W --> RUNTIME[(Agent runtime\nagent.db / agent_*)]
    RUNTIME --> THREADS[thread + message\nconversation history]
    RUNTIME --> RUNS[run + run_step + tool_call\nstatus, lease, attempts]
    RUNS --> REPLAY[Crash replay\nrebuild from recorded steps]
    RUNS --> REAP[reap_expired\ndead worker's lease -> requeue or dead-letter]
    RUNS --> CANCEL[cancel_requested\nchecked between steps only]
```

Source: [`architecture.mmd`](architecture.mmd) (Mermaid) and
[`architecture.dot`](architecture.dot) (Graphviz, rendered to
[`architecture.png`](architecture.png) with `dot -Tpng architecture.dot -o
architecture.png`).

## Reading the diagram

**Request path.** A student's message becomes a row in the queue
(`scripts.ask`), not a direct function call. A worker claims it — atomically,
so two workers can never claim the same run — leases it, and only then hands it
to the supervisor. The supervisor has exactly two tools, `ask_balance` and
`ask_desk`; it cannot touch leave data itself even if a model tried to invent a
shortcut.

**Least privilege.** The balance specialist's toolset contains no write tool at
all — not "a write tool that refuses," an *absent* one. The desk specialist is
constructed with one student's roll number baked in and no tool that accepts a
different one, so it structurally cannot act for anyone else.

**The rule that can't be skipped.** `max_days_per_application` is a row, and
`apply_leave` checks it inside the same transaction as the write. Change the
number in the table and the very next call respects it — nothing in a prompt
has to change.

**Durability.** Every model step and tool call is recorded before the next one
starts. If a worker dies, `reap_expired` notices the stale lease and requeues
the run (or dead-letters it, past `max_attempts`); whichever worker picks it up
next rebuilds exactly where the model left off from those recorded steps
(`app/runner.py:rebuild`), and every write it's about to repeat is guarded by
an idempotency key stored next to that write's result.

**Cancellation.** A cancel request only sets a flag. The worker checks that
flag *between* steps — never inside a tool call — so a leave application is
never left half-applied because a student changed their mind mid-run.
