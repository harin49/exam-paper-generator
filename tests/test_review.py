"""Tests for skill/scripts/extract_paper.py and compare_solutions.py. Run from the project root:
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
sys.path.insert(0, os.path.join(ROOT, "skill", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA  # noqa: E402
import compare_solutions as cs  # noqa: E402
import extract_paper as ep  # noqa: E402
from render import leaves  # noqa: E402

EXAMPLE = TEST_DATA


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def perfect_solver(qdoc):
    """The answers file a flawless solver would write for this key."""
    answers = []
    for q in qdoc["questions"]:
        if "options" in q:
            answers.append({"number": q["number"], "choice": q["correctOption"]})
            continue
        for labels, leaf in leaves(q["parts"]):
            a = {"number": q["number"], "id": ep.part_id(labels), "answer": "text"}
            if "computed" in leaf:
                a["values"] = [{"value": c["value"], "unit": c["unit"]} for c in leaf["computed"]]
            answers.append(a)
    return {"answers": answers}


class PlainText(unittest.TestCase):
    def test_markup_becomes_plain_text(self):
        self.assertEqual(ep.plain_text("9.8 m s<sup>−2</sup> and F<sub>2</sub>"), "9.8 m s^(−2) and F_2")
        self.assertEqual(ep.plain_text("does <b>not</b> <i>depend</i><br/>on"), "does not depend\non")
        self.assertIsNone(ep.plain_text(None))

    def test_part_ids(self):
        self.assertEqual(ep.part_id(("a",)), "a")
        self.assertEqual(ep.part_id(("b", "ii")), "b(ii)")
        self.assertEqual(ep.part_id(("",)), "")


class Extract(unittest.TestCase):
    def setUp(self):
        self.qdoc = load(os.path.join(EXAMPLE, "questions.json"))
        self.spec = load(os.path.join(EXAMPLE, "spec.json"))
        self.data = ep.extract(self.qdoc, self.spec)

    def test_no_answer_fields_anywhere(self):
        self.assertEqual(ep.find_forbidden(self.data), [])
        text = json.dumps(self.data, ensure_ascii=False)
        for secret in ("explanation", "correctOption", "marking", "computed", "vt_graph.png"):
            self.assertNotIn(secret, text)

    def test_answer_text_is_not_present(self):
        text = json.dumps(self.data, ensure_ascii=False)
        # model answers and explanations from the key must not appear in the solver's input
        for q in self.qdoc["questions"]:
            if "options" in q:
                self.assertNotIn(ep.plain_text(q["explanation"]), text)
            else:
                for _, leaf in leaves(q["parts"]):
                    self.assertNotIn(ep.plain_text(leaf["answer"]), text)

    def test_every_question_and_part_is_present(self):
        self.assertEqual([q["number"] for q in self.data["questions"]],
                         [q["number"] for q in self.qdoc["questions"]])
        ids = ep.answerable_ids(self.qdoc)
        in_input = {}
        for q in self.data["questions"]:
            found = []

            def walk(parts):
                for p in parts:
                    if "parts" in p:
                        walk(p["parts"])
                    else:
                        found.append(p["id"])
            walk(q.get("parts", []))
            in_input[q["number"]] = found
        self.assertEqual(in_input, ids)

    def test_mcq_has_options_and_no_key(self):
        q1 = self.data["questions"][0]
        self.assertEqual(q1["type"], "mcq")
        self.assertEqual(len(q1["options"]), 4)
        self.assertNotIn("correctOption", q1)

    def test_nested_ids(self):
        q12 = next(q for q in self.data["questions"] if q["number"] == 12)
        group = q12["parts"][0]
        self.assertNotIn("id", group)
        self.assertEqual([p["id"] for p in group["parts"]], ["a(i)", "a(ii)"])

    def test_paper_diagram_description_is_kept_but_not_answer_diagram(self):
        qdoc = copy.deepcopy(self.qdoc)
        q = next(q for q in qdoc["questions"] if q["number"] == 7)
        q["diagram"] = {"description": "A vernier scale", "file": "v.png"}
        q["parts"][0]["answerDiagram"] = {"description": "SECRET", "file": "s.png"}
        data = ep.extract(qdoc, self.spec)
        out = next(x for x in data["questions"] if x["number"] == 7)
        self.assertEqual(out["diagram"], {"description": "A vernier scale"})
        self.assertNotIn("SECRET", json.dumps(data))

    def test_constants_come_from_the_spec(self):
        self.assertEqual(self.data["paper"]["constants"], self.spec["content"]["constants"])

    def test_leak_guard_finds_forbidden_keys(self):
        self.assertEqual(ep.find_forbidden({"a": [{"answer": 1}]}), ["solver-input.a[0].answer"])


class ExtractCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name in ("questions.json", "spec.json"):
            shutil.copy(os.path.join(EXAMPLE, name), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ep.main(["extract_paper.py", *args])
        return code, buf.getvalue()

    def test_default_output_location(self):
        code, out = self.run_main(os.path.join(self.tmp, "questions.json"))
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "review", "solver-input.json")))
        self.assertIn("no answers", out)

    def test_missing_file(self):
        code, out = self.run_main(os.path.join(self.tmp, "nope.json"))
        self.assertEqual(code, 2)

    def test_usage(self):
        self.assertEqual(self.run_main()[0], 2)


class Compare(unittest.TestCase):
    def setUp(self):
        self.qdoc = load(os.path.join(EXAMPLE, "questions.json"))
        self.solver = perfect_solver(self.qdoc)

    def find(self, number, pid=""):
        return next(a for a in self.solver["answers"] if a["number"] == number and a.get("id", "") == pid)

    def messages(self):
        return cs.compare(self.qdoc, self.solver).errors

    def test_perfect_solver_has_no_mismatches(self):
        r = cs.compare(self.qdoc, self.solver)
        self.assertEqual(r.errors, [])
        self.assertTrue(r.info)               # theory parts are listed for judgment

    def test_theory_parts_are_listed_with_both_answers(self):
        r = cs.compare(self.qdoc, self.solver)
        text = "\n".join(r.info)
        self.assertIn("key:", text)
        self.assertIn("solver: text", text)

    def test_v1_wrong_mcq_option(self):
        a = self.find(1)
        a["choice"] = "d"
        self.assertEqual(self.messages(), ["[V1] Q1: the solver chose (d) but the key says (c)"])

    def test_mcq_choice_is_case_and_space_insensitive(self):
        self.find(1)["choice"] = " C "
        self.assertEqual(self.messages(), [])

    def test_v2_wrong_value(self):
        a = self.find(11, "b")
        a["values"] = [{"value": 1.5, "unit": "m"}]
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("[V2] Q11(b): the solver's 1.5 m matches nothing in the key"))

    def test_value_within_one_percent_matches(self):
        a = self.find(11, "b")
        a["values"] = [{"value": a["values"][0]["value"] * 1.005, "unit": "m"}]
        self.assertEqual(self.messages(), [])

    def test_v3_power_of_ten_is_a_unit_difference(self):
        a = self.find(11, "b")
        a["values"] = [{"value": a["values"][0]["value"] * 100, "unit": "cm"}]
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("[V3] Q11(b)"), msgs)
        self.assertIn("unit difference", msgs[0])

    def test_v3_sign_only_difference(self):
        a = self.find(11, "b")
        a["values"] = [{"value": -a["values"][0]["value"], "unit": "m"}]
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("[V3] Q11(b)"), msgs)
        self.assertIn("only in sign", msgs[0])

    def test_v4_no_values_for_a_numerical_part(self):
        a = self.find(11, "b")
        del a["values"]
        msgs = self.messages()
        self.assertEqual(len(msgs), 1)
        self.assertTrue(msgs[0].startswith("[V4] Q11(b)"), msgs)

    def test_extra_intermediate_values_in_the_key_are_fine(self):
        # the key may list intermediates; the solver only has to match what it reports
        a = next(a for a in self.solver["answers"] if len(a.get("values", [])) > 1)
        a["values"] = a["values"][:1]
        self.assertEqual(self.messages(), [])

    def test_v5_unanswered_question_and_part(self):
        self.solver["answers"] = [a for a in self.solver["answers"]
                                  if not (a["number"] == 2 or (a["number"] == 7 and a["id"] == "b"))]
        msgs = self.messages()
        self.assertIn("[V5] Q2: the solver gave no answer", msgs)
        self.assertIn("[V5] Q7(b): the solver gave no answer", msgs)

    def test_v5_unknown_part_and_duplicates(self):
        self.solver["answers"].append({"number": 7, "id": "z", "answer": "x"})
        self.solver["answers"].append(copy.deepcopy(self.find(1)))
        msgs = self.messages()
        self.assertTrue(any("does not exist in the key" in m for m in msgs), msgs)
        self.assertTrue(any("answered more than once" in m for m in msgs), msgs)

    def test_v5_malformed_file(self):
        self.assertTrue(cs.compare(self.qdoc, {"answers": "no"}).errors[0].startswith("[V5]"))
        self.assertTrue(cs.compare(self.qdoc, []).errors[0].startswith("[V5]"))
        self.solver["answers"][0] = {"choice": "a"}
        self.assertTrue(any("integer" in m for m in self.messages()))

    def test_v5_bad_value_entry(self):
        self.find(11, "b")["values"] = ["1.5"]
        self.assertTrue(any(m.startswith("[V5] Q11(b)") for m in self.messages()))

    def test_v6_problem_reported_by_the_solver(self):
        self.find(5)["problem"] = "Option (b) and (c) are both correct"
        r = cs.compare(self.qdoc, self.solver)
        self.assertEqual(r.errors, [])
        self.assertEqual(r.warnings, ["[V6] Q5: the solver reports a problem: Option (b) and (c) are both correct"])

    def test_blank_problem_is_ignored(self):
        self.find(5)["problem"] = "   "
        self.assertEqual(cs.compare(self.qdoc, self.solver).warnings, [])

    def test_closeness_helpers(self):
        self.assertTrue(cs.close(100, 100.9))
        self.assertFalse(cs.close(100, 102))
        self.assertTrue(cs.power_of_ten_apart(0.994, 99.4))
        self.assertFalse(cs.power_of_ten_apart(5, 5))
        self.assertFalse(cs.power_of_ten_apart(5, -50))


class CompareCommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.q = os.path.join(self.tmp, "questions.json")
        shutil.copy(os.path.join(EXAMPLE, "questions.json"), self.q)
        self.s = os.path.join(self.tmp, "solver.json")
        with open(self.s, "w", encoding="utf-8") as f:
            json.dump(perfect_solver(load(self.q)), f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cs.main(["compare_solutions.py", *args])
        return code, buf.getvalue()

    def test_clean_run(self):
        code, out = self.run_main(self.q, self.s)
        self.assertEqual(code, 0, out)
        self.assertIn("NO MISMATCHES", out)

    def test_mismatch_exit_code_and_json(self):
        d = load(self.s)
        d["answers"][0]["choice"] = "d"
        with open(self.s, "w", encoding="utf-8") as f:
            json.dump(d, f)
        code, out = self.run_main(self.q, self.s)
        self.assertEqual(code, 1)
        self.assertIn("[V1] Q1", out)
        code, out = self.run_main(self.q, self.s, "--json")
        self.assertEqual(json.loads(out)["mismatches"], ["[V1] Q1: the solver chose (d) but the key says (c)"])

    def test_out_writes_the_report_to_a_file(self):
        path = os.path.join(self.tmp, "compare-output.txt")
        code, out = self.run_main(self.q, self.s, "--out", path)
        self.assertEqual(code, 0, out)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), out)
        self.assertEqual(self.run_main(self.q, self.s, "--out")[0], 2)

    def test_unreadable_input(self):
        self.assertEqual(self.run_main(self.q, os.path.join(self.tmp, "missing.json"))[0], 2)
        with open(self.s, "w") as f:
            f.write("{not json")
        self.assertEqual(self.run_main(self.q, self.s)[0], 2)

    def test_usage(self):
        self.assertEqual(self.run_main()[0], 2)


if __name__ == "__main__":
    unittest.main()
