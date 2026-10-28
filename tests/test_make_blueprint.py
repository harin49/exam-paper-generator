"""Tests for skill/scripts/make_blueprint.py. Run from the project root:
    python3 -m unittest discover tests
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
import make_blueprint as mb  # noqa: E402

# The real (frozen) concept list, because these tests need all ten book chapters, and a full-size
# 50-mark spec kept as test data, because they test the generator at the scale of a real paper.
REF = os.path.join(ROOT, "skill", "references", "icse9-physics-selina")
SPEC = os.path.join(ROOT, "tests", "test_data", "spec-50-marks.json")
TEMPLATE = os.path.join(ROOT, "skill", "schemas", "paper-spec.template.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def leaves(questions):
    for q in questions:
        if "parts" in q:
            for p in q["parts"]:
                yield q, p
        else:
            yield q, q


class Blueprint(unittest.TestCase):
    def setUp(self):
        self.spec = load(SPEC)
        self.concepts = load(os.path.join(REF, "concepts.json"))
        with open(os.path.join(REF, "syllabus.md"), encoding="utf-8") as f:
            self.syllabus = f.read()

    def build(self, spec=None):
        return mb.build(spec or self.spec, self.concepts, self.syllabus)

    def test_example_spec_builds_cleanly(self):
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        rules = {w.split("]")[0] + "]" for w in r.warnings if w.startswith("[Q")}
        self.assertEqual(rules - {"[Q14]"}, set())      # only possible overlaps are flagged
        self.assertEqual(len(qs), 26)

    def test_hits_targets_exactly(self):
        _, r = self.build()
        info = " | ".join(r.info)
        self.assertIn("Numerical/theory: 50.0% / 50.0%", info)
        self.assertIn("easy 50.0% (target 50%), medium 50.0% (target 50%)", info)

    def test_deterministic(self):
        a, _ = self.build()
        b, _ = self.build(copy.deepcopy(self.spec))
        self.assertEqual(json.dumps(a), json.dumps(b))

    def test_respects_syllabus_kinds(self):
        qs, _ = self.build()
        theory_only = {c["tag"] for e in self.concepts["chapters"].values() for c in e["concepts"]
                       if c["kinds"] == ["theory"]}
        for q, leaf in leaves(qs):
            if leaf["concept"] in theory_only:
                self.assertEqual(leaf["kind"], "theory", f"Q{q['number']} {leaf['concept']}")
        self.assertFalse(any(leaf["kind"] == "numerical" and leaf["concept"] in ("vernier_callipers", "screw_gauge")
                             for _, leaf in leaves(qs)))

    def test_respects_max_marks(self):
        qs, _ = self.build()
        max_marks = {c["tag"]: c["maxMarks"] for e in self.concepts["chapters"].values() for c in e["concepts"]}
        for q, leaf in leaves(qs):
            self.assertLessEqual(leaf["marks"], max_marks[leaf["concept"]])

    def test_every_section_has_numerical_and_theory(self):
        qs, _ = self.build()
        for sid in ("A", "B", "C"):
            kinds = {leaf["kind"] for q, leaf in leaves(qs) if q["section"] == sid}
            self.assertEqual(kinds, {"numerical", "theory"}, sid)

    def test_every_chapter_in_compulsory_section(self):
        qs, _ = self.build()
        self.assertEqual({q["chapter"] for q in qs if q["section"] == "A"}, {1, 2, 3, 4, 5})

    def test_template_spec(self):
        qs, r = self.build(load(TEMPLATE))
        self.assertEqual(r.errors, [])
        self.assertEqual(sum(1 for q in qs if q["section"] == "C"), 4)

    def test_per_section_numbering(self):
        self.spec["pattern"]["numbering"] = "per_section"
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        self.assertEqual([q["number"] for q in qs if q["section"] == "B"], list(range(1, 8)))

    def test_section_without_subparts(self):
        b = next(s for s in self.spec["pattern"]["sections"] if s["id"] == "B")
        b["subParts"] = "none"
        del b["maxSubParts"]
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        for q in qs:
            if q["section"] == "B":
                self.assertEqual([p["label"] for p in q["parts"]], [""])

    def test_long_questions_have_enough_parts(self):
        qs, _ = self.build()
        for q in qs:
            if q["section"] == "C":
                self.assertGreaterEqual(len(q["parts"]), 3)
                self.assertEqual(sum(p["marks"] for p in q["parts"]), 10)

    def test_mostly_theory_chapters_still_build(self):
        self.spec["exam"]["chapters"] = [6, 10]
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        self.assertTrue(any(w.startswith("[Q12]") for w in r.warnings))   # can't reach 50% numerical

    def test_concept_list_for_other_board(self):
        self.concepts["board"] = "CBSE"
        _, r = self.build()
        self.assertIn("conceptList: is for board \"CBSE\"", " | ".join(r.errors))

    def test_chapter_missing_from_concept_list(self):
        del self.concepts["chapters"]["5"]
        _, r = self.build()
        self.assertTrue(r.errors)

    def test_invalid_spec(self):
        self.spec["pattern"]["totalMarks"] = 99
        qs, r = self.build()
        self.assertIsNone(qs)
        self.assertIn("spec: [S7]", " | ".join(r.errors))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "paper")
        os.makedirs(self.dir)
        self.spec = os.path.join(self.dir, "spec.json")
        shutil.copy(SPEC, self.spec)
        self.out = os.path.join(self.dir, "blueprint.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *extra):
        return mb.main(["make_blueprint.py", self.spec, "--concepts", os.path.join(REF, "concepts.json"),
                        "--json", *extra])

    def test_writes_draft_with_relative_paths(self):
        self.assertEqual(self.run_main(), 0)
        doc = load(self.out)
        self.assertEqual(doc["status"], "draft")
        self.assertEqual(doc["spec"], "spec.json")
        self.assertTrue(os.path.exists(os.path.join(self.dir, doc["conceptList"])))

    def test_relative_paths_resolve_through_a_symlinked_folder(self):
        real = os.path.join(self.tmp, "real", "a", "b")
        os.makedirs(real)
        link = os.path.join(self.tmp, "link")
        os.symlink(real, link)
        self.dir = os.path.join(link, "paper")
        os.makedirs(self.dir)
        self.spec = os.path.join(self.dir, "spec.json")
        shutil.copy(SPEC, self.spec)
        self.out = os.path.join(self.dir, "blueprint.json")
        self.assertEqual(self.run_main(), 0)
        doc = load(self.out)
        self.assertEqual(doc["spec"], "spec.json")
        self.assertTrue(os.path.exists(os.path.join(self.dir, doc["conceptList"])))

    def test_will_not_overwrite_approved(self):
        self.run_main()
        doc = load(self.out)
        doc["status"] = "approved"
        with open(self.out, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(load(self.out)["status"], "approved")
        self.assertEqual(self.run_main("--force"), 0)
        self.assertEqual(load(self.out)["status"], "draft")

    def test_missing_concept_list(self):
        rc = mb.main(["make_blueprint.py", self.spec, "--concepts", os.path.join(self.tmp, "nope.json")])
        self.assertEqual(rc, 2)

    def test_concept_list_without_syllabus_field_is_refused(self):
        doc = load(os.path.join(REF, "concepts.json"))
        del doc["syllabus"]
        bad = os.path.join(self.tmp, "concepts-no-syllabus.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        rc = mb.main(["make_blueprint.py", self.spec, "--concepts", bad])
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
