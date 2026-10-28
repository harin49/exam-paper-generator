"""Tests for skill/scripts/validate_concepts.py. Run from the project root:
    python3 -m unittest discover tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
import validate_concepts as vc  # noqa: E402

REF = os.path.join(ROOT, "skill", "references", "icse9-physics-selina")


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

    def test_syllabus_sections(self):
        ids, leaves = vc.syllabus_sections(self.syllabus)
        self.assertIn("3", ids)
        self.assertNotIn("3", leaves)          # has 3(i)...3(v)
        self.assertIn("2", leaves)             # no sub-sections
        self.assertEqual(len(leaves), 22)

    def test_duplicate_tag(self):
        self.doc["chapters"]["5"]["concepts"].append(dict(concept(self.doc, "pascals_law"), source="4(ii)"))
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
        concept(self.doc, "pascals_law")["source"] = "4(iii)"
        self.assertIn("[C5] chapter 4 'pascals_law': source \"4(iii)\" is not a section", self.errors())

    def test_heading_as_source(self):
        concept(self.doc, "newtons_first_law")["source"] = "3"
        self.assertIn("source 3 has sub-sections", self.errors())

    def test_uncovered_section(self):
        self.doc["chapters"]["8"]["concepts"] = [c for c in self.doc["chapters"]["8"]["concepts"]
                                                  if c["source"] != "7(ii)"]
        self.assertIn("[C6] syllabus [7(ii)]: has no concept (not covered)", self.errors())

    def test_unknown_field(self):
        concept(self.doc, "pascals_law")["level"] = "easy"
        self.assertIn("unknown field 'level'", self.errors())

    def test_draft_status_warns(self):
        self.doc["status"] = "draft"
        r = vc.validate(self.doc, self.syllabus)
        self.assertTrue(any("status is \"draft\"" in w for w in r.warnings))
        self.doc["status"] = "approved"
        self.assertEqual(vc.validate(self.doc, self.syllabus).warnings, [])


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
