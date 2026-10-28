#!/usr/bin/env python3
"""Make a blueprint (blueprint.json) from a paper spec and a concept list.

Usage:
    python3 make_blueprint.py SPEC.json --concepts CONCEPTS.json [--out BLUEPRINT.json] [--force] [--json]

The blueprint is written beside the spec unless --out is given. An existing blueprint that the
teacher approved (approvals.json beside it, see approvals.py) is never overwritten unless --force is
given.

Every decision is made by fixed rules, so the same spec and concept list always give the same
blueprint:
  1. Chapters: each section's questions are spread across the spec's chapters, then single questions
     are moved between chapters while that improves the balance (compulsory coverage first, then
     chapter tolerance, then evenness within sections, then closeness to target).
  2. Parts: each question's marks are split into parts using the spec's sub-part limits, cycling
     through the best splits so questions in a section vary.
  3. Kinds: each part becomes numerical or theory to approach the spec's split within each
     section, using only kinds that some concept in its chapter supports at that many marks.
  4. Difficulty: each part gets the level furthest below its target (levels at 0% are never used).
  5. Concepts: each part gets the least-used concept of its chapter that allows its kind and marks,
     preferring one not already used in the same question and one whose maxMarks fits the part
     (a concept meant for parts 3+ marks bigger counts as already used once).
  6. Correct options: each MCQ section's correct letters are dealt in shuffled rounds of a, b, c, d
     (every letter once per round), so the letters are used evenly and none comes up more than twice
     in a row. The shuffle is seeded from the spec, so the same spec always gives the same letters.
The result is then checked with the same rules as check_questions.py (Q2-Q14 where they apply).

Exit codes: 0 written, 1 errors (in the inputs, or the result fails a check), 2 a file could not be read.
"""
import hashlib
import json
import math
import os
import random
import sys
from fractions import Fraction
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_questions as cq  # noqa: E402
from approvals import is_approved  # noqa: E402
from spec_types import Kind, Numbering, SectionType, SubParts  # noqa: E402
from validate_concepts import validate as validate_concepts  # noqa: E402
from validate_paper_spec import Report, frac, validate as validate_spec  # noqa: E402

LETTERS = "abcdefghijklmnopqrstuvwxyz"
LEVEL_ORDER = ("easy", "medium", "hard")


class BlueprintError(Exception):
    pass


