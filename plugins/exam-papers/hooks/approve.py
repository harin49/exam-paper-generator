#!/usr/bin/env python3
"""The plugin's UserPromptExpansion hook: records the teacher's typed commands. Reads the
hook's JSON on stdin. Only a command the user types expands, so Claude and its subagents cannot get
here. (guard.py stops them from writing the files this hook writes.)
- /exam-papers:approve GATE [TASK] records the approval in that task's approvals.json.
- /exam-papers:approve concepts [PACK] records the approval of a syllabus pack's concept list in
  syllabi/PACK/approvals.json, if the list passes validate_concepts.py. Without PACK it goes to the
  one pack whose concept list is not approved as it is now.
- /exam-papers:decide accept R2 R4 reject R5 [TASK] records the teacher's decision on the open review
  findings in that task's review/decisions.json (review_status.py checks it: every finding listed to
  decide is accepted or rejected; an open error may also be rejected, and so may a fix the writer
  made, which undoes it).
TASK is a folder under papers/ (its name or its path); without it, the command goes to the one task
that is waiting for it. If it cannot be recorded, the command is blocked and the reason shown.
"""
import glob
import json
import os
import re
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN, "skills", "make-paper", "scripts"))
from approvals import GATES, is_approved, record_approval  # noqa: E402
from next_step import WORKFLOW, next_step, read_workflow  # noqa: E402
from review_status import record_decision, status  # noqa: E402
from task_files import load_json  # noqa: E402
import validate_concepts  # noqa: E402

COMMAND = "exam-papers:approve"
DECIDE = "exam-papers:decide"
USAGE = (f"Type /{COMMAND} followed by one of: {', '.join(GATES)}, and optionally the paper's folder "
         "(for concepts: the pack's folder under syllabi/).")
DECIDE_USAGE = (f"Type /{DECIDE} accept R2 R4 reject R5 (each finding listed to decide, accepted or "
                "rejected), and optionally the paper's folder at the end.")
FINDING = re.compile(r"R[1-9][0-9]*")


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def waiting_tasks(root, step_ids, steps):
    """The task folders under root/papers/ whose next step is one of step_ids."""
    found = []
    for folder in sorted(glob.glob(os.path.join(root, "papers", "*", ""))):
        try:
            step = next_step(folder, steps)[1]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if step is not None and step["id"] in step_ids:
            found.append(folder.rstrip(os.sep))
    return found


def where_papers_are(root, steps):
    """One line per paper under root/papers/: its next step, and a hint when that step's output is
    already there but the step was never recorded (Claude forgot next_step.py --done)."""
    lines = []
    for folder in sorted(glob.glob(os.path.join(root, "papers", "*", ""))):
        name = os.path.basename(folder.rstrip(os.sep))
        try:
            step = next_step(folder, steps)[1]
        except (OSError, ValueError, KeyError, TypeError) as e:
            lines.append(f"{name}: cannot work out its next step ({e})")
            continue
        if step is None:
            lines.append(f"{name}: every step is done")
            continue
        line = f"{name}: next step is {step['id']}"
        outputs = step.get("outputs", [])
        if outputs and all(os.path.isfile(os.path.join(folder, o)) for o in outputs):
            line += (f" ({', '.join(outputs)} already there but the step is not recorded: ask Claude to "
                     f"run next_step.py {name} --done {step['id']}, then type the command again)")
        lines.append(line)
    return lines


def pick_task(root, folder, waiting, what, retype, where=None):
    """(the task, None) or (None, the reason to block). where: a function giving where_papers_are()
    lines, called only when no paper is waiting (it works out every paper's next step)."""
    if folder:
        named = os.path.realpath(os.path.join(root, "papers", folder) if os.sep not in folder
                                 else os.path.join(root, folder))
        tasks = [t for t in waiting if os.path.realpath(t) == named]
        if not tasks:
            return None, (f"{folder} is not waiting for {what}. Ask Claude to run next_step.py on it "
                          "to see its next step.")
        return tasks[0], None
    if len(waiting) == 1:
        return waiting[0], None
    if not waiting:
        return None, (f"No paper under {os.path.join(root, 'papers')} is waiting for {what}."
                      + ("".join(f"\n- {w}" for w in where()) if where else ""))
    names = ", ".join(os.path.basename(t) for t in waiting)
    return None, f"Several papers are waiting for {what} ({names}). Type {retype} FOLDER with one of them."


def typed(event, command):
    """The words after the command, and the command as typed; the app may put other text first."""
    m = re.search(r"/" + re.escape(command) + r"\b([^\n]*)", event.get("prompt") or "")
    return (m.group(1).split(), m.group(0).strip()) if m else ([], "/" + command)


