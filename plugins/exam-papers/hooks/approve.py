#!/usr/bin/env python3
"""The plugin's hooks for the teacher's typed commands (D6, D20). Reads the hook's JSON on stdin.

UserPromptExpansion: only a command the user types expands, so Claude and its subagents cannot get
here.
- /exam-papers:approve GATE [TASK] records the approval in that task's approvals.json.
- /exam-papers:decide accept R2 R4 reject R5 [TASK] records the teacher's decision on the open review
  findings in that task's review/decisions.json (review_status.py checks it: every finding listed to
  decide is accepted or rejected; an open error may also be rejected, and so may a fix the writer
  made, which undoes it).
TASK is a folder under papers/ (its name or its path); without it, the command goes to the one task
that is waiting for it. If it cannot be recorded, the command is blocked and the reason shown.

PreToolUse: deny any Write or Edit of a file named approvals.json or decisions.json, and any Bash
command that mentions one, whoever asks (Claude or a subagent). A Bash command that builds the name
some other way is not caught: this guards against mistakes, not a determined adversary.
"""
import glob
import json
import os
import re
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN, "skills", "make-paper", "scripts"))
from approvals import APPROVALS, GATES, record_approval  # noqa: E402
from next_step import WORKFLOW, next_step, read_workflow  # noqa: E402
from review_status import record_decision, status  # noqa: E402

COMMAND = "exam-papers:approve"
DECIDE = "exam-papers:decide"
USAGE = f"Type /{COMMAND} followed by one of: {', '.join(GATES)}, and optionally the paper's folder."
DECIDE_USAGE = (f"Type /{DECIDE} accept R2 R4 reject R5 (each finding listed to decide, accepted or "
                "rejected), and optionally the paper's folder at the end.")
PROTECTED = (APPROVALS, "decisions.json")
FINDING = re.compile(r"R[1-9][0-9]*")


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
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


def pick_task(root, folder, waiting, what, retype):
    """(the task, None) or (None, the reason to block)."""
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
        return None, f"No paper under {os.path.join(root, 'papers')} is waiting for {what}."
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
    task, reason = pick_task(root, words[1] if len(words) == 2 else None,
                             waiting_tasks(root, {f"approve_{gate}"}, steps), f"a {gate} approval",
                             f"/{COMMAND} {gate}")
    if reason:
        return block(reason)
    rec = record_approval(task, gate, text)
    print(f"Approval recorded by the exam-papers hook: {gate} ({rec['file']}, sha256 {rec['sha256'][:12]}) "
          f"for {task}. Run next_step.py on that folder and continue.")
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
    task, reason = pick_task(root, folder, waiting,
                             "a decision on review findings", f"/{DECIDE} ...")
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


def on_tool(event):
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    if tool == "Bash":
        named = [f for f in PROTECTED if f in (args.get("command") or "")]
        if named:
            return deny(f"{named[0]} is written only by the plugin's hook, and Bash may not touch it. "
                        f"Read it with the Read tool; the teacher types /{COMMAND} or /{DECIDE}.")
        return 0
    name = os.path.basename(args.get("file_path") or args.get("notebook_path") or "")
    if name in PROTECTED:
        return deny(f"{name} is written only by the plugin's hook. The teacher types /{COMMAND} or "
                    f"/{DECIDE}; never write it yourself.")
    return 0


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    name = event.get("hook_event_name")
    if name == "UserPromptExpansion":
        return on_expansion(event)
    if name == "PreToolUse":
        return on_tool(event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
