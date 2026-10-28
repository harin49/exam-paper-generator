"""Shared paths for the unit tests.

TEST_DATA is a small test paper (spec, concept list, syllabus, blueprint, questions and a diagram)
that the tests use to check the scripts. It is fixed test data: it does not change when example
papers or the real concept lists change.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DATA = os.path.join(ROOT, "tests", "test_data")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
