"""Reading and writing the scripts' files: JSON, content hashes and the run log of a paper's task
folder.

TASK/run.jsonl is append-only: one JSON object per line, never rewritten. Every line has "time" and
"event" ("done" from next_step.py, "approved" from the approval hook, "decided" and "round_closed"
from review_status.py).
"""
import hashlib
import json
import os
from datetime import datetime, timezone

RUN_LOG = "run.jsonl"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, doc):
    """Write doc as indented JSON with a final newline. It goes to a temporary file first and then
    replaces path, so a reader never sees a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


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
