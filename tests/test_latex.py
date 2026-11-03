"""Tests for the make-paper skill's scripts/latex.py. Run from the project root:
    python3 -m unittest discover tests
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugins", "exam-papers", "skills", "make-paper", "scripts"))
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp())
import latex  # noqa: E402


class Split(unittest.TestCase):
    def test_inline_display_and_escaped_dollars(self):
        self.assertEqual(latex.split(r"Find $\frac{a}{b}$ if it costs \$5. $$v^2=u^2+2as$$ done"),
                         [("text", "Find "), ("inline", r"\frac{a}{b}"), ("text", " if it costs $5. "),
                          ("display", "v^2=u^2+2as"), ("text", " done")])

    def test_two_formulas_side_by_side_stay_inline(self):
        self.assertEqual(latex.split("$a$$b$"), [("inline", "a"), ("inline", "b")])

    def test_plain_text(self):
        self.assertEqual(latex.split("no maths here"), [("text", "no maths here")])
        self.assertFalse(latex.has_math("costs \\$5"))

    def test_unclosed_or_empty_is_an_error(self):
        for bad in ("open $x", "$$", "$ $"):
            with self.assertRaises(ValueError, msg=bad):
                latex.split(bad)
        self.assertEqual(latex.split_quiet("open $x"), [("text", "open $x")])


class Problems(unittest.TestCase):
    def test_school_maths_typesets(self):
        for ok in (r"$\frac{a+b}{2}$", r"$\sqrt{x^2+y^2}$", r"$4.5 \times 10^{3}$", r"$\int_0^1 x\,dx$",
                   r"$\Delta p/\Delta t$", r"$$v^2 = u^2 + 2as$$", "no maths", "costs \\$5"):
            self.assertEqual(latex.problems(ok), [], ok)

    def test_what_mathtext_cannot_do_is_reported_with_a_reason(self):
        self.assertEqual(latex.problems(r"$\begin{pmatrix}1\end{pmatrix}$"),
                         [r"$\begin{pmatrix}1\end{pmatrix}$ cannot be typeset: Unknown symbol: \begin, found '\'"])
        self.assertIn("Expected \\frac{num}{den}", latex.problems(r"$\frac{a}$")[0])
        self.assertIn("something is missing", latex.problems("$x^$")[0])
        self.assertIn("has no closing $", latex.problems("open $x")[0])


class Image(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_draws_a_png_with_size_and_depth(self):
        path, w, h, depth = latex.image(r"\frac{a+b}{2}", 10.5, self.tmp)
        self.assertTrue(path.endswith(".png") and os.path.isfile(path))
        self.assertTrue(10 < w < 30 and 10 < h < 20 and 0 < depth < h, (w, h, depth))
        again = latex.image(r"\frac{a+b}{2}", 10.5, self.tmp)
        self.assertEqual(again[0], path)                                   # same formula, same file
        self.assertGreater(latex.image(r"\frac{a+b}{2}", 10.5, self.tmp, display=True)[1], w)


class NumberMarks(unittest.TestCase):
    def test_a_leading_latex_number_reads_as_the_html_marks(self):
        cases = {r"$4.5 \times 10^{3}$ N": "4.5 × 10<sup>3</sup> N",
                 r"$2.0 \times 10^{-4}$": "2.0 × 10<sup>-4</sup>",
                 r"$50{,}000$ J": "50,000 J",
                 "12 m": "12 m",
                 r"$\frac{1}{2}$": r"\frac{1}{2}"}
        for text, want in cases.items():
            self.assertEqual(latex.number_marks(text), want, text)


if __name__ == "__main__":
    unittest.main()
