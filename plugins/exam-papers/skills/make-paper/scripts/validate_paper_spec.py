#!/usr/bin/env python3
"""Validate a paper spec: the JSON file that defines an exam's scope, pattern,
content rules and output.

Usage:
    python3 validate_paper_spec.py SPEC.json [--json]

Exit codes:
    0  valid (warnings may still be printed)
    1  errors found: fix the spec before writing any questions
    2  the file could not be read or is not valid JSON
"""
import json
import math
import os
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from report import Report, frac, fmt, is_int, is_num  # noqa: E402
from spec_types import (PACK_NAME, Diagrams, Difficulty, KeyPart, Numbering,  # noqa: E402
                        SectionType, SubParts, WeightMode)
from task_files import load_json  # noqa: E402

SECTION_TYPES = SectionType.values()
SUBPARTS = SubParts.values()
NUMBERING = Numbering.values()
WEIGHT_MODES = WeightMode.values()
DIAGRAMS = Diagrams.values()
KEY_PARTS = KeyPart.values()
DIFFICULTY_LEVELS = Difficulty.values()

ALLOWED_KEYS = {
    "root": {"exam", "pattern", "content", "output"},
    "exam": {"board", "class", "subject", "book", "syllabusPack", "chapters"},
    "pattern": {"totalMarks", "durationMinutes", "sections", "numbering", "smallestMarkUnit"},
    "section": {"id", "type", "questionsOffered", "questionsToAttempt", "marksPerQuestion",
                "sectionTotal", "mcqOptions", "subParts", "minSubParts", "maxSubParts", "difficulty"},
    "content": {"chapterWeightage", "numericalTheorySplit",
                "everyChapterInCompulsorySection", "diagrams", "showChapterNames",
                "constants", "avoidOverlappingConcepts"},
    "output": {"header", "answerKey"},
    "answerKey": {"include"},
}


def check_keys(r, obj, kind, path):
    for k in obj:
        if k not in ALLOWED_KEYS[kind]:
            r.warn(path, f"unknown field '{k}' (typo?)", rule="S16")


def need(r, obj, key, path, check, desc, rule="S1"):
    """Return obj[key] if present and valid, else record an error and return None."""
    p = f"{path}.{key}" if path else key
    if key not in obj:
        r.error(p, "is required", rule=rule)
        return None
    if not check(obj[key]):
        r.error(p, f"must be {desc} (got {json.dumps(obj[key])})", rule=rule)
        return None
    return obj[key]


def check_percent_target(r, obj, path, keys=None):
    """A target that is a list or dict of percentages summing to 100, plus a tolerance."""
    if not isinstance(obj, dict):
        r.error(path, "must be an object with 'target' and a tolerance", rule="S11")
        return
    t = obj.get("target")
    vals = t.values() if isinstance(t, dict) else t
    if t is None or not isinstance(t, (list, dict)) or not all(is_num(v) and v >= 0 for v in vals):
        r.error(f"{path}.target", "must be a list or object of non-negative percentages", rule="S11")
    else:
        if isinstance(t, dict) and keys and set(t) != keys:
            r.error(f"{path}.target", f"must have exactly the keys {sorted(keys)}", rule="S11")
        if abs(sum(vals) - 100) > 1e-9:
            r.error(f"{path}.target", f"percentages must add up to 100 (they add up to {fmt(sum(vals))})", rule="S11")
    tol = obj.get("tolerancePercent")
    if not (is_num(tol) and 0 <= tol <= 100):
        r.error(f"{path}.tolerancePercent", "must be a number from 0 to 100", rule="S11")


