#!/usr/bin/env python3
"""Start a new paper: make its task folder under papers/ and put a copy of the spec in it.

Usage:
    python3 new_paper.py SPEC.json [--root DIR] [--date YYYY-MM-DD]

Creates DIR/papers/ if it does not exist (DIR defaults to the current folder, which should be the
teacher's workspace folder), then a new folder named board-class-subject-date, for example
    papers/icse-9-physics-2026-10-27/
and copies SPEC.json into it as spec.json. The date is today's unless --date is given. If that folder
already exists, -2, -3, ... is added to the name: an existing task folder is never reused or
overwritten. Prints the new folder's path.

Everything for the paper then goes in that folder: blueprint.json, questions.json, diagram images,
review/ and the two PDFs. To carry on with an earlier paper, use its existing folder instead of
running this again.

Exit codes: 0 folder made, 2 the spec could not be read or lacks exam.board/class/subject.
"""
import datetime
import json
import os
import re
import shutil
import sys


def slug(text):
    """'Computer Science' -> 'computer-science'."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def task_name(spec, date):
    ex = spec["exam"]
    parts = [slug(ex["board"]), slug(ex["class"]), slug(ex["subject"]), date]
    if not all(parts):
        raise ValueError("exam.board, exam.class and exam.subject must not be empty")
    return "-".join(parts)


def make_folder(output_dir, name):
    """Create output_dir/name (or name-2, name-3, ...) and return its path."""
    os.makedirs(output_dir, exist_ok=True)
    n = 1
    while True:
        folder = os.path.join(output_dir, name if n == 1 else f"{name}-{n}")
        try:
            os.mkdir(folder)
            return folder
        except FileExistsError:
            n += 1


def main(argv):
    args = argv[1:]
    opts = {}
    for flag in ("--root", "--date"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                print(f"{flag} needs a value")
                return 2
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1:
        print(__doc__.strip())
        return 2
    date = opts.get("--date") or datetime.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        print(f"--date must look like 2026-10-27, not {date!r}")
        return 2
    try:
        with open(args[0], encoding="utf-8") as f:
            spec = json.load(f)
        name = task_name(spec, date)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Cannot read the spec: {e}")
        return 2
    folder = make_folder(os.path.join(opts.get("--root", "."), "papers"), name)
    shutil.copyfile(args[0], os.path.join(folder, "spec.json"))
    print(folder)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
