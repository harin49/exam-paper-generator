"""Tests for the make-paper skill's scripts/review_status.py. Run from the project root:
    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA, load_json  # noqa: E402
import review_status as rs  # noqa: E402
from task_files import file_hash  # noqa: E402


def finding(rid, severity="error", status="open", **extra):
    return dict({"id": rid, "severity": severity, "status": status, "location": "Q12(b)",
                 "problem": "p", "evidence": "e", "suggestedFix": "f"}, **extra)


class Task(unittest.TestCase):
    def setUp(self):
        self.task = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.task, "review"))
        shutil.copy(os.path.join(TEST_DATA, "questions.json"), self.task)

    def tearDown(self):
        shutil.rmtree(self.task)

    def write(self, name, doc):
        with open(os.path.join(self.task, name), "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def report(self, *findings):
        self.write("review/reviewer-report.json", {"findings": list(findings)})

    def close(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rs.close_round(self.task)
        return code, buf.getvalue()

    def decide(self, rnd, accepted=(), rejected=()):
        path = os.path.join(self.task, "review", "decisions.json")
        doc = load_json(path) if os.path.isfile(path) else {"decisions": []}
        doc["decisions"].append({"round": rnd, "report": "x", "accepted": list(accepted),
                                 "rejected": list(rejected)})
        self.write("review/decisions.json", doc)

    def revise(self, text):
        """The writer changes the questions (a new round will follow)."""
        q = load_json(os.path.join(self.task, "questions.json"))
        q["questions"][0]["text"] = text
        self.write("questions.json", q)

    def state(self):
        return rs.status(self.task)


class Status(Task):
    def test_an_unclosed_report_must_be_closed_first(self):
        self.report(finding("R1"))
        self.assertEqual(self.state()["next"], "close")
        self.assertEqual(self.close()[0], 0)
        self.assertEqual(self.state()["round"], 1)
        self.assertEqual(self.state()["next"], "revise")

    def test_errors_are_revised_and_warnings_decided_first(self):
        self.report(finding("R1"), finding("R2", "warning"), finding("R3", "suggestion"))
        self.close()
        s = self.state()
        self.assertEqual((s["next"], s["toDecide"], s["toAddress"]), ("decide", ["R2", "R3"], ["R1"]))
        self.decide(1, accepted=["R2"], rejected=["R3"])
        s = self.state()
        self.assertEqual((s["next"], s["toAddress"], s["rejected"]), ("revise", ["R1", "R2"], ["R3"]))

    def test_nothing_open_is_done(self):
        self.report(finding("R1", status="resolved"), finding("R2", "suggestion"))
        self.close()
        self.decide(1, rejected=["R2"])
        self.assertEqual(self.state()["next"], "done")

    def test_a_rejected_finding_stays_closed_even_if_reopened(self):
        self.report(finding("R1", "warning"))
        self.close()
        self.decide(1, rejected=["R1"])
        self.revise("Changed.")
        self.report(finding("R1", "warning", note="Still unclear."))
        self.close()
        self.assertEqual(self.state()["next"], "done")

    def test_the_cap_turns_open_findings_into_disputes(self):
        self.report(finding("R1"), finding("R2", "warning"))
        self.close()
        self.decide(1, accepted=["R2"])
        for text in ("two", "three"):
            self.revise(text)
            self.close()
        s = self.state()
        self.assertEqual((s["round"], s["next"], s["disputes"], s["toAddress"]), (3, "decide", ["R1", "R2"], []))
        self.decide(3, accepted=["R1"], rejected=["R2"])
        s = self.state()
        self.assertEqual((s["next"], s["toAddress"]), ("revise", ["R1"]))
        self.revise("four")
        self.close()
        self.assertEqual(self.state()["disputes"], ["R1"])            # the extra round is spent

    def test_a_disagreement_the_reviewer_keeps_open_is_a_dispute_at_once(self):
        self.report(finding("R1"), finding("R2"))
        self.close()
        self.revise("Round 2.")
        self.write("review/writer-response.json", {"responses": [
            {"id": "R1", "action": "disagree", "location": "Q1", "reason": "The key is right."},
            {"id": "R2", "action": "fixed", "location": "Q2", "change": "c"}]})
        self.report(finding("R1", note="Still wrong."), finding("R2", status="resolved"))
        self.close()
        s = self.state()
        self.assertEqual((s["round"], s["next"], s["disputes"], s["toAddress"]), (2, "decide", ["R1"], []))
        self.decide(2, accepted=["R1"])                    # one more round, with the teacher's instruction
        self.assertEqual((self.state()["next"], self.state()["toAddress"]), ("revise", ["R1"]))

    def test_a_disagreement_the_reviewer_accepts_is_resolved(self):
        self.report(finding("R1"))
        self.close()
        self.revise("Round 2.")
        self.write("review/writer-response.json", {"responses": [
            {"id": "R1", "action": "disagree", "location": "Q1", "reason": "The key is right."}]})
        self.report(finding("R1", status="resolved", note="The writer is right."))
        self.close()
        self.assertEqual(self.state()["next"], "done")

    def test_a_new_undecided_warning_after_the_cap_is_asked_about(self):
        self.report(finding("R1", "warning"))
        for text in ("x", "y", "z"):
            self.revise(text)
            self.close()
        s = self.state()
        self.assertEqual((s["next"], s["toDecide"], s["disputes"]), ("decide", ["R1"], []))

    def test_bad_decisions_are_errors(self):
        self.report(finding("R1"))
        self.close()
        for doc in ({"decisions": [{"round": 1, "accepted": ["R9"], "rejected": []}]},
                    {"decisions": [{"round": 1, "accepted": ["R1"], "rejected": ["R1"]}]},
                    {"decisions": [{"accepted": [], "rejected": []}]},
                    {"decisions": {}}):
            self.write("review/decisions.json", doc)
            with self.assertRaises(rs.StatusError, msg=doc):
                self.state()

    def test_a_malformed_report_is_an_error(self):
        self.write("review/reviewer-report.json", {"findings": [{"id": "R1"}]})
        with self.assertRaises(rs.StatusError):
            self.state()


class CloseRound(Task):
    def test_saves_the_round_and_is_idempotent(self):
        self.report(finding("R1"))
        self.assertEqual(self.close(), (0, "Closed round 1.\n"))
        self.assertEqual(self.close()[1], "Round 1 is already closed.\n")
        rounds = rs.read_rounds(self.task)
        self.assertEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["report"], file_hash(os.path.join(self.task, "review", "reviewer-report.json")))
        saved = os.path.join(self.task, "review", "rounds", "1")
        self.assertEqual(sorted(os.listdir(saved)), ["questions.json", "reviewer-report.json"])
        with open(os.path.join(self.task, "run.jsonl"), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.readline())["event"], "round_closed")

    def test_the_same_report_on_revised_questions_is_a_new_round(self):
        self.report()
        self.close()
        self.revise("Changed.")
        self.assertEqual(self.state()["next"], "close")
        self.assertEqual(self.close()[1], "Closed round 2.\n")

    def test_a_writer_response_alone_makes_a_new_round(self):
        self.report(finding("R1"))
        self.close()
        self.write("review/writer-response.json", {"responses": [{"id": "R1", "action": "disagree"}]})
        self.assertEqual(self.state()["next"], "close")

    def test_refuses_a_dropped_finding(self):
        self.report(finding("R1"), finding("R2", "warning"))
        self.close()
        self.revise("Changed.")
        self.report(finding("R1", status="resolved"))
        code, out = self.close()
        self.assertEqual(code, 1)
        self.assertIn("R2 from the previous round is missing", out)
        self.assertEqual(len(rs.read_rounds(self.task)), 1)

    def test_a_severity_change_needs_a_note(self):
        self.report(finding("R1", "warning"))
        self.close()
        self.revise("Changed.")
        self.report(finding("R1", "error"))
        code, out = self.close()
        self.assertEqual(code, 1)
        self.assertIn("R1 changed from warning to error without a note", out)
        self.report(finding("R1", "error", note="The revision made the key wrong."))
        self.assertEqual(self.close()[0], 0)


class Changes(Task):
    def test_lists_changed_fields_by_part(self):
        self.report()
        self.close()
        q = load_json(os.path.join(self.task, "questions.json"))
        leaf = next(p for x in q["questions"] for p in x.get("parts", []) if "answer" in p)
        old = leaf["answer"]
        leaf["answer"] = "A new answer."
        self.write("questions.json", q)
        text = rs.changes(self.task)
        self.assertIn("since round 1 was reviewed:", text)
        self.assertIn(f"answer:\n  before: {old}\n  after:  A new answer.", text)

    def test_no_changes_and_no_rounds(self):
        self.assertIn("No round has been closed yet", rs.changes(self.task))
        self.report()
        self.close()
        self.assertTrue(rs.changes(self.task).endswith(" none"))


class Fixes(Task):
    """The final approval's list of changes (--fixes), and undoing a fix."""

    def answer_part(self):
        q = load_json(os.path.join(self.task, "questions.json"))
        for x in q["questions"]:
            for p in x.get("parts", []):
                if "answer" in p:
                    return q, x, p

    def writer_fixes(self, rid, new_answer, action="fixed"):
        q, x, p = self.answer_part()
        p["answer"] = new_answer
        self.write("questions.json", q)
        loc = f"Q{x['number']}({p['label']})"
        self.write("review/writer-response.json",
                   {"responses": [{"id": rid, "action": action, "location": loc, "change": f"Now: {new_answer}"}]})
        return loc

    def test_lists_each_fix_with_its_label_verdict_and_text(self):
        self.report(finding("R1"), finding("R2", "warning"))
        self.close()
        self.decide(1, accepted=["R2"])
        _, _, p = self.answer_part()
        old = p["answer"]
        loc = self.writer_fixes("R1", "A fixed answer.")
        self.report(finding("R1", status="resolved", note="Now right."), finding("R2", "warning"))
        self.close()
        self.assertTrue(os.path.isfile(os.path.join(self.task, "review", "rounds", "2", "writer-response.json")))
        text = rs.fixes(self.task)
        self.assertIn("## Round 2: the revision after round 1", text)
        self.assertIn(f"R1  error  {loc}  AUTOMATIC  fixed", text)
        self.assertIn("Reviewer in round 2: resolved (Now right.)", text)
        self.assertIn(f"before: {old}", text)
        self.assertIn("after:  A fixed answer.", text)
        self.assertIn("## Changes no writer response accounts for\nNone.", text)

    def test_an_unclaimed_edit_is_flagged(self):
        self.report()
        self.close()
        self.revise("Edited by hand.")
        self.close()
        text = rs.fixes(self.task)
        self.assertIn("No writer revision", text)
        self.assertIn("Round 2:\n  Q", text)
        self.assertIn("after:  Edited by hand.", text)
        self.assertIsNone(rs.read_rounds(self.task)[1]["writerResponse"])

    def test_no_revisions(self):
        self.report()
        self.close()
        self.assertIn("No revisions: the paper is as the writer first drafted it.", rs.fixes(self.task))

    def test_undoing_a_fix_sends_it_back_to_the_writer_once(self):
        self.report(finding("R1"))
        self.close()
        self.writer_fixes("R1", "A fixed answer.")
        self.report(finding("R1", status="resolved"))
        self.close()
        s = self.state()
        self.assertEqual((s["next"], s["fixed"]), ("done", ["R1"]))
        self.assertEqual(rs.record_decision(self.task, [], ["R1"], "/exam-papers:decide reject R1"), [])
        [d] = load_json(os.path.join(self.task, "review", "decisions.json"))["decisions"]
        self.assertEqual(d["undo"], ["R1"])
        s = self.state()
        self.assertEqual((s["next"], s["toRevert"]), ("revise", ["R1"]))
        self.writer_fixes("R1", "The old answer again.", action="reverted")
        self.assertEqual(self.state()["toRevert"], [])
        self.report(finding("R1", status="open", note="Wrong again."))     # rejected: stays closed
        self.close()
        self.assertEqual(self.state()["next"], "done")
        self.assertIn("UNDONE BY YOU  reverted", rs.fixes(self.task))

    def test_rejecting_a_dispute_does_not_revert(self):
        self.report(finding("R1"))
        self.close()
        for text in ("two", "three"):
            self.writer_fixes("R1", text)
            self.close()
        self.assertEqual(self.state()["disputes"], ["R1"])
        self.assertEqual(rs.record_decision(self.task, [], ["R1"], "/exam-papers:decide reject R1"), [])
        self.assertEqual(load_json(os.path.join(self.task, "review", "decisions.json"))["decisions"][0]["undo"], [])
        self.assertEqual(self.state()["next"], "done")

    def test_a_resolved_finding_nobody_fixed_cannot_be_rejected(self):
        self.report(finding("R1", status="resolved"))
        self.close()
        problems = rs.record_decision(self.task, [], ["R1"], "/exam-papers:decide reject R1")
        self.assertIn("R1 cannot be rejected now", " ".join(problems))


class CommandLine(Task):
    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rs.main(["review_status.py", self.task, *args])
        return code, buf.getvalue()

    def test_not_flag_for_next_step(self):
        self.report(finding("R1"))
        self.assertEqual(self.run_main("--not", "close")[0], 1)
        self.assertEqual(self.run_main("--close-round")[0], 0)
        self.assertEqual(self.run_main("--not", "close")[0], 0)
        self.assertEqual(self.run_main("--not", "revise")[0], 1)
        self.assertEqual(self.run_main("--not", "maybe")[0], 2)

    def test_not_is_false_when_the_status_cannot_be_read(self):
        self.assertEqual(self.run_main("--not", "decide")[0], 1)      # no report yet: the step is due
        self.assertEqual(self.run_main()[0], 2)

    def test_summary_and_json(self):
        self.report(finding("R1"), finding("R2", "warning"))
        self.run_main("--close-round")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Teacher to decide: R2", out)
        self.assertIn("Writer to address: R1", out)
        self.assertIn("NEXT: decide", out)
        self.assertEqual(json.loads(self.run_main("--json")[1])["next"], "decide")


if __name__ == "__main__":
    unittest.main()