def validate(spec):
    r = Report()
    if not isinstance(spec, dict):
        r.error("", "the spec must be a JSON object", rule="S1")
        return r
    check_keys(r, spec, "root", "root")

    # ---------------- exam ----------------
    chapters = []
    exam = need(r, spec, "exam", "", lambda x: isinstance(x, dict), "an object")
    if exam is not None:
        check_keys(r, exam, "exam", "exam")
        for k in ("board", "subject"):
            need(r, exam, k, "exam", lambda x: isinstance(x, str) and x.strip(), "a non-empty string")
        if "book" in exam and not (isinstance(exam["book"], str) and exam["book"].strip()):
            r.error("exam.book", "must be a non-empty string (or left out: the book is optional)", rule="S1")
        need(r, exam, "class", "exam", lambda x: is_int(x) and x > 0, "a positive whole number")
        need(r, exam, "syllabusPack", "exam", lambda x: isinstance(x, str) and PACK_NAME.match(x),
             "the name of the syllabus pack's folder under syllabi/: lower case letters and digits, "
             "words joined by hyphens (e.g. \"icse9-physics-selina\")", rule="S20")
        ch = need(r, exam, "chapters", "exam",
                  lambda x: isinstance(x, list) and x and all(is_int(c) and c > 0 for c in x),
                  "a non-empty list of positive chapter numbers", rule="S2")
        if ch:
            if len(set(ch)) != len(ch):
                r.error("exam.chapters", "contains duplicates", rule="S2")
            chapters = sorted(set(ch))

    # ---------------- pattern ----------------
    sections = []
    smu = None
    pattern = need(r, spec, "pattern", "", lambda x: isinstance(x, dict), "an object")
    if pattern is not None:
        check_keys(r, pattern, "pattern", "pattern")
        total = need(r, pattern, "totalMarks", "pattern", lambda x: is_num(x) and x > 0, "a positive number")
        need(r, pattern, "durationMinutes", "pattern", lambda x: is_int(x) and x > 0, "a positive whole number")
        need(r, pattern, "numbering", "pattern", lambda x: x in NUMBERING, f"one of {sorted(NUMBERING)}")
        smu = need(r, pattern, "smallestMarkUnit", "pattern",
                   lambda x: is_num(x) and x > 0 and (1 / frac(x)).denominator == 1,
                   "a positive unit that divides 1 evenly (e.g. 1, 0.5, 0.25)", rule="S3")
        secs = need(r, pattern, "sections", "pattern", lambda x: isinstance(x, list) and x,
                    "a non-empty list")
        ids = set()
        for i, s in enumerate(secs or []):
            p = f"pattern.sections[{i}]"
            if not isinstance(s, dict):
                r.error(p, "must be an object", rule="S1")
                continue
            check_keys(r, s, "section", p)
            sid = need(r, s, "id", p, lambda x: isinstance(x, str) and x.strip(), "a non-empty string")
            if sid:
                p = f"pattern.sections[{sid}]"
                if sid in ids:
                    r.error(p, "duplicate section id", rule="S4")
                ids.add(sid)
            stype = need(r, s, "type", p, lambda x: x in SECTION_TYPES, f"one of {sorted(SECTION_TYPES)}")
            off = need(r, s, "questionsOffered", p, lambda x: is_int(x) and x > 0, "a positive whole number")
            att = need(r, s, "questionsToAttempt", p, lambda x: is_int(x) and x > 0, "a positive whole number")
            mpq = need(r, s, "marksPerQuestion", p, lambda x: is_num(x) and x > 0, "a positive number")
            stot = need(r, s, "sectionTotal", p, lambda x: is_num(x) and x > 0, "a positive number")
            sub = need(r, s, "subParts", p, lambda x: x in SUBPARTS, f"one of {sorted(SUBPARTS)}")

            if off and att and att > off:
                r.error(p, f"questionsToAttempt ({att}) is more than questionsOffered ({off})", rule="S5")
            if att and mpq and stot and frac(att) * frac(mpq) != frac(stot):
                r.error(p, f"sectionTotal is {fmt(stot)} but {att} questions × {fmt(mpq)} marks = "
                           f"{fmt(float(frac(att) * frac(mpq)))}", rule="S6")
            if mpq and smu and (frac(mpq) / frac(smu)).denominator != 1:
                r.error(p, f"marksPerQuestion ({fmt(mpq)}) is not a multiple of smallestMarkUnit ({fmt(smu)})", rule="S8")

            if stype == SectionType.MCQ:
                if sub and sub != SubParts.NONE:
                    r.error(p, "an mcq section must have subParts 'none'", rule="S9")
                need(r, s, "mcqOptions", p, lambda x: is_int(x) and x >= 2, "a whole number of at least 2", rule="S9")
            elif "mcqOptions" in s:
                r.warn(p, "mcqOptions is ignored for a non-mcq section", rule="S17")

            mn, mx = s.get("minSubParts"), s.get("maxSubParts")
            if sub == SubParts.NONE and (mn is not None or mx is not None):
                r.error(p, "minSubParts/maxSubParts set but subParts is 'none'", rule="S10")
            for k, v in (("minSubParts", mn), ("maxSubParts", mx)):
                if v is not None and not (is_int(v) and v >= 2):
                    r.error(f"{p}.{k}", "must be a whole number of at least 2", rule="S10")
            if is_int(mn) and is_int(mx) and mn > mx:
                r.error(p, f"minSubParts ({mn}) is more than maxSubParts ({mx})", rule="S10")
            if sub == SubParts.REQUIRED and mn is None:
                r.warn(p, "subParts is 'required' but minSubParts is not set; 2 will be assumed", rule="S18")
            if is_int(mn) and mpq and smu and frac(mpq) / frac(smu) < mn:
                r.error(p, f"{fmt(mpq)} marks cannot be split into {mn} parts of at least {fmt(smu)} mark each", rule="S10")

            if "difficulty" in s:
                check_percent_target(r, s["difficulty"], f"{p}.difficulty", DIFFICULTY_LEVELS)
            else:
                r.error(f"{p}.difficulty", "is required", rule="S1")

            if all(v is not None for v in (sid, off, att, mpq)):
                sections.append({"id": sid, "offered": off, "attempt": att, "marks": mpq,
                                 "compulsory": off == att, "subParts": sub,
                                 "difficulty": s.get("difficulty")})

        if total and secs and all(isinstance(s, dict) and is_num(s.get("sectionTotal")) for s in secs):
            st = sum(frac(s["sectionTotal"]) for s in secs)
            if st != frac(total):
                r.error("pattern", f"section totals add up to {fmt(float(st))} but totalMarks is {fmt(total)}", rule="S7")

    # ---------------- content ----------------
    content = need(r, spec, "content", "", lambda x: isinstance(x, dict), "an object")
    weight_mode, tol_marks, weights, every_ch = None, None, None, False
    if content is not None:
        check_keys(r, content, "content", "content")
        cw = need(r, content, "chapterWeightage", "content", lambda x: isinstance(x, dict), "an object")
        if cw is not None:
            weight_mode = need(r, cw, "mode", "content.chapterWeightage", lambda x: x in WEIGHT_MODES,
                               f"one of {sorted(WEIGHT_MODES)}")
            tol_marks = need(r, cw, "toleranceMarks", "content.chapterWeightage",
                             lambda x: is_num(x) and x >= 0, "a non-negative number")
            if weight_mode == WeightMode.CUSTOM:
                w = need(r, cw, "weights", "content.chapterWeightage",
                         lambda x: isinstance(x, dict) and all(is_num(v) and v >= 0 for v in x.values()),
                         "an object mapping chapter number to percentage", rule="S12")
                if w is not None:
                    keys = set()
                    for k in w:
                        if not (k.isdigit() and int(k) in chapters):
                            r.error("content.chapterWeightage.weights", f"'{k}' is not a chapter in exam.chapters", rule="S12")
                        else:
                            keys.add(int(k))
                    missing = set(chapters) - keys
                    if missing:
                        r.error("content.chapterWeightage.weights", f"no weight for chapter(s) {sorted(missing)}", rule="S12")
                    if abs(sum(w.values()) - 100) > 1e-9:
                        r.error("content.chapterWeightage.weights", f"must add up to 100 (they add up to {fmt(sum(w.values()))})", rule="S12")
                    weights = {int(k): v for k, v in w.items() if k.isdigit()}
            elif "weights" in cw:
                r.warn("content.chapterWeightage", "weights are ignored when mode is 'equal'", rule="S17")

        if "numericalTheorySplit" in content:
            nts = content["numericalTheorySplit"]
            check_percent_target(r, nts, "content.numericalTheorySplit")
            if isinstance(nts, dict) and isinstance(nts.get("target"), list) and len(nts["target"]) != 2:
                r.error("content.numericalTheorySplit.target", "must have exactly two values: [numerical, theory]", rule="S11")
        else:
            r.error("content.numericalTheorySplit", "is required", rule="S1")

        every_ch = need(r, content, "everyChapterInCompulsorySection", "content",
                        lambda x: isinstance(x, bool), "true or false")
        need(r, content, "diagrams", "content", lambda x: x in DIAGRAMS, f"one of {sorted(DIAGRAMS)}")
        need(r, content, "showChapterNames", "content", lambda x: isinstance(x, bool), "true or false")
        need(r, content, "avoidOverlappingConcepts", "content", lambda x: isinstance(x, bool), "true or false")
        if "constants" in content and not (isinstance(content["constants"], dict) and
                                           all(is_num(v) for v in content["constants"].values())):
            r.error("content.constants", "must be an object of name: number", rule="S1")

    # ---------------- output ----------------
    out = need(r, spec, "output", "", lambda x: isinstance(x, dict), "an object")
    if out is not None:
        check_keys(r, out, "output", "output")
        if "header" not in out:
            r.error("output.header", "is required (use null for no header)", rule="S15")
        elif out["header"] is not None and not isinstance(out["header"], str):
            r.error("output.header", "must be text or null", rule="S15")
        ak = need(r, out, "answerKey", "output", lambda x: isinstance(x, dict), "an object")
        if ak is not None:
            check_keys(r, ak, "answerKey", "output.answerKey")
            need(r, ak, "include", "output.answerKey",
                 lambda x: isinstance(x, list) and set(x) <= KEY_PARTS,
                 f"a list drawn from {sorted(KEY_PARTS)} (empty for answers only)")

    # ---------------- feasibility (only if the structure is sound) ----------------
    if not r.errors and chapters and sections:
        feasibility(r, chapters, sections, weight_mode, weights, tol_marks, every_ch)
    return r


