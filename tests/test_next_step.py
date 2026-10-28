"""Tests for the make-paper skill's scripts/next_step.py and workflow.json. Run from the project root:
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
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA, load_json  # noqa: E402
import next_step as ns  # noqa: E402
from render import output_names  # noqa: E402

STEPS = ns.read_workflow(ns.WORKFLOW)


class Workflow(unittest.TestCase):
    """The real workflow.json of the make-paper skill."""

    def test_steps_are_in_skill_order(self):
        order = [tuple(int(n) for n in s["skillStep"].split(".")) for s in STEPS]
        self.assertEqual(order, sorted(order))
        self.assertEqual(STEPS[0]["id"], "new_paper")
        self.assertEqual(STEPS[-1]["done"], {"never": True})

    def test_every_script_it_names_exists(self):
        text = json.dumps(STEPS)
        scripts = set(re.findall(r"scripts/\w+\.py", text))
        self.assertTrue(scripts)
        for s in scripts:
            self.assertTrue(os.path.isfile(os.path.join(ns.SKILL_DIR, s)), s)
        self.assertNotIn("skill/scripts", text)                 # the old repo-relative paths

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
                        {"steps": [dict(STEPS[0], by="robot")]},
                        {"steps": [dict(STEPS[0], done={"recorded": []})]},
                        {"steps": [dict(STEPS[0], outputs=["x"], done={"recorded": ["spec.json"]})]},
                        {"steps": [dict(STEPS[0], inputs="spec.json")]}):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(doc, f)
                with self.assertRaises(ns.WorkflowError, msg=doc):
                    ns.read_workflow(path)
        finally:
            shutil.rmtree(tmp)


class NextStep(unittest.TestCase):
    """Walks a task folder (the 21-mark test paper) through the workflow, recording each step as Claude would."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.task = os.path.join(self.tmp, "task")
        os.makedirs(os.path.join(self.task, "review"))
        self.add("spec.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def add(self, name, content=None):
        """Write a file into the task folder (a copy of the test data file when there is no content)."""
        path = os.path.join(self.task, name)
        if content is None:
            shutil.copy(os.path.join(TEST_DATA, name), path)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content if isinstance(content, str) else json.dumps(content))

    def edit(self, name):
        """Change a file's content without changing what it means."""
        with open(os.path.join(self.task, name), "a", encoding="utf-8") as f:
            f.write("\n")

    def done(self, step_id):
        self.assertIsNone(ns.record_done(self.task, STEPS, step_id))

    def next_id(self):
        return ns.next_step(self.task, STEPS)[1]["id"]

    def ready_for_review(self):
        self.add("concepts.json")
        self.add("blueprint.json")
        self.done("make_blueprint")
        self.add("questions.json")

    def review_round(self, compare="Result: NO MISMATCHES\n"):
        self.add("review/solver-input.json", {})
        self.done("extract_paper")
        self.add("review/solver-answers.json", {})
        self.done("blind_solver")
        self.add("review/compare-output.txt", compare)
        self.done("compare_solutions")

    def first_review_round(self, compare="Result: NO MISMATCHES\n"):
        self.ready_for_review()
        self.review_round(compare)
        self.add("review/reviewer-report.json", {})
        self.add("review/reviewer-report.html", "<!doctype html>")
        self.done("reviewer")

    def decide(self, accepted):
        self.add("review/fixes.json", {"accepted": accepted, "rejected": []})
        self.done("decide_fixes")

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

    def test_a_blueprint_that_was_not_recorded_is_not_done(self):
        self.add("blueprint.json")
        self.assertEqual(self.next_id(), "make_blueprint")

    def test_changing_the_spec_remakes_the_blueprint(self):
        self.add("blueprint.json")
        self.done("make_blueprint")
        self.edit("spec.json")
        self.assertEqual(self.next_id(), "make_blueprint")

    def test_draft_blueprint_waits_for_approval(self):
        bp = load_json(os.path.join(TEST_DATA, "blueprint.json"))
        bp["status"] = "draft"
        self.add("blueprint.json", bp)
        self.done("make_blueprint")
        self.assertEqual(self.next_id(), "approve_blueprint")

    def test_approving_the_blueprint_does_not_undo_making_it(self):
        # Approval changes blueprint.json, an output of make_blueprint: outputs need only exist.
        bp = load_json(os.path.join(TEST_DATA, "blueprint.json"))
        bp["status"] = "draft"
        self.add("blueprint.json", bp)
        self.done("make_blueprint")
        self.add("blueprint.json")
        self.assertEqual(self.next_id(), "draft_questions")

    def test_failing_questions_stay_on_the_check(self):
        self.add("concepts.json")
        self.add("blueprint.json")
        self.done("make_blueprint")
        q = load_json(os.path.join(TEST_DATA, "questions.json"))
        q["questions"][0]["marks"] = 2
        self.add("questions.json", q)
        self.assertEqual(self.next_id(), "check_questions")

    def test_review_steps_run_in_order(self):
        self.ready_for_review()
        self.assertEqual(self.next_id(), "extract_paper")
        self.add("review/solver-input.json", {})
        self.assertEqual(self.next_id(), "extract_paper")         # written but not recorded yet
        self.done("extract_paper")
        self.assertEqual(self.next_id(), "blind_solver")
        self.add("review/solver-answers.json", {})
        self.done("blind_solver")
        self.assertEqual(self.next_id(), "compare_solutions")
        self.add("review/compare-output.txt", "Result: NO MISMATCHES\n")
        self.done("compare_solutions")
        self.assertEqual(self.next_id(), "reviewer")
        self.add("review/reviewer-report.json", {})
        self.add("review/reviewer-report.html", "<!doctype html>")
        self.done("reviewer")
        self.assertEqual(self.next_id(), "decide_fixes")

    def test_file_times_do_not_matter(self):
        # A copy, a checkout or a re-save changes file times; only contents count.
        self.first_review_round()
        for root, _, files in os.walk(self.task):
            for f in files:
                os.utime(os.path.join(root, f), (1_000_000_000, 1_000_000_000))
        copy = os.path.join(self.tmp, "copy")
        shutil.copytree(self.task, copy)
        self.assertEqual(self.next_id(), "decide_fixes")
        self.assertEqual(ns.next_step(copy, STEPS)[1]["id"], "decide_fixes")

    def test_rewriting_the_review_html_unchanged_keeps_the_decision(self):
        # The bug that started D14: re-printing the findings sent a finished paper back to 5.5.
        self.first_review_round()
        self.decide([])
        self.add("review/reviewer-report.html", "<!doctype html>")
        self.assertEqual(self.next_id(), "render")

    def test_the_build_waits_for_the_fix_decision(self):
        # The order this run went wrong in once: PDFs built while the review was unfinished.
        self.first_review_round()
        self.build_pdfs()
        self.assertEqual(self.next_id(), "decide_fixes")
        self.assertIn("decide_fixes", ns.record_done(self.task, STEPS, "render"))

    def test_no_fixes_accepted_goes_straight_to_the_build(self):
        self.first_review_round()
        self.decide([])
        self.assertEqual(self.next_id(), "render")
        self.build_pdfs()
        self.done("render")
        self.assertEqual(self.next_id(), "deliver")

    def test_accepted_fixes_send_the_paper_back_through_the_blind_solver(self):
        self.first_review_round()
        self.decide(["R1"])
        self.assertEqual(self.next_id(), "apply_fixes")
        self.edit("questions.json")                           # the fixes are applied
        self.done("apply_fixes")
        self.assertEqual(self.next_id(), "extract_paper")
        self.review_round()
        self.assertEqual(self.next_id(), "render")             # the reviewer does not run again

    def test_mismatches_after_fixes_go_back_to_the_user(self):
        self.first_review_round()
        self.decide(["R1"])
        self.edit("questions.json")
        self.done("apply_fixes")
        self.review_round("MISMATCHES:\n  - [V2] Q7(b)\n\nResult: 1 MISMATCH(ES)\n")
        self.assertEqual(self.next_id(), "decide_fixes")

    def test_editing_questions_by_hand_after_fixes_does_not_apply_them_again(self):
        self.first_review_round()
        self.decide(["R1"])
        self.edit("questions.json")
        self.done("apply_fixes")
        self.review_round()
        self.edit("questions.json")                           # the teacher's own edit
        self.assertEqual(self.next_id(), "extract_paper")
        self.review_round()
        self.assertEqual(self.next_id(), "render")

    def test_editing_questions_after_the_build_needs_a_rebuild(self):
        self.first_review_round()
        self.decide([])
        self.build_pdfs()
        self.done("render")
        self.edit("questions.json")
        self.assertEqual(self.next_id(), "extract_paper")


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(TEST_DATA, "spec.json"), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_records_hashes_in_state_and_appends_to_the_run_log(self):
        shutil.copy(os.path.join(TEST_DATA, "blueprint.json"), self.tmp)
        self.assertIsNone(ns.record_done(self.tmp, STEPS, "make_blueprint"))
        self.assertIsNone(ns.record_done(self.tmp, STEPS, "make_blueprint"))
        state = load_json(os.path.join(self.tmp, "state.json"))
        record = state["steps"]["make_blueprint"]
        self.assertEqual(record["inputs"], {"spec.json": ns.file_hash(os.path.join(self.tmp, "spec.json"))})
        self.assertEqual(set(record["outputs"]), {"blueprint.json"})
        with open(os.path.join(self.tmp, "run.jsonl"), encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        self.assertEqual([(x["event"], x["step"]) for x in lines], [("done", "make_blueprint")] * 2)

    def test_refuses_a_step_with_a_missing_output(self):
        error = ns.record_done(self.tmp, STEPS, "make_blueprint")
        self.assertIn("blueprint.json missing", error)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "state.json")))

    def test_refuses_a_step_while_an_earlier_one_is_not_done(self):
        os.makedirs(os.path.join(self.tmp, "review"))
        with open(os.path.join(self.tmp, "review", "solver-answers.json"), "w") as f:
            f.write("{}")
        self.assertIn("make_blueprint", ns.record_done(self.tmp, STEPS, "blind_solver"))

    def test_refuses_an_unknown_step_and_a_missing_folder(self):
        self.assertIn("no step", ns.record_done(self.tmp, STEPS, "nope"))
        self.assertIn("no task folder", ns.record_done(os.path.join(self.tmp, "x"), STEPS, "new_paper"))

    def test_a_broken_state_file_is_an_error(self):
        with open(os.path.join(self.tmp, "state.json"), "w") as f:
            f.write("[]")
        with self.assertRaises(ns.WorkflowError):
            ns.next_step(self.tmp, STEPS)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(TEST_DATA, "spec.json"), self.tmp)
        bp = load_json(os.path.join(TEST_DATA, "blueprint.json"))
        bp["status"] = "draft"
        with open(os.path.join(self.tmp, "blueprint.json"), "w", encoding="utf-8") as f:
            json.dump(bp, f)
        ns.record_done(self.tmp, STEPS, "make_blueprint")

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
        self.assertIn(f"next_step.py\" {self.tmp} --done approve_blueprint", out)

    def test_done(self):
        code, out = self.run_main(self.tmp, "--done", "approve_blueprint")
        self.assertEqual(code, 1, out)                          # still a draft: not done...
        self.assertIn("Not recorded", out)
        bp = load_json(os.path.join(self.tmp, "blueprint.json"))
        bp["status"] = "approved"                               # ...until the user approves it
        with open(os.path.join(self.tmp, "blueprint.json"), "w", encoding="utf-8") as f:
            json.dump(bp, f)
        self.assertEqual(self.run_main(self.tmp, "--done", "approve_blueprint")[0], 0)
        code, out = self.run_main(self.tmp, "--done", "nope")
        self.assertEqual(code, 1)
        self.assertEqual(self.run_main(self.tmp, "--done")[0], 2)

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
