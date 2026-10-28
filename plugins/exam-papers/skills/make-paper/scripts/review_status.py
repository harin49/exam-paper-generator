#!/usr/bin/env python3
"""Work out where a paper's review loop stands, and close each review round.

Usage:
    python3 review_status.py TASK [--json]
    python3 review_status.py TASK --not STATE
    python3 review_status.py TASK --close-round
    python3 review_status.py TASK --changes

TASK is the paper's task folder. The files it reads, all in TASK/review/:
    reviewer-report.json   the reviewer's findings, every one so far with its status (review-format.md)
    rounds.json            the closed rounds: {"rounds": [{"round", "key", "report", "questions", "time"}]}
    rounds/N/              round N's questions.json and reviewer-report.json, as they were reviewed
    decisions.json         the teacher's decisions: {"decisions": [{"round", "report", "accepted",
                           "rejected", ...}]}; "round" is the closed round decided on (it settles
                           that round's disputes), "report" the SHA-256 of its report (for the record)

With no option it prints the status: the round, the open findings, what the teacher has to decide,
what the writer has to address, and the next state:
    close    the round under review is not closed yet: the report, questions.json or the writer's
             responses differ from the last closed round (a report can repeat word for word)
    decide   the teacher decides (gate 3): an open warning or suggestion nobody has decided, or, from
             round 3 on, anything still open that the teacher has not settled for this round
    revise   the writer revises: open errors and open accepted findings (before round 3), or the
             findings the teacher accepted for one more round (from round 3 on)
    done     nothing is open (rejected findings stay closed)

--not STATE exits 0 when the next state is not STATE and 1 when it is (next_step.py uses it).
--close-round checks the report against the previous round (every earlier ID still there, a note
wherever the severity changed), then copies questions.json and the report into rounds/N/ and appends
round N to rounds.json. Closing the same round twice does nothing.
--changes prints what changed in questions.json since the last closed round, part by part.

Exit codes:
    0  printed (or --not: the next state is not STATE; or the round was closed)
    1  --not: the next state is STATE; --close-round: the report breaks a rule (nothing closed)
    2  a file could not be read, or a report or decision is malformed
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_review import check as check_report  # noqa: E402
from task_files import file_hash, log_event, now  # noqa: E402

MAX_ROUNDS = 3
STATES = ("close", "decide", "revise", "done")
REPORT = os.path.join("review", "reviewer-report.json")
ROUNDS = os.path.join("review", "rounds.json")
ROUNDS_DIR = os.path.join("review", "rounds")
DECISIONS = os.path.join("review", "decisions.json")
WRITER_RESPONSE = os.path.join("review", "writer-response.json")


def round_key(task):
    """What identifies a round: the report, the questions it reviewed and the writer's last responses."""
    parts = [file_hash(os.path.join(task, p)) or "-" for p in (REPORT, "questions.json", WRITER_RESPONSE)]
    return ":".join(parts)


class StatusError(ValueError):
    pass


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_report(task):
    path = os.path.join(task, REPORT)
    try:
        doc = load(path)
    except (OSError, ValueError) as e:
        raise StatusError(f"cannot read {path}: {e}")
    problems = check_report(doc)
    if problems:
        raise StatusError(f"{path} breaks the findings format: " + "; ".join(problems))
    return doc


def read_rounds(task):
    path = os.path.join(task, ROUNDS)
    if not os.path.isfile(path):
        return []
    doc = load(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("rounds"), list):
        raise StatusError(f"{path} has no 'rounds' list")
    return doc["rounds"]


def read_decisions(task, ids):
    path = os.path.join(task, DECISIONS)
    if not os.path.isfile(path):
        return []
    doc = load(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("decisions"), list):
        raise StatusError(f"{path} has no 'decisions' list")
    for i, d in enumerate(doc["decisions"], 1):
        if not isinstance(d, dict) or not all(isinstance(d.get(k), list) for k in ("accepted", "rejected")):
            raise StatusError(f"{path}: decision {i} needs 'accepted' and 'rejected' lists")
        if not isinstance(d.get("round"), int) or isinstance(d.get("round"), bool):
            raise StatusError(f"{path}: decision {i} needs the 'round' it was made in")
        unknown = sorted(set(d["accepted"] + d["rejected"]) - ids)
        if unknown:
            raise StatusError(f"{path}: decision {i} names unknown findings: {', '.join(unknown)}")
        both = sorted(set(d["accepted"]) & set(d["rejected"]))
        if both:
            raise StatusError(f"{path}: decision {i} both accepts and rejects {', '.join(both)}")
    return doc["decisions"]


def cross_round_problems(report, previous):
    """Rules between a report and the previous round's: earlier IDs kept, severity changes noted."""
    problems = []
    now_by_id = {f["id"]: f for f in report["findings"]}
    for f in previous["findings"]:
        g = now_by_id.get(f["id"])
        if g is None:
            problems.append(f"{f['id']} from the previous round is missing (findings are never dropped; "
                            "mark them resolved)")
        elif g["severity"] != f["severity"] and not (g.get("note") or "").strip():
            problems.append(f"{f['id']} changed from {f['severity']} to {g['severity']} without a note")
    return problems


