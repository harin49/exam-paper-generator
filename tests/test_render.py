"""Tests for the make-paper skill's scripts/render.py. Run from the project root:
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
import render  # noqa: E402

try:
    import pypdf
except ImportError:          # text checks on the PDFs are skipped without it
    pypdf = None

EXAMPLE = TEST_DATA
NB = " "


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pdf_text(path):
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(path).pages)


class Markup(unittest.TestCase):
    def test_tags_are_converted(self):
        self.assertEqual(render.markup("cm<sup>2</sup> and F<sub>2</sub>"),
                         "cm<super>2</super> and F<sub>2</sub>")
        self.assertIn("<b>not</b>", render.markup("does <b>not</b> depend"))
        self.assertIn("<br/>", render.markup("a<br/>b"))

    def test_other_angle_brackets_and_ampersands_are_escaped(self):
        self.assertEqual(render.markup("if a < b & b > c"), "if a &lt; b &amp; b &gt; c")

    def test_value_stays_with_unit(self):
        self.assertEqual(render.markup("10 m"), f"10{NB}m")
        self.assertEqual(render.markup("9.8 m s<sup>−2</sup>"), f"9.8{NB}m{NB}s<super>−2</super>")
        self.assertEqual(render.markup("10<sup>5</sup> Pa"), f"10<super>5</super>{NB}Pa")
        self.assertEqual(render.markup("1030 kg m<sup>−3</sup>"), f"1030{NB}kg{NB}m<super>−3</super>")

    def test_ordinary_words_are_not_glued(self):
        self.assertEqual(render.markup("in 5 marks"), "in 5 marks")
        self.assertEqual(render.markup("Q 3 and more"), "Q 3 and more")

    def test_standalone_compound_unit_is_kept_together(self):
        self.assertEqual(render.markup("kg m s<sup>−1</sup>"), f"kg{NB}m{NB}s<super>−1</super>")

    def test_times_sign_is_kept_with_its_numbers(self):
        self.assertIn(f"4{NB}×{NB}10", render.markup("4 × 10<sup>4</sup> Pa"))

    def test_symbol_is_kept_with_its_value(self):
        self.assertEqual(render.markup("(Take g = 9.8 m s<sup>−2</sup>.)"),
                         f"(Take g{NB}={NB}9.8{NB}m{NB}s<super>−2</super>.)")
        self.assertIn(f"π{NB}={NB}3.14", render.markup("Take π = 3.14."))
        self.assertIn(f"F<sub>2</sub>{NB}={NB}50", render.markup("F<sub>2</sub> = 50 × 200"))
        self.assertIn("slope = g", render.markup("slope = g/4π"))          # a word, not a symbol
        self.assertIn("Δp = m(v", render.markup("Δp = m(v − u)"))         # no number after '='

    def test_plain_strips_tags(self):
        self.assertEqual(render.plain("m s<sup>−2</sup> <b>x</b>"), "m s−2 x")


class Wording(unittest.TestCase):
    def setUp(self):
        self.spec = load(os.path.join(EXAMPLE, "spec.json"))
        self.secs = {s["id"]: s for s in self.spec["pattern"]["sections"]}

    def test_marks(self):
        self.assertEqual([render.fmt_marks(x) for x in (0.5, 1, 1.5, 3, 2.25, 0.75)],
                         ["½", "1", "1½", "3", "2¼", "¾"])
        self.assertEqual(render.marks_word(1), "mark")
        self.assertEqual(render.marks_word(1.5), "marks")

    def test_duration(self):
        self.assertEqual(render.duration_text(75), "1 hour 15 minutes")
        self.assertEqual(render.duration_text(120), "2 hours")
        self.assertEqual(render.duration_text(45), "45 minutes")
        self.assertEqual(render.duration_text(61), "1 hour 1 minute")

    def test_chapter_list(self):
        self.assertEqual(render.chapter_list([5, 1, 2, 3, 4]), "1–5")
        self.assertEqual(render.chapter_list([1, 3, 5]), "1, 3, 5")
        self.assertEqual(render.chapter_list([2, 3]), "2, 3")

    def test_section_wording(self):
        self.assertEqual(render.section_subtitle(self.secs["A"]),
                         "Answer all questions. Each question carries 1 mark. [6 × 1 = 6]")
        self.assertEqual(render.section_subtitle(self.secs["B"]),
                         "Attempt any THREE questions. Each question carries 3 marks. [3 × 3 = 9]")
        self.assertEqual(render.section_subtitle(self.secs["C"]),
                         "Attempt any ONE question. Each question carries 6 marks. [1 × 6 = 6]")

    def test_instructions_come_from_the_spec(self):
        text = "\n".join(render.instructions(self.spec, True, True))
        self.assertIn("This paper has three sections: A, B and C.", text)
        self.assertIn("<b>Section A</b>: Answer <b>all</b> questions.", text)
        self.assertIn("<b>Section B</b>: Attempt <b>any three</b> questions out of four.", text)
        self.assertIn("<b>Section C</b>: Attempt <b>any one</b> question out of three.", text)
        self.assertIn("sub-parts are shown in parentheses", text)
        self.assertIn("Show all working", text)
        self.assertIn(f"Take g{NB}={NB}9.8{NB}m s<sup>−2</sup> unless stated otherwise.", text)

    def test_instructions_leave_out_what_does_not_apply(self):
        spec = copy.deepcopy(self.spec)
        spec["content"]["constants"] = {}
        text = "\n".join(render.instructions(spec, False, False))
        self.assertNotIn("sub-parts", text)
        self.assertNotIn("Show all working", text)
        self.assertNotIn("Take ", text)

    def test_unknown_constant_is_printed_plainly(self):
        self.assertEqual(render.constants_text({"speed_of_light": 3e8}),
                         f"speed of light{NB}={NB}3e+08")


class Fonts(unittest.TestCase):
    def test_no_family_installed(self):
        self.assertIsNone(render.find_font({"a"}, families=[("Nope", [["/no/such/file.ttf"]] * 4)]))

    def test_font_is_found_and_covers_physics_characters(self):
        found = render.find_font(set("−×÷½π√≈ρΔ°") | {NB})
        self.assertIsNotNone(found, "no usable serif font installed")
        self.assertEqual(found[2], [])

    def test_uncovered_character_is_reported(self):
        found = render.find_font({""})
        self.assertIsNotNone(found)
        self.assertEqual(found[2], [""])


class Build(unittest.TestCase):
    """End-to-end: the test paper is a complete, valid paper (with one diagram)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name in ("questions.json", "spec.json", "blueprint.json", "concepts.json", "vt_graph.png"):
            shutil.copy(os.path.join(EXAMPLE, name), self.tmp)
        self.q = os.path.join(self.tmp, "questions.json")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def set_questions(self, change):
        d = load(self.q)
        change(d)
        with open(self.q, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def set_spec(self, change):
        path = os.path.join(self.tmp, "spec.json")
        d = load(path)
        change(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def run_main(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = render.main(["render.py", self.q, "--out", self.out])
        return code, buf.getvalue()

    def paths(self):
        paper, key = render.output_names(load(os.path.join(self.tmp, "spec.json")))
        return os.path.join(self.out, paper), os.path.join(self.out, key)

    def test_both_pdfs_are_built(self):
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        paper, key = self.paths()
        for p in (paper, key):
            self.assertTrue(os.path.getsize(p) > 5000, p)
        self.assertNotIn("WARNING", out)

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_paper_text_comes_from_the_spec(self):
        self.run_main()
        text = pdf_text(self.paths()[0])
        for expected in ("Time allowed: 40 minutes", "Maximum Marks: 21", "SECTION B",
                         "Attempt any THREE questions", "[3 × 3 = 9]", "Attempt any ONE question.", "General Instructions",
                         "End of Question Paper"):
            self.assertIn(expected, text)
        self.assertNotIn("Marking:", text)           # the paper never shows the scheme
        self.assertNotIn("Chapter 2", text)          # showChapterNames is false

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_key_has_answers_and_marking(self):
        self.run_main()
        text = pdf_text(self.paths()[1])
        for expected in ("Answer Key and Marking Scheme", "Chapters 1–3", "Explanation", "Marking:",
                         "SECTION C — Long Answer, 6 marks each (any one)", "0.993 m"):
            self.assertIn(expected, text)

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_key_follows_the_include_list(self):
        self.set_spec(lambda d: d["output"]["answerKey"].update(include=["answers"]))
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        text = pdf_text(self.paths()[1])
        self.assertNotIn("Marking:", text)
        self.assertNotIn("Explanation", text)
        self.assertIn("0.993 m", text)

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_chapter_names_when_the_spec_asks(self):
        self.set_spec(lambda d: d["content"].update(showChapterNames=True))
        self.run_main()
        text = pdf_text(self.paths()[0])
        self.assertIn("Chapter 2: Motion in One Dimension", text)

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_missing_diagram_gets_a_placeholder_and_a_warning(self):
        os.remove(os.path.join(self.tmp, "vt_graph.png"))
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("WARNING: 1 diagram image(s) are missing", out)
        self.assertIn("vt_graph.png", out)
        self.assertIn("Diagram not yet drawn", pdf_text(self.paths()[0]))   # Q12's diagram is on the paper

    @unittest.skipUnless(pypdf, "pypdf not installed")
    def test_diagram_on_a_part_is_printed(self):
        # A spanned table cell shows only its first column, so a part's diagram must sit there.
        def move_diagram_to_part(d):
            q12 = next(q for q in d["questions"] if q["number"] == 12)
            leaf = next(p for p in q12["parts"] if "parts" not in p)
            leaf["diagram"] = q12.pop("diagram")
        self.set_questions(move_diagram_to_part)
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        images = sum(len(page.images) for page in pypdf.PdfReader(self.paths()[0]).pages)
        self.assertEqual(images, 1)

    def test_questions_that_fail_the_checker_are_not_built(self):
        def break_marks(d):
            d["questions"][0]["marks"] = 2
        self.set_questions(break_marks)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("were not built", out)
        self.assertFalse(os.path.exists(self.out))

    def test_unreadable_input(self):
        os.remove(os.path.join(self.tmp, "spec.json"))
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("Cannot read input", out)

    def test_usage(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(render.main(["render.py"]), 2)


if __name__ == "__main__":
    unittest.main()
