"""Stable fingerprints for side effects. Hashing, used for exactly-once."""
import hashlib
import json
import re
from datetime import date


def _normalize(val):
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, dict):
        return {k: _normalize(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_normalize(v) for v in val]
    return val


def canonical_json(value) -> str:
    """TODO (Part 2.1): one spelling per meaning.
    Sorted keys, no spaces, and whole floats as integers (12.0 and 12 are the same drive id),
    including inside nested dicts and lists."""
    normalized = _normalize(value)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def idempotency_key(run_id: str, step_seq: int, tool_name: str, args: dict) -> str:
    """TODO (Part 2.1): the same tool call at the same step of the same run must always get the same key.
    SHA-256 hex digest of canonical_json([run_id, step_seq, tool_name, args]).

    Today it returns a random value, so a replayed call looks brand new."""
    payload = canonical_json([run_id, step_seq, tool_name, args])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def notification_dedupe_key(roll_no: str, message: str, day: date) -> str:
    """TODO (Part 3.3): the same message to the same student on the same day is one notification.
    SHA-256 hex of canonical_json([roll_no, message with runs of whitespace collapsed and trimmed, day.isoformat()]).

    Today it returns a random value, so nothing is ever deduplicated."""
    cleaned_msg = re.sub(r"\s+", " ", message).strip()
    payload = canonical_json([roll_no, cleaned_msg, day.isoformat()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

