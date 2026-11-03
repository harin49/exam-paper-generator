"""The teacher's approvals, kept in approvals.json: a paper's (TASK/approvals.json, for the blueprint
and the final paper) and a syllabus pack's (syllabi/<pack>/approvals.json, for its concept list).

Only the plugin's approval hook (hooks/approve.py) writes approvals.json, when the teacher types
/exam-papers:approve GATE; another hook stops Claude and its subagents from writing it (D6). Each
record names the gate, the approved file and that file's SHA-256 hash:

    [{"gate": "blueprint", "file": "blueprint.json", "sha256": "...", "time": "...", "command": "..."}]

A gate is approved while its latest record's hash matches the file now, so editing an approved file
voids its approval.
"""
import os

from task_files import file_hash, load_json, log_event, now, write_json

APPROVALS = "approvals.json"
GATES = {"blueprint": "blueprint.json", "paper": "questions.json", "concepts": "concepts.json"}


def read_approvals(folder):
    """Every approval record of TASK, oldest first. Empty if there is no approvals.json."""
    path = os.path.join(folder, APPROVALS)
    if not os.path.isfile(path):
        return []
    doc = load_json(path)
    if not isinstance(doc, list):
        raise ValueError(f"{path} must be a list of approval records")
    return doc


def is_approved(folder, gate, path=None):
    """True while the latest approval of gate matches its file's current content (path, if given,
    is the file to compare instead of the gate's file in folder)."""
    records = [a for a in read_approvals(folder) if isinstance(a, dict) and a.get("gate") == gate]
    if not records:
        return False
    current = file_hash(path or os.path.join(folder, GATES[gate]))
    return current is not None and records[-1].get("sha256") == current


def record_approval(folder, gate, command):
    """Append an approval of gate's file as it is now. Only the approval hook calls this."""
    name = GATES[gate]
    record = {"gate": gate, "file": name, "sha256": file_hash(os.path.join(folder, name)),
              "time": now(), "command": command}
    records = read_approvals(folder) + [record]
    write_json(os.path.join(folder, APPROVALS), records)
    log_event(folder, "approved", gate=gate, file=name, sha256=record["sha256"])
    return record