def on_expansion(event):
    name = event.get("command_name")
    if name not in (COMMAND, DECIDE):
        return 0
    if event.get("command_source") != "plugin" or event.get("agent_id"):
        return block("Approvals and decisions are taken only from a command the teacher types.")
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    steps = read_workflow(WORKFLOW)
    if name == DECIDE:
        return on_decide(event, root, steps)
    words, text = typed(event, COMMAND)
    if not words or words[0] not in GATES or len(words) > 2:
        return block(USAGE)
    gate = words[0]
    if gate == "concepts":
        return on_approve_concepts(root, words[1] if len(words) == 2 else None, text)
    task, reason = pick_task(root, words[1] if len(words) == 2 else None,
                             waiting_tasks(root, {f"approve_{gate}"}, steps), f"a {gate} approval",
                             f"/{COMMAND} {gate}", lambda: where_papers_are(root, steps))
    if reason:
        return block(reason)
    rec = record_approval(task, gate, text)
    print(f"Approval recorded by the exam-papers hook: {gate} ({rec['file']}, sha256 {rec['sha256'][:12]}) "
          f"for {task}. Run next_step.py on that folder and continue.")
    return 0


def unapproved_packs(root):
    """The pack folders under root/syllabi/ whose concept list is not approved as it is now."""
    found = []
    for folder in sorted(glob.glob(os.path.join(root, "syllabi", "*", ""))):
        folder = folder.rstrip(os.sep)
        if os.path.isfile(os.path.join(folder, "concepts.json")):
            try:
                if not is_approved(folder, "concepts"):
                    found.append(folder)
            except (OSError, ValueError):
                found.append(folder)
    return found


def on_approve_concepts(root, name, text):
    if name:
        pack = os.path.join(root, "syllabi", name) if os.sep not in name else os.path.join(root, name)
        if not os.path.isfile(os.path.join(pack, "concepts.json")):
            return block(f"{name} has no concepts.json under {os.path.join(root, 'syllabi')}.")
    else:
        waiting = unapproved_packs(root)
        if not waiting:
            return block(f"No pack under {os.path.join(root, 'syllabi')} has a concept list waiting for approval.")
        if len(waiting) > 1:
            names = ", ".join(os.path.basename(p) for p in waiting)
            return block(f"Several packs have a concept list waiting for approval ({names}). "
                         f"Type /{COMMAND} concepts PACK with one of them.")
        pack = waiting[0]
    try:
        doc = load_json(os.path.join(pack, "concepts.json"))
        with open(os.path.join(pack, doc.get("syllabus", "syllabus.md")), encoding="utf-8") as f:
            report = validate_concepts.validate(doc, f.read())
    except (OSError, ValueError, AttributeError) as e:
        return block(f"Cannot check the concept list in {pack}: {e}")
    if report.errors:
        shown = "; ".join(report.errors[:5]) + (f"; and {len(report.errors) - 5} more" if len(report.errors) > 5 else "")
        return block(f"The concept list in {pack} fails validate_concepts.py, so it cannot be approved: {shown}")
    rec = record_approval(pack, "concepts", text)
    print(f"Approval recorded by the exam-papers hook: concepts (concepts.json, sha256 {rec['sha256'][:12]}) "
          f"for {pack}. Papers can now be made from this pack.")
    return 0


def on_decide(event, root, steps):
    words, text = typed(event, DECIDE)
    accepted, rejected, folder, mode = [], [], None, None
    for i, w in enumerate(words):
        if w in ("accept", "reject"):
            mode = w
        elif FINDING.fullmatch(w) and mode:
            (accepted if mode == "accept" else rejected).append(w)
        elif i == len(words) - 1 and mode and not FINDING.fullmatch(w):
            folder = w
        else:
            return block(DECIDE_USAGE)
    waiting = waiting_tasks(root, {"decide_fixes", "apply_fixes", "approve_paper"}, steps)
    task, reason = pick_task(root, folder, waiting, "a decision on review findings", f"/{DECIDE} ...",
                             lambda: where_papers_are(root, steps))
    if reason:
        return block(reason)
    try:
        problems = record_decision(task, accepted, rejected, text)
    except (OSError, ValueError, KeyError, TypeError) as e:
        problems = [str(e)]
    if problems:
        return block("Not recorded: " + "; ".join(problems) + ". " + DECIDE_USAGE)
    s = status(task)
    undo = f"; fixes to undo {', '.join(s['toRevert'])}" if s["toRevert"] else ""
    print(f"Decision recorded by the exam-papers hook for {task} (round {s['round']}): "
          f"accepted {', '.join(accepted) or 'none'}; rejected {', '.join(rejected) or 'none'}{undo}. "
          f"Next: {s['next']}. Run next_step.py on that folder and continue.")
    return 0


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if event.get("hook_event_name") == "UserPromptExpansion":
        return on_expansion(event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
