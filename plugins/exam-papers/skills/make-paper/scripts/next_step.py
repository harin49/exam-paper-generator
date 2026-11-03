#!/usr/bin/env python3
"""Print the one workflow step that may run next for a paper's task folder.

Usage:
    python3 next_step.py TASK [--json] [--workflow FILE]
    python3 next_step.py TASK --done STEP_ID [--workflow FILE]

TASK is the paper's task folder (papers/<board>-<class>-<subject>-<date>/ in the teacher's workspace).
The steps and their order come from workflow.json in this skill's folder (or FILE). Each step has a "done" condition that is checked
against TASK; the next step is the first one that is not done. Steps are never run side by side:
do the step this prints, wait for it to finish, then run this script again.

When a step has finished, record it with --done STEP_ID. A step marked "recordsItself" in the workflow
(the four script steps: make_blueprint, extract_paper, compare_solutions, render) is recorded by its
script when it succeeds (record_own_step), so nobody has to remember it. That saves the SHA-256 hashes of the step's
"inputs" and "outputs" in TASK/state.json (the latest record of each step) and appends the record to
TASK/run.jsonl (one JSON object per line, never rewritten). --done refuses a step while an earlier
step is not done, while one of the step's outputs is missing, or while the step's own "done"
condition would still not hold (an approval that has not been given, a check that fails).

A step that was done can become not done when an earlier file changes: for example, editing
questions.json after the blind solver ran makes the blind paper out of date, so extract_paper.py
is next again. Contents decide this, never file times, so copying the folder changes nothing.

"done" conditions (paths are relative to TASK; {paper_pdf} and {key_pdf} are the PDF names
render.py uses for the spec):
    {"exists": PATH}                              the file exists
    {"recorded": [PATH, ...]}                     the step was recorded with --done, each PATH (one of
                                                  the step's "inputs") still has the hash it had then
                                                  (or is still missing, if it was missing then), and
                                                  every one of the step's "outputs" exists
    {"passes": SCRIPT, "args": [PATH, ...],       the script (relative to this skill's folder) exits 0;
     "flags": [TEXT, ...], "reads": [PATH, ...]}  flags (optional) go after the paths ("." is TASK);
                                                  reads (optional) names the files the script reads
                                                  beyond its args (used by --done, see record_done)
    {"approved": GATE}                            the teacher approved GATE's file (approvals.py) and
                                                  the file has not changed since
    {"all": [...]} / {"any": [...]}               every / at least one condition holds
    {"never": true}                               never done (the last step)

Exit codes:
    0  the next step was printed (or, with --done, the step was recorded)
    1  --done: the step was not recorded (the message says why)
    2  the workflow file or the task folder's spec could not be read, or the workflow is malformed
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from approvals import GATES, is_approved  # noqa: E402
from render import output_names  # noqa: E402
from task_files import file_hash, log_event, now  # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(SKILL_DIR, "workflow.json")
STEP_KEYS = {"id", "skillStep", "title", "by", "waitsForUser", "run", "done"}
STATE = "state.json"
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
        for key in ("inputs", "outputs"):
            if not isinstance(s.get(key, []), list):
                raise WorkflowError(f"step '{s['id']}': '{key}' must be a list of paths")
        if not isinstance(s.get("recordsItself", False), bool):
            raise WorkflowError(f"step '{s['id']}': 'recordsItself' must be true or false")
        for paths in recorded_paths(s["done"]):
            if not s.get("outputs"):
                raise WorkflowError(f"step '{s['id']}': a 'recorded' condition needs the step's 'outputs'")
            if not set(paths) <= set(s.get("inputs", [])):
                raise WorkflowError(f"step '{s['id']}': 'recorded' paths must be among the step's 'inputs'")
        ids.add(s["id"])
    return steps


def recorded_paths(cond):
    """Every path list of the "recorded" conditions inside cond."""
    if isinstance(cond, dict):
        if "recorded" in cond:
            yield cond["recorded"]
        for c in cond.get("all", []) + cond.get("any", []):
            yield from recorded_paths(c)


class Task:
    """The task folder, and the condition checks run against it."""

    def __init__(self, folder, ignore=()):
        self.folder = folder
        self.names = {}
        self.records = read_state(folder)
        self.ignore = set(ignore)       # paths whose conditions count as holding (see record_done)
        spath = os.path.join(folder, "spec.json")
        if os.path.isfile(spath):
            paper, key = output_names(load(spath))
            self.names = {"{paper_pdf}": paper, "{key_pdf}": key}

    def path(self, p):
        return os.path.join(self.folder, self.names.get(p, p))

    def hashes(self, paths):
        return {p: file_hash(self.path(p)) for p in paths}

    def holds(self, cond, step):
        if not isinstance(cond, dict) or len(cond) == 0:
            raise WorkflowError(f"a condition must be a non-empty object: {cond!r}")
        if "all" in cond:
            return all(self.holds(c, step) for c in cond["all"])
        if "any" in cond:
            return any(self.holds(c, step) for c in cond["any"])
        if "never" in cond:
            return False
        read = ([cond["exists"]] if "exists" in cond else []) + cond.get("args", []) + cond.get("reads", [])
        if "approved" in cond:
            if cond["approved"] not in GATES:
                raise WorkflowError(f"unknown gate in {cond!r}: one of {', '.join(GATES)}")
            read.append(GATES[cond["approved"]])
        if self.ignore & set(read):
            return True
        if "exists" in cond:
            return os.path.isfile(self.path(cond["exists"]))
        if "recorded" in cond:
            record = self.records.get(step["id"])
            if record is None or not all(os.path.isfile(self.path(o)) for o in step["outputs"]):
                return False
            current = self.hashes([p for p in cond["recorded"] if p not in self.ignore])
            return all(p in record["inputs"] and record["inputs"][p] == h for p, h in current.items())
        if "passes" in cond:
            args = [os.path.abspath(self.path(a)) for a in cond.get("args", [])]
            if not all(os.path.exists(a) for a in args):
                return False
            run = subprocess.run([sys.executable, os.path.join(SKILL_DIR, cond["passes"]), *args,
                                  *cond.get("flags", [])],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return run.returncode == 0
        if "approved" in cond:
            return is_approved(self.folder, cond["approved"])
        raise WorkflowError(f"unknown condition: {cond!r}")


def read_state(folder):
    """The latest record of each step: {step id: record}. Empty if TASK has no state.json yet."""
    path = os.path.join(folder, STATE)
    if not os.path.isfile(path):
        return {}
    doc = load(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("steps"), dict):
        raise WorkflowError(f"{path} has no 'steps' object")
    return doc["steps"]


def next_step(folder, steps, ignore=()):
    """(the steps already done, the next step). The first step is next if TASK does not exist."""
    task = Task(folder, ignore) if os.path.isdir(folder) else None
    done = []
    for s in steps:
        if task is None or not task.holds(s["done"], s):
            return done, s
        done.append(s)
    return done, None


def record_done(folder, steps, step_id):
    """Record that step_id has finished. Returns an error message, or None when it was recorded."""
    by_id = {s["id"]: s for s in steps}
    if step_id not in by_id:
        return f"there is no step '{step_id}' in the workflow"
    if not os.path.isdir(folder):
        return f"there is no task folder {folder}"
    step = by_id[step_id]
    # A step can change files that earlier steps read (apply_fixes edits questions.json, so the
    # check and the blind solver are due again). Those earlier steps were done before it ran.
    done, _ = next_step(folder, steps, ignore=step.get("outputs", []))
    index = [s["id"] for s in steps].index(step_id)
    if len(done) < index:
        return (f"step '{step_id}' cannot be recorded yet: step '{steps[len(done)]['id']}' "
                "before it is not done")
    task = Task(folder)
    missing = [o for o in step.get("outputs", []) if not os.path.isfile(task.path(o))]
    if missing:
        return f"step '{step_id}' is not finished: {', '.join(task.names.get(o, o) for o in missing)} missing"
    record = {"time": now(),
              "inputs": task.hashes(step.get("inputs", [])),
              "outputs": task.hashes(step.get("outputs", []))}
    records = dict(task.records, **{step_id: record})
    task.records = records
    if step["done"] != {"never": True} and not task.holds(step["done"], step):
        return f"step '{step_id}' is not finished: its done condition in workflow.json does not hold"
    tmp = os.path.join(folder, STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"steps": records}, f, indent=2)
        f.write("\n")
    os.replace(tmp, os.path.join(folder, STATE))
    log_event(folder, "done", step=step_id, inputs=record["inputs"], outputs=record["outputs"])
    return None


def record_own_step(folder, step_id):
    """For a step's script, once it has succeeded: record the step as --done would. Returns the line
    to print, or None when folder is not a paper's task folder (no spec.json), e.g. in a test."""
    if not os.path.isfile(os.path.join(folder, "spec.json")):
        return None
    try:
        error = record_done(folder, read_workflow(WORKFLOW), step_id)
    except (OSError, ValueError, KeyError, TypeError) as e:
        error = str(e)
    if error:
        return f"Step not recorded: {error}"
    return f"Recorded: {step_id} (this script records its own step; no --done needed)."


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
    done_id = None
    if "--done" in args:
        i = args.index("--done")
        if i + 1 >= len(args):
            print("--done needs a step id")
            return 2
        done_id = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    folder = args[0]
    if done_id is not None:
        try:
            error = record_done(folder, read_workflow(wpath), done_id)
        except (OSError, ValueError, KeyError, TypeError) as e:
            error = str(e)
        if error:
            print(f"Not recorded: {error}")
            return 1
        print(f"Recorded: {done_id}. Run next_step.py again for the next step.")
        return 0
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
    if step.get("recordsItself"):
        print("\nDo this step only. The script records the step itself when it succeeds (it prints")
        print("\"Recorded: ...\"); then run next_step.py again.")
        return 0
    script = os.path.join(SKILL_DIR, "scripts", "next_step.py")
    print("\nDo this step only. When it has finished, record it:")
    print(f'  python3 "{script}" {folder.rstrip("/")} --done {step["id"]}')
    print("then run next_step.py again.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
