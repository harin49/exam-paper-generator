#!/usr/bin/env python3
"""Compare the blind solver's answers with the answer key in questions.json.

Usage:
    python3 compare_solutions.py QUESTIONS.json SOLVER_ANSWERS.json [--json] [--out FILE]

The solver's answers file is described in schemas/review-format.md. The comparison is mechanical:

    V1  an MCQ: the solver chose a different option from the key's correctOption
    V2  a numerical part: a value the solver gave matches no computed value in the key
    V3  the same, but the two differ only by a power of ten (probably a unit difference) or only
        in sign (probably a direction convention)
    V4  a numerical part: the solver gave no values at all, or gave none for a value the question asks
        for (key values marked "working" are steps the marking scheme checks, not asked for, so the
        solver need not give them; if it does, they must still match)
    V5  coverage or format: a question or part is unanswered, an id is unknown or repeated, or the
        answers file is malformed
    V6  (warning) the solver reported a problem with a question: ambiguous, missing data, or no
        single correct answer

Values match when they agree to within 1%. Theory parts cannot be compared by a script: each is
listed under INFO with the key's answer and the solver's answer, for the reviewer to judge.

--out FILE also writes the report to FILE (review/compare-output.txt in the workflow), so the reviewer
and next_step.py can read it.

Exit codes:
    0  no mismatches (V1-V5)
    1  mismatches found: show them to the user; do not change anything until they have seen them
    2  a file could not be read or is not valid JSON
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from next_step import record_own_step  # noqa: E402
from paper import leaves, part_id, plain_text, where  # noqa: E402
from report import Report, fmt, is_num  # noqa: E402
from task_files import load_json  # noqa: E402

TOLERANCE = 0.01          # relative: solvers round to 3 or 4 significant figures


def close(a, b, tol=TOLERANCE):
    return abs(a - b) <= tol * max(abs(a), abs(b))


def power_of_ten_apart(a, b, tol=TOLERANCE):
    """True if a/b is (within tol) 10, 100, 0.1 ... but not 1."""
    if a == 0 or b == 0 or (a < 0) != (b < 0):
        return False
    k = round(math.log10(abs(a / b)))
    return k != 0 and abs(k) <= 9 and close(a, b * 10 ** k, tol)


def solver_index(sdoc, r):
    """{(question number, part id or ''): answer entry}; reports malformed entries as V5."""
    index = {}
    answers = sdoc.get("answers") if isinstance(sdoc, dict) else None
    if not isinstance(answers, list):
        r.error("answers file", 'must be an object with an "answers" list', "V5")
        return index
    for i, a in enumerate(answers):
        loc = f"answers[{i}]"
        if not isinstance(a, dict) or not isinstance(a.get("number"), int):
            r.error(loc, 'each answer needs an integer "number"', "V5")
            continue
        key = (a["number"], a.get("id", ""))
        if not isinstance(key[1], str):
            r.error(loc, '"id" must be text', "V5")
            continue
        if key in index:
            r.error(loc, f"Q{key[0]} {key[1] or '(whole question)'} is answered more than once", "V5")
            continue
        index[key] = a
    return index


def clean_values(entry, loc, r):
    vals = entry.get("values", [])
    out = []
    if not isinstance(vals, list):
        r.error(loc, '"values" must be a list of {"value", "unit"}', "V5")
        return out
    for v in vals:
        if isinstance(v, dict) and is_num(v.get("value")):
            out.append((v["value"], v.get("unit", "") if isinstance(v.get("unit", ""), str) else ""))
        else:
            r.error(loc, f'a value must look like {{"value": 3.5, "unit": "m"}}, got {json.dumps(v)}', "V5")
    return out


def compare(qdoc, sdoc):
    r = Report()
    index = solver_index(sdoc, r)
    for (n, pid), a in index.items():
        if isinstance(a.get("problem"), str) and a["problem"].strip():
            r.warn(where(n, [pid] if pid else []), f"the solver reports a problem: {a['problem'].strip()}", "V6")
    used = set()
    for q in qdoc["questions"]:
        n = q["number"]
        if "options" in q:
            a = index.get((n, ""))
            used.add((n, ""))
            if a is None:
                r.error(where(n), "the solver gave no answer", "V5")
                continue
            choice = a.get("choice")
            if not isinstance(choice, str):
                r.error(where(n), 'the answer needs a "choice" such as "b"', "V5")
            elif choice.strip().lower() != q["correctOption"]:
                r.error(where(n), f"the solver chose ({choice.strip().lower()}) but the key says "
                                  f"({q['correctOption']})", "V1")
            continue
        for labels, leaf in leaves(q["parts"]):
            pid = part_id(labels)
            loc = where(n, [x for x in labels if x])
            a = index.get((n, pid))
            used.add((n, pid))
            if a is None:
                r.error(loc, "the solver gave no answer", "V5")
                continue
            if "computed" in leaf:
                compare_values(r, loc, leaf, clean_values(a, loc, r))
            else:
                r.info.append(f"{loc}: theory part, judge by reading\n"
                              f"      key:    {plain_text(leaf['answer'])}\n"
                              f"      solver: {a.get('answer', '(no text given)')}")
    for key in index:
        if key not in used:
            r.error(where(key[0], [key[1]] if key[1] else []), "the solver answered a part that does not "
                    "exist in the key", "V5")
    return r


def compare_values(r, loc, leaf, got):
    want = [(c["value"], c.get("unit", "")) for c in leaf["computed"]]
    if not got:
        r.error(loc, "numerical part, but the solver gave no values; the key has "
                + ", ".join(f"{fmt(v)} {plain_text(u)}".strip() for v, u in want), "V4")
        return
    for value, unit in got:
        if any(close(value, w) for w, _ in want):
            continue
        key_text = ", ".join(f"{fmt(w)} {plain_text(u)}".strip() for w, u in want)
        mine = f"{fmt(value)} {unit}".strip()
        if any(close(abs(value), abs(w)) and (value < 0) != (w < 0) for w, _ in want):
            r.error(loc, f"the solver's {mine} differs from the key ({key_text}) only in sign; probably a "
                         "direction convention", "V3")
        elif any(power_of_ten_apart(value, w) for w, _ in want):
            r.error(loc, f"the solver's {mine} differs from the key ({key_text}) by a power of ten; "
                         "probably a unit difference", "V3")
        else:
            r.error(loc, f"the solver's {mine} matches nothing in the key ({key_text})", "V2")
    for c in leaf["computed"]:
        if c.get("working") is True:
            continue
        w = c["value"]
        # A value already reported under V3 (sign or power of ten) is not reported again as missing.
        if not any(close(v, w) or close(abs(v), abs(w)) or power_of_ten_apart(v, w) for v, _ in got):
            name = f"{c['label']} " if c.get("label") else ""
            r.error(loc, f"the solver gave no value for {name}({fmt(w)} {plain_text(c.get('unit', ''))}"
                         .rstrip() + ")", "V4")


def main(argv):
    args = argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a file path")
            return 2
        out = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2:
        print(__doc__.strip())
        return 2
    try:
        qdoc, sdoc = load_json(args[0]), load_json(args[1])
        r = compare(qdoc, sdoc)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Cannot read input: {e}")
        return 2
    if as_json:
        report = json.dumps({"mismatches": r.errors, "problems": r.warnings, "theory_parts": r.info},
                            indent=2, ensure_ascii=False)
    else:
        lines = [f"Key:    {args[0]}\nSolver: {args[1]}"]
        for title, items in (("MISMATCHES:", r.errors), ("PROBLEMS REPORTED BY THE SOLVER:", r.warnings),
                             (f"THEORY PARTS ({len(r.info)}): for the reviewer to judge", r.info)):
            if items:
                lines.append("\n" + title)
                lines += [f"  - {m}" for m in items]
        lines.append("\nResult: " + ("NO MISMATCHES" if not r.errors else f"{len(r.errors)} MISMATCH(ES)"))
        report = "\n".join(lines)
    print(report)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        # Mismatches (exit 1) are a finished comparison too; the step is the report being written.
        recorded = record_own_step(os.path.dirname(os.path.abspath(args[0])), "compare_solutions")
        if recorded and not as_json:
            print(recorded)
    return 0 if not r.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
