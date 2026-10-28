"""Tests for the make-paper skill's scripts/number_syllabus.py. Run from the project root:
    python3 -m unittest discover tests
"""
import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
import number_syllabus as ns  # noqa: E402

TEXT = """# Civics

## 1. Elections

Meaning; Composition and functions of Election Commission;
Direct and Indirect election.

- General election
- Mid-term election and By-election

1. Unicameral and Bicameral Legislatures
"""


class Number(unittest.TestCase):
    def test_paragraphs_and_list_items_are_points(self):
        out, points = ns.number(TEXT)
        self.assertEqual([p for p, _ in points], ["S1", "S2", "S3", "S4"])
        self.assertEqual(points[0][1], "Meaning; Composition and functions of Election Commission; "
                                       "Direct and Indirect election.")
        self.assertIn("[S1] Meaning; Composition", out)
        self.assertIn("- [S2] General election\n- [S3] Mid-term election", out)
        self.assertIn("1. [S4] Unicameral", out)
        self.assertIn("## 1. Elections\n", out)                      # headings are not points

    def test_only_ids_are_added(self):
        out, _ = ns.number(TEXT)
        self.assertEqual(re.sub(r"\[S\d+\] ", "", out), TEXT)

    def test_plain_lines_without_blank_lines_are_one_point(self):
        _, points = ns.number("Topic one\nTopic two\n")
        self.assertEqual(len(points), 1)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src, self.out = os.path.join(self.tmp, "original.md"), os.path.join(self.tmp, "syllabus.md")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(TEXT)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ns.main(["number_syllabus.py", *args])
        return code, buf.getvalue()

    def test_writes_and_lists_the_points(self):
        code, out = self.run_main(self.src, self.out)
        self.assertEqual(code, 0, out)
        self.assertIn("4 points", out)
        self.assertIn("[S2] General election", out)
        with open(self.src, encoding="utf-8") as f:
            self.assertEqual(f.read(), TEXT)                           # the teacher's file is untouched

    def test_refuses_to_overwrite_or_renumber(self):
        self.run_main(self.src, self.out)
        self.assertEqual(self.run_main(self.src, self.out)[0], 1)
        self.assertEqual(self.run_main(self.src, self.out, "--force")[0], 0)
        code, out = self.run_main(self.out, os.path.join(self.tmp, "again.md"))
        self.assertEqual(code, 1)
        self.assertIn("already has point ids", out)

    def test_long_points_are_reported(self):
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("word " * 130)
        code, out = self.run_main(self.src, self.out)
        self.assertEqual(code, 0)
        self.assertIn("Long points (over 120 words)", out)

    def test_usage_and_missing_file(self):
        self.assertEqual(self.run_main(self.src)[0], 2)
        self.assertEqual(self.run_main(os.path.join(self.tmp, "nope.md"), self.out)[0], 2)


if __name__ == "__main__":
    unittest.main()
