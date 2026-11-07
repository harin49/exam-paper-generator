"""Tests for the make-paper skill's scripts/make_blueprint.py. Run from the project root:
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
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
import make_blueprint as mb  # noqa: E402
from approvals import is_approved, record_approval  # noqa: E402

# The real (frozen) concept list, because these tests need all ten book chapters, and a full-size
# 50-mark spec kept as test data, because they test the generator at the scale of a real paper.
REF = os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "assets", "syllabi", "icse9-physics-selina")
SPEC = os.path.join(ROOT, "tests", "test_data", "spec-50-marks.json")
TEMPLATE = os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "schemas", "paper-spec.template.json")


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
        # 15 and 21 marks cannot split 50/50, so A and B come as close as one mark allows
        self.assertIn("Difficulty, section A: easy 53.3% (target 50%), medium 46.7% (target 50%)", info)
        self.assertIn("Difficulty, section B: easy 52.4% (target 50%), medium 47.6% (target 50%)", info)
        self.assertIn("Difficulty, section C: easy 50.0% (target 50%), medium 50.0% (target 50%)", info)

    def test_each_section_gets_its_own_difficulty(self):
        spec = load(TEMPLATE)
        qs, r = self.build(spec)
        self.assertEqual(r.errors, [])
        self.assertEqual([w for w in r.warnings if w.startswith("[Q13]")], [])
        hard = {q["section"] for q, leaf in leaves(qs) if leaf["difficulty"] == "hard"}
        self.assertEqual(hard, {"C"})       # only section C's target allows hard

    def test_deterministic(self):
        a, _ = self.build()
        b, _ = self.build(copy.deepcopy(self.spec))
        self.assertEqual(json.dumps(a), json.dumps(b))

    def test_mcq_correct_options_spread_evenly(self):
        qs, _ = self.build()
        mcq_ids = {s["id"] for s in self.spec["pattern"]["sections"] if s["type"] == "mcq"}
        letters = [x["correctOption"] for x in qs if x["section"] in mcq_ids]
        self.assertEqual(len(letters), 15)
        counts = [letters.count(c) for c in "abcd"]
        self.assertLessEqual(max(counts) - min(counts), 1)
        runs = [letters[i] == letters[i + 1] == letters[i + 2] for i in range(len(letters) - 2)]
        self.assertFalse(any(runs), f"three in a row: {''.join(letters)}")
        self.assertTrue(all("correctOption" not in x for x in qs if x["section"] not in mcq_ids))

    def test_easier_parts_come_first(self):
        qs, _ = self.build()
        rank = {"easy": 0, "medium": 1, "hard": 2}
        for q in qs:
            levels = [rank[p["difficulty"]] for p in q.get("parts", [])]
            self.assertEqual(levels, sorted(levels), f"Q{q['number']}")
            if "parts" in q:
                self.assertEqual(sum(p["marks"] for p in q["parts"]), q["marks"])

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

    PENDULUM = ["simple_pendulum_terms", "pendulum_frequency", "pendulum_time_period_formula",
                "pendulum_l_t2_graph"]

    def test_excluded_concepts_are_never_used(self):
        self.spec["content"]["excludedConcepts"] = self.PENDULUM
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        self.assertFalse({leaf["concept"] for _, leaf in leaves(qs)} & set(self.PENDULUM))
        self.assertTrue(any(q["chapter"] == 1 for q in qs))      # chapter 1 keeps its other concepts

    def test_excluded_concept_not_in_the_paper(self):
        self.spec["content"]["excludedConcepts"] = ["neutral_points", "pendulm_frequency"]
        _, r = self.build()
        self.assertIn("blueprint: content.excludedConcepts names neutral_points, pendulm_frequency: "
                      "not a concept in the paper's chapters [1, 2, 3, 4, 5]", r.errors[0])

    def test_excluding_a_whole_chapter(self):
        self.spec["content"]["excludedConcepts"] = [c["tag"] for c in self.concepts["chapters"]["1"]["concepts"]]
        _, r = self.build()
        self.assertIn("leaves out every concept in chapter 1", r.errors[0])

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
        self.spec["exam"]["chapters"] = [5]               # Heat and Energy: one numerical concept
        qs, r = self.build()
        self.assertEqual(r.errors, [])
        self.assertTrue(any(w.startswith("[Q12]") for w in r.warnings))   # can't reach 50% numerical

    def test_concept_list_for_other_board(self):
        self.concepts["board"] = "CBSE"
        _, r = self.build()
        self.assertIn("conceptList: is for board \"CBSE\"", " | ".join(r.errors))

    def test_book_compared_only_when_both_name_one(self):
        del self.spec["exam"]["book"]
        self.assertEqual(self.build()[1].errors, [])
        self.spec["exam"]["book"] = "Another Book"
        self.assertIn("conceptList: is for book", " | ".join(self.build()[1].errors))
        del self.concepts["book"]
        self.assertEqual(self.build()[1].errors, [])

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
        # A copy of the sample pack, approved as the teacher would with /exam-papers:approve concepts.
        self.pack = os.path.join(self.tmp, "syllabi", "icse9-physics-selina")
        shutil.copytree(REF, self.pack)
        record_approval(self.pack, "concepts", "/exam-papers:approve concepts")
        self.concepts = os.path.join(self.pack, "concepts.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *extra):
        return mb.main(["make_blueprint.py", self.spec, "--concepts", self.concepts, "--json", *extra])

    def test_finds_the_specs_pack_above_its_folder(self):
        # The workspace layout: syllabi/<pack>/ and papers/<task>/spec.json side by side.
        task = os.path.join(self.tmp, "papers", "icse-9-physics")
        os.makedirs(task)
        spec = os.path.join(task, "spec.json")
        shutil.copy(SPEC, spec)
        self.assertEqual(mb.find_concept_list(spec, load(spec)), self.concepts)
        self.assertEqual(mb.main(["make_blueprint.py", spec, "--json"]), 0)
        self.assertEqual(load(os.path.join(task, "blueprint.json"))["conceptList"],
                         "../../syllabi/icse9-physics-selina/concepts.json")

    def test_a_missing_pack_is_a_read_error(self):
        doc = load(SPEC)
        doc["exam"]["syllabusPack"] = "cbse10-maths-none"
        with open(self.spec, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        self.assertEqual(mb.main(["make_blueprint.py", self.spec]), 2)
        self.assertIsNone(mb.find_concept_list(self.spec, doc))

    def test_records_its_own_step_in_a_task_folder(self):
        self.assertEqual(self.run_main(), 0)
        state = load(os.path.join(self.dir, "state.json"))
        self.assertIn("make_blueprint", state["steps"])

    def test_an_unapproved_concept_list_is_refused(self):
        os.remove(os.path.join(self.pack, "approvals.json"))
        self.assertEqual(self.run_main(), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_editing_an_approved_concept_list_voids_its_approval(self):
        with open(self.concepts, "a", encoding="utf-8") as f:
            f.write("\n")
        self.assertEqual(self.run_main(), 1)

    def test_writes_draft_with_relative_paths(self):
        self.assertEqual(self.run_main(), 0)
        doc = load(self.out)
        self.assertNotIn("status", doc)                 # approval lives in approvals.json
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
        record_approval(self.dir, "blueprint", "/exam-papers:approve blueprint")
        self.assertEqual(self.run_main(), 1)
        self.assertTrue(is_approved(self.dir, "blueprint"))
        self.assertEqual(self.run_main("--force"), 0)

    def test_overwrites_a_blueprint_edited_after_approval(self):
        self.run_main()
        record_approval(self.dir, "blueprint", "/exam-papers:approve blueprint")
        with open(self.out, "a", encoding="utf-8") as f:
            f.write("\n")
        self.assertEqual(self.run_main(), 0)

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
