#!/usr/bin/env python3
"""Give every point of a syllabus a unique id, [S1], [S2], ..., for the concept list to point to.

Usage:
    python3 number_syllabus.py SYLLABUS OUT [--force]

SYLLABUS is the teacher's syllabus (Markdown or plain text), which is not changed. OUT (usually
syllabi/<pack>/syllabus.md; its folder is made if needed) gets the same
text with "[Sn] " inserted at the start of each point, in order. A point is a paragraph (lines between
blank lines) or a list item ("- ", "* ", "+ " or "1. " at a line start); headings ("#" lines) are not
points. Nothing else is changed, so OUT minus its ids is the teacher's text.

Every concept's "source" in concepts.json is one of these ids, and validate_concepts.py checks that
every point has a concept (C6). A point longer than LONG words is reported: if the syllabus runs
several topics together without blank lines, add blank lines between them in SYLLABUS and run this
again, so each point is one topic.

Refuses (exit 1) if SYLLABUS already has [Sn] ids, or if OUT exists and --force is not given.

Exit codes: 0 written, 1 refused, 2 a file could not be read or written.
"""
import os
import re
import sys

POINT_ID = re.compile(r"\[S\d+\]")
LIST_ITEM = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)")
HEADING = re.compile(r"^\s*#")
LONG = 120


def number(text):
    """(the numbered text, [(id, the point's text)])."""
    out, points, starts_point = [], [], True
    for line in text.split("\n"):
        if not line.strip():
            out.append(line)
            starts_point = True
            continue
        if HEADING.match(line):
            out.append(line)
            starts_point = True
            continue
        item = LIST_ITEM.match(line)
        if starts_point or item:
            pid = f"S{len(points) + 1}"
            lead = item.group(1) if item else re.match(r"^\s*", line).group(0)
            out.append(f"{lead}[{pid}] {line[len(lead):]}")
            points.append([pid, line[len(lead):].strip()])
            starts_point = False
        else:
            out.append(line)
            points[-1][1] += " " + line.strip()
    return "\n".join(out), [tuple(p) for p in points]


def main(argv):
    args = [a for a in argv[1:] if a != "--force"]
    if len(args) != 2:
        print(__doc__.strip())
        return 2
    src, out = args
    try:
        with open(src, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"Cannot read input: {e}")
        return 2
    if POINT_ID.search(text):
        print(f"{src} already has point ids like [S1]; number the teacher's original instead.")
        return 1
    if os.path.exists(out) and "--force" not in argv:
        print(f"{out} exists; not overwriting it (use --force to replace it).")
        return 1
    numbered, points = number(text)
    if not points:
        print(f"{src} has no text to number.")
        return 1
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(numbered)
    except OSError as e:
        print(f"Cannot write {out}: {e}")
        return 2
    print(f"Wrote {out}: {len(points)} points.")
    long_points = [(pid, len(t.split())) for pid, t in points if len(t.split()) > LONG]
    for pid, t in points:
        print(f"  [{pid}] {t[:90]}{'...' if len(t) > 90 else ''}")
    if long_points:
        print(f"\nLong points (over {LONG} words), which may run several topics together: "
              + ", ".join(f"{pid} ({n} words)" for pid, n in long_points))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
