#!/usr/bin/env python3
"""The plugin's approval hooks (D6). Reads the hook's JSON input on stdin.

UserPromptExpansion: when the teacher types /exam-papers:approve GATE [TASK], record the approval in
that task's approvals.json. Only a command the user types expands, so Claude and its subagents cannot
get here. TASK is a folder under papers/ (its name or its path); without it, the approval goes to the
one task that is waiting at that gate. If the approval cannot be recorded, the command is blocked and
the reason shown.

PreToolUse: deny any Write or Edit of a file named approvals.json, and any Bash command that mentions
it, whoever asks (Claude or a subagent). A Bash command that builds the name some other way is not
caught: this guards against mistakes, not a determined adversary.
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

COMMAND = "exam-papers:approve"
USAGE = f"Type /{COMMAND} followed by one of: {', '.join(GATES)}, and optionally the paper's folder."


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def waiting_tasks(root, gate, steps):
    """The task folders under root/papers/ whose next step is this gate's approval."""
    found = []
    for folder in sorted(glob.glob(os.path.join(root, "papers", "*", ""))):
        try:
            step = next_step(folder, steps)[1]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if step is not None and step["id"] == f"approve_{gate}":
            found.append(folder.rstrip(os.sep))
    return found


def on_expansion(event):
    if event.get("command_name") != COMMAND:
        return 0
    if event.get("command_source") != "plugin" or event.get("agent_id"):
        return block("Approvals are taken only from a command the teacher types.")
    prompt = event.get("prompt") or ""
    m = re.search(r"/" + re.escape(COMMAND) + r"\b([^\n]*)", prompt)
    words = m.group(1).split() if m else []
    if not words or words[0] not in GATES or len(words) > 2:
        return block(USAGE)
    gate = words[0]
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    steps = read_workflow(WORKFLOW)
    waiting = waiting_tasks(root, gate, steps)
    if len(words) == 2:
        named = os.path.realpath(os.path.join(root, "papers", words[1]) if os.sep not in words[1]
                                 else os.path.join(root, words[1]))
        tasks = [t for t in waiting if os.path.realpath(t) == named]
        if not tasks:
            return block(f"{words[1]} is not waiting for a {gate} approval. Ask Claude to run "
                         "next_step.py on it to see its next step.")
    elif len(waiting) == 1:
        tasks = waiting
    elif not waiting:
        return block(f"No paper under {os.path.join(root, 'papers')} is waiting for a {gate} approval.")
    else:
        names = ", ".join(os.path.basename(t) for t in waiting)
        return block(f"Several papers are waiting for a {gate} approval ({names}). "
                     f"Type /{COMMAND} {gate} FOLDER with one of them.")
    task = tasks[0]
    rec = record_approval(task, gate, prompt[m.start():m.end()].strip())
    print(f"Approval recorded by the exam-papers hook: {gate} ({rec['file']}, sha256 {rec['sha256'][:12]}) "
          f"for {task}. Run next_step.py on that folder and continue.")
    return 0


def on_tool(event):
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    if tool == "Bash":
        if APPROVALS in (args.get("command") or ""):
            return deny(f"{APPROVALS} is written only by the approval hook, and Bash may not touch it. "
                        "Read it with the Read tool; the teacher approves by typing "
                        f"/{COMMAND}.")
        return 0
    path = args.get("file_path") or args.get("notebook_path") or ""
    if os.path.basename(path) == APPROVALS:
        return deny(f"{APPROVALS} is written only by the approval hook. The teacher approves by "
                    f"typing /{COMMAND}; never write it yourself.")
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
