"""Tests for skill/scripts/check_questions.py. Run from the project root:
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import TEST_DATA  # noqa: E402
import check_questions as cq  # noqa: E402

EXAMPLE = TEST_DATA
CONCEPTS = os.path.join(EXAMPLE, "concepts.json")


def load(name):
    with open(os.path.join(EXAMPLE, name), encoding="utf-8") as f:
        return json.load(f)


def q(doc, number):
    return next(x for x in doc["questions"] if x["number"] == number)


class BlueprintMatch(unittest.TestCase):
    """Rule Q15: questions.json must match its blueprint on every structural field."""

    def setUp(self):
        self.qdoc = load("questions.json")
        self.bdoc = load("blueprint.json")

    def errors(self):
        return " | ".join(cq.check(self.qdoc, self.bdoc).errors)

    def test_example_matches(self):
        self.assertEqual(cq.check(self.qdoc, self.bdoc).errors, [])

    def test_changed_chapter(self):
        q(self.qdoc, 12)["chapter"] = 5
        self.assertIn("Q12: chapter is 5 but the blueprint says 2", self.errors())

    def test_changed_question_marks(self):
        q(self.qdoc, 1)["marks"] = 2
        self.assertIn("Q1: marks is 2 but the blueprint says 1", self.errors())

    def test_changed_mcq_difficulty(self):
        q(self.qdoc, 3)["difficulty"] = "easy"
        self.assertIn("Q3: difficulty is \"easy\" but the blueprint says \"medium\"", self.errors())

    def test_changed_part_marks(self):
        parts = q(self.qdoc, 7)["parts"]
        parts[0]["marks"], parts[1]["marks"] = 2, 1
        e = self.errors()
        self.assertIn("Q7(a): marks is 2 but the blueprint says 1", e)
        self.assertIn("Q7(b): marks is 1 but the blueprint says 2", e)

    def test_changed_kind_in_subpart(self):
        q(self.qdoc, 12)["parts"][0]["parts"][1]["kind"] = "theory"
        self.assertIn("Q12(a)(ii): kind is \"theory\" but the blueprint says \"numerical\"", self.errors())

    def test_changed_concepts(self):
        q(self.qdoc, 12)["concepts"] = ["acceleration", "second_equation_of_motion", "distance_displacement",
                                        "retardation"]
        self.assertIn("Q12: concepts differ from the blueprint: missing vt_graph_slope; extra retardation",
                      self.errors())

    def test_concept_order_does_not_matter(self):
        q(self.qdoc, 12)["concepts"].reverse()
        self.assertEqual(cq.check(self.qdoc, self.bdoc).errors, [])

    def test_missing_question(self):
        self.qdoc["questions"].pop()
        self.assertIn("there are 12 questions but the blueprint has 13", self.errors())

    def test_extra_part(self):
        q(self.qdoc, 11)["parts"].append({"label": "d", "marks": 1})
        self.assertIn("Q11: has 4 parts but the blueprint has 3", self.errors())

    def test_leaf_turned_into_group(self):
        part = q(self.qdoc, 7)["parts"][1]
        part["parts"] = [{"label": "i", "marks": 2}]
        self.assertIn("Q7(b): the blueprint says this part has no sub-parts", self.errors())

    def test_mcq_given_parts(self):
        q(self.qdoc, 2)["parts"] = []
        self.assertIn("Q2: the blueprint says this question has no parts", self.errors())

    def test_relabelled_part(self):
        q(self.qdoc, 7)["parts"][1]["label"] = "c"
        self.assertIn("Q7(b): label is \"c\" but the blueprint says \"b\"", self.errors())

    def test_draft_blueprint_rejected(self):
        self.bdoc["status"] = "draft"
        self.assertIn("questions may only be written from an approved blueprint", self.errors())

    def test_different_spec(self):
        self.qdoc["spec"] = "other-spec.json"
        self.assertIn("spec: is \"other-spec.json\" but the blueprint says \"spec.json\"", self.errors())

    def test_wording_changes_are_allowed(self):
        q(self.qdoc, 12)["parts"][1]["text"] = "Compare the distance and the displacement of the car."
        q(self.qdoc, 12)["parts"][1]["answer"] = "Something else entirely."
        self.assertEqual(cq.check(self.qdoc, self.bdoc).errors, [])


class CommandLine(unittest.TestCase):
    """Runs main() on a copy laid out like the project, so relative paths resolve."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "examples", "paper")
        os.makedirs(self.dir)
        for name in ("questions.json", "blueprint.json", "spec.json", "concepts.json"):
            shutil.copy(os.path.join(EXAMPLE, name), self.dir)
        self.qpath = os.path.join(self.dir, "questions.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_main(self, *extra):
        return cq.main(["check_questions.py", self.qpath, "--json", *extra])

    def test_default_blueprint_passes(self):
        self.assertEqual(self.run_main(), 0)

    def test_mismatch_fails(self):
        doc = load("questions.json")
        q(doc, 12)["chapter"] = 5
        with open(self.qpath, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        self.assertEqual(self.run_main(), 1)

    def test_missing_spec(self):
        os.remove(os.path.join(self.dir, "spec.json"))
        self.assertEqual(self.run_main(), 2)

    def test_missing_concept_list(self):
        os.remove(os.path.join(self.dir, "concepts.json"))
        self.assertEqual(self.run_main(), 2)

    def test_missing_blueprint(self):
        self.assertEqual(self.run_main("--blueprint", os.path.join(self.dir, "nope.json")), 2)

    def test_explicit_blueprint(self):
        other = os.path.join(self.dir, "approved-plan.json")
        shutil.copy(os.path.join(EXAMPLE, "blueprint.json"), other)
        os.rename(os.path.join(self.dir, "blueprint.json"), os.path.join(self.dir, "old.json"))
        self.assertEqual(self.run_main("--blueprint", other), 0)


class WithSpec(unittest.TestCase):
    """Base for rules that need the spec: every test starts from today's paper, which passes."""

    def setUp(self):
        self.qdoc = load("questions.json")
        self.spec = load("spec.json")
        with open(CONCEPTS, encoding="utf-8") as f:
            self.concepts = json.load(f)

    def result(self):
        return cq.check(self.qdoc, spec=self.spec, concepts=self.concepts)

    def errors(self):
        return " | ".join(self.result().errors)


class ExampleWithSpec(WithSpec):
    def test_example_passes_all_rules(self):
        r = cq.check(self.qdoc, load("blueprint.json"), self.spec, self.concepts)
        self.assertEqual(r.errors, [])

    def test_invalid_spec_skips_dependent_rules(self):
        self.spec["pattern"]["totalMarks"] = 99
        e = self.errors()
        self.assertIn("[S] spec: has 1 error(s)", e)
        self.assertNotIn("[Q3]", e)


class FieldsQ1(WithSpec):
    def test_missing_mcq_text(self):
        del q(self.qdoc, 4)["text"]
        self.assertIn("[Q1] Q4: 'text' is required", self.errors())

    def test_marks_wrong_type(self):
        q(self.qdoc, 11)["parts"][0]["marks"] = "1"
        self.assertIn("[Q1] Q11(a): marks must be a positive number", self.errors())

    def test_bad_difficulty_value(self):
        q(self.qdoc, 5)["difficulty"] = "tricky"
        self.assertIn("[Q1] Q5: difficulty must be one of", self.errors())

    def test_unknown_question_field(self):
        q(self.qdoc, 7)["chaptr"] = 3
        self.assertIn("[Q1] Q7: unknown field 'chaptr'", self.errors())

    def test_mcq_field_on_parted_question(self):
        q(self.qdoc, 11)["options"] = ["x", "y"]
        self.assertIn("[Q1] Q11: unknown field 'options'", self.errors())

    def test_leaf_missing_marking(self):
        del q(self.qdoc, 11)["parts"][2]["marking"]
        self.assertIn("[Q1] Q11(c): 'marking' is required", self.errors())

    def test_marking_item_bad_marks(self):
        q(self.qdoc, 11)["parts"][1]["marking"][0]["marks"] = 0
        self.assertIn("[Q1] Q11(b) marking #1: marks must be a positive number", self.errors())

    def test_nesting_too_deep(self):
        sub = q(self.qdoc, 12)["parts"][0]["parts"][0]
        sub["parts"] = [copy.deepcopy(sub)]
        self.assertIn("[Q1] Q12(a)(i): sub-parts cannot have their own parts", self.errors())

    def test_computed_missing_expression(self):
        del q(self.qdoc, 7)["parts"][1]["computed"][0]["expression"]
        self.assertIn("[Q1] Q7(b) computed #1: 'expression' is required", self.errors())

    def test_multiple_computed_need_labels(self):
        del q(self.qdoc, 11)["parts"][0]["computed"][1]["label"]
        self.assertIn("[Q1] Q11(a) computed #2: needs a label", self.errors())

    def test_diagram_without_description(self):
        q(self.qdoc, 12)["parts"][0]["parts"][0]["answerDiagram"] = {"file": "g.png"}
        self.assertIn("'description' is required", self.errors())

    def test_stem_must_be_text_or_null(self):
        q(self.qdoc, 7)["stem"] = 42
        self.assertIn("[Q1] Q7: stem must be text or null", self.errors())


class SequenceQ2(WithSpec):
    def test_number_gap(self):
        q(self.qdoc, 10)["number"] = 11
        self.assertIn("[Q2] Q11: is numbered 11 but should be 10", self.errors())

    def test_section_out_of_order(self):
        qs = self.qdoc["questions"]
        c = qs.pop(10)                      # Q11, section C
        qs.insert(6, c)                     # now between A and B
        for i, x in enumerate(qs, 1):
            x["number"] = i
        e = self.errors()
        self.assertIn("[Q2] Q8: section B comes after section C", e)
        self.assertIn("[Q2] Q12: section C appears again after section B", e)

    def test_part_label_out_of_order(self):
        q(self.qdoc, 11)["parts"][1]["label"] = "c"
        self.assertIn("[Q2] Q11(c): part 2 should be labelled \"b\"", self.errors())

    def test_subpart_label_wrong(self):
        q(self.qdoc, 12)["parts"][0]["parts"][1]["label"] = "iii"
        self.assertIn("[Q2] Q12(a)(iii): sub-part 2 should be labelled \"ii\"", self.errors())


class SectionCountsQ3(WithSpec):
    def test_wrong_marks_for_section(self):
        q(self.qdoc, 1)["marks"] = 2
        self.assertIn("[Q3] Q1: is worth 2 marks but section A questions are worth 1", self.errors())

    def test_question_moved_to_other_section(self):
        q(self.qdoc, 10)["section"] = "C"
        e = self.errors()
        self.assertIn("[Q3] section B: has 3 questions but the spec offers 4", e)
        self.assertIn("[Q3] section C: has 4 questions but the spec offers 3", e)

    def test_unknown_section(self):
        q(self.qdoc, 13)["section"] = "D"
        self.assertIn("[Q3] Q13: section \"D\" is not in the spec", self.errors())


class McqQ4(WithSpec):
    def test_too_few_options(self):
        q(self.qdoc, 6)["options"].pop()
        self.assertIn("[Q4] Q6: has 3 options but the spec says 4", self.errors())

    def test_correct_option_out_of_range(self):
        q(self.qdoc, 6)["correctOption"] = "e"
        self.assertIn("[Q4] Q6: correctOption is \"e\" but the options run a–d", self.errors())

    def test_duplicate_options(self):
        q(self.qdoc, 2)["options"][3] = q(self.qdoc, 2)["options"][0]
        self.assertIn("[Q4] Q2: has two identical options", self.errors())

    def test_mcq_with_parts(self):
        q(self.qdoc, 3)["parts"] = []
        self.assertIn("[Q4] Q3: an MCQ must not have parts", self.errors())

    # Q1 is numerical: options 12, 120, 1200 (correct, c), 12000 kg m⁻³; computed 1200.
    def test_correct_option_shows_wrong_value(self):
        q(self.qdoc, 1)["correctOption"] = "b"
        self.assertIn("[Q4] Q1: the correct option (b) shows \"120 kg m<sup>−3</sup>\" but the computed "
                      "value is 1200", self.errors())

    def test_two_options_show_the_computed_value(self):
        q(self.qdoc, 1)["options"][3] = "1.2 × 10<sup>3</sup> kg m<sup>−3</sup>"
        self.assertIn("[Q4] Q1: option (d) also shows the computed value 1200: two options would be "
                      "correct", self.errors())

    def test_correct_option_without_a_number(self):
        q(self.qdoc, 1)["options"][2] = "ten times that of water"
        self.assertIn("[Q4] Q1: is numerical, but the correct option (c) does not start with a number",
                      self.errors())

    def test_rounded_and_scientific_options_match(self):
        q1 = q(self.qdoc, 1)
        q1["computed"][0].update(expression="3700 / 3", value=1233.3333)
        q1["options"][2] = "1.23 × 10<sup>3</sup> kg m<sup>−3</sup>"
        self.assertNotIn("[Q4] Q1", self.errors())

    def test_theory_mcq_options_are_not_checked(self):
        self.assertEqual(q(self.qdoc, 2)["kind"], "theory")
        q(self.qdoc, 2)["options"][0] = "5 m"
        self.assertNotIn("[Q4] Q2", self.errors())


class OptionNumber(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(cq.option_number("1.25 Hz"), (1.25, 0.01))
        self.assertEqual(cq.option_number("−0.5 m"), (-0.5, 0.1))
        self.assertEqual(cq.option_number("50,000 Pa"), (50000.0, 1))
        value, step = cq.option_number("5 × 10<sup>−3</sup> m")
        self.assertAlmostEqual(value, 0.005)
        self.assertAlmostEqual(step, 0.001)
        self.assertIsNone(cq.option_number("It doubles"))


class PartCountsQ5(WithSpec):
    def test_too_few_parts_in_long_answer(self):
        q(self.qdoc, 11)["parts"] = q(self.qdoc, 11)["parts"][:2]
        self.assertIn("[Q5] Q11: has 2 part(s) but section C needs at least 3", self.errors())

    def test_too_many_parts_in_short_answer(self):
        parts = q(self.qdoc, 7)["parts"]
        for label in ("c", "d"):
            extra = copy.deepcopy(parts[1])
            extra["label"] = label
            parts.append(extra)
        self.assertIn("[Q5] Q7: has 4 parts but section B allows at most 3", self.errors())

    def test_section_without_subparts(self):
        b = next(s for s in self.spec["pattern"]["sections"] if s["id"] == "B")
        b["subParts"] = "none"
        del b["maxSubParts"]
        self.assertIn("[Q5] Q7: section B has no sub-parts, so the question must be a single part",
                      self.errors())


class MarksQ6(WithSpec):
    def test_parts_do_not_add_up(self):
        q(self.qdoc, 7)["parts"][1]["marks"] = 3
        q(self.qdoc, 7)["parts"][1]["marking"][1]["marks"] = 2
        self.assertIn("[Q6] Q7: parts add up to 4 marks but the question is worth 3", self.errors())

    def test_group_does_not_match_subparts(self):
        q(self.qdoc, 12)["parts"][0]["parts"][1]["marks"] = 2
        q(self.qdoc, 12)["parts"][0]["parts"][1]["marking"][0]["marks"] = 2
        e = self.errors()
        self.assertIn("[Q6] Q12(a): sub-parts add up to 3 marks but the part is worth 2", e)
        self.assertNotIn("Q12: parts add up", e)   # the question total still uses the group's 2

    def test_marking_does_not_add_up(self):
        q(self.qdoc, 9)["parts"][1]["marking"][0]["marks"] = 1
        self.assertIn("[Q6] Q9(b): marking adds up to 2.5 but the part is worth 2", self.errors())

    def test_marking_in_subpart(self):
        q(self.qdoc, 12)["parts"][0]["parts"][1]["marking"][0]["marks"] = 0.5
        self.assertIn("[Q6] Q12(a)(ii): marking adds up to 0.5 but the part is worth 1", self.errors())

    def test_quarter_marks_rejected(self):
        q(self.qdoc, 9)["parts"][1]["marking"] = [
            {"marks": 0.25, "for": "working"}, {"marks": 1.75, "for": "answer"}]
        e = self.errors()
        self.assertIn("[Q6] Q9(b) marking #1: marks 0.25 is not a multiple of the smallest mark unit (0.5)", e)
        self.assertNotIn("marking adds up", e)      # the total is still right

    def test_whole_marks_only_spec(self):
        self.spec["pattern"]["smallestMarkUnit"] = 1
        e = self.errors()
        self.assertIn("[Q6] Q9(b) marking #1: marks 0.5 is not a multiple of the smallest mark unit (1)", e)

    def test_mcqs_not_affected(self):
        self.assertEqual([m for m in self.result().errors if m.startswith("[Q6] Q1:")], [])


class AnswersQ7(WithSpec):
    def computed(self, number, *path):
        x = q(self.qdoc, number)
        for i in path:
            x = x["parts"][i]
        return x["computed"]

    def test_missing_computed_on_numerical_part(self):
        del q(self.qdoc, 7)["parts"][1]["computed"]
        self.assertIn("[Q7] Q7(b): is numerical but has no computed answers", self.errors())

    def test_missing_computed_on_numerical_mcq(self):
        del q(self.qdoc, 5)["computed"]
        self.assertIn("[Q7] Q5: is numerical but has no computed answers", self.errors())

    def test_value_does_not_match(self):
        self.computed(11, 0)[0]["value"] = 3
        self.assertIn("[Q7] Q11(a) computed #1 (time period): expression gives 2 but value is 3", self.errors())

    def test_mismatch_in_subpart(self):
        self.computed(12, 0, 1)[0]["value"] = 70
        self.assertIn("[Q7] Q12(a)(ii) computed #1: expression gives 50 but value is 70", self.errors())

    def test_letter_constant_rejected(self):
        self.computed(10, 0)[0]["expression"] = "2 * g"
        e = self.errors()
        self.assertIn("[Q7] Q10(a) computed #1: expression \"2 * g\" uses 'g'; write constants as numbers", e)
        self.assertNotIn("cannot be calculated: uses", e)

    def test_other_function_rejected(self):
        self.computed(10, 0)[0]["expression"] = "round(2 * 9.8)"
        self.assertIn("uses round(); only sqrt() is allowed", self.errors())

    def test_syntax_error(self):
        self.computed(10, 0)[0]["expression"] = "2 * * 9.8"
        self.assertIn("\"2 * * 9.8\" is not valid arithmetic", self.errors())

    def test_division_by_zero(self):
        self.computed(9, 1)[0]["expression"] = "600 / 0"
        self.assertIn("cannot be calculated: division by zero", self.errors())

    def test_huge_power_rejected(self):
        self.computed(9, 1)[0]["expression"] = "10 ** 1000"
        self.assertIn("the power 1000 is too large", self.errors())

    def test_small_rounding_is_accepted(self):
        self.computed(11, 1)[0]["value"] = 0.993          # exact result is 0.992948...
        self.assertEqual([e for e in self.result().errors if "[Q7]" in e], [])

    def test_bigger_rounding_is_rejected(self):
        self.computed(11, 1)[0]["value"] = 0.99
        self.assertIn("[Q7] Q11(b) computed #1: expression gives 0.992948 but value is 0.99", self.errors())

    def test_pi_and_sqrt_allowed(self):
        import math
        c = self.computed(11, 1)[0]
        c["expression"] = "2 * pi * sqrt(1 / 9.8)"
        c["value"] = 2 * math.pi * math.sqrt(1 / 9.8)
        self.assertEqual([e for e in self.result().errors if "[Q7]" in e], [])

    def test_theory_parts_need_no_computed(self):
        self.assertNotIn("Q11(c)", " ".join(e for e in self.result().errors if "[Q7]" in e))


class ConceptsQ8(WithSpec):
    def test_unknown_tag(self):
        q(self.qdoc, 7)["concepts"] = ["pendulum_length_graph", "unit_changes"]
        self.assertIn("[Q8] Q7: concept 'unit_changes' is not in the concept list", self.errors())

    def test_tag_from_another_chapter(self):
        q(self.qdoc, 7)["concepts"] = ["pendulum_length_graph", "linear_momentum"]
        self.assertIn("[Q8] Q7: concept 'linear_momentum' belongs to chapter 3, but the question is "
                      "from chapter 1", self.errors())

    def test_chapter_not_in_spec(self):
        q(self.qdoc, 7)["chapter"] = 6
        self.assertIn("[Q8] Q7: chapter 6 is not one of the spec's chapters [1, 2, 3]", self.errors())

    def test_duplicate_tag(self):
        q(self.qdoc, 7)["concepts"] = ["unit_conversion", "unit_conversion"]
        self.assertIn("[Q8] Q7: lists the same concept tag twice", self.errors())

    def test_concept_list_for_another_book(self):
        self.concepts["book"] = "Frank Physics Part I"
        self.assertIn("[Q8] conceptList: is for book \"Frank Physics Part I\" but the spec says "
                      "\"Selina Concise Physics Part I\"", self.errors())

    def test_tag_listed_in_two_chapters(self):
        self.concepts["chapters"]["3"]["concepts"].append(dict(self.concepts["chapters"]["1"]["concepts"][0]))
        self.assertIn("[Q8] conceptList: tag 'si_units' is listed under chapters 1 and 3", self.errors())

    def test_malformed_concept_list(self):
        self.concepts = {"chapter": {}}
        self.assertIn("[Q8] conceptList: must be an object with a 'chapters' object", self.errors())


class DifficultyQ9(WithSpec):
    def test_hard_part_rejected(self):
        q(self.qdoc, 11)["parts"][2]["difficulty"] = "hard"
        self.assertIn("[Q9] Q11(c): is hard, but the spec's difficulty target for hard is 0%", self.errors())

    def test_hard_mcq_rejected(self):
        q(self.qdoc, 5)["difficulty"] = "hard"
        self.assertIn("[Q9] Q5: is hard, but the spec's difficulty target for hard is 0%", self.errors())

    def test_hard_subpart_rejected(self):
        q(self.qdoc, 12)["parts"][0]["parts"][0]["difficulty"] = "hard"
        self.assertIn("[Q9] Q12(a)(i): is hard", self.errors())

    def test_hard_allowed_when_target_above_zero(self):
        self.spec["content"]["difficulty"]["target"] = {"easy": 40, "medium": 40, "hard": 20}
        q(self.qdoc, 11)["parts"][2]["difficulty"] = "hard"
        self.assertEqual([e for e in self.result().errors if "[Q9]" in e], [])

    def test_any_zero_level_is_excluded(self):
        self.spec["content"]["difficulty"]["target"] = {"easy": 0, "medium": 100, "hard": 0}
        self.assertIn("[Q9] Q2: is easy, but the spec's difficulty target for easy is 0%", self.errors())


class CompulsoryCoverageQ10(WithSpec):
    def move_mcqs_to_chapter_2(self):
        for n, tag in ((5, "speed_velocity"), (6, "vt_graph_slope")):
            q(self.qdoc, n)["chapter"] = 2
            q(self.qdoc, n)["concepts"] = [tag]
            q(self.qdoc, n)["concept"] = tag

    def test_missing_chapter(self):
        self.move_mcqs_to_chapter_2()
        self.assertIn("[Q10] section A: no compulsory question from chapter(s) 3", self.errors())

    def test_not_required_by_spec(self):
        self.move_mcqs_to_chapter_2()
        self.spec["content"]["everyChapterInCompulsorySection"] = False
        self.assertEqual([e for e in self.result().errors if "[Q10]" in e], [])


class BalanceQ11toQ14(WithSpec):
    def warnings(self, rule):
        return [w for w in self.result().warnings if w.startswith(f"[{rule}]")]

    def test_example_warnings(self):
        r = self.result()
        self.assertEqual(r.errors, [])
        self.assertEqual(self.warnings("Q11"), [])
        self.assertEqual(self.warnings("Q12"), [])
        self.assertEqual(self.warnings("Q13"), [])
        self.assertEqual(len(self.warnings("Q14")), 4)

    def test_example_info(self):
        info = " | ".join(self.result().info)
        self.assertIn("ch1 14 (target 12.0)", info)
        self.assertIn("Numerical/theory: 47.2% / 52.8%", info)
        self.assertIn("easy 50.0% (target 50%)", info)

    def test_chapter_outside_tighter_tolerance(self):
        self.spec["content"]["chapterWeightage"]["toleranceMarks"] = 1.5
        w = self.warnings("Q11")
        self.assertEqual(len(w), 1)
        self.assertIn("chapter 1 has 14 marks (target 12.0)", w[0])
        self.assertNotIn("chapter 2", w[0])

    def test_custom_weights(self):
        self.spec["content"]["chapterWeightage"] = {
            "mode": "custom", "toleranceMarks": 5,
            "weights": {"1": 60, "2": 20, "3": 20}}
        self.assertIn("chapter 1 has 14 marks (target 21.6)", self.warnings("Q11")[0])

    def test_numerical_split_outside(self):
        self.spec["content"]["numericalTheorySplit"]["target"] = [70, 30]
        self.assertIn("numerical is 47.2% of marks offered, outside the target 70% ± 5", self.warnings("Q12")[0])

    def test_difficulty_within_new_target(self):
        self.spec["content"]["difficulty"]["target"] = {"easy": 55, "medium": 45, "hard": 0}
        self.assertEqual(self.warnings("Q13"), [])

    def test_difficulty_outside_new_target(self):
        self.spec["content"]["difficulty"]["target"] = {"easy": 70, "medium": 30, "hard": 0}
        w = self.warnings("Q13")
        self.assertEqual(len(w), 1)
        self.assertIn("easy is 50.0% (target 70%); medium is 50.0% (target 30%)", w[0])

    def test_shared_concept_message(self):
        w = " | ".join(self.warnings("Q14"))
        self.assertIn("[Q14] concept 'least_count': is used by Q8 and Q11; check they don't test "
                      "the same thing", w)

    def test_shared_concepts_off(self):
        self.spec["content"]["avoidOverlappingConcepts"] = False
        self.assertEqual(self.warnings("Q14"), [])

    def test_warnings_do_not_fail(self):
        self.spec["content"]["numericalTheorySplit"]["target"] = [90, 10]
        self.assertEqual(self.result().errors, [])


class PartConceptsQ8(WithSpec):
    """Per-part 'concept' fields, as make_blueprint.py writes them (the test paper has them on every part)."""

    def info(self, tag):
        for entry in self.concepts["chapters"].values():
            for c in entry["concepts"]:
                if c["tag"] == tag:
                    return c

    def q8(self):
        return [e for e in self.result().errors if e.startswith("[Q8]")]

    def test_consistent_question_passes(self):
        self.assertEqual(self.q8(), [])

    def test_concept_not_in_question(self):
        q(self.qdoc, 12)["parts"][1]["concept"] = "retardation"
        self.assertIn("[Q8] Q12(b): concept 'retardation' is not in the question's concepts",
                      " | ".join(self.q8()))

    def test_kind_not_allowed(self):
        self.info("second_equation_of_motion")["kinds"] = ["theory"]
        self.assertIn("[Q8] Q12(a)(ii): is numerical, but concept 'second_equation_of_motion' only allows theory",
                      " | ".join(self.q8()))

    def test_marks_over_concept_max(self):
        self.info("vt_graph_slope")["maxMarks"] = 0.5
        self.assertIn("[Q8] Q12(c): is worth 2 marks, but concept 'vt_graph_slope' allows at most 0.5 per part",
                      " | ".join(self.q8()))

    def test_all_or_none(self):
        del q(self.qdoc, 12)["parts"][1]["concept"]
        self.assertIn("[Q8] Q12: some parts name their concept and some don't", " | ".join(self.q8()))

    def test_question_concepts_must_match_parts(self):
        q(self.qdoc, 12)["concepts"].append("retardation")
        self.assertIn("[Q8] Q12: the question's concepts should be exactly the concepts its parts name",
                      " | ".join(self.q8()))

    def test_mcq_concept(self):
        self.info("newton_first_law")["kinds"] = ["numerical"]
        self.assertIn("[Q8] Q6: is theory, but concept 'newton_first_law' only allows numerical",
                      " | ".join(self.q8()))

    def test_blueprint_compares_correct_option(self):
        bdoc = load("blueprint.json")
        next(x for x in bdoc["questions"] if x["number"] == 1)["correctOption"] = "a"
        errs = cq.check(self.qdoc, bdoc, self.spec, self.concepts).errors
        self.assertIn("[Q15] Q1: correctOption is \"c\" but the blueprint says \"a\"", " | ".join(errs))

    def test_blueprint_without_correct_option(self):
        bdoc = load("blueprint.json")
        del next(x for x in bdoc["questions"] if x["number"] == 1)["correctOption"]
        errs = cq.check(self.qdoc, bdoc, self.spec, self.concepts).errors
        self.assertIn("[Q15] blueprint: gives no correctOption for Q1;", " | ".join(errs))

    def test_blueprint_compares_concepts(self):
        bdoc = load("blueprint.json")
        bp = next(x for x in bdoc["questions"] if x["number"] == 12)
        bp["parts"][0]["parts"][1]["concept"] = "acceleration"
        errs = cq.check(self.qdoc, bdoc, self.spec, self.concepts).errors
        self.assertIn("[Q15] Q12(a)(ii): concept is \"second_equation_of_motion\" but the blueprint says \"acceleration\"",
                      " | ".join(errs))


if __name__ == "__main__":
    unittest.main()
