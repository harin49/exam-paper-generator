"""Content hashes and the run log of a paper's task folder, shared by next_step.py and approvals.py.

TASK/run.jsonl is append-only: one JSON object per line, never rewritten. Every line has "time" and
"event" ("done" from next_step.py --done, "approved" from the approval hook).
"""
import hashlib
import json
import os
from datetime import datetime, timezone

RUN_LOG = "run.jsonl"


def file_hash(path):
    """The SHA-256 of the file, or None if there is no such file."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(folder, event, **fields):
    """Append one line to TASK/run.jsonl."""
    with open(os.path.join(folder, RUN_LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(dict({"time": now(), "event": event}, **fields), ensure_ascii=False) + "\n")
