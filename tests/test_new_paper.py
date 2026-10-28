"""Tests for the make-paper skill's scripts/new_paper.py. Run from the project root:
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
import new_paper  # noqa: E402

SPEC = os.path.join(ROOT, "examples", "icse9-physics-ch1-5", "spec.json")


class Names(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(new_paper.slug("Computer Science"), "computer-science")
        self.assertEqual(new_paper.slug("ICSE"), "icse")
        self.assertEqual(new_paper.slug(9), "9")
        self.assertEqual(new_paper.slug("  Maths / Applied! "), "maths-applied")

    def test_task_name(self):
        spec = {"exam": {"board": "ICSE", "class": 9, "subject": "Physics"}}
        self.assertEqual(new_paper.task_name(spec, "2026-10-27"), "icse-9-physics-2026-10-27")

    def test_empty_field_is_refused(self):
        with self.assertRaises(ValueError):
            new_paper.task_name({"exam": {"board": "", "class": 9, "subject": "Physics"}}, "2026-10-27")


class Folders(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root)

    def run_main(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = new_paper.main(["new_paper.py", *args])
        return code, buf.getvalue().strip()

    def test_creates_papers_and_task_folder_with_the_spec(self):
        self.assertFalse(os.path.exists(os.path.join(self.root, "papers")))
        code, out = self.run_main(SPEC, "--root", self.root, "--date", "2026-10-27")
        self.assertEqual(code, 0, out)
        folder = os.path.join(self.root, "papers", "icse-9-physics-2026-10-27")
        self.assertEqual(out, folder)
        self.assertTrue(os.path.isdir(folder))
        with open(SPEC, encoding="utf-8") as a, open(os.path.join(folder, "spec.json"), encoding="utf-8") as b:
            self.assertEqual(json.load(a), json.load(b))

    def test_existing_papers_folder_is_kept(self):
        os.makedirs(os.path.join(self.root, "papers", "other-paper"))
        self.run_main(SPEC, "--root", self.root, "--date", "2026-10-27")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "papers", "other-paper")))

    def test_same_name_gets_a_number_and_nothing_is_overwritten(self):
        _, first = self.run_main(SPEC, "--root", self.root, "--date", "2026-10-27")
        marker = os.path.join(first, "questions.json")
        with open(marker, "w") as f:
            f.write("keep me")
        _, second = self.run_main(SPEC, "--root", self.root, "--date", "2026-10-27")
        _, third = self.run_main(SPEC, "--root", self.root, "--date", "2026-10-27")
        self.assertEqual(os.path.basename(second), "icse-9-physics-2026-10-27-2")
        self.assertEqual(os.path.basename(third), "icse-9-physics-2026-10-27-3")
        with open(marker) as f:
            self.assertEqual(f.read(), "keep me")

    def test_default_date_is_today(self):
        import datetime
        _, out = self.run_main(SPEC, "--root", self.root)
        self.assertTrue(os.path.basename(out).endswith(datetime.date.today().isoformat()))

    def test_bad_inputs(self):
        self.assertEqual(self.run_main()[0], 2)
        self.assertEqual(self.run_main(SPEC, "--root", self.root, "--date", "27-10-2026")[0], 2)
        self.assertEqual(self.run_main(os.path.join(self.root, "missing.json"), "--root", self.root)[0], 2)
        bad = os.path.join(self.root, "bad.json")
        with open(bad, "w") as f:
            f.write("{not json")
        self.assertEqual(self.run_main(bad, "--root", self.root)[0], 2)
        nofield = os.path.join(self.root, "nofield.json")
        with open(nofield, "w") as f:
            json.dump({"exam": {"board": "ICSE"}}, f)
        code, out = self.run_main(nofield, "--root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("Cannot read the spec", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "papers")))   # nothing made on failure


if __name__ == "__main__":
    unittest.main()