# ---------------- 1. chapters ----------------
def allocate_chapters(sections, chapters, targets, tol, every_ch):
    """Returns {section id: {chapter: number of questions}}."""
    load = {c: Fraction(0) for c in chapters}
    counts = {}
    for s in sorted(sections, key=lambda s: -frac(s["marksPerQuestion"])):
        n, k, m = s["questionsOffered"], len(chapters), frac(s["marksPerQuestion"])
        cnt = {c: n // k for c in chapters}
        for c in chapters:
            load[c] += cnt[c] * m
        for _ in range(n % k):
            c = min(chapters, key=lambda c: (load[c] - targets[c], chapters.index(c)))
            cnt[c] += 1
            load[c] += m
        counts[s["id"]] = cnt
    compulsory = [s["id"] for s in sections if s["questionsOffered"] == s["questionsToAttempt"]]
    marks = {s["id"]: frac(s["marksPerQuestion"]) for s in sections}

    def score(cnts):
        ld = {c: sum(cnts[sid][c] * marks[sid] for sid in cnts) for c in chapters}
        missing = sum(1 for c in chapters if every_ch and not any(cnts[sid][c] for sid in compulsory))
        dev = max(abs(ld[c] - targets[c]) for c in chapters)
        uneven = sum(max(v.values()) - min(v.values()) for v in cnts.values())
        sumsq = sum((ld[c] - targets[c]) ** 2 for c in chapters)
        return (missing, max(Fraction(0), dev - tol), uneven, dev, sumsq)

    best = score(counts)
    for _ in range(500):
        move = None
        for sid, a, b in product([s["id"] for s in sections], chapters, chapters):
            if a == b or counts[sid][a] == 0:
                continue
            counts[sid][a] -= 1
            counts[sid][b] += 1
            sc = score(counts)
            counts[sid][a] += 1
            counts[sid][b] -= 1
            if sc < best:
                best, move = sc, (sid, a, b)
        if not move:
            break
        sid, a, b = move
        counts[sid][a] -= 1
        counts[sid][b] += 1
    return counts


# ---------------- 2. parts ----------------
def candidate_splits(marks, section, smu, cap):
    """Ordered list of mark splits (tuples) allowed for one question, best first."""
    if section["type"] == SectionType.MCQ:
        return [None]
    if section["subParts"] == SubParts.NONE:
        return [("",)]
    step = frac(smu)
    sizes = [x * step for x in range(1, int(frac(cap) / step) + 1)]
    sizes = [x for x in sizes if x.denominator == 1] or sizes   # prefer whole-mark parts
    mn = section.get("minSubParts", 2 if section["subParts"] == SubParts.REQUIRED else 1)
    mx = section.get("maxSubParts", int(frac(marks) / step))
    ideal = min(max(math.ceil(float(frac(marks)) / 2.5), mn), mx)
    total = frac(marks)
    found = []

    def build(prefix, remaining, k):
        if len(prefix) == k:
            if remaining == 0:
                found.append(tuple(prefix))
            return
        for x in sizes:
            if x <= remaining:
                build(prefix + [x], remaining - x, k)

    for k in range(mn, mx + 1):
        if k <= 12:
            build([], total, k)
    if not found:
        raise BlueprintError(f"section {section['id']}: {marks} marks cannot be split into {mn}-{mx} parts of at "
                             f"most {cap} marks each (the largest maxMarks of the chapter's concepts)")
    found.sort(key=lambda t: (abs(len(t) - ideal), -min(t), max(t) - min(t), t))
    best = found[0]
    return [t for t in found if (abs(len(t) - ideal), -min(t), max(t) - min(t)) ==
            (abs(len(best) - ideal), -min(best), max(best) - min(best))]


# ---------------- 3-5. kinds, difficulty, concepts ----------------
def assign_kinds(leaves, by_chapter, num_target_pct):
    """Numerical/theory per part, balanced within each section so every section gets a share."""
    def possible(leaf):
        return sorted({k for c in by_chapter[leaf["chapter"]] if c["maxMarks"] >= leaf["marks"]
                       for k in c["kinds"]})

    sections = {}
    for leaf in leaves:
        sections.setdefault(leaf["section"], []).append(leaf)
    for sec_leaves in sections.values():
        target = sum(l["marks"] for l in sec_leaves) * frac(num_target_pct) / 100
        num = Fraction(0)
        flexible = []
        for leaf in sec_leaves:
            p = possible(leaf)
            if not p:
                raise BlueprintError(f"chapter {leaf['chapter']} has no concept that can carry a "
                                     f"{leaf['marks']}-mark part")
            if len(p) == 1:
                leaf["kind"] = p[0]
                num += leaf["marks"] if p[0] == Kind.NUMERICAL else 0
            else:
                flexible.append(leaf)
        # equal-mark parts are taken round-robin across chapters (1st of each chapter, then 2nd...),
        # so numerical parts are spread over chapters instead of filling the first ones
        rank, seen = {}, {}
        for leaf in flexible:
            key = (leaf["chapter"], leaf["marks"])
            rank[leaf["seq"]] = seen.get(key, 0)
            seen[key] = rank[leaf["seq"]] + 1
        for leaf in sorted(flexible, key=lambda l: (-l["marks"], rank[l["seq"]], l["seq"])):
            if abs(num + leaf["marks"] - target) < abs(num - target):
                leaf["kind"] = Kind.NUMERICAL.value
                num += leaf["marks"]
            else:
                leaf["kind"] = Kind.THEORY.value


def assign_difficulty(leaves, targets_pct, offered):
    levels = [l for l in LEVEL_ORDER if l in targets_pct and targets_pct[l] > 0]
    target = {l: offered * frac(targets_pct[l]) / 100 for l in levels}
    got = {l: Fraction(0) for l in levels}
    order = sorted(leaves, key=lambda l: (-l["marks"], l["kind"] != Kind.NUMERICAL, l["seq"]))
    for leaf in order:
        # numerical parts lean harder, theory parts easier, when deficits are close
        pref = levels[::-1] if leaf["kind"] == Kind.NUMERICAL else levels
        lvl = max(pref, key=lambda l: (target[l] - got[l], -pref.index(l)))
        leaf["difficulty"] = lvl
        got[lvl] += leaf["marks"]


def assign_concepts(leaves, by_chapter):
    used = {}

    def fitting(leaf):
        return [c for c in by_chapter[leaf["chapter"]]
                if leaf["kind"] in c["kinds"] and c["maxMarks"] >= leaf["marks"]]

    # most constrained parts first (fewest fitting concepts), so they get a free concept before
    # flexible parts take it
    for leaf in sorted(leaves, key=lambda l: (len(fitting(l)), -l["marks"], l["seq"])):
        pool = fitting(leaf)
        if not pool:
            raise BlueprintError(f"no concept in chapter {leaf['chapter']} allows a {leaf['marks']}-mark "
                                 f"{leaf['kind']} part")
        in_q = leaf["question"]["_concepts"]
        # a concept meant for much bigger parts (e.g. a derivation on a 1-mark MCQ) counts as if
        # already used once, so it is only chosen when nothing that fits better is free
        def key(c):
            poor_fit = 1 if c["maxMarks"] - leaf["marks"] >= 3 else 0
            return (c["tag"] in in_q, used.get(c["tag"], 0) + poor_fit,
                    c["maxMarks"] - leaf["marks"], by_chapter[leaf["chapter"]].index(c))
        best = min(pool, key=key)
        leaf["concept"] = best["tag"]
        used[best["tag"]] = used.get(best["tag"], 0) + 1
        in_q.append(best["tag"])


# ---------------- 6. correct options ----------------
def assign_correct_options(questions, spec):
    """Give every MCQ a correctOption, dealt in shuffled rounds of the section's letters."""
    seed = hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()
    for s in spec["pattern"]["sections"]:
        if s["type"] != SectionType.MCQ:
            continue
        rng = random.Random(f"{seed}:{s['id']}")
        mcqs = [q for q in questions if q["section"] == s["id"]]
        letters = []
        while len(letters) < len(mcqs):
            round_ = list(LETTERS[:s["mcqOptions"]])
            rng.shuffle(round_)
            letters += round_
        for q, letter in zip(mcqs, letters):
            q["correctOption"] = letter


# ---------------- assemble ----------------
def number_value(x):
    x = float(x)
    return int(x) if x.is_integer() else x


def make(spec, concepts):
    """Returns (blueprint without file paths, Report)."""
    sections = spec["pattern"]["sections"]
    chapters = list(spec["exam"]["chapters"])
    rules = spec["content"]
    smu = spec["pattern"]["smallestMarkUnit"]

    by_chapter = {}
    for c in chapters:
        entry = concepts["chapters"].get(str(c))
        if not entry:
            raise BlueprintError(f"the concept list has no chapter {c}")
        by_chapter[c] = [dict(x, maxMarks=frac(x["maxMarks"])) for x in entry["concepts"]]

    offered = sum(frac(s["questionsOffered"]) * frac(s["marksPerQuestion"]) for s in sections)
    cw = rules["chapterWeightage"]
    if cw["mode"] == "custom":
        targets = {c: offered * frac(cw["weights"][str(c)]) / 100 for c in chapters}
    else:
        targets = {c: offered / len(chapters) for c in chapters}
    counts = allocate_chapters(sections, chapters, targets, frac(cw["toleranceMarks"]),
                               rules["everyChapterInCompulsorySection"])

    questions, leaves, seq = [], [], 0
    for s in sections:
        sec_chapters = [c for c in chapters for _ in range(counts[s["id"]][c])]
        for i, ch in enumerate(sec_chapters):
            cap = max(c["maxMarks"] for c in by_chapter[ch])
            splits = candidate_splits(s["marksPerQuestion"], s, smu, cap)
            split = splits[i % len(splits)]
            q = {"section": s["id"], "chapter": ch, "marks": s["marksPerQuestion"], "_concepts": []}
            if split is None:
                items = [q]
            else:
                q["parts"] = [{"label": "" if split == ("",) else LETTERS[j],
                               "marks": number_value(s["marksPerQuestion"]) if split == ("",) else number_value(m)}
                              for j, m in enumerate(split)]
                items = q["parts"]
            for it in items:
                seq += 1
                leaves.append({"obj": it, "chapter": ch, "marks": frac(it["marks"]), "seq": seq,
                               "section": s["id"],
                               "sectionMarks": frac(s["marksPerQuestion"]), "question": q})
            questions.append(q)

    assign_kinds(leaves, by_chapter, rules["numericalTheorySplit"]["target"][0])
    assign_difficulty(leaves, rules["difficulty"]["target"], offered)
    assign_concepts(leaves, by_chapter)
    for leaf in leaves:
        leaf["obj"].update(kind=leaf["kind"], difficulty=leaf["difficulty"], concept=leaf["concept"])

    number = 0
    prev = None
    out = []
    for q in questions:
        if spec["pattern"]["numbering"] == Numbering.PER_SECTION and q["section"] != prev:
            number = 0
        prev = q["section"]
        number += 1
        item = {"number": number, "section": q["section"], "chapter": q["chapter"], "marks": q["marks"],
                "concepts": list(dict.fromkeys(q["_concepts"]))}
        if "parts" in q:
            item["parts"] = q["parts"]
        else:
            item.update(kind=q["kind"], difficulty=q["difficulty"], concept=q["concept"])
        out.append(item)
    assign_correct_options(out, spec)
    return out


def self_check(questions, spec, concepts):
    """Run the check_questions.py rules that apply to a blueprint (no wording yet)."""
    r = Report()
    spec_sections = {s["id"]: s for s in spec["pattern"]["sections"]}
    chapters = spec["exam"]["chapters"]
    rules = spec["content"]
    cq.check_sequence(r, questions, spec_sections, spec["pattern"]["numbering"])
    cq.check_labels(r, questions, spec_sections)
    cq.check_section_counts(r, questions, spec_sections)
    cq.check_part_counts(r, questions, spec_sections)
    cq.check_marks(r, questions, spec["pattern"]["smallestMarkUnit"])
    tags = cq.read_concept_list(r, concepts, spec)
    cq.check_concepts(r, questions, tags, chapters)
    cq.check_excluded_difficulty(r, questions, rules["difficulty"]["target"])
    if rules["everyChapterInCompulsorySection"]:
        cq.check_compulsory_coverage(r, questions, spec_sections, chapters)
    cq.check_balance(r, questions, chapters, rules)
    if rules["avoidOverlappingConcepts"]:
        cq.check_shared_concepts(r, questions)
    return r


def build(spec, concepts, syllabus_text=None):
    """Validate inputs, make the blueprint questions and check them. Returns (questions or None, Report)."""
    r = Report()
    sr = validate_spec(spec)
    for e in sr.errors:
        r.errors.append(f"spec: {e}")
    if syllabus_text is not None:
        cr = validate_concepts(concepts, syllabus_text)
        for e in cr.errors:
            r.errors.append(f"concept list: {e}")
        for w in cr.warnings:
            r.warnings.append(f"concept list: {w}")
    if r.errors:
        return None, r
    try:
        questions = make(spec, concepts)
    except BlueprintError as e:
        r.error("blueprint", str(e))
        return None, r
    sc = self_check(questions, spec, concepts)
    r.errors += sc.errors
    r.warnings += sc.warnings
    r.info += sc.info
    return questions, r


def main(argv):
    args = argv[1:]
    as_json, force = "--json" in args, "--force" in args
    args = [a for a in args if a not in ("--json", "--force")]
    opts = {}
    for flag in ("--concepts", "--out"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"{flag} needs a file path")
                return 2
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or "--concepts" not in opts:
        print(__doc__.strip())
        return 2
    spath, cpath = args[0], opts["--concepts"]
    out = opts.get("--out") or os.path.join(os.path.dirname(spath), "blueprint.json")
    try:
        with open(spath, encoding="utf-8") as f:
            spec = json.load(f)
        with open(cpath, encoding="utf-8") as f:
            concepts = json.load(f)
        syl = concepts.get("syllabus") if isinstance(concepts, dict) else None
        if not syl or not isinstance(syl, str):
            print(f"Cannot check the concept list: {cpath} has no \"syllabus\" field naming its syllabus file")
            return 2
        with open(os.path.join(os.path.dirname(cpath), syl), encoding="utf-8") as f:
            syllabus_text = f.read()
    except (OSError, ValueError) as e:
        print(f"Cannot read input: {e}")
        return 2

    if os.path.exists(out) and not force:
        try:
            approved = is_approved(os.path.dirname(os.path.abspath(out)), "blueprint", out)
        except (OSError, ValueError):
            approved = False
        if approved:
            print(f"{out} is an approved blueprint; not overwriting it (use --force to replace it)")
            return 1

    questions, r = build(spec, concepts, syllabus_text)
    if questions is not None and not r.errors:
        # realpath, not abspath: a relative path computed through a symlinked folder (on macOS, /tmp
        # and /var are links into /private) climbs out of the wrong parent once the OS resolves "..".
        base = os.path.dirname(os.path.realpath(out))
        doc = {"spec": os.path.relpath(os.path.realpath(spath), base),
               "conceptList": os.path.relpath(os.path.realpath(cpath), base),
               "questions": questions}
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")

    if as_json:
        print(json.dumps({"written": not r.errors, "out": out, "errors": r.errors, "warnings": r.warnings,
                          "info": r.info}, indent=2, ensure_ascii=False))
    else:
        print(f"Spec:         {spath}\nConcept list: {cpath}")
        for title, items in (("ERRORS", r.errors), ("WARNINGS", r.warnings), ("INFO", r.info)):
            if items:
                print(f"\n{title}:")
                for m in items:
                    print(f"  - {m}")
        print("\nResult: " + (f"WRITTEN to {out} (not approved yet)" if not r.errors
                              else f"NOT WRITTEN ({len(r.errors)} error(s))"))
    return 0 if not r.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
