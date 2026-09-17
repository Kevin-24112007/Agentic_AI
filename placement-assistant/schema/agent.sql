-- The agent's memory. Business data (students, drives, applications) is NOT in here.
-- Run by ConversationStore.migrate(). SQLite: foreign keys are switched on per connection.

-- Given, as the pattern to follow.
CREATE TABLE IF NOT EXISTS thread (
    id          TEXT PRIMARY KEY,
    student_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- TODO (Part 3.1): message, run, run_step, tool_call.
-- The handout lists the columns and constraints for each table.