def difficulty_mix(r, sections, offered):
    """Report the paper's difficulty mix that the section targets add up to (info), and warn (S21)
    when a section without parts cannot meet its target: each of its questions has one level, so
    each moves the section's mix by a whole question's share."""
    levels = [d.value for d in Difficulty]
    paper = {lvl: sum(frac(s["offered"]) * frac(s["marks"]) * frac(s["difficulty"]["target"][lvl])
                      for s in sections) / offered for lvl in levels}
    r.info.append("Paper difficulty mix from the section targets: " +
                  ", ".join(f"{lvl} {float(paper[lvl]):.1f}%" for lvl in levels))
    for s in sections:
        if s["subParts"] != SubParts.NONE:
            continue
        n, target = s["offered"], s["difficulty"]["target"]
        tol = frac(s["difficulty"]["tolerancePercent"])
        lo, hi = {}, {}
        for lvl in levels:
            t = frac(target[lvl])
            lo[lvl] = 0 if t == 0 else max(0, math.ceil((t - tol) * n / 100))
            hi[lvl] = 0 if t == 0 else min(n, math.floor((t + tol) * n / 100))
        if any(lo[lvl] > hi[lvl] for lvl in levels) or not sum(lo.values()) <= n <= sum(hi.values()):
            r.warn(f"pattern.sections[{s['id']}].difficulty",
                   f"{n} whole questions cannot meet this target within ±{fmt(tol)}%: each question has "
                   f"one level and is {float(Fraction(100, n)):.1f}% of the section", rule="S21")


