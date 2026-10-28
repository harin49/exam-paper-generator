"""Tests for the make-paper skill's scripts/render_review.py. Run from the project root:
    python3 -m unittest discover tests
"""
import contextlib
import copy
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
from helpers import TEST_DATA  # noqa: E402
import render_review as rr  # noqa: E402

FINDINGS = {"findings": [
    {"id": "R1", "severity": "error", "status": "open", "location": "Q18(b)", "problem": "The key gives 4 N.",
     "evidence": "F = ma = 8 × 5 = 40 N.", "suggestedFix": "Change the answer to 40 N."},
    {"id": "R2", "severity": "warning", "status": "open", "location": "Q6 and Q17(b)", "problem": "Same idea twice.",
     "evidence": "Q6: \"rest\"\nQ17(b): \"rest\"", "suggestedFix": "Reword Q17(b)."},
    {"id": "R3", "severity": "suggestion", "status": "open", "location": "Q3", "problem": "Options <a> & <b> overlap.",
     "evidence": "\"least count\" and \"Vernier constant\".", "suggestedFix": "Use \"parallax error\"."},
]}


class Check(unittest.TestCase):
    def broken(self, change):
        doc = copy.deepcopy(FINDINGS)
        change(doc)
        return rr.check(doc)

    def test_valid_and_empty_files_pass(self):
        self.assertEqual(rr.check(FINDINGS), [])
        self.assertEqual(rr.check({"findings": []}), [])

    def test_shape(self):
        self.assertTrue(rr.check([]))
        self.assertTrue(rr.check({"findings": [], "extra": 1}))
        self.assertIn("finding 1: must be an object", rr.check({"findings": ["x"]}))

    def test_missing_unknown_and_blank_fields(self):
        self.assertIn("finding 1: missing evidence", self.broken(lambda d: d["findings"][0].pop("evidence")))
        self.assertIn("finding 1: unknown field fix", self.broken(lambda d: d["findings"][0].update(fix="x")))
        self.assertIn("finding 2: problem must be non-empty text",
                      self.broken(lambda d: d["findings"][1].update(problem=" ")))

    def test_dismissed_mismatches(self):
        doc = dict(copy.deepcopy(FINDINGS), dismissed=[
            {"mismatch": "[V1] Q5: the solver chose (d) but the key says (b)", "reason": "The solver used g = 9.8."}])
        self.assertEqual(rr.check(doc), [])
        self.assertEqual(rr.check({"findings": [], "dismissed": []}), [])
        self.assertTrue(rr.check({"findings": [], "dismissed": {}}))
        self.assertIn("dismissed 1: must have exactly the fields mismatch and reason",
                      rr.check({"findings": [], "dismissed": [{"mismatch": "x"}]}))
        self.assertIn("dismissed 1: mismatch and reason must be non-empty text",
                      rr.check({"findings": [], "dismissed": [{"mismatch": "x", "reason": ""}]}))
        text = rr.text_report(doc["findings"], doc["dismissed"])
        self.assertIn("## Solver mismatches dismissed by the reviewer\n- [V1] Q5", text)
        self.assertIn("Reason: The solver used g = 9.8.", text)
        page = rr.html_report(doc["findings"], {}, doc["dismissed"])
        self.assertIn("Solver mismatches dismissed", page)
        self.assertNotIn("Solver mismatches dismissed", rr.html_report(doc["findings"], {}))

    def test_ids_run_in_order(self):
        self.assertIn("finding 2: id must be R2, not 'R3'",
                      self.broken(lambda d: d["findings"][1].update(id="R3")))

    def test_severity_and_status_values(self):
        self.assertIn("finding 1: severity must be error, warning or suggestion, not 'major'",
                      self.broken(lambda d: d["findings"][0].update(severity="major")))
        self.assertIn("finding 2: status must be open or resolved, not 'fixed'",
                      self.broken(lambda d: d["findings"][1].update(status="fixed")))
        self.assertIn("finding 1: missing status", self.broken(lambda d: d["findings"][0].pop("status")))

    def test_any_severity_order_and_an_optional_note(self):
        # A later round keeps IDs, so an error can follow a suggestion (R4 found in round 2).
        self.assertEqual(self.broken(lambda d: d["findings"][2].update(severity="error")), [])
        self.assertEqual(self.broken(lambda d: d["findings"][0].update(note="Fixed in round 2.")), [])
        self.assertIn("finding 1: note must be non-empty text",
                      self.broken(lambda d: d["findings"][0].update(note="")))