def status(task):
    """The loop's state as a dict (see the docstring)."""
    report = read_report(task)
    findings = report["findings"]
    ids = {f["id"] for f in findings}
    rounds = read_rounds(task)
    decisions = read_decisions(task, ids)
    n = len(rounds)
    verdict = {}                               # the latest decision on each finding
    for d in decisions:
        verdict.update({i: "accepted" for i in d["accepted"]})
        verdict.update({i: "rejected" for i in d["rejected"]})
    for_this_round = {i for d in decisions if d["round"] == n for i in d["accepted"]}
    open_ = [f for f in findings if f["status"] == "open" and verdict.get(f["id"]) != "rejected"]

    to_decide, to_address, disputes = [], [], []
    if n < MAX_ROUNDS:
        for f in open_:
            if f["severity"] == "error" or verdict.get(f["id"]) == "accepted":
                to_address.append(f["id"])
            elif f["id"] not in verdict:
                to_decide.append(f["id"])
    else:
        for f in open_:
            if f["id"] in for_this_round:
                to_address.append(f["id"])
            elif f["severity"] == "error" or verdict.get(f["id"]) == "accepted":
                disputes.append(f["id"])
            else:
                to_decide.append(f["id"])

    if not rounds or rounds[-1].get("key") != round_key(task):
        state = "close"
    elif to_decide or disputes:
        state = "decide"
    elif to_address:
        state = "revise"
    else:
        state = "done"
    return {"round": n, "maxRounds": MAX_ROUNDS, "next": state,
            "open": {s: [f["id"] for f in open_ if f["severity"] == s]
                     for s in ("error", "warning", "suggestion")},
            "resolved": [f["id"] for f in findings if f["status"] == "resolved"],
            "rejected": sorted((i for i, v in verdict.items() if v == "rejected"), key=lambda i: int(i[1:])),
            "toDecide": to_decide, "disputes": disputes, "toAddress": to_address}


def close_round(task):
    report = read_report(task)
    sha = file_hash(os.path.join(task, REPORT))
    rounds = read_rounds(task)
    key = round_key(task)
    if rounds and rounds[-1].get("key") == key:
        print(f"Round {len(rounds)} is already closed.")
        return 0
    if rounds:
        previous = load(os.path.join(task, ROUNDS_DIR, str(len(rounds)), "reviewer-report.json"))
        problems = cross_round_problems(report, previous)
        if problems:
            print("The report cannot close the round; the reviewer must fix:")
            for p in problems:
                print(f"  - {p}")
            return 1
    n = len(rounds) + 1
    folder = os.path.join(task, ROUNDS_DIR, str(n))
    os.makedirs(folder, exist_ok=True)
    shutil.copyfile(os.path.join(task, REPORT), os.path.join(folder, "reviewer-report.json"))
    shutil.copyfile(os.path.join(task, "questions.json"), os.path.join(folder, "questions.json"))
    rounds.append({"round": n, "key": key, "report": sha,
                   "questions": file_hash(os.path.join(task, "questions.json")), "time": now()})
    with open(os.path.join(task, ROUNDS), "w", encoding="utf-8") as f:
        json.dump({"rounds": rounds}, f, indent=2)
        f.write("\n")
    log_event(task, "round_closed", round=n, report=sha)
    print(f"Closed round {n}.")
    return 0


def leaves(questions):
    """(location, fields without nested parts) for every question and part, in order."""
    def walk(node, loc):
        yield loc, {k: v for k, v in node.items() if k != "parts"}
        for p in node.get("parts", []) or []:
            if isinstance(p, dict):
                label = p.get("label") or ""
                yield from walk(p, f"{loc}({label})" if label else loc + " ")
    for q in questions:
        if isinstance(q, dict):
            yield from walk(q, f"Q{q.get('number')}")


def show(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def changes(task):
    rounds = read_rounds(task)
    if not rounds:
        return "No round has been closed yet: nothing to compare with."
    n = len(rounds)
    old = load(os.path.join(task, ROUNDS_DIR, str(n), "questions.json")).get("questions", [])
    new = load(os.path.join(task, "questions.json")).get("questions", [])
    before, after = dict(leaves(old)), dict(leaves(new))
    lines = []
    for loc in list(after) + [x for x in before if x not in after]:
        a, b = before.get(loc, {}), after.get(loc, {})
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                lines += [f"{loc.strip()} {key}:", f"  before: {show(a.get(key, '(none)'))}",
                          f"  after:  {show(b.get(key, '(none)'))}"]
    head = f"Changes to questions.json since round {n} was reviewed:"
    return head + ("\n" + "\n".join(lines) if lines else " none")


def summary(s):
    def ids(xs):
        return ", ".join(xs) or "none"
    o = s["open"]
    lines = [f"Review round {s['round']} (after round {s['maxRounds']}, open findings go to the teacher)",
             f"Open: errors {ids(o['error'])}; warnings {ids(o['warning'])}; suggestions {ids(o['suggestion'])}",
             f"Resolved: {ids(s['resolved'])}. Rejected by the teacher: {ids(s['rejected'])}.",
             f"Teacher to decide: {ids(s['toDecide'])}",
             f"Disputes (still open after round {s['maxRounds']}): {ids(s['disputes'])}",
             f"Writer to address: {ids(s['toAddress'])}",
             f"NEXT: {s['next']}"]
    return "\n".join(lines)


def main(argv):
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    mode, state = None, None
    for flag in ("--close-round", "--changes"):
        if flag in args:
            mode = flag
            args.remove(flag)
    if "--not" in args:
        i = args.index("--not")
        if i + 1 >= len(args) or args[i + 1] not in STATES:
            print(f"--not needs one of: {', '.join(STATES)}")
            return 2
        mode, state = "--not", args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    task = args[0]
    try:
        if mode == "--close-round":
            return close_round(task)
        if mode == "--changes":
            print(changes(task))
            return 0
        s = status(task)
    except (OSError, ValueError, KeyError, TypeError) as e:   # StatusError is a ValueError
        print(f"Cannot work out the review status: {e}")
        return 2 if mode != "--not" else 1
    if mode == "--not":
        return 0 if s["next"] != state else 1
    print(json.dumps(s, indent=2) if as_json else summary(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
