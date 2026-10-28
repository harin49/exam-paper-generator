"""Guards for skill/SKILL.md: every script and file it names must exist, and every script must be named.
Run from the project root:
    python3 -m unittest discover tests
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skill", "SKILL.md")

with open(SKILL, encoding="utf-8") as f:
    TEXT = f.read()

PATH_RE = re.compile(r"(?<![\w/.-])((?:skill|agents|examples)/[\w./-]+\.(?:py|md|json))")
SCRIPTS = sorted(f for f in os.listdir(os.path.join(ROOT, "skill", "scripts")) if f.endswith(".py"))


class SkillMd(unittest.TestCase):
    def test_every_named_path_exists(self):
        missing = [p for p in sorted(set(PATH_RE.findall(TEXT))) if not os.path.exists(os.path.join(ROOT, p))]
        self.assertEqual(missing, [])

    def test_every_script_is_named_by_its_full_path(self):
        unnamed = [s for s in SCRIPTS if f"skill/scripts/{s}" not in TEXT]
        self.assertEqual(unnamed, [])

    def test_no_script_is_named_by_a_short_relative_path(self):
        self.assertEqual(re.findall(r"(?<!skill/)\bscripts/\w+\.py", TEXT), [])

    def test_every_command_runs_a_script_from_the_project_root(self):
        cmds = re.findall(r"^\s*python3 (\S+)", TEXT, re.M)
        self.assertTrue(cmds)
        for c in cmds:
            self.assertTrue(c.startswith("skill/scripts/"), c)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, c)), c)

    def test_agent_prompts_are_named(self):
        for name in ("agents/blind-solver.md", "agents/reviewer.md"):
            self.assertIn(name, TEXT)

    def test_agents_are_started_by_type_not_pasted(self):
        # Pasting an agent file into a general-purpose subagent drops its tool limits.
        with open(os.path.join(ROOT, "skill", "workflow.json"), encoding="utf-8") as f:
            workflow = f.read()
        for text in (TEXT, workflow):
            self.assertNotIn("full text of", text)
        for name in ("blind-solver", "reviewer"):
            self.assertIn(f"`{name}` subagent by its type", TEXT)


class AgentFiles(unittest.TestCase):
    def test_blind_solver_prompt_names_no_other_file(self):
        with open(os.path.join(ROOT, "agents", "blind-solver.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(re.findall(r"`[\w/.-]+\.(?:md|py)`", text), [])

    def test_agent_tools_are_limited(self):
        for name in ("blind-solver", "reviewer"):
            with open(os.path.join(ROOT, "agents", f"{name}.md"), encoding="utf-8") as f:
                head = f.read().split("---")[1]
            self.assertIn("tools: Read, Write, Bash", head, name)


if __name__ == "__main__":
    unittest.main()