class Output(unittest.TestCase):
    def test_text_report_keeps_the_wording(self):
        text = rr.text_report(FINDINGS["findings"])
        self.assertTrue(text.startswith("# Review of questions.json\n"
                                        "Findings: 3 (open: 1 error, 1 warning, 1 suggestion; resolved: 0)\n"))
        self.assertIn("## R2  Q6 and Q17(b)  warning  (open)\nProblem: Same idea twice.", text)
        self.assertIn("Suggested fix: Change the answer to 40 N.", text)
        self.assertEqual(rr.text_report([]), "# Review of questions.json\nFindings: none")

    def test_counts_are_pluralised(self):
        two = [dict(FINDINGS["findings"][1], id="R1"), dict(FINDINGS["findings"][1], id="R2")]
        self.assertEqual(rr.counts_line(two), "Findings: 2 (open: 0 errors, 2 warnings, 0 suggestions; resolved: 0)")

    def test_open_findings_come_first_by_severity(self):
        found = copy.deepcopy(FINDINGS["findings"])
        found[0].update(status="resolved", note="Fixed in round 2.")
        found.append(dict(found[1], id="R4", severity="error", status="open"))
        text = rr.text_report(found)
        order = [line.split()[1] for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(order, ["R4", "R2", "R3", "R1"])
        self.assertIn("Note: Fixed in round 2.", text)
        page = rr.html_report(found, {})
        self.assertIn('<span class="chip">1 resolved</span>', page)
        self.assertLess(page.index('id="R4"'), page.index('id="R1"'))

    def test_html_escapes_text_and_shows_every_finding(self):
        page = rr.html_report(FINDINGS["findings"], {})
        self.assertTrue(page.startswith("<!doctype html>"))
        for fid in ("R1", "R2", "R3"):
            self.assertIn(f'id="{fid}"', page)
        self.assertIn("Options &lt;a&gt; &amp; &lt;b&gt; overlap.", page)
        self.assertNotIn("<a>", page)
        self.assertIn("Q6: &quot;rest&quot;<br>Q17(b)", page)              # line breaks kept
        self.assertIn('<span class="chip error">1 open error</span>', page)
        self.assertIn("prefers-color-scheme:dark", page)

    def test_html_with_no_findings(self):
        self.assertIn("The reviewer found nothing to report.", rr.html_report([], {}))

    def test_paper_line_comes_from_the_spec(self):
        with open(os.path.join(TEST_DATA, "spec.json"), encoding="utf-8") as f:
            spec = json.load(f)
        self.assertIn("Physics · Class IX (ICSE)", rr.paper_line(spec))
        self.assertEqual(rr.paper_line({}), "")


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "review"))
        shutil.copy(os.path.join(TEST_DATA, "spec.json"), self.tmp)
        self.path = os.path.join(self.tmp, "review", "reviewer-report.json")
        self.html = os.path.join(self.tmp, "review", "reviewer-report.html")
        self.write(FINDINGS)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, doc):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rr.main(["render_review.py", *args])
        return code, buf.getvalue()

    def test_writes_html_beside_the_findings_and_prints_them(self):
        code, out = self.run_main(self.path)
        self.assertEqual(code, 0, out)
        self.assertIn("## R1  Q18(b)  error  (open)", out)
        self.assertIn(f"Wrote {self.html}", out)
        with open(self.html, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Physics · Class IX (ICSE)", page)                  # from the task's spec.json

    def test_same_findings_give_the_same_page(self):
        self.run_main(self.path)
        with open(self.html, encoding="utf-8") as f:
            first = f.read()
        self.run_main(self.path)
        with open(self.html, encoding="utf-8") as f:
            self.assertEqual(f.read(), first)

    def test_rerun_with_the_same_findings_leaves_the_page_untouched(self):
        self.run_main(self.path)
        os.utime(self.html, ns=(1, 1))                  # an old timestamp, as if written long ago
        code, out = self.run_main(self.path)
        self.assertEqual(code, 0, out)
        self.assertEqual(os.stat(self.html).st_mtime_ns, 1)
        self.assertIn("is already up to date", out)

    def test_changed_findings_rewrite_the_page(self):
        self.run_main(self.path)
        os.utime(self.html, ns=(1, 1))
        doc = copy.deepcopy(FINDINGS)
        doc["findings"][0]["problem"] = "A different problem."
        self.write(doc)
        self.run_main(self.path)
        self.assertNotEqual(os.stat(self.html).st_mtime_ns, 1)

    def test_print_writes_nothing(self):
        code, out = self.run_main(self.path, "--print")
        self.assertEqual(code, 0, out)
        self.assertIn("## R1  Q18(b)  error  (open)", out)
        self.assertFalse(os.path.exists(self.html))

    def test_print_still_checks_the_format(self):
        self.write({"findings": [{"id": "R1"}]})
        code, out = self.run_main(self.path, "--print")
        self.assertEqual(code, 1)
        self.assertIn("nothing was written", out)

    def test_print_and_out_together_are_refused(self):
        self.assertEqual(self.run_main(self.path, "--print", "--out", "x.html")[0], 2)

    def test_out_option(self):
        other = os.path.join(self.tmp, "other.html")
        self.assertEqual(self.run_main(self.path, "--out", other)[0], 0)
        self.assertTrue(os.path.isfile(other))
        self.assertEqual(self.run_main(self.path, "--out")[0], 2)

    def test_broken_findings_write_nothing(self):
        doc = copy.deepcopy(FINDINGS)
        doc["findings"][0]["severity"] = "major"
        self.write(doc)
        code, out = self.run_main(self.path)
        self.assertEqual(code, 1)
        self.assertIn("nothing was written", out)
        self.assertFalse(os.path.exists(self.html))

    def test_unreadable_input_and_usage(self):
        self.write("{not json")
        self.assertEqual(self.run_main(self.path)[0], 2)
        self.assertEqual(self.run_main(os.path.join(self.tmp, "missing.json"))[0], 2)
        self.assertEqual(self.run_main()[0], 2)


if __name__ == "__main__":
    unittest.main()
