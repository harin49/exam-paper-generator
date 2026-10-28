"""Tests for the make-paper skill's scripts/validate_paper_spec.py. Run from the project root:
    python3 -m unittest discover tests
"""
import copy
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA  # noqa: E402
import validate_paper_spec as v  # noqa: E402

TEMPLATE = os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "schemas", "paper-spec.template.json")
EXAMPLE = os.path.join(TEST_DATA, "spec.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ValidSpecs(unittest.TestCase):
    def test_template_is_valid(self):
        r = v.validate(load(TEMPLATE))
        self.assertEqual(r.errors, [])

    def test_example_is_valid(self):
        r = v.validate(load(EXAMPLE))
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, [])


class BrokenSpecs(unittest.TestCase):
    def setUp(self):
        self.spec = load(EXAMPLE)

    def errors(self):
        return " | ".join(v.validate(self.spec).errors)

    def sec(self, sid):
        return next(s for s in self.spec["pattern"]["sections"] if s["id"] == sid)

    def test_section_total_mismatch(self):
        self.sec("B")["sectionTotal"] = 21
        self.assertIn("sectionTotal is 21", self.errors())

    def test_sections_do_not_add_up(self):
        self.spec["pattern"]["totalMarks"] = 60
        self.assertIn("section totals add up to 21", self.errors())

    def test_attempt_more_than_offered(self):
        self.sec("C")["questionsToAttempt"] = 4
        self.sec("C")["sectionTotal"] = 24
        self.spec["pattern"]["totalMarks"] = 39
        self.assertIn("questionsToAttempt (4) is more than questionsOffered (3)", self.errors())

    def test_mcq_with_subparts(self):
        self.sec("A")["subParts"] = "allowed"
        self.assertIn("mcq section must have subParts 'none'", self.errors())

    def test_marks_not_multiple_of_smallest_unit(self):
        self.spec["pattern"]["smallestMarkUnit"] = 1
        self.sec("B")["marksPerQuestion"] = 2.5
        self.sec("B")["sectionTotal"] = 7.5
        self.spec["pattern"]["totalMarks"] = 19.5
        self.assertIn("not a multiple of smallestMarkUnit", self.errors())

    def test_too_many_required_subparts(self):
        self.sec("C")["minSubParts"] = 25
        self.assertIn("cannot be split into 25 parts", self.errors())

    def test_measure_on_attempted_rejected(self):
        self.spec["content"]["measureOn"] = "attempted"
        self.assertIn("'attempted' is not supported", self.errors())

    def test_split_must_add_to_100(self):
        self.spec["content"]["numericalTheorySplit"]["target"] = [60, 50]
        self.assertIn("must add up to 100", self.errors())

    def test_difficulty_keys(self):
        self.spec["content"]["difficulty"]["target"] = {"easy": 50, "medium": 50}
        self.assertIn("must have exactly the keys", self.errors())

    def test_too_few_compulsory_questions(self):
        a = self.sec("A")
        a["questionsOffered"] = a["questionsToAttempt"] = 2
        a["sectionTotal"] = 2
        self.spec["pattern"]["totalMarks"] = 17
        self.assertIn("only 2 questions for 3 chapters", self.errors())

    def test_custom_weights_missing_chapter(self):
        self.spec["content"]["chapterWeightage"] = {
            "mode": "custom", "toleranceMarks": 5,
            "weights": {"1": 50, "2": 50}}
        self.assertIn("no weight for chapter(s) [3]", self.errors())

    def test_syllabus_pack_is_required_and_well_formed(self):
        del self.spec["exam"]["syllabusPack"]
        self.assertIn("[S20] exam.syllabusPack: is required", self.errors())
        for bad in ("ICSE9-Physics", "icse9_physics", "icse9 physics", "", "-icse9"):
            self.spec["exam"]["syllabusPack"] = bad
            self.assertIn("[S20] exam.syllabusPack", self.errors(), bad)

    def test_missing_required_field(self):
        del self.spec["output"]["header"]
        self.assertIn("output.header: is required", self.errors())

    def test_unknown_field_is_a_warning(self):
        self.sec("A")["marksPerQuestoin"] = 1
        r = v.validate(self.spec)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("unknown field 'marksPerQuestoin'" in w for w in r.warnings))

    def test_tolerance_too_tight_is_a_warning(self):
        self.spec["content"]["chapterWeightage"]["toleranceMarks"] = 0
        r = v.validate(self.spec)
        self.assertEqual(r.errors, [])
        self.assertTrue(any("beyond the tolerance" in w for w in r.warnings))


class CommandLine(unittest.TestCase):
    def run_main(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write(text)
        try:
            return v.main(["validate_paper_spec.py", f.name, "--json"])
        finally:
            os.unlink(f.name)

    def test_exit_codes(self):
        good = json.dumps(load(EXAMPLE))
        bad = load(EXAMPLE)
        bad["pattern"]["totalMarks"] = 99
        self.assertEqual(self.run_main(good), 0)
        self.assertEqual(self.run_main(json.dumps(bad)), 1)
        self.assertEqual(self.run_main("{ not json"), 2)


if __name__ == "__main__":
    unittest.main()
