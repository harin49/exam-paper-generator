#!/usr/bin/env python3
"""Make the blind solver's input from a questions.json file: the paper as a student sees it, with
no answers.

Usage:
    python3 extract_paper.py QUESTIONS.json [--out FILE]

Writes FILE (default: review/solver-input.json beside QUESTIONS.json). Only what the printed paper
shows is kept: number, section, marks, text, stem, options, parts, the description of any diagram
printed on the paper, and the spec's constants. Everything else is left out, so nothing can leak
the answers: answer, marking, explanation, correctOption, computed, kind, difficulty, chapter,
concepts, answerDiagram. Markup is turned into plain text (m s<sup>-2</sup> becomes m s^(-2)).

Each answerable part gets an "id" (a, b(i), ...; "" for a single unlabelled part) which the solver
repeats in its answers file (see schemas/review-format.md).

Exit codes: 0 written, 2 a file could not be read.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import leaves  # noqa: E402

# Keys that must never appear in the solver's input.
FORBIDDEN = {"answer", "marking", "explanation", "correctOption", "computed", "kind", "difficulty",
             "chapter", "concepts", "concept", "answerDiagram", "conceptList"}


def plain_text(s):
    """Question markup -> plain text a model can read exactly."""
    if s is None:
        return None
    s = re.sub(r"<sup>(.*?)</sup>", r"^(\1)", s)
    s = re.sub(r"<sub>(.*?)</sub>", r"_\1", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</?(?:b|i)>", "", s)
    return s.replace(" ", " ")


def part_id(labels):
    """('b', 'ii') -> 'b(ii)'; ('',) -> ''."""
    first, rest = labels[0], labels[1:]
    return first if not rest else first + "".join(f"({x})" for x in rest)


def diagram_of(obj):
    d = obj.get("diagram")
    return {"description": plain_text(d["description"])} if d else None


def paper_part(p, prefix=()):
    labels = prefix + (p["label"],)
    out = {"label": p["label"], "text": plain_text(p["text"]), "marks": p["marks"]}
    if "parts" in p:
        out["parts"] = [paper_part(sp, labels) for sp in p["parts"]]
    else:
        out["id"] = part_id(labels)
    if diagram_of(p):
        out["diagram"] = diagram_of(p)
    return out


def paper_question(q):
    out = {"number": q["number"], "section": q["section"], "marks": q["marks"]}
    if "options" in q:
        out["type"] = "mcq"
        out["text"] = plain_text(q["text"])
        out["options"] = [plain_text(o) for o in q["options"]]
    else:
        out["type"] = "parts"
        out["stem"] = plain_text(q.get("stem"))
        out["parts"] = [paper_part(p) for p in q["parts"]]
    if diagram_of(q):
        out["diagram"] = diagram_of(q)
    return out


def extract(qdoc, spec):
    ex = spec["exam"]
    return {
        "paper": {"board": ex["board"], "class": ex["class"], "subject": ex["subject"],
                  "constants": spec["content"].get("constants", {})},
        "questions": [paper_question(q) for q in qdoc["questions"]],
    }


def find_forbidden(obj, path="solver-input"):
    """Paths of any forbidden key in the output (a leak guard)."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN:
                found.append(f"{path}.{k}")
            found += find_forbidden(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += find_forbidden(v, f"{path}[{i}]")
    return found


def answerable_ids(qdoc):
    """{question number: [part ids]} for the key side (used by compare_solutions.py)."""
    out = {}
    for q in qdoc["questions"]:
        out[q["number"]] = [] if "options" in q else [part_id(lab) for lab, _ in leaves(q["parts"])]
    return out


def main(argv):
    args = argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out needs a file path")
            return 2
        out = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    qpath = args[0]
    folder = os.path.dirname(os.path.abspath(qpath))
    try:
        with open(qpath, encoding="utf-8") as f:
            qdoc = json.load(f)
        with open(os.path.join(folder, qdoc.get("spec", "spec.json")), encoding="utf-8") as f:
            spec = json.load(f)
        data = extract(qdoc, spec)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Cannot read input: {e}")
        return 2
    leaks = find_forbidden(data)
    if leaks:                       # cannot happen unless the code above is changed wrongly
        print("Refusing to write: answer fields found in the output: " + ", ".join(leaks))
        return 2
    out = out or os.path.join(folder, "review", "solver-input.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_parts = sum(len(v) for v in answerable_ids(qdoc).values())
    print(f"Wrote {out}: {len(data['questions'])} questions, {n_parts} answerable parts, no answers.")
    from next_step import record_own_step                     # here: next_step imports render
    recorded = record_own_step(folder, "extract_paper")
    if recorded:
        print(recorded)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
