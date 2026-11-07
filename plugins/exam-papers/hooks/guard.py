#!/usr/bin/env python3
"""PreToolUse hook: refuse tool calls that break the plugin's rules. Reads the hook's JSON
input on stdin; inside a subagent it carries "agent_type" (e.g. "exam-papers:blind-solver").

- Nobody (Claude or a subagent) writes approvals.json or decisions.json: only the approval hook
  (approve.py) does, when the teacher types a command. Any Write or Edit of a file with either name
  is denied, and so is any Bash command that mentions one (reading uses the Read tool).
- The blind solver sees only the blind paper: it may read solver-input.json and its own
  solver-answers.json, write only solver-answers.json, and run no Bash command that names a file
  holding the key or the review.
- The writer never sees the solver's answers or the comparison (it learns of mismatches only through
  the reviewer's findings), and never changes the blueprint.
- Main Claude and the reviewer are limited only by the first rule.

Bash commands can only be matched by the file names they contain, so a command that reaches a file
another way is not caught: this guards against mistakes, not a determined adversary.
"""
import json
import os
import sys

SOLVER = "exam-papers:blind-solver"
WRITER = "exam-papers:writer"

PROTECTED = ("approvals.json", "decisions.json")
SOLVER_READS = {"solver-input.json", "solver-answers.json"}
SOLVER_WRITES = {"solver-answers.json"}
# Files that hold the key, the plan or the review, which the solver must not reach through Bash.
SOLVER_BASH_BLOCKED = ("questions.json", "blueprint.json", "reviewer-report", "compare-output",
                       "writer-response", "decisions.json", "rounds", "make_diagrams", "state.json",
                       "run.jsonl")
WRITER_HIDDEN = ("solver-answers.json", "compare-output.txt")
WRITER_FIXED = {"blueprint.json"}

READ_TOOLS = {"Read", "Grep", "Glob"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def target(args):
    return args.get("file_path") or args.get("notebook_path") or args.get("path") or ""


def protected_rule(tool, args):
    if tool == "Bash":
        named = [f for f in PROTECTED if f in (args.get("command") or "")]
        if named:
            return (f"{named[0]} is written only by the plugin's hook, and Bash may not touch it. "
                    "Read it with the Read tool; the teacher types /exam-papers:approve or "
                    "/exam-papers:decide.")
    elif tool in WRITE_TOOLS and os.path.basename(target(args)) in PROTECTED:
        return (f"{os.path.basename(target(args))} is written only by the plugin's hook. The teacher "
                "types /exam-papers:approve or /exam-papers:decide; never write it yourself.")
    return None


def solver_rule(tool, args):
    name = os.path.basename(target(args))
    if tool in READ_TOOLS and name not in SOLVER_READS:
        return "The blind solver reads only the blind paper (solver-input.json)."
    if tool in WRITE_TOOLS and name not in SOLVER_WRITES:
        return "The blind solver writes only its answers (solver-answers.json)."
    if tool == "Bash" and any(f in (args.get("command") or "") for f in SOLVER_BASH_BLOCKED):
        return "The blind solver may not reach the key or the review; use Bash only for arithmetic."
    return None


def writer_rule(tool, args):
    text = target(args) + " " + (args.get("pattern") or "") + " " + (args.get("command") or "")
    if any(f in text for f in WRITER_HIDDEN):
        return ("The writer never sees the blind solver's answers or the comparison; work from the "
                "reviewer's findings.")
    if tool in WRITE_TOOLS and os.path.basename(target(args)) in WRITER_FIXED:
        return "The blueprint is approved and fixed; the writer never changes it."
    return None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if event.get("hook_event_name") != "PreToolUse":
        return 0
    tool, args = event.get("tool_name"), event.get("tool_input") or {}
    reason = protected_rule(tool, args)
    agent_rule = {SOLVER: solver_rule, WRITER: writer_rule}.get(event.get("agent_type"))
    if reason is None and agent_rule is not None:
        reason = agent_rule(tool, args)
    return deny(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
