"""Tests for the make-paper skill's scripts/validate_concepts.py. Run from the project root:
    python3 -m unittest discover tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
import validate_concepts as vc  # noqa: E402

REF = os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "assets", "syllabi", "icse9-physics-selina")


def concept(doc, tag):
    for entry in doc["chapters"].values():
        for c in entry["concepts"]:
            if c["tag"] == tag:
                return c
    raise KeyError(tag)


class ConceptList(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REF, "concepts.json"), encoding="utf-8") as f:
            self.doc = json.load(f)
        with open(os.path.join(REF, "syllabus.md"), encoding="utf-8") as f:
            self.syllabus = f.read()

    def errors(self):
        return " | ".join(vc.validate(self.doc, self.syllabus).errors)

    def test_real_list_is_valid(self):
        self.assertEqual(vc.validate(self.doc, self.syllabus).errors, [])

    def test_syllabus_points(self):
        self.assertEqual(vc.syllabus_points(self.syllabus), [f"S{i}" for i in range(1, 54)])

    def test_points_must_run_in_order(self):
        self.syllabus = self.syllabus.replace("[S7]", "[S70]")
        self.assertIn("[C5] syllabus: point ids must run S1, S2, ... once each, in order", self.errors())

    def test_syllabus_without_points(self):
        r = vc.validate(self.doc, "## 1. Measurements\n\nSome text.\n")
        self.assertIn("has no point ids like [S1]", " | ".join(r.errors))

    def test_duplicate_tag(self):
        self.doc["chapters"]["5"]["concepts"].append(dict(concept(self.doc, "pascals_law"), source="S21"))
        self.assertIn("[C2] chapter 5 'pascals_law': tag is also used in chapter 4", self.errors())

    def test_tag_not_snake_case(self):
        concept(self.doc, "pascals_law")["tag"] = "Pascal's law"
        self.assertIn("must be snake_case", self.errors())

    def test_unknown_kind(self):
        concept(self.doc, "pascals_law")["kinds"] = ["practical"]
        self.assertIn("[C3] chapter 4 'pascals_law': kinds must be a non-empty list", self.errors())

    def test_repeated_kind(self):
        concept(self.doc, "pascals_law")["kinds"] = ["theory", "theory"]
        self.assertIn("kinds lists the same kind twice", self.errors())

    def test_bad_max_marks(self):
        concept(self.doc, "pascals_law")["maxMarks"] = 0
        self.assertIn("[C4] chapter 4 'pascals_law': maxMarks must be a positive number", self.errors())

    def test_unknown_source(self):
        concept(self.doc, "pascals_law")["source"] = "S99"
        self.assertIn("[C5] chapter 4 'pascals_law': source \"S99\" is not a point of the syllabus", self.errors())
        concept(self.doc, "pascals_law")["source"] = "4(ii)"                # an old-style section id
        self.assertIn("source \"4(ii)\" is not a point", self.errors())

    def test_uncovered_point(self):
        self.doc["chapters"]["7"]["concepts"] = [c for c in self.doc["chapters"]["7"]["concepts"]
                                                  if c["source"] != "S45"]
        self.assertIn("[C6] syllabus [S45]: has no concept and is not listed in notTested", self.errors())

    def test_not_tested_points(self):
        del self.doc["notTested"]["S53"]
        self.assertIn("[C6] syllabus [S53]: has no concept", self.errors())
        self.doc["notTested"]["S53"] = " "
        self.assertIn("[C6] notTested S53: needs a reason", self.errors())
        self.doc["notTested"]["S99"] = "x"
        self.assertIn("[C5] notTested S99: is not a point of the syllabus", self.errors())
        del self.doc["notTested"]["S99"]
        self.doc["notTested"]["S53"] = "A note."
        self.doc["notTested"]["S52"] = "Also listed."
        r = vc.validate(self.doc, self.syllabus)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("notTested S52: also has concepts (electromagnet_and_uses)" in w for w in r.warnings))
        self.doc["notTested"] = []
        self.assertIn("notTested must be an object", self.errors())

    def test_unknown_field(self):
        concept(self.doc, "pascals_law")["level"] = "easy"
        self.assertIn("unknown field 'level'", self.errors())

    def test_book_is_optional(self):
        del self.doc["book"]
        self.assertEqual(vc.validate(self.doc, self.syllabus).errors, [])

    def test_status_is_ignored_with_a_warning(self):
        self.assertEqual(vc.validate(self.doc, self.syllabus).warnings, [])
        self.doc["status"] = "approved"
        r = vc.validate(self.doc, self.syllabus)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("status is ignored" in w for w in r.warnings))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name in ("concepts.json", "syllabus.md"):
            shutil.copy(os.path.join(REF, name), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self):
        return vc.main(["validate_concepts.py", os.path.join(self.tmp, "concepts.json"), "--json"])

    def test_valid(self):
        self.assertEqual(self.run_main(), 0)

    def test_missing_syllabus(self):
        os.remove(os.path.join(self.tmp, "syllabus.md"))
        self.assertEqual(self.run_main(), 2)


if __name__ == "__main__":
    unittest.main()
