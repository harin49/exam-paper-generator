#!/usr/bin/env python3
"""Print the one workflow step that may run next for a paper's task folder.

Usage:
    python3 next_step.py TASK [--json] [--workflow FILE]

TASK is the paper's task folder (papers/<board>-<class>-<subject>-<date>/ in the teacher's workspace).
The steps and their order come from workflow.json in this skill's folder (or FILE). Each step has a "done" condition that is checked
against TASK; the next step is the first one that is not done. Steps are never run side by side:
do the step this prints, wait for it to finish, then run this script again.

A step that was done can become not done when an earlier file changes: for example, editing
questions.json after the blind solver ran makes the blind paper out of date, so extract_paper.py
is next again.

"done" conditions (paths are relative to TASK; {paper_pdf} and {key_pdf} are the PDF names
render.py uses for the spec):
    {"exists": PATH}                              the file exists
    {"newer": PATH, "than": [PATH, ...]}          PATH exists and was written after every file in
                                                  "than" (missing "than" files are ignored)
    {"passes": SCRIPT, "args": [PATH, ...]}       the script (relative to this skill's folder) exits 0
    {"equals": PATH, "field": F, "value": V}      JSON file PATH has field F equal to V
    {"empty": PATH, "field": F}                   JSON file PATH has field F as an empty list
    {"contains": PATH, "text": T}                 the file contains the text T
    {"all": [...]} / {"any": [...]}               every / at least one condition holds
    {"never": true}                               never done (the last step)

Exit codes:
    0  the next step was printed
    2  the workflow file or the task folder's spec could not be read, or the workflow is malformed
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import output_names  # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(SKILL_DIR, "workflow.json")
STEP_KEYS = {"id", "skillStep", "title", "by", "waitsForUser", "run", "done"}
BY = {"script", "subagent", "claude", "user"}


class WorkflowError(ValueError):
    pass


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_workflow(path):
    doc = load(path)
    steps = doc.get("steps") if isinstance(doc, dict) else None
    if not isinstance(steps, list) or not steps:
        raise WorkflowError("the workflow has no 'steps' list")
    ids = set()
    for s in steps:
        if not isinstance(s, dict) or not STEP_KEYS <= set(s):
            raise WorkflowError(f"every step needs {', '.join(sorted(STEP_KEYS))}: {s!r}")
        if s["id"] in ids:
            raise WorkflowError(f"step id '{s['id']}' is used twice")
        if s["by"] not in BY:
            raise WorkflowError(f"step '{s['id']}': 'by' must be one of {', '.join(sorted(BY))}")
        ids.add(s["id"])
    return steps


class Task:
    """The task folder, and the condition checks run against it."""

    def __init__(self, folder):
        self.folder = folder
        self.names = {}
        spath = os.path.join(folder, "spec.json")
        if os.path.isfile(spath):
            paper, key = output_names(load(spath))
            self.names = {"{paper_pdf}": paper, "{key_pdf}": key}

    def path(self, p):
        return os.path.join(self.folder, self.names.get(p, p))

    def mtime(self, p):
        return os.stat(self.path(p)).st_mtime_ns

    def read_json(self, p):
        try:
            return load(self.path(p))
        except (OSError, ValueError):
            return None

    def holds(self, cond):
        if not isinstance(cond, dict) or len(cond) == 0:
            raise WorkflowError(f"a condition must be a non-empty object: {cond!r}")
        if "all" in cond:
            return all(self.holds(c) for c in cond["all"])
        if "any" in cond:
            return any(self.holds(c) for c in cond["any"])
        if "never" in cond:
            return False
        if "exists" in cond:
            return os.path.isfile(self.path(cond["exists"]))
        if "newer" in cond:
            if not os.path.isfile(self.path(cond["newer"])):
                return False
            t = self.mtime(cond["newer"])
            return all(t > self.mtime(o) for o in cond.get("than", []) if os.path.isfile(self.path(o)))
        if "passes" in cond:
            args = [os.path.abspath(self.path(a)) for a in cond.get("args", [])]
            if not all(os.path.isfile(a) for a in args):
                return False
            run = subprocess.run([sys.executable, os.path.join(SKILL_DIR, cond["passes"]), *args],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return run.returncode == 0
        if "equals" in cond:
            doc = self.read_json(cond["equals"])
            return isinstance(doc, dict) and doc.get(cond["field"]) == cond["value"]
        if "empty" in cond:
            doc = self.read_json(cond["empty"])
            return isinstance(doc, dict) and doc.get(cond["field"]) == []
        if "contains" in cond:
            try:
                with open(self.path(cond["contains"]), encoding="utf-8") as f:
                    return cond["text"] in f.read()
            except OSError:
                return False
        raise WorkflowError(f"unknown condition: {cond!r}")


def next_step(folder, steps):
    """(the steps already done, the next step). The first step is next if TASK does not exist."""
    task = Task(folder) if os.path.isdir(folder) else None
    done = []
    for s in steps:
        if task is None or not task.holds(s["done"]):
            return done, s
        done.append(s)
    return done, None


def main(argv):
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    wpath = WORKFLOW
    if "--workflow" in args:
        i = args.index("--workflow")
        if i + 1 >= len(args):
            print("--workflow needs a file path")
            return 2
        wpath = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    folder = args[0]
    try:
        steps = read_workflow(wpath)
        done, step = next_step(folder, steps)
    except (OSError, ValueError, KeyError, TypeError) as e:   # WorkflowError is a ValueError
        print(f"Cannot work out the next step: {e}")
        return 2

    if as_json:
        print(json.dumps({"task": folder, "done": [s["id"] for s in done],
                          "next": step and {k: step[k] for k in step if k != "done"}},
                         indent=2, ensure_ascii=False))
        return 0
    print(f"Task: {folder}")
    print("Done: " + (", ".join(f"{s['skillStep']} {s['id']}" for s in done) or "nothing yet"))
    if step is None:
        print("\nEvery step is done.")
        return 0
    run = step["run"].replace("${CLAUDE_SKILL_DIR}", SKILL_DIR).replace("TASK", folder.rstrip("/"))
    print(f"\nNEXT: step {step['skillStep']}, {step['id']}: {step['title']}")
    print(f"  By:   {step['by']}")
    print(f"  Run:  {run}")
    if step.get("note"):
        print(f"  Note: {step['note']}")
    if step["waitsForUser"]:
        print("\nSTOP after this step: wait for the user's answer before anything else.")
    print("\nDo this step only. When it has finished, run next_step.py again.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
