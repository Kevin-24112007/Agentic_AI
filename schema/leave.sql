-- leave.db: domain data for the Leave Request Assistant.

CREATE TABLE IF NOT EXISTS student (
    id INTEGER PRIMARY KEY,
    roll_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    dept TEXT NOT NULL,
    leave_balance INTEGER NOT NULL CHECK (leave_balance >= 0)
);

CREATE TABLE IF NOT EXISTS holiday (
    id INTEGER PRIMARY KEY,
    holiday_date TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

-- Business rules live in data, not in prompts.
CREATE TABLE IF NOT EXISTS policy (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL CHECK (value >= 0)
);

CREATE TABLE IF NOT EXISTS leave_request (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES student(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    days INTEGER NOT NULL CHECK (days > 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'withdrawn')),
    created_at REAL NOT NULL,
    UNIQUE(student_id, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS notification (
    id INTEGER PRIMARY KEY,
    roll_no TEXT NOT NULL,
    message TEXT NOT NULL,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);

-- Side-effect idempotency records live next to domain effects.
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at REAL NOT NULL
);
