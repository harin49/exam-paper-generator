#!/usr/bin/env python3
"""Validate a concept list (concepts.json) against the syllabus it was drafted from.

Usage:
    python3 validate_concepts.py CONCEPTS.json [--json]

The syllabus is the file named in the list's "syllabus" field, relative to the list's folder. Its
points carry ids [S1], [S2], ... in order, added by number_syllabus.py.

Rules (see schemas/concept-list-format.md in this skill):
    C1  fields present with the right types; no unknown fields
    C2  tags are snake_case and unique across the whole list
    C3  kinds is a non-empty list of allowed kinds, without repeats
    C4  maxMarks is a positive number
    C5  the syllabus's point ids run S1, S2, ... in order, and every source is one of them
    C6  every syllabus point has at least one concept, or is listed in notTested with a reason (coverage)

Exit codes: 0 valid, 1 errors, 2 a file could not be read.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec_types import Kind  # noqa: E402
from validate_paper_spec import Report, is_int, is_num  # noqa: E402

TOP_KEYS = {"board", "class", "book", "syllabus", "syllabusYear", "status", "chapters", "note", "notTested"}
TOP_REQUIRED = {"board", "class", "syllabus", "chapters"}
CHAPTER_KEYS = {"title", "concepts"}
CONCEPT_KEYS = {"tag", "source", "kinds", "maxMarks"}
TAG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
POINT_RE = re.compile(r"\[(S\d+)\]")


def syllabus_points(text):
    """The point ids in the order they appear in the syllabus."""
    return POINT_RE.findall(text)


def keys_ok(r, obj, allowed, required, loc):
    for k in sorted(required - set(obj)):
        r.error(loc, f"'{k}' is required", "C1")
    for k in sorted(set(obj) - allowed):
        r.error(loc, f"unknown field '{k}'", "C1")


def validate(doc, syllabus_text):
    r = Report()
    if not isinstance(doc, dict):
        r.error("file", "must be a JSON object", "C1")
        return r
    keys_ok(r, doc, TOP_KEYS, TOP_REQUIRED, "file")
    for k in ("board", "book", "syllabus"):                  # book is optional
        if k in doc and not (isinstance(doc[k], str) and doc[k].strip()):
            r.error("file", f"{k} must be non-empty text", "C1")
    if "class" in doc and not (is_int(doc["class"]) and doc["class"] > 0):
        r.error("file", "class must be a positive whole number", "C1")
    if "status" in doc:
        r.warn("file", "status is ignored: a concept list is approved by the teacher typing "
                       "/exam-papers:approve concepts (the field can be deleted)", "C1")

    chapters = doc.get("chapters")
    if not (isinstance(chapters, dict) and chapters):
        r.error("file", "chapters must be a non-empty object keyed by chapter number", "C1")
        return r

    ids = syllabus_points(syllabus_text)
    if not ids:
        r.error("syllabus", "has no point ids like [S1]: number it with number_syllabus.py", "C5")
    elif ids != [f"S{i}" for i in range(1, len(ids) + 1)]:
        r.error("syllabus", "point ids must run S1, S2, ... once each, in order (number the teacher's "
                            "original again with number_syllabus.py)", "C5")
    seen_tags, covered = {}, {}
    for ch, entry in chapters.items():
        cloc = f"chapter {ch}"
        if not ch.isdigit():
            r.error(cloc, "chapter keys must be chapter numbers", "C1")
        if not isinstance(entry, dict):
            r.error(cloc, "must be an object", "C1")
            continue
        keys_ok(r, entry, CHAPTER_KEYS, CHAPTER_KEYS, cloc)
        if "title" in entry and not (isinstance(entry["title"], str) and entry["title"].strip()):
            r.error(cloc, "title must be non-empty text", "C1")
        concepts = entry.get("concepts")
        if not (isinstance(concepts, list) and concepts):
            r.error(cloc, "concepts must be a non-empty list", "C1")
            continue
        for i, c in enumerate(concepts, 1):
            loc = f"{cloc} concept #{i}"
            if not isinstance(c, dict):
                r.error(loc, "must be an object", "C1")
                continue
            tag = c.get("tag")
            if isinstance(tag, str):
                loc = f"{cloc} '{tag}'"
            keys_ok(r, c, CONCEPT_KEYS, CONCEPT_KEYS, loc)

            if "tag" in c:
                if not (isinstance(tag, str) and TAG_RE.match(tag)):
                    r.error(loc, f"tag {json.dumps(tag)} must be snake_case (a-z, 0-9, _)", "C2")
                elif tag in seen_tags:
                    r.error(loc, f"tag is also used in chapter {seen_tags[tag]}", "C2")
                else:
                    seen_tags[tag] = ch

            if "kinds" in c:
                k = c["kinds"]
                if not (isinstance(k, list) and k and all(x in Kind.values() for x in k)):
                    r.error(loc, f"kinds must be a non-empty list drawn from {sorted(Kind.values())}", "C3")
                elif len(set(k)) != len(k):
                    r.error(loc, "kinds lists the same kind twice", "C3")

            if "maxMarks" in c and not (is_num(c["maxMarks"]) and c["maxMarks"] > 0):
                r.error(loc, "maxMarks must be a positive number", "C4")

            if "source" in c:
                src = c["source"]
                if not isinstance(src, str) or src not in ids:
                    r.error(loc, f"source {json.dumps(src)} is not a point of the syllabus", "C5")
                else:
                    covered.setdefault(src, []).append(tag)

    not_tested = doc.get("notTested", {})
    if not isinstance(not_tested, dict):
        r.error("file", "notTested must be an object: {\"S7\": \"the reason\"}", "C1")
        not_tested = {}
    for pid, why in not_tested.items():
        if pid not in ids:
            r.error(f"notTested {pid}", "is not a point of the syllabus", "C5")
        elif not (isinstance(why, str) and why.strip()):
            r.error(f"notTested {pid}", "needs a reason", "C6")
        elif pid in covered:
            r.warn(f"notTested {pid}", f"also has concepts ({', '.join(covered[pid])})", "C6")
    for pid in dict.fromkeys(ids):
        if pid not in covered and pid not in not_tested:
            r.error(f"syllabus [{pid}]", "has no concept and is not listed in notTested (not covered)", "C6")

    by_ch = []
    for ch, entry in chapters.items():
        cs = entry.get("concepts") if isinstance(entry, dict) else None
        if isinstance(cs, list):
            n_num = sum(1 for c in cs if isinstance(c, dict) and Kind.NUMERICAL in (c.get("kinds") or []))
            by_ch.append(f"ch{ch} {len(cs)} ({n_num} numerical)")
    r.info.append("Concepts per chapter: " + ", ".join(by_ch))
    r.info.append(f"Syllabus points covered: {len(covered)} of {len(set(ids))}; not tested: "
                  + (", ".join(f"{p} ({w})" for p, w in not_tested.items()) or "none"))
    return r


def main(argv):
    args = [a for a in argv[1:] if a != "--json"]
    as_json = "--json" in argv
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    path = args[0]
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        spath = os.path.join(os.path.dirname(path), doc.get("syllabus", "") if isinstance(doc, dict) else "")
        with open(spath, encoding="utf-8") as f:
            text = f.read()
    except (OSError, ValueError) as e:
        print(f"Cannot read input: {e}")
        return 2
    r = validate(doc, text)
    if as_json:
        print(json.dumps({"valid": not r.errors, "errors": r.errors, "warnings": r.warnings,
                          "info": r.info}, indent=2, ensure_ascii=False))
    else:
        print(f"Concept list: {path}\nSyllabus:     {spath}")
        for title, items in (("ERRORS", r.errors), ("WARNINGS", r.warnings), ("INFO", r.info)):
            if items:
                print(f"\n{title}:")
                for m in items:
                    print(f"  - {m}")
        print("\nResult: " + ("VALID" if not r.errors else f"INVALID ({len(r.errors)} error(s))"))
    return 0 if not r.errors else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
