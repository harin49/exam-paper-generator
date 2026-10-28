"""Tests for skill/scripts/next_step.py and skill/workflow.json. Run from the project root:
    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA, load_json  # noqa: E402
import next_step as ns  # noqa: E402
from render import output_names  # noqa: E402

STEPS = ns.read_workflow(ns.WORKFLOW)


class Workflow(unittest.TestCase):
    """The real skill/workflow.json."""

    def test_steps_are_in_skill_order(self):
        order = [tuple(int(n) for n in s["skillStep"].split(".")) for s in STEPS]
        self.assertEqual(order, sorted(order))
        self.assertEqual(STEPS[0]["id"], "new_paper")
        self.assertEqual(STEPS[-1]["done"], {"never": True})

    def test_every_script_it_names_exists(self):
        text = json.dumps(STEPS)
        scripts = set(re.findall(r"skill/scripts/\w+\.py", text))
        self.assertTrue(scripts)
        for s in scripts:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, s)), s)

    def test_approval_points_wait_for_the_user(self):
        waiting = [s["id"] for s in STEPS if s["waitsForUser"]]
        self.assertEqual(waiting, ["approve_blueprint", "decide_fixes"])
        self.assertTrue(all(STEPS[i]["by"] == "user" for i, s in enumerate(STEPS) if s["waitsForUser"]))

    def test_malformed_workflows_are_refused(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "w.json")
            for doc in ({}, {"steps": []}, {"steps": [{"id": "x"}]},
                        {"steps": [dict(STEPS[0]), dict(STEPS[0])]},
                        {"steps": [dict(STEPS[0], by="robot")]}):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f)
                with self.assertRaises(ns.WorkflowError, msg=doc):
                    ns.read_workflow(path)
        finally:
            shutil.rmtree(tmp)


class NextStep(unittest.TestCase):
    """Walks a task folder (the 21-mark test paper) through the workflow."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.task = os.path.join(self.tmp, "task")
        os.makedirs(os.path.join(self.task, "review"))
        self.clock = 1_700_000_000
        self.add("spec.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def add(self, name, content=None):
        """Write a file into the task folder, later than every file written before it."""
        path = os.path.join(self.task, name)
        if content is None:
            shutil.copy(os.path.join(TEST_DATA, name), path)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content if isinstance(content, str) else json.dumps(content))
        self.clock += 10
        os.utime(path, (self.clock, self.clock))

    def next_id(self):
        return ns.next_step(self.task, STEPS)[1]["id"]

    def ready_for_review(self):
        for name in ("concepts.json", "blueprint.json", "questions.json"):
            self.add(name)

    def first_review_round(self, compare="Result: NO MISMATCHES\n"):
        self.ready_for_review()
        self.add("review/solver-input.json", {})
        self.add("review/solver-answers.json", {})
        self.add("review/compare-output.txt", compare)
        self.add("review/reviewer-report.html", "<!doctype html>")

    def build_pdfs(self):
        for name in output_names(load_json(os.path.join(self.task, "spec.json"))):
            self.add(name, "%PDF")

    def test_missing_folder_starts_at_new_paper(self):
        done, step = ns.next_step(os.path.join(self.tmp, "nope"), STEPS)
        self.assertEqual((done, step["id"]), ([], "new_paper"))

    def test_valid_spec_goes_to_the_blueprint(self):
        self.assertEqual(self.next_id(), "make_blueprint")

    def test_invalid_spec_stays_on_validation(self):
        spec = load_json(os.path.join(TEST_DATA, "spec.json"))
        spec["pattern"]["totalMarks"] = 99
        self.add("spec.json", spec)
        self.assertEqual(self.next_id(), "validate_spec")

    def test_blueprint_older_than_the_spec_is_remade(self):
        self.add("blueprint.json")
        self.add("spec.json")
        self.assertEqual(self.next_id(), "make_blueprint")

    def test_draft_blueprint_waits_for_approval(self):
        bp = load_json(os.path.join(TEST_DATA, "blueprint.json"))
        bp["status"] = "draft"
        self.add("blueprint.json", bp)
        self.assertEqual(self.next_id(), "approve_blueprint")

    def test_approved_blueprint_goes_to_drafting(self):
        self.add("blueprint.json")
        self.assertEqual(self.next_id(), "draft_questions")

    def test_failing_questions_stay_on_the_check(self):
        self.add("concepts.json")
        self.add("blueprint.json")
        q = load_json(os.path.join(TEST_DATA, "questions.json"))
        q["questions"][0]["marks"] = 2
        self.add("questions.json", q)
        self.assertEqual(self.next_id(), "check_questions")

    def test_review_steps_run_in_order(self):
        self.ready_for_review()
        self.assertEqual(self.next_id(), "extract_paper")
        self.add("review/solver-input.json", {})
        self.assertEqual(self.next_id(), "blind_solver")
        self.add("review/solver-answers.json", {})
        self.assertEqual(self.next_id(), "compare_solutions")
        self.add("review/compare-output.txt", "Result: NO MISMATCHES\n")
        self.assertEqual(self.next_id(), "reviewer")
        self.add("review/reviewer-report.html", "<!doctype html>")
        self.assertEqual(self.next_id(), "decide_fixes")

    def test_the_build_waits_for_the_fix_decision(self):
        # The order this run went wrong in once: PDFs built while the review was unfinished.
        self.first_review_round()
        self.build_pdfs()
        self.assertEqual(self.next_id(), "decide_fixes")

    def test_no_fixes_accepted_goes_straight_to_the_build(self):
        self.first_review_round()
        self.add("review/fixes.json", {"accepted": [], "rejected": ["R1"]})
        self.assertEqual(self.next_id(), "render")
        self.build_pdfs()
        self.assertEqual(self.next_id(), "deliver")

    def test_accepted_fixes_send_the_paper_back_through_the_blind_solver(self):
        self.first_review_round()
        self.add("review/fixes.json", {"accepted": ["R1"], "rejected": []})
        self.assertEqual(self.next_id(), "apply_fixes")
        self.add("questions.json")                       # the fixes are applied
        self.assertEqual(self.next_id(), "extract_paper")
        self.add("review/solver-input.json", {})
        self.add("review/solver-answers.json", {})
        self.assertEqual(self.next_id(), "compare_solutions")
        self.add("review/compare-output.txt", "Result: NO MISMATCHES\n")
        self.assertEqual(self.next_id(), "render")        # the reviewer does not run again

    def test_mismatches_after_fixes_go_back_to_the_user(self):
        self.first_review_round()
        self.add("review/fixes.json", {"accepted": ["R1"], "rejected": []})
        self.add("questions.json")
        self.add("review/solver-input.json", {})
        self.add("review/solver-answers.json", {})
        self.add("review/compare-output.txt", "MISMATCHES:\n  - [V2] Q7(b)\n\nResult: 1 MISMATCH(ES)\n")
        self.assertEqual(self.next_id(), "decide_fixes")

    def test_editing_questions_after_the_build_needs_a_rebuild(self):
        self.first_review_round()
        self.add("review/fixes.json", {"accepted": [], "rejected": []})
        self.build_pdfs()
        self.add("questions.json")
        self.assertEqual(self.next_id(), "extract_paper")


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(TEST_DATA, "spec.json"), self.tmp)
        bp = load_json(os.path.join(TEST_DATA, "blueprint.json"))
        bp["status"] = "draft"
        with open(os.path.join(self.tmp, "blueprint.json"), "w", encoding="utf-8") as f:
            json.dump(bp, f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ns.main(["next_step.py", *args])
        return code, buf.getvalue()

    def test_text_names_one_step_and_says_to_stop_at_approvals(self):
        code, out = self.run_main(self.tmp)
        self.assertEqual(code, 0, out)
        self.assertIn("NEXT: step 2, approve_blueprint", out)
        self.assertIn("STOP after this step", out)
        self.assertEqual(out.count("NEXT:"), 1)
        self.assertIn(f"{self.tmp}/blueprint.json", out)        # TASK is filled in

    def test_json(self):
        code, out = self.run_main(self.tmp, "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["done"], ["new_paper", "validate_spec", "make_blueprint"])
        self.assertEqual(doc["next"]["id"], "approve_blueprint")
        self.assertTrue(doc["next"]["waitsForUser"])

    def test_bad_workflow_and_usage(self):
        path = os.path.join(self.tmp, "w.json")
        with open(path, "w") as f:
            f.write("{not json")
        self.assertEqual(self.run_main(self.tmp, "--workflow", path)[0], 2)
        self.assertEqual(self.run_main(self.tmp, "--workflow")[0], 2)
        self.assertEqual(self.run_main()[0], 2)


if __name__ == "__main__":
    unittest.main()