def feasibility(r, chapters, sections, mode, weights, tol, every_ch):
    offered = sum(frac(s["offered"]) * frac(s["marks"]) for s in sections)
    attempted = sum(frac(s["attempt"]) * frac(s["marks"]) for s in sections)
    r.info.append(f"Marks offered: {fmt(float(offered))}; marks a student attempts: {fmt(float(attempted))}")
    difficulty_mix(r, sections, offered)

    if every_ch:
        comp = sum(s["offered"] for s in sections if s["compulsory"])
        if comp == 0:
            r.error("content.everyChapterInCompulsorySection",
                    "is true but no section is compulsory (every section has a choice)", rule="S14")
            return
        if comp < len(chapters):
            r.error("content.everyChapterInCompulsorySection",
                    f"is true but the compulsory sections have only {comp} questions for {len(chapters)} chapters", rule="S14")
            return

    if mode == WeightMode.CUSTOM and weights:
        target = {c: offered * frac(weights[c]) / 100 for c in chapters}
    else:
        target = {c: offered / len(chapters) for c in chapters}

    # Greedy balance: seed one compulsory question per chapter if required, then place the
    # remaining questions largest first on whichever chapter is furthest below its target.
    items = []
    for s in sections:
        items += [(frac(s["marks"]), s["compulsory"], s["id"]) for _ in range(s["offered"])]
    load = {c: Fraction(0) for c in chapters}
    count = {c: {} for c in chapters}

    def place(c, it):
        load[c] += it[0]
        count[c][it[2]] = count[c].get(it[2], 0) + 1

    if every_ch:
        comp_items = sorted((it for it in items if it[1]), key=lambda it: it[0])
        for c, it in zip(chapters, comp_items):
            place(c, it)
            items.remove(it)
    for it in sorted(items, key=lambda it: -it[0]):
        c = min(chapters, key=lambda c: (load[c] - target[c], c))
        place(c, it)

    worst = max(abs(load[c] - target[c]) for c in chapters)
    dist = ", ".join(f"ch{c}: {fmt(float(load[c]))}" for c in chapters)
    r.info.append(f"Target per chapter: " + ", ".join(f"ch{c}: {float(target[c]):.1f}" for c in chapters))
    r.info.append(f"A balanced split is possible, e.g. {dist} (largest gap {float(worst):.1f} marks)")
    if tol is not None and worst > frac(tol):
        r.warn("content.chapterWeightage",
               f"the best split found is {float(worst):.1f} marks from target, beyond the "
               f"tolerance of {fmt(tol)}; consider a larger tolerance or a different pattern", rule="S19")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    try:
        spec = load_json(args[0])
    except (OSError, json.JSONDecodeError) as e:
        print(f"Cannot read {args[0]}: {e}")
        return 2
    r = validate(spec)
    if as_json:
        print(json.dumps({"valid": not r.errors, "errors": r.errors,
                          "warnings": r.warnings, "info": r.info}, indent=2, ensure_ascii=False))
    else:
        print(f"Paper spec: {args[0]}")
        for title, items in (("ERRORS", r.errors), ("WARNINGS", r.warnings), ("INFO", r.info)):
            if items:
                print(f"\n{title}:")
                for m in items:
                    print(f"  - {m}")
        print("\nResult: " + ("VALID" if not r.errors else f"INVALID ({len(r.errors)} error(s))"))
    return 0 if not r.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
